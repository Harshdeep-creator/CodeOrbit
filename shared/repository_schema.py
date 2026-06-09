"""Repository analysis schema used by every engine output.

This module is intentionally dependency-free. Engines should return or enrich
``RepositoryState`` instead of inventing transport-specific payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class LineRef:
    file: str
    line: int
    symbol: Optional[str] = None


@dataclass
class ImportInfo:
    module: str
    names: List[str] = field(default_factory=list)
    alias: Optional[str] = None
    line: int = 0
    raw: str = ""


@dataclass
class CallInfo:
    name: str
    line: int
    raw: str = ""


@dataclass
class FunctionInfo:
    id: str
    name: str
    file: str
    start_line: int
    end_line: int
    class_name: Optional[str] = None
    parameters: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    call_refs: List[CallInfo] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    complexity: int = 1
    source: str = ""


@dataclass
class ClassInfo:
    id: str
    name: str
    file: str
    start_line: int
    end_line: int
    bases: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)


@dataclass
class FileInfo:
    path: str
    language: str
    size: int = 0
    lines: int = 0
    imports: List[ImportInfo] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    parse_errors: List[str] = field(default_factory=list)


@dataclass
class GraphNode:
    id: str
    type: str
    label: str
    file: Optional[str] = None
    line: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    source: str
    target: str
    type: str
    evidence: List[LineRef] = field(default_factory=list)
    weight: float = 1.0


@dataclass
class Issue:
    id: str
    type: str
    severity: str
    title: str
    description: str
    evidence: List[LineRef] = field(default_factory=list)
    confidence: float = 0.8


@dataclass
class QueryResponse:
    answer: str
    evidence: Dict[str, List[Any]] = field(
        default_factory=lambda: {"files": [], "functions": [], "lines": []}
    )
    graph_path: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RepositoryState:
    root_path: str
    files: Dict[str, FileInfo] = field(default_factory=dict)
    functions: Dict[str, FunctionInfo] = field(default_factory=dict)
    classes: Dict[str, ClassInfo] = field(default_factory=dict)
    graph_nodes: Dict[str, GraphNode] = field(default_factory=dict)
    graph_edges: List[GraphEdge] = field(default_factory=list)
    embeddings: Dict[str, List[float]] = field(default_factory=dict)
    entry_points: List[str] = field(default_factory=list)
    main_logic: List[str] = field(default_factory=list)
    execution_flows: Dict[str, List[str]] = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
