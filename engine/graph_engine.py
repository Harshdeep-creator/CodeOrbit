"""Dependency, knowledge graph, entry-point, and flow generation engine."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from shared.repository_schema import GraphEdge, GraphNode, LineRef, RepositoryState


class GraphEngine:
    """Build file/function graphs and derive execution intelligence."""

    def build(self, state: RepositoryState) -> RepositoryState:
        state.graph_nodes.clear()
        state.graph_edges.clear()
        self._add_nodes(state)
        self._add_import_edges(state)
        self._add_call_edges(state)
        state.entry_points = self.detect_entry_points(state)
        state.main_logic = self.find_main_logic(state)
        state.execution_flows = self.generate_execution_flows(state)
        state.metadata["reverse_dependencies"] = self.reverse_dependencies(state)
        state.metadata["impact_index"] = self.impact_index(state)
        return state

    def detect_entry_points(self, state: RepositoryState) -> List[str]:
        exact = [path for path in state.files if Path(path).name in self.entrypoint_names()]
        package_entries = [
            path for path in state.files if Path(path).name in {"__main__.py", "cli.py"} or path.endswith("/bin/index.js")
        ]
        return sorted(dict.fromkeys(exact + package_entries))

    def entrypoint_names(self) -> Set[str]:
        return {"main.py", "app.py", "index.js", "server.js"}

    def find_main_logic(self, state: RepositoryState, limit: int = 10) -> List[str]:
        in_degree = defaultdict(float)
        out_degree = defaultdict(float)
        for edge in state.graph_edges:
            out_degree[edge.source] += edge.weight
            in_degree[edge.target] += edge.weight

        scores = {}
        for node_id, node in state.graph_nodes.items():
            if node.type not in {"file", "function"}:
                continue
            scores[node_id] = in_degree[node_id] * 1.5 + out_degree[node_id]

        return [node_id for node_id, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]]

    def generate_execution_flows(self, state: RepositoryState, max_depth: int = 24) -> Dict[str, List[str]]:
        adjacency = self._adjacency(state, edge_types={"calls", "imports", "contains"})
        flows: Dict[str, List[str]] = {}
        for entry in state.entry_points:
            flows[entry] = self._entry_flow(entry, state, adjacency, max_depth)
        return flows

    def path_between(self, state: RepositoryState, start: str, target: str, max_depth: int = 20) -> List[str]:
        adjacency = self._adjacency(state)
        queue = deque([(start, [start])])
        seen = {start}
        while queue:
            node, path = queue.popleft()
            if node == target:
                return path
            if len(path) > max_depth:
                continue
            for nxt in adjacency.get(node, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, path + [nxt]))
        return []

    def reverse_dependencies(self, state: RepositoryState) -> Dict[str, List[str]]:
        reverse: Dict[str, List[str]] = defaultdict(list)
        for edge in state.graph_edges:
            if edge.type in {"imports", "calls"}:
                reverse[edge.target].append(edge.source)
        return {node: sorted(dict.fromkeys(sources)) for node, sources in reverse.items()}

    def impact_index(self, state: RepositoryState, max_depth: int = 12) -> Dict[str, List[str]]:
        reverse = self._reverse_adjacency(state, edge_types={"imports", "calls"})
        impacted = {}
        for node_id in state.graph_nodes:
            if node_id.startswith(("file:", "function:")):
                impacted[node_id] = self._bfs_order(node_id, reverse, max_depth)[1:]
        return impacted

    def impacted_by_change(self, state: RepositoryState, node_id: str, max_depth: int = 12) -> List[str]:
        reverse = self._reverse_adjacency(state, edge_types={"imports", "calls"})
        return self._bfs_order(node_id, reverse, max_depth)[1:]

    def evidence_from_path(self, state: RepositoryState, path: List[str]) -> Dict[str, List[Any]]:
        files = []
        functions = []
        lines = []
        for node_id in path:
            node = state.graph_nodes.get(node_id)
            if not node:
                continue
            if node.file:
                files.append(node.file)
            if node.type == "function":
                fn = state.functions.get(node_id)
                if fn:
                    functions.append({"id": fn.id, "name": fn.name, "file": fn.file, "line": fn.start_line})
                    lines.append({"file": fn.file, "line": fn.start_line, "symbol": fn.name})
            elif node.line and node.file:
                lines.append({"file": node.file, "line": node.line, "symbol": node.label})
        return {
            "files": sorted(dict.fromkeys(files)),
            "functions": self._dedupe_dicts(functions, "id"),
            "lines": self._dedupe_dicts(lines, "file", "line", "symbol"),
        }

    def _add_nodes(self, state: RepositoryState) -> None:
        for path, file_info in state.files.items():
            state.graph_nodes[f"file:{path}"] = GraphNode(
                id=f"file:{path}",
                type="file",
                label=path,
                file=path,
                metadata={"language": file_info.language, "lines": file_info.lines},
            )
        for fn in state.functions.values():
            state.graph_nodes[fn.id] = GraphNode(
                id=fn.id,
                type="function",
                label=fn.name,
                file=fn.file,
                line=fn.start_line,
                metadata={"class_name": fn.class_name, "complexity": fn.complexity},
            )
            state.graph_edges.append(
                GraphEdge(
                    source=f"file:{fn.file}",
                    target=fn.id,
                    type="contains",
                    evidence=[LineRef(file=fn.file, line=fn.start_line, symbol=fn.name)],
                )
            )
        for cls in state.classes.values():
            state.graph_nodes[cls.id] = GraphNode(
                id=cls.id,
                type="class",
                label=cls.name,
                file=cls.file,
                line=cls.start_line,
                metadata={"bases": cls.bases},
            )
            state.graph_edges.append(
                GraphEdge(
                    source=f"file:{cls.file}",
                    target=cls.id,
                    type="contains",
                    evidence=[LineRef(file=cls.file, line=cls.start_line, symbol=cls.name)],
                )
            )

    def _add_import_edges(self, state: RepositoryState) -> None:
        files_by_stem = self._files_by_module_name(state)
        for path, file_info in state.files.items():
            for imp in file_info.imports:
                target = self._resolve_import(imp.module, path, files_by_stem)
                target_id = f"file:{target}" if target else f"external:{imp.module}"
                if target_id not in state.graph_nodes:
                    state.graph_nodes[target_id] = GraphNode(id=target_id, type="external", label=imp.module)
                state.graph_edges.append(
                    GraphEdge(
                        source=f"file:{path}",
                        target=target_id,
                        type="imports",
                        evidence=[LineRef(file=path, line=imp.line, symbol=imp.module)],
                    )
                )

    def _add_call_edges(self, state: RepositoryState) -> None:
        functions_by_name = self._functions_by_short_name(state)
        imported_symbols = self._imported_symbol_map(state)
        for fn in state.functions.values():
            call_refs = fn.call_refs or []
            if not call_refs:
                call_refs = []
                for call in fn.calls:
                    call_refs.append(LineRef(file=fn.file, line=fn.start_line, symbol=call))
            for call_ref in call_refs:
                call_name = getattr(call_ref, "name", None) or getattr(call_ref, "symbol", "")
                call_line = getattr(call_ref, "line", fn.start_line)
                target = self._resolve_call(call_name, fn, functions_by_name, imported_symbols)
                if target:
                    state.graph_edges.append(
                        GraphEdge(
                            source=fn.id,
                            target=target,
                            type="calls",
                            evidence=[LineRef(file=fn.file, line=call_line, symbol=call_name)],
                        )
                    )

    def _files_by_module_name(self, state: RepositoryState) -> Dict[str, str]:
        mapping = {}
        for path in state.files:
            p = Path(path)
            mapping[p.stem] = path
            mapping[path.replace("/", ".").rsplit(".", 1)[0]] = path
        return mapping

    def _resolve_import(self, module: str, importer: str, files_by_stem: Dict[str, str]) -> Optional[str]:
        if not module:
            return None
        normalized = module.replace("/", ".").removeprefix("./").removeprefix("../")
        importer_parent = Path(importer).parent.as_posix().replace("/", ".")
        candidates = [normalized, normalized.split(".")[-1], normalized.replace("/", ".")]
        if module.startswith(".") and importer_parent != ".":
            candidates.insert(0, f"{importer_parent}.{normalized.lstrip('.')}")
        for candidate in candidates:
            if candidate in files_by_stem:
                return files_by_stem[candidate]
        return None

    def _functions_by_short_name(self, state: RepositoryState) -> Dict[str, List[str]]:
        mapping = defaultdict(list)
        for fn in state.functions.values():
            mapping[fn.name].append(fn.id)
            mapping[f"{Path(fn.file).stem}.{fn.name}"].append(fn.id)
            mapping[f"{fn.file.replace('/', '.').rsplit('.', 1)[0]}.{fn.name}"].append(fn.id)
            if fn.class_name:
                mapping[f"{fn.class_name}.{fn.name}"].append(fn.id)
        return mapping

    def _imported_symbol_map(self, state: RepositoryState) -> Dict[str, Dict[str, List[str]]]:
        functions_by_name = self._functions_by_short_name(state)
        file_modules = self._files_by_module_name(state)
        mapping: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        for file_path, file_info in state.files.items():
            for imp in file_info.imports:
                target_file = self._resolve_import(imp.module, file_path, file_modules)
                module_name = Path(target_file).stem if target_file else imp.module.split(".")[-1]
                for imported_name in imp.names:
                    for candidate in (f"{module_name}.{imported_name}", imported_name):
                        for fn_id in functions_by_name.get(candidate, []):
                            if not target_file or state.functions[fn_id].file == target_file:
                                mapping[file_path][imported_name].append(fn_id)
                if target_file:
                    for fn in state.functions.values():
                        if fn.file == target_file:
                            mapping[file_path][f"{module_name}.{fn.name}"].append(fn.id)
        return {file: {name: sorted(dict.fromkeys(ids)) for name, ids in symbols.items()} for file, symbols in mapping.items()}

    def _resolve_call(
        self,
        call: str,
        caller,
        functions_by_name: Dict[str, List[str]],
        imported_symbols: Dict[str, Dict[str, List[str]]],
    ) -> Optional[str]:
        if not call:
            return None
        imported = imported_symbols.get(caller.file, {})
        for candidate in (call, call.split(".")[-1]):
            if imported.get(candidate):
                return imported[candidate][0]
        candidates = [call, call.split(".")[-1]]
        for candidate in candidates:
            matches = functions_by_name.get(candidate, [])
            same_file = [match for match in matches if f":{caller.file}:" in match and match != caller.id]
            if same_file:
                return same_file[0]
            if "." in call and matches:
                return matches[0]
        return None

    def _adjacency(self, state: RepositoryState, edge_types: Optional[Set[str]] = None) -> Dict[str, List[str]]:
        adjacency = defaultdict(list)
        for edge in state.graph_edges:
            if edge_types is None or edge.type in edge_types:
                adjacency[edge.source].append(edge.target)
        for values in adjacency.values():
            values.sort()
        return adjacency

    def _reverse_adjacency(self, state: RepositoryState, edge_types: Optional[Set[str]] = None) -> Dict[str, List[str]]:
        adjacency = defaultdict(list)
        for edge in state.graph_edges:
            if edge_types is None or edge.type in edge_types:
                adjacency[edge.target].append(edge.source)
        for values in adjacency.values():
            values.sort()
        return adjacency

    def _entry_flow(self, entry: str, state: RepositoryState, adjacency: Dict[str, List[str]], max_depth: int) -> List[str]:
        start_file = f"file:{entry}"
        flow = [start_file]
        starts = self._entry_function_nodes(entry, state)
        for start in starts:
            for node in self._bfs_order(start, adjacency, max_depth):
                if node not in flow:
                    flow.append(node)
        if len(flow) == 1:
            for node in self._bfs_order(start_file, adjacency, max_depth):
                if node not in flow:
                    flow.append(node)
        return flow

    def _entry_function_nodes(self, entry: str, state: RepositoryState) -> List[str]:
        preferred = {"main", "run", "start", "handler", "create_app"}
        candidates = []
        fallback = []
        for fn in state.functions.values():
            if fn.file != entry:
                continue
            if fn.name in preferred:
                candidates.append(fn.id)
            else:
                fallback.append(fn.id)
        return sorted(candidates) or sorted(fallback)

    def _bfs_order(self, start: str, adjacency: Dict[str, List[str]], max_depth: int) -> List[str]:
        order = []
        queue = deque([(start, 0)])
        seen = {start}
        while queue:
            node, depth = queue.popleft()
            order.append(node)
            if depth >= max_depth:
                continue
            for nxt in adjacency.get(node, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, depth + 1))
        return order

    def _dedupe_dicts(self, values: List[Dict[str, Any]], *keys: str) -> List[Dict[str, Any]]:
        seen = set()
        result = []
        for value in values:
            identity = tuple(value.get(key) for key in keys)
            if identity not in seen:
                seen.add(identity)
                result.append(value)
        return result
