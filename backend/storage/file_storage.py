"""Filesystem operations for repository uploads and cleanup."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

from fastapi import UploadFile

from backend.core.config import Settings, get_settings
from backend.core.errors import InvalidUploadError, StorageError

GITHUB_URL_PATTERN = re.compile(r"^https?://(www\.)?github\.com/[\w.-]+/[\w.-]+/?(\.git)?$")


class FileStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()

    def validate_archive(self, file: UploadFile) -> None:
        if not file.filename:
            raise InvalidUploadError("Upload filename is missing.")
        if not file.filename.lower().endswith(".zip"):
            raise InvalidUploadError("Only ZIP archives are supported.")
        if file.size is not None and file.size > self.settings.max_upload_bytes:
            raise InvalidUploadError(
                f"Upload exceeds maximum size of {self.settings.max_upload_size_mb} MB.",
                {"max_size_mb": self.settings.max_upload_size_mb},
            )

    async def extract_zip(self, upload_file: UploadFile, dest_dir: Path | None = None) -> str:
        self.validate_archive(upload_file)
        target_dir = dest_dir or (self.settings.repos_dir / str(uuid.uuid4()))
        target_dir.mkdir(parents=True, exist_ok=True)

        zip_path = target_dir / "upload.zip"
        total_bytes = 0
        try:
            with zip_path.open("wb") as handle:
                while True:
                    chunk = await upload_file.read(1024 * 1024)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > self.settings.max_upload_bytes:
                        raise InvalidUploadError(
                            f"Upload exceeds maximum size of {self.settings.max_upload_size_mb} MB."
                        )
                    handle.write(chunk)
        except InvalidUploadError:
            self.cleanup_repository(str(target_dir))
            raise
        except Exception as exc:
            self.cleanup_repository(str(target_dir))
            raise StorageError("Failed to store uploaded archive.", {"reason": str(exc)}) from exc

        extract_root = target_dir / "src"
        extract_root.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                if archive.testzip() is not None:
                    raise InvalidUploadError("Corrupted ZIP archive detected.")
                archive.extractall(extract_root)
        except zipfile.BadZipFile as exc:
            self.cleanup_repository(str(target_dir))
            raise InvalidUploadError("Invalid or corrupted ZIP archive.") from exc
        except InvalidUploadError:
            self.cleanup_repository(str(target_dir))
            raise
        except Exception as exc:
            self.cleanup_repository(str(target_dir))
            raise StorageError("Failed to extract archive.", {"reason": str(exc)}) from exc
        finally:
            zip_path.unlink(missing_ok=True)

        root_path = self._resolve_content_root(extract_root)
        if not any(root_path.rglob("*")):
            self.cleanup_repository(str(target_dir))
            raise InvalidUploadError("Uploaded archive is empty.")
        return str(root_path.resolve())

    def clone_github(self, url: str, dest_dir: Path | None = None) -> str:
        if not GITHUB_URL_PATTERN.match(url.strip()):
            raise InvalidUploadError("Invalid GitHub repository URL.")
        target_dir = dest_dir or (self.settings.repos_dir / str(uuid.uuid4()))
        target_dir.mkdir(parents=True, exist_ok=True)
        clone_path = target_dir / "src"
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url.strip(), str(clone_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError as exc:
            self.cleanup_repository(str(target_dir))
            raise InvalidUploadError("Git is not installed on this server.") from exc
        except subprocess.CalledProcessError as exc:
            self.cleanup_repository(str(target_dir))
            raise InvalidUploadError("Failed to clone GitHub repository.", {"stderr": exc.stderr.strip()}) from exc
        except subprocess.TimeoutExpired as exc:
            self.cleanup_repository(str(target_dir))
            raise InvalidUploadError("Git clone timed out.") from exc

        if not any(clone_path.rglob("*")):
            self.cleanup_repository(str(target_dir))
            raise InvalidUploadError("Cloned repository is empty.")
        return str(clone_path.resolve())

    def compute_repo_hash(self, root_path: str) -> str:
        root = Path(root_path)
        if not root.exists():
            raise StorageError("Repository path does not exist.", {"path": root_path})

        digest = hashlib.sha256()
        ignored_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
        file_hashes: list[str] = []

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in ignored_dirs for part in path.parts):
                continue
            try:
                content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            file_hashes.append(f"{rel}:{content_hash}")

        for item in file_hashes:
            digest.update(item.encode("utf-8"))
        return digest.hexdigest()

    def cleanup_repository(self, root_path: str) -> None:
        path = Path(root_path)
        if not path.exists():
            return
        parent = path.parent
        if parent.name == str(path.name) or parent.name in {"src", "repositories"}:
            shutil.rmtree(parent if path.name == "src" else path, ignore_errors=True)
        else:
            shutil.rmtree(path, ignore_errors=True)

    def _resolve_content_root(self, extract_root: Path) -> Path:
        entries = [item for item in extract_root.iterdir() if item.name != "__MACOSX"]
        if len(entries) == 1 and entries[0].is_dir():
            return entries[0]
        return extract_root
