"""静的解析結果を結ぶFactGraph。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class FactNode:
    id: str
    kind: str
    label: str
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class FactEdge:
    source: str
    target: str
    kind: str
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class FactGraph:
    """model/control/tool/observationの候補edgeを保持する。"""

    def __init__(self) -> None:
        self.nodes: dict[str, FactNode] = {}
        self.edges: list[FactEdge] = []

    def add_node(
        self,
        *,
        node_id: str,
        kind: str,
        label: str,
        evidence_ids: list[str] | None = None,
    ) -> FactNode:
        existing = self.nodes.get(node_id)
        if existing:
            for evidence_id in evidence_ids or []:
                if evidence_id not in existing.evidence_ids:
                    existing.evidence_ids.append(evidence_id)
            return existing
        node = FactNode(
            id=node_id,
            kind=kind,
            label=label,
            evidence_ids=list(evidence_ids or []),
        )
        self.nodes[node_id] = node
        return node

    def add_edge(
        self,
        *,
        source: str,
        target: str,
        kind: str,
        evidence_ids: list[str] | None = None,
    ) -> FactEdge:
        edge = FactEdge(
            source=source,
            target=target,
            kind=kind,
            evidence_ids=list(evidence_ids or []),
        )
        for existing in self.edges:
            if (
                existing.source == edge.source
                and existing.target == edge.target
                and existing.kind == edge.kind
            ):
                for evidence_id in edge.evidence_ids:
                    if evidence_id not in existing.evidence_ids:
                        existing.evidence_ids.append(evidence_id)
                return existing
        self.edges.append(edge)
        return edge

    def has_node_kind(self, kind: str) -> bool:
        return any(node.kind == kind for node in self.nodes.values())

    def has_edge_kind(self, *kinds: str) -> bool:
        return any(edge.kind in kinds for edge in self.edges)

    def edge_evidence(self, *kinds: str) -> list[str]:
        result: list[str] = []
        for edge in self.edges:
            if edge.kind in kinds:
                result.extend(edge.evidence_ids)
        return list(dict.fromkeys(result))

    def node_evidence(self, *kinds: str) -> list[str]:
        result: list[str] = []
        for node in self.nodes.values():
            if node.kind in kinds:
                result.extend(node.evidence_ids)
        return list(dict.fromkeys(result))

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
        }

