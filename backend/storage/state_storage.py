"""Pickle-based RepositoryState persistence."""

from __future__ import annotations

import pickle
from pathlib import Path

from shared.repository_schema import RepositoryState

from backend.core.errors import StorageError


class StateStorage:
    def save_state(self, state: RepositoryState, path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("wb") as handle:
                pickle.dump(state, handle, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:
            raise StorageError("Failed to save repository state.", {"path": path}) from exc

    def load_state(self, path: str) -> RepositoryState:
        target = Path(path)
        if not target.exists():
            raise StorageError("Repository state snapshot not found.", {"path": path})
        try:
            with target.open("rb") as handle:
                state = pickle.load(handle)
        except Exception as exc:
            raise StorageError("Failed to load repository state.", {"path": path}) from exc
        if not isinstance(state, RepositoryState):
            raise StorageError("Invalid repository state snapshot.", {"path": path})
        return state

    def state_exists(self, path: str) -> bool:
        return Path(path).is_file()

    def delete_state(self, path: str) -> None:
        target = Path(path)
        if target.exists():
            target.unlink()
