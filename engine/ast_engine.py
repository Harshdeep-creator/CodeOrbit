"""AST extraction for Python, JavaScript, and TypeScript repositories."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from shared.repository_schema import CallInfo, ClassInfo, FileInfo, FunctionInfo, ImportInfo, RepositoryState


class AstEngine:
    """Extract symbols, imports, and call relationships from source files."""

    def analyze_repository(
        self,
        root_path: str,
        state: Optional[RepositoryState] = None,
        ignore_dirs: Optional[Iterable[str]] = None,
    ) -> RepositoryState:
        root = Path(root_path).resolve()
        state = state or RepositoryState(root_path=str(root))
        ignored = set(ignore_dirs or {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"})

        for path in self._iter_source_files(root, ignored):
            self.analyze_file(path, root, state)

        return state

    def analyze_file(self, path: Path, root: Path, state: RepositoryState) -> None:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        language = self.detect_language(path)
        file_info = FileInfo(path=rel, language=language, size=len(text), lines=text.count("\n") + 1)

        if language == "python":
            self._parse_python(rel, text, file_info, state)
        elif language in {"javascript", "typescript"}:
            self._parse_js_ts(rel, text, file_info, state)

        state.files[rel] = file_info

    def _iter_source_files(self, root: Path, ignored: Set[str]) -> Iterable[Path]:
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ignored and not d.startswith(".pytest_cache")]
            for name in files:
                path = Path(current) / name
                if path.suffix.lower() in self.supported_extensions():
                    yield path

    def supported_extensions(self) -> Set[str]:
        return {".py", ".js", ".jsx", ".ts", ".tsx"}

    def detect_language(self, path: Path) -> str:
        return {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
        }.get(path.suffix.lower(), "unknown")

    def _parse_python(self, rel: str, text: str, file_info: FileInfo, state: RepositoryState) -> None:
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            file_info.parse_errors.append(f"{exc.msg} at line {exc.lineno}")
            return

        lines = text.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    file_info.imports.append(
                        ImportInfo(module=alias.name, alias=alias.asname, line=node.lineno, raw=self._line(lines, node.lineno))
                    )
            elif isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
                file_info.imports.append(
                    ImportInfo(module=node.module or "", names=names, line=node.lineno, raw=self._line(lines, node.lineno))
                )

        def visit_body(body: List[ast.stmt], current_class: Optional[str] = None, scope: Optional[List[str]] = None) -> None:
            scope = scope or []
            for node in body:
                if isinstance(node, ast.ClassDef):
                    qualified_name = ".".join(scope + [node.name])
                    class_id = f"class:{rel}:{qualified_name}"
                    cls = ClassInfo(
                        id=class_id,
                        name=node.name,
                        file=rel,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        bases=[self._expr_name(base) for base in node.bases if self._expr_name(base)],
                    )
                    state.classes[class_id] = cls
                    file_info.classes.append(class_id)
                    visit_body(node.body, qualified_name, scope + [node.name])
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified_name = ".".join(scope + [node.name])
                    function_id = f"function:{rel}:{qualified_name}"
                    call_refs = self._python_call_refs(node, lines)
                    calls = [call.name for call in call_refs]
                    decorators = [self._expr_name(dec) for dec in node.decorator_list if self._expr_name(dec)]
                    fn = FunctionInfo(
                        id=function_id,
                        name=node.name,
                        file=rel,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        class_name=current_class,
                        parameters=[arg.arg for arg in node.args.args],
                        calls=calls,
                        call_refs=call_refs,
                        decorators=decorators,
                        complexity=self._python_complexity(node),
                        source="\n".join(lines[node.lineno - 1 : getattr(node, "end_lineno", node.lineno)]),
                    )
                    state.functions[function_id] = fn
                    file_info.functions.append(function_id)
                    file_info.calls.extend(calls)
                    if current_class:
                        class_id = f"class:{rel}:{current_class}"
                        if class_id in state.classes:
                            state.classes[class_id].methods.append(function_id)
                    visit_body(node.body, current_class, scope + [node.name])

        visit_body(tree.body)

    def _parse_js_ts(self, rel: str, text: str, file_info: FileInfo, state: RepositoryState) -> None:
        scrubbed = self._strip_js_comments(text)
        lines = text.splitlines()

        for line_no, line in enumerate(lines, start=1):
            import_info = self._parse_js_import(line, line_no)
            if import_info:
                file_info.imports.append(import_info)

        class_spans = self._find_js_classes(scrubbed)
        for name, start, end in class_spans:
            class_id = f"class:{rel}:{name}"
            state.classes[class_id] = ClassInfo(id=class_id, name=name, file=rel, start_line=start, end_line=end)
            file_info.classes.append(class_id)

        function_spans = self._find_js_functions(scrubbed)
        for name, start, end in function_spans:
            class_name = self._owning_class(start, class_spans)
            qualified = f"{class_name}.{name}" if class_name else name
            function_id = f"function:{rel}:{qualified}"
            source = "\n".join(lines[start - 1 : end])
            call_refs = self._extract_js_call_refs(source, start)
            calls = [call.name for call in call_refs]
            fn = FunctionInfo(
                id=function_id,
                name=name,
                file=rel,
                start_line=start,
                end_line=end,
                class_name=class_name,
                parameters=self._extract_js_params(source),
                calls=calls,
                call_refs=call_refs,
                complexity=self._js_complexity(source),
                source=source,
            )
            state.functions[function_id] = fn
            file_info.functions.append(function_id)
            file_info.calls.extend(calls)
            if class_name:
                class_id = f"class:{rel}:{class_name}"
                if class_id in state.classes:
                    state.classes[class_id].methods.append(function_id)

    def _find_js_classes(self, text: str) -> List[Tuple[str, int, int]]:
        spans = []
        for match in re.finditer(r"\bclass\s+([A-Za-z_$][\w$]*)[^{]*\{", text):
            spans.append((match.group(1), self._line_number(text, match.start()), self._line_number(text, self._matching_brace(text, match.end() - 1))))
        return spans

    def _find_js_functions(self, text: str) -> List[Tuple[str, int, int]]:
        patterns = [
            r"\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{",
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{",
            r"\b([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{",
        ]
        spans = []
        seen = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                name = match.group(1)
                if name in {"if", "for", "while", "switch", "catch", "function"}:
                    continue
                brace = text.find("{", match.start(), match.end() + 1)
                if brace == -1:
                    continue
                start = self._line_number(text, match.start())
                key = (name, start)
                if key in seen:
                    continue
                seen.add(key)
                spans.append((name, start, self._line_number(text, self._matching_brace(text, brace))))
        return sorted(spans, key=lambda item: item[1])

    def _extract_js_calls(self, source: str) -> List[str]:
        return [call.name for call in self._extract_js_call_refs(source, 1)]

    def _extract_js_call_refs(self, source: str, start_line: int) -> List[CallInfo]:
        calls = []
        for match in re.finditer(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(", source):
            name = match.group(1)
            if name.split(".")[-1] not in {"if", "for", "while", "switch", "catch", "function"}:
                calls.append(CallInfo(name=name, line=start_line + source.count("\n", 0, match.start()), raw=name))
        return calls

    def _parse_js_import(self, line: str, line_no: int) -> Optional[ImportInfo]:
        from_match = re.search(r"^\s*import\s+(.+?)\s+from\s+['\"]([^'\"]+)['\"]", line)
        if from_match:
            names = self._parse_js_import_names(from_match.group(1))
            return ImportInfo(module=from_match.group(2), names=names, line=line_no, raw=line.strip())
        side_effect = re.search(r"^\s*import\s+['\"]([^'\"]+)['\"]", line)
        if side_effect:
            return ImportInfo(module=side_effect.group(1), line=line_no, raw=line.strip())
        require_match = re.search(r"^\s*(?:const|let|var)\s+(.+?)\s*=\s*require\(['\"]([^'\"]+)['\"]\)", line)
        if require_match:
            names = self._parse_js_import_names(require_match.group(1))
            return ImportInfo(module=require_match.group(2), names=names, line=line_no, raw=line.strip())
        return None

    def _parse_js_import_names(self, text: str) -> List[str]:
        cleaned = text.replace("{", "").replace("}", "").replace("* as", "").strip()
        names = []
        for part in cleaned.split(","):
            token = part.strip()
            if not token:
                continue
            if " as " in token:
                token = token.split(" as ", 1)[1].strip()
            if ":" in token:
                token = token.split(":", 1)[1].strip()
            names.append(token)
        return names

    def _extract_js_params(self, source: str) -> List[str]:
        match = re.search(r"\(([^)]*)\)", source)
        if not match:
            return []
        return [p.strip().split(":")[0].strip() for p in match.group(1).split(",") if p.strip()]

    def _owning_class(self, line: int, class_spans: List[Tuple[str, int, int]]) -> Optional[str]:
        for name, start, end in class_spans:
            if start <= line <= end:
                return name
        return None

    def _python_complexity(self, node: ast.AST) -> int:
        branch_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.ExceptHandler, ast.BoolOp, ast.IfExp, ast.Match)
        return 1 + sum(1 for child in ast.walk(node) if isinstance(child, branch_nodes))

    def _python_call_refs(self, node: ast.AST, lines: List[str]) -> List[CallInfo]:
        refs = []
        for call in ast.walk(node):
            if isinstance(call, ast.Call):
                name = self._expr_name(call.func)
                if name:
                    refs.append(CallInfo(name=name, line=getattr(call, "lineno", node.lineno), raw=self._line(lines, getattr(call, "lineno", node.lineno))))
        return refs

    def _js_complexity(self, source: str) -> int:
        return 1 + len(re.findall(r"\b(if|for|while|case|catch|\?\s*)\b|&&|\|\|", source))

    def _expr_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._expr_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            return self._expr_name(node.func)
        if isinstance(node, ast.Constant):
            return str(node.value)
        return ""

    def _line(self, lines: List[str], line_no: int) -> str:
        return lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""

    def _strip_js_comments(self, text: str) -> str:
        text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        return re.sub(r"//.*", "", text)

    def _line_number(self, text: str, index: int) -> int:
        return text.count("\n", 0, max(index, 0)) + 1

    def _matching_brace(self, text: str, open_index: int) -> int:
        depth = 0
        for idx in range(open_index, len(text)):
            if text[idx] == "{":
                depth += 1
            elif text[idx] == "}":
                depth -= 1
                if depth == 0:
                    return idx
        return len(text) - 1
