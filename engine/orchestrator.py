"""Brain layer for routing repository questions to the right engines."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from engine.analysis_engine import AnalysisEngine
from engine.ast_engine import AstEngine
from engine.embedding_engine import EmbeddingEngine
from engine.graph_engine import GraphEngine
from shared.repository_schema import QueryResponse, RepositoryState


class QueryIntent(str, Enum):
    STRUCTURE = "STRUCTURE"
    FLOW = "FLOW"
    SEMANTIC = "SEMANTIC"
    RISK = "RISK"
    EXPLANATION = "EXPLANATION"


class IntelligenceOrchestrator:
    """Analyze repositories and answer questions with graph-backed evidence."""

    def __init__(
        self,
        ast_engine: Optional[AstEngine] = None,
        graph_engine: Optional[GraphEngine] = None,
        embedding_engine: Optional[EmbeddingEngine] = None,
        analysis_engine: Optional[AnalysisEngine] = None,
    ) -> None:
        self.ast_engine = ast_engine or AstEngine()
        self.graph_engine = graph_engine or GraphEngine()
        self.embedding_engine = embedding_engine or EmbeddingEngine()
        self.analysis_engine = analysis_engine or AnalysisEngine()

    def analyze_repository(self, root_path: str) -> RepositoryState:
        state = self.ast_engine.analyze_repository(root_path)
        self.graph_engine.build(state)
        self.embedding_engine.build(state)
        self.analysis_engine.analyze(state)
        return state

    def answer_query(self, query: str, root_path: Optional[str] = None, state: Optional[RepositoryState] = None) -> Dict:
        if state is None:
            if root_path is None:
                raise ValueError("Either root_path or state is required.")
            state = self.analyze_repository(root_path)

        intent = self.classify_query(query)
        response = self.route_query(query, intent, state)
        state.metadata["last_query_intent"] = intent.value
        state.metadata["last_query_response"] = response.to_dict()
        return response.to_dict()

    def classify_query(self, query: str) -> QueryIntent:
        normalized = query.lower()
        if self._is_locator_query(normalized) or self._is_impact_query(normalized) or normalized.startswith("explain "):
            return QueryIntent.EXPLANATION
        terms = self._intent_terms()
        scores = {
            QueryIntent.STRUCTURE: self._score_terms(normalized, terms[QueryIntent.STRUCTURE]),
            QueryIntent.FLOW: self._score_terms(normalized, terms[QueryIntent.FLOW]),
            QueryIntent.SEMANTIC: self._score_terms(normalized, terms[QueryIntent.SEMANTIC]),
            QueryIntent.RISK: self._score_terms(normalized, terms[QueryIntent.RISK]),
        }
        best, score = max(scores.items(), key=lambda item: (item[1], item[0].value))
        if score == 0 or sum(1 for value in scores.values() if value > 0) > 1:
            return QueryIntent.EXPLANATION
        return best

    def _intent_terms(self) -> Dict[QueryIntent, set]:
        return {
            QueryIntent.STRUCTURE: {"function", "class", "import", "symbol", "where defined", "defined", "structure", "ast"},
            QueryIntent.FLOW: {"flow", "trace", "execution", "entry", "path", "calls", "call graph"},
            QueryIntent.SEMANTIC: {"search", "similar", "meaning", "semantic", "find code", "related", "logic", "authentication", "auth"},
            QueryIntent.RISK: {"risk", "dead code", "security", "smell", "complexity", "circular", "hotspot", "vulnerability"},
        }

    def route_query(self, query: str, intent: QueryIntent, state: RepositoryState) -> QueryResponse:
        if intent == QueryIntent.STRUCTURE:
            return self._answer_structure(query, state)
        if intent == QueryIntent.FLOW:
            return self._answer_flow(query, state)
        if intent == QueryIntent.SEMANTIC:
            return self._answer_semantic(query, state)
        if intent == QueryIntent.RISK:
            return self._answer_risk(query, state)
        return self._answer_explanation(query, state)

    def _answer_structure(self, query: str, state: RepositoryState) -> QueryResponse:
        matches = self._matched_functions(query, state)[:8]
        files = self._matched_files(query, state)[:8]
        if not matches and not files:
            matches = list(state.functions)[:8]
            files = list(state.files)[:8]

        answer = (
            f"Repository structure includes {len(state.files)} files, "
            f"{len(state.classes)} classes, and {len(state.functions)} functions."
        )
        return QueryResponse(
            answer=answer,
            evidence=self._evidence(state, files=files, functions=matches),
            graph_path=[],
            confidence=self._confidence(self._evidence(state, files=files, functions=matches), [], 0.84),
        )

    def _answer_flow(self, query: str, state: RepositoryState) -> QueryResponse:
        if not state.entry_points:
            return QueryResponse(
                answer="No standard entry points were detected.",
                evidence=self._evidence(state),
                graph_path=[],
                confidence=self._confidence(self._evidence(state), [], 0.42),
            )

        entry = self._best_entry_for_query(query, state)
        path = state.execution_flows.get(entry, [])
        answer = f"Execution flow starts at `{entry}` and reaches {max(len(path) - 1, 0)} graph nodes."
        evidence = self.graph_engine.evidence_from_path(state, path)
        return QueryResponse(
            answer=answer,
            evidence=evidence,
            graph_path=path,
            confidence=self._confidence(evidence, path, 0.86),
        )

    def _answer_semantic(self, query: str, state: RepositoryState) -> QueryResponse:
        results = self.embedding_engine.search(state, query, limit=8)
        files = [node.removeprefix("file:") for node, _ in results if node.startswith("file:")]
        functions = [node for node, _ in results if node.startswith("function:")]
        if results:
            top = ", ".join(node for node, _ in results[:3])
            answer = f"Semantic search found the strongest matches in {top}."
            confidence = min(0.9, max(score for _, score in results) + 0.35)
        else:
            answer = "Semantic search did not find a confident match."
            confidence = 0.35
        evidence = self._evidence(state, files, functions)
        return QueryResponse(answer=answer, evidence=evidence, graph_path=[], confidence=self._confidence(evidence, [], confidence))

    def _answer_risk(self, query: str, state: RepositoryState) -> QueryResponse:
        terms = query.lower()
        issues = [
            issue
            for issue in state.issues
            if issue.type.replace("_", " ") in terms or any(word in terms for word in issue.title.lower().split())
        ]
        if not issues:
            issues = state.issues[:8]

        if not issues:
            evidence = self._evidence(state)
            return QueryResponse(
                answer="No risks were detected by the analysis engine from the current RepositoryState.",
                evidence=evidence,
                graph_path=[],
                confidence=self._confidence(evidence, [], 0.42),
            )

        counts: Dict[str, int] = {}
        for issue in issues:
            counts[issue.severity] = counts.get(issue.severity, 0) + 1
        summary = ", ".join(f"{count} {severity}" for severity, count in sorted(counts.items()))
        answer = f"Detected {len(issues)} relevant risk findings: {summary}."
        issue_evidence = {
            "files": sorted({ref.file for issue in issues for ref in issue.evidence}),
            "functions": self._functions_from_symbols(state, {ref.symbol for issue in issues for ref in issue.evidence if ref.symbol}),
            "lines": [ref.__dict__ for issue in issues for ref in issue.evidence],
        }
        graph_path = self._risk_graph_path(state, issues)
        graph_evidence = self.graph_engine.evidence_from_path(state, graph_path)
        evidence = self._merge_evidence(issue_evidence, graph_evidence)
        return QueryResponse(
            answer=answer,
            evidence=evidence,
            graph_path=graph_path,
            confidence=self._confidence(evidence, graph_path, 0.86),
        )

    def _answer_explanation(self, query: str, state: RepositoryState) -> QueryResponse:
        semantic = self.embedding_engine.search(state, query, limit=5)
        files = [node.removeprefix("file:") for node, _ in semantic if node.startswith("file:")]
        functions = [node for node, _ in semantic if node.startswith("function:")]
        ast_files = self._matched_files(query, state)
        ast_functions = self._matched_functions(query, state)
        include_analysis = self._is_impact_query(query.lower()) or self._has_risk_terms(query.lower())
        issues = self._relevant_issues(query, state)[:5] if include_analysis else []
        path = self._hybrid_graph_path(query, state, ast_functions + functions)

        issue_evidence = self._issue_evidence(state, issues)
        graph_evidence = self.graph_engine.evidence_from_path(state, path)
        structure_evidence = self._evidence(state, ast_files + files, ast_functions + functions)
        merged_evidence = self._merge_evidence(structure_evidence, graph_evidence, issue_evidence)
        components = []
        if structure_evidence["files"] or structure_evidence["functions"]:
            components.append("structure")
        if path:
            components.append("graph flow")
        if semantic:
            components.append("semantic similarity")
        if issues:
            components.append("risk findings")
        component_text = ", ".join(components) if components else "available RepositoryState fields"
        ceiling = 0.82
        if self._is_impact_query(query.lower()) and not path:
            ceiling = 0.55
        answer = (
            f"Hybrid analysis used {component_text} from RepositoryState. "
            f"Matched {len(merged_evidence['files'])} files, {len(merged_evidence['functions'])} functions, "
            f"{len(path)} graph nodes, and {len(issues)} relevant findings."
        )
        return QueryResponse(
            answer=answer,
            evidence=merged_evidence,
            graph_path=path,
            confidence=self._confidence(merged_evidence, path, ceiling),
        )

    def _score_terms(self, query: str, terms: Iterable[str]) -> int:
        return sum(1 for term in terms if term in query)

    def _is_locator_query(self, query: str) -> bool:
        return ("where" in query or "handled" in query or "defined" in query) and any(
            term in query for term in {"auth", "authentication", "login", "logic"}
        )

    def _is_impact_query(self, query: str) -> bool:
        return any(term in query for term in {"what breaks", "breaks", "impact", "change"})

    def _has_risk_terms(self, query: str) -> bool:
        return any(term in query for term in {"risk", "dead code", "security", "smell", "complexity", "circular", "hotspot", "vulnerability"})

    def _matched_functions(self, query: str, state: RepositoryState) -> List[str]:
        terms = self._expanded_query_terms(query)
        return [
            fn.id
            for fn in state.functions.values()
            if self._matches_terms(fn.name, terms) or (fn.class_name and self._matches_terms(fn.class_name, terms))
        ]

    def _matched_files(self, query: str, state: RepositoryState) -> List[str]:
        terms = self._expanded_query_terms(query)
        return [path for path in state.files if self._matches_terms(path, terms) or self._matches_terms(Path(path).stem, terms)]

    def _best_entry_for_query(self, query: str, state: RepositoryState) -> str:
        normalized = query.lower()
        for entry in state.entry_points:
            if Path(entry).name.lower() in normalized or entry.lower() in normalized:
                return entry
        return state.entry_points[0]

    def _hybrid_graph_path(self, query: str, state: RepositoryState, function_ids: List[str]) -> List[str]:
        if self._is_impact_query(query.lower()):
            targets = [fn for fn in function_ids if fn in state.graph_nodes]
            if not targets:
                semantic = self.embedding_engine.search(state, query, limit=3)
                targets = [node for node, _ in semantic if node in state.graph_nodes]
            for target in targets:
                impacted = self.graph_engine.impacted_by_change(state, target)
                if impacted:
                    return [target] + impacted[:12]
        if state.entry_points:
            return state.execution_flows.get(state.entry_points[0], [])[:12]
        return [fn for fn in function_ids if fn in state.graph_nodes][:12]

    def _risk_graph_path(self, state: RepositoryState, issues: List) -> List[str]:
        for issue in issues:
            for ref in issue.evidence:
                containing = [
                    fn
                    for fn in state.functions.values()
                    if fn.file == ref.file and fn.start_line <= ref.line <= fn.end_line
                ]
                containing.sort(key=lambda fn: (fn.end_line - fn.start_line, fn.start_line))
                if containing:
                    fn = containing[0]
                    impacted = self.graph_engine.impacted_by_change(state, fn.id)
                    return [fn.id] + impacted[:12]
                file_node = f"file:{ref.file}"
                if file_node in state.graph_nodes:
                    impacted = self.graph_engine.impacted_by_change(state, file_node)
                    return [file_node] + impacted[:12]
        return []

    def _expanded_query_terms(self, query: str) -> set:
        raw_terms = {part for part in query.lower().replace("?", " ").replace(",", " ").split() if part}
        expanded = set(raw_terms)
        if raw_terms & {"auth", "authentication", "login"}:
            expanded.update({"auth", "authentication", "login", "signin", "sign_in"})
        return expanded

    def _matches_terms(self, value: str, terms: set) -> bool:
        normalized = value.lower().replace("_", " ").replace("-", " ").replace("/", " ").replace(".", " ")
        compact = normalized.replace(" ", "")
        return any(term in normalized or term in compact for term in terms)

    def _evidence(self, state: RepositoryState, files: Optional[List[str]] = None, functions: Optional[List[str]] = None) -> Dict:
        files = sorted(dict.fromkeys(files or []))
        functions = sorted(dict.fromkeys(functions or []))
        function_context = []
        lines = []
        for fn_id in functions:
            fn = state.functions.get(fn_id)
            if fn:
                function_context.append({"id": fn.id, "name": fn.name, "file": fn.file, "line": fn.start_line})
                lines.append({"file": fn.file, "line": fn.start_line, "symbol": fn.name})
                if fn.file not in files:
                    files.append(fn.file)
        for file in files:
            if file in state.files and not any(line["file"] == file for line in lines):
                lines.append({"file": file, "line": 1, "symbol": None})
        return {"files": sorted(dict.fromkeys(files)), "functions": function_context, "lines": self._dedupe_lines(lines)}

    def _merge_evidence(self, *items: Dict) -> Dict:
        files = []
        functions = []
        lines = []
        for item in items:
            files.extend(item.get("files", []))
            functions.extend(item.get("functions", []))
            lines.extend(item.get("lines", []))
        return {
            "files": sorted(dict.fromkeys(files)),
            "functions": self._dedupe_functions(functions),
            "lines": self._dedupe_lines(lines),
        }

    def _relevant_issues(self, query: str, state: RepositoryState) -> List:
        terms = query.lower()
        issues = [
            issue
            for issue in state.issues
            if issue.type.replace("_", " ") in terms
            or any(word and word in terms for word in issue.title.lower().replace("`", "").split())
        ]
        return issues or state.issues[:5]

    def _issue_evidence(self, state: RepositoryState, issues: List) -> Dict:
        files = sorted({ref.file for issue in issues for ref in issue.evidence})
        symbols = {ref.symbol for issue in issues for ref in issue.evidence if ref.symbol}
        return {"files": files, "functions": self._functions_from_symbols(state, symbols), "lines": [ref.__dict__ for issue in issues for ref in issue.evidence]}

    def _functions_from_symbols(self, state: RepositoryState, symbols: set) -> List[Dict]:
        contexts = []
        for fn in state.functions.values():
            if fn.name in symbols or any(symbol and symbol.endswith(f".{fn.name}") for symbol in symbols):
                contexts.append({"id": fn.id, "name": fn.name, "file": fn.file, "line": fn.start_line})
        return self._dedupe_functions(contexts)

    def _dedupe_functions(self, functions: List[Dict]) -> List[Dict]:
        seen = set()
        result = []
        for fn in functions:
            identity = fn.get("id") or (fn.get("name"), fn.get("file"), fn.get("line"))
            if identity not in seen:
                seen.add(identity)
                result.append(fn)
        return result

    def _dedupe_lines(self, lines: List[Dict]) -> List[Dict]:
        seen = set()
        result = []
        for line in lines:
            identity = (line.get("file"), line.get("line"), line.get("symbol"))
            if identity not in seen:
                seen.add(identity)
                result.append(line)
        return result

    def _confidence(self, evidence: Dict, graph_path: List[str], ceiling: float) -> float:
        if not evidence.get("files") and not evidence.get("functions") and not evidence.get("lines"):
            return min(ceiling, 0.35)
        score = 0.45
        if evidence.get("files"):
            score += 0.15
        if evidence.get("functions"):
            score += 0.15
        if evidence.get("lines"):
            score += 0.15
        if graph_path:
            score += 0.10
        return round(min(ceiling, score), 2)
