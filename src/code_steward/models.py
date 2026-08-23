from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CodeUnit:
    """One indexed declaration with its retrieval metadata."""

    unit_id: str
    path: str
    kind: str
    name: str
    qualname: str
    start_line: int
    end_line: int
    signature: str = ""
    parameters: list[dict[str, str]] = field(default_factory=list)
    returns: str = ""
    purpose: str = ""
    doc_text: str = ""
    concepts: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    owns: list[str] = field(default_factory=list)
    not_owns: list[str] = field(default_factory=list)
    body_hash: str = ""
    git_file_commit: str = ""
    explicit_region: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Endpoint:
    """One FastAPI route discovered on an indexed unit."""

    unit_id: str
    path: str
    method: str
    route: str
    response_model: str = ""
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class HardRelationship:
    """Deterministic code fact linking a unit to a target."""

    source_unit_id: str
    relation: str
    target_kind: str
    target_ref: str
    provenance: str
    evidence: dict[str, Any] = field(default_factory=dict)
    source_hash: str = ""
    target_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class SoftRelationship:
    """Scored similarity inference between two indexed units."""

    source_unit_id: str
    relation: str
    target_unit_id: str
    score: float
    provenance: str
    evidence: dict[str, Any] = field(default_factory=dict)
    source_hash: str = ""
    target_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SearchResult:
    """One scored retrieval candidate with its evidence."""

    unit: CodeUnit
    score: float
    evidence: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = self.unit.to_dict()
        data["score"] = round(self.score, 2)
        data["evidence"] = {key: round(value, 2) for key, value in self.evidence.items()}
        return data
