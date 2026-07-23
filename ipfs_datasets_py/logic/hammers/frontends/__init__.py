"""Native ITP frontend adapters and goal snapshots (HAMMER-006).

This package implements the ``## HAMMER-006`` entry of
``docs/logic/itp_hammer_taskboard.todo.md``: a common adapter protocol
(:mod:`.base`) that every native ITP frontend implements, plus one concrete
adapter per supported :class:`~ipfs_datasets_py.logic.hammers.models.ITPKind`:

- :mod:`.lean` — :class:`LeanFrontend`, driving a real ``lean`` toolchain.
- :mod:`.coq` — :class:`CoqFrontend`, driving a real ``coqtop`` toolchain.
- :mod:`.isabelle` — :class:`IsabelleFrontend`, driving a real ``isabelle``
  toolchain (structurally complete but, per the HAMMER-002 capability
  inventory, unexercised against a live toolchain in this repository's
  probed environments — see :mod:`.isabelle`'s module docstring).

Every adapter shares the same non-fabrication contract described in
:mod:`.base`: a :class:`~.base.GoalSnapshot` may only be produced by
genuinely invoking the target ITP's own executable and parsing its native
diagnostic output; an unavailable frontend returns structured
:class:`~.base.CapabilityEvidence` rather than guessing.
"""

from __future__ import annotations

from typing import Dict

from ..models import ITPKind
from .base import (
    DEFAULT_TIMEOUT_SECONDS,
    BoundedProcessResult,
    CapabilityEvidence,
    FrontendUnavailableError,
    GoalCaptureError,
    GoalSnapshot,
    ITPFrontend,
    LocalHypothesis,
    SourcePosition,
    UniverseContext,
    run_bounded_process,
)
from .coq import CoqFrontend
from .isabelle import IsabelleFrontend
from .lean import LeanFrontend

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "BoundedProcessResult",
    "CapabilityEvidence",
    "CoqFrontend",
    "FrontendUnavailableError",
    "GoalCaptureError",
    "GoalSnapshot",
    "ITPFrontend",
    "IsabelleFrontend",
    "LeanFrontend",
    "LocalHypothesis",
    "SourcePosition",
    "UniverseContext",
    "get_frontend",
    "iter_frontends",
    "run_bounded_process",
]

_FRONTEND_CLASSES = {
    ITPKind.LEAN: LeanFrontend,
    ITPKind.COQ: CoqFrontend,
    ITPKind.ISABELLE: IsabelleFrontend,
}


def get_frontend(itp: ITPKind, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> ITPFrontend:
    """Return the concrete :class:`ITPFrontend` adapter for ``itp``.

    Raises:
        ValueError: If ``itp`` is not one of the :class:`ITPKind` values
            with a registered frontend adapter.
    """

    try:
        frontend_cls = _FRONTEND_CLASSES[itp]
    except KeyError as exc:
        raise ValueError(f"no frontend adapter registered for ITPKind {itp!r}") from exc
    return frontend_cls(timeout=timeout)


def iter_frontends(*, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Dict[ITPKind, ITPFrontend]:
    """Return a mapping of every registered :class:`ITPKind` to a fresh
    concrete frontend adapter instance."""

    return {itp: frontend_cls(timeout=timeout) for itp, frontend_cls in _FRONTEND_CLASSES.items()}
