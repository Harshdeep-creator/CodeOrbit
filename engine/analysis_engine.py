"""Repository risk, smell, cycle, and hotspot analysis."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Dict, List, Set

from shared.repository_schema import Issue, LineRef, RepositoryState


class AnalysisEngine:
    """Detect actionable repository risks from structured state."""

    def analyze(self, state: RepositoryState) -> RepositoryState:
        issues: List[Issue] = []
        issues.extend(self.detect_dead_code(state))
        issues.extend(self.detect_circular_dependencies(state))
        issues.extend(self.detect_security_smells(state))
        issues.extend(self.detect_architecture_smells(state))
        issues.extend(self.detect_complexity_hotspots(state))
        issues.extend(self.detect_impact_hotspots(state))
        state.issues = sorted(issues, key=lambda issue: (self._severity_rank(issue.severity), issue.type, issue.id))
        return state

    def detect_dead_code(self, state: RepositoryState) -> List[Issue]:
        called = {edge.target for edge in state.graph_edges if edge.type == "calls"}
        entry_files = {f"file:{entry}" for entry in state.entry_points}
        reachable = set()
        for flow in state.execution_flows.values():
            reachable.update(flow)

        issues = []
        for fn in state.functions.values():
            publicish = not fn.name.startswith("_") and fn.name in {"main", "handler", "run", "start"}
            if fn.id not in called and fn.id not in reachable and not publicish and f"file:{fn.file}" not in entry_files:
                issues.append(
                    Issue(
                        id=self._issue_id("dead_code", fn.id),
                        type="dead_code",
                        severity="medium",
                        title=f"Potentially unused function `{fn.name}`",
                        description="No internal call path or execution-flow traversal references this function.",
                        evidence=[LineRef(file=fn.file, line=fn.start_line, symbol=fn.name)],
                        confidence=0.72,
                    )
                )
        return issues

    def detect_circular_dependencies(self, state: RepositoryState) -> List[Issue]:
        adjacency = defaultdict(list)
        for edge in state.graph_edges:
            if edge.type == "imports" and edge.source.startswith("file:") and edge.target.startswith("file:"):
                adjacency[edge.source].append(edge.target)

        issues = []
        for cycle in self._cycles(adjacency):
            files = [node.removeprefix("file:") for node in cycle]
            evidence = self._cycle_evidence(state, cycle)
            issues.append(
                Issue(
                    id=self._issue_id("cycle", "->".join(cycle)),
                    type="circular_dependency",
                    severity="high",
                    title="Circular module dependency",
                    description="Import graph contains a cycle: " + " -> ".join(files),
                    evidence=evidence,
                    confidence=0.9,
                )
            )
        return issues

    def detect_security_smells(self, state: RepositoryState) -> List[Issue]:
        issues = []
        dangerous_calls = {"eval", "exec", "os.system", "subprocess.call", "subprocess.Popen", "child_process.exec"}
        for fn in state.functions.values():
            call_refs = fn.call_refs or []
            for call_ref in call_refs:
                call = call_ref.name
                if call in dangerous_calls or call.endswith(".exec"):
                    issues.append(
                        Issue(
                            id=self._issue_id("security", fn.id, call),
                            type="security_smell",
                            severity="high",
                            title=f"Dangerous runtime execution via `{call}`",
                            description="Dynamic execution or shell invocation should be reviewed for input control and escaping.",
                            evidence=[LineRef(file=fn.file, line=call_ref.line, symbol=call)],
                            confidence=0.82,
                        )
                    )
            secret_line = self._secret_line(fn)
            if secret_line:
                issues.append(
                    Issue(
                        id=self._issue_id("secret", fn.id),
                        type="security_smell",
                        severity="critical",
                        title="Possible hardcoded secret",
                        description="A credential-like assignment appears in source code.",
                        evidence=[LineRef(file=fn.file, line=secret_line, symbol=fn.name)],
                        confidence=0.78,
                    )
                )
        return issues

    def detect_impact_hotspots(self, state: RepositoryState) -> List[Issue]:
        impact_index = state.metadata.get("impact_index", {})
        issues = []
        for node_id, impacted in impact_index.items():
            if len(impacted) < 8:
                continue
            node = state.graph_nodes.get(node_id)
            if not node or not node.file:
                continue
            issues.append(
                Issue(
                    id=self._issue_id("impact", node_id),
                    type="architecture_smell",
                    severity="medium",
                    title="High change-impact surface",
                    description=f"`{node_id}` has {len(impacted)} reverse graph dependents.",
                    evidence=[LineRef(file=node.file, line=node.line or 1, symbol=node.label)],
                    confidence=0.78,
                )
            )
        return issues

    def detect_architecture_smells(self, state: RepositoryState) -> List[Issue]:
        issues = []
        for path, file_info in state.files.items():
            outgoing = [edge for edge in state.graph_edges if edge.source == f"file:{path}" and edge.type == "imports"]
            if len(outgoing) >= 12:
                issues.append(
                    Issue(
                        id=self._issue_id("fanout", path),
                        type="architecture_smell",
                        severity="medium",
                        title="High module fan-out",
                        description=f"`{path}` imports {len(outgoing)} modules, which may indicate too many responsibilities.",
                        evidence=[LineRef(file=path, line=1)],
                        confidence=0.75,
                    )
                )
            if len(file_info.functions) >= 20 or file_info.lines >= 600:
                issues.append(
                    Issue(
                        id=self._issue_id("large_file", path),
                        type="architecture_smell",
                        severity="medium",
                        title="Large source file",
                        description="File size and symbol count suggest this module may be carrying multiple concerns.",
                        evidence=[LineRef(file=path, line=1)],
                        confidence=0.7,
                    )
                )
        return issues

    def detect_complexity_hotspots(self, state: RepositoryState) -> List[Issue]:
        issues = []
        for fn in state.functions.values():
            if fn.complexity >= 10:
                severity = "high" if fn.complexity >= 16 else "medium"
                issues.append(
                    Issue(
                        id=self._issue_id("complexity", fn.id),
                        type="complexity_hotspot",
                        severity=severity,
                        title=f"Complexity hotspot `{fn.name}`",
                        description=f"Estimated cyclomatic complexity is {fn.complexity}.",
                        evidence=[LineRef(file=fn.file, line=fn.start_line, symbol=fn.name)],
                        confidence=0.85,
                    )
                )
        return issues

    def _cycles(self, adjacency: Dict[str, List[str]]) -> List[List[str]]:
        cycles: Set[tuple] = set()

        def visit(node: str, path: List[str]) -> None:
            for nxt in adjacency.get(node, []):
                if nxt in path:
                    cycle = path[path.index(nxt) :] + [nxt]
                    canonical = min(tuple(cycle[i:] + cycle[1:i + 1]) for i in range(len(cycle) - 1))
                    cycles.add(canonical)
                elif len(path) < 20:
                    visit(nxt, path + [nxt])

        for node in adjacency:
            visit(node, [node])
        return [list(cycle) for cycle in sorted(cycles)]

    def _issue_id(self, *parts: str) -> str:
        digest = hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()[:12]
        return f"issue:{digest}"

    def _severity_rank(self, severity: str) -> int:
        return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 4)

    def _contains_secret(self, source: str) -> bool:
        return bool(re.search(r"(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}", source, re.I))

    def _secret_line(self, fn) -> int:
        for offset, line in enumerate(fn.source.splitlines(), start=0):
            if self._contains_secret(line):
                return fn.start_line + offset
        return 0

    def _cycle_evidence(self, state: RepositoryState, cycle: List[str]) -> List[LineRef]:
        evidence = []
        pairs = list(zip(cycle, cycle[1:]))
        for source, target in pairs:
            for edge in state.graph_edges:
                if edge.type == "imports" and edge.source == source and edge.target == target:
                    evidence.extend(edge.evidence)
                    break
        if evidence:
            return evidence
        return [LineRef(file=node.removeprefix("file:"), line=1) for node in cycle if node.startswith("file:")]
