"""SAWM-038 multi-view and cross-domain program-world projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


VIEWS: tuple[str, ...] = (
    "text",
    "ast",
    "cfg",
    "call",
    "data_flow",
    "symbolic_ir",
    "proof",
    "trace",
    "failure",
    "dataset",
    "legal",
    "security",
    "intent",
    "procedure",
)


class ProgramViewError(ValueError):
    """Closed program-view contract violation."""


@dataclass(frozen=True, slots=True)
class ProgramWorldProjectionRequest:
    view: str
    source_cid: str
    privacy_admitted: bool
    freshness: str = "fresh"


@dataclass(frozen=True, slots=True)
class ProgramWorldView:
    view: str
    source_cid: str
    invalidators: tuple[str, ...]
    privacy_admitted: bool


@dataclass(frozen=True, slots=True)
class CrossDomainProgramView:
    source_view: str
    target_view: str
    allowed: bool


@dataclass(frozen=True, slots=True)
class MultiViewInvalidation:
    view: str
    reason_code: str


def build_program_world_view(request: Mapping[str, Any]) -> ProgramWorldView:
    view = str(request.get("view") or "")
    if view not in VIEWS:
        raise ProgramViewError(f"unknown view {view}")
    if request.get("privacy_admitted") is not True:
        raise ProgramViewError("view is not privacy admitted")
    if request.get("freshness") == "stale":
        raise ProgramViewError("stale view")
    return ProgramWorldView(
        view=view,
        source_cid=str(request.get("source_cid") or ""),
        invalidators=("source_change", "privacy_revoke", "freshness_revoke"),
        privacy_admitted=True,
    )
