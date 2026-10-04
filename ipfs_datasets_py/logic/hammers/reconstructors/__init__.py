"""Native ITP proof reconstructors and kernel verification (HAMMER-010).

This package provides one concrete
:class:`~ipfs_datasets_py.logic.hammers.reconstruction.Reconstructor` per
supported :class:`~ipfs_datasets_py.logic.hammers.models.ITPKind`:

- :mod:`.lean` — :class:`LeanReconstructor`, driving a real ``lean``
  toolchain and its ``#print axioms`` mechanism.
- :mod:`.coq` — :class:`CoqReconstructor`, driving a real ``coqtop``
  toolchain and its ``Print Assumptions`` mechanism.
- :mod:`.isabelle` — :class:`IsabelleReconstructor`, driving a real
  ``isabelle process`` toolchain (structurally complete but, per the
  HAMMER-002 capability inventory, unexercised against a live toolchain in
  this repository's probed environments — see :mod:`.isabelle`'s module
  docstring, matching :mod:`~ipfs_datasets_py.logic.hammers.frontends.
  isabelle`'s documented status).

Every reconstructor shares the common protocol and helpers defined in
:mod:`ipfs_datasets_py.logic.hammers.reconstruction`: it reconstructs a
native tactic/proof term from *untrusted* candidate evidence, substitutes it
for the single incomplete-proof marker in a caller-supplied native source,
and asks the real target-ITP kernel to check it in a pinned, versioned
environment. Only the kernel's own acceptance can ever promote a hammer run
to ``verified``.
"""

from __future__ import annotations

from typing import Dict

from ..models import ITPKind
from ..reconstruction import DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS, Reconstructor
from .coq import CoqReconstructor
from .isabelle import IsabelleReconstructor
from .lean import LeanReconstructor

__all__ = [
    "CoqReconstructor",
    "IsabelleReconstructor",
    "LeanReconstructor",
    "get_reconstructor",
    "iter_reconstructors",
]

_RECONSTRUCTOR_CLASSES = {
    ITPKind.LEAN: LeanReconstructor,
    ITPKind.COQ: CoqReconstructor,
    ITPKind.ISABELLE: IsabelleReconstructor,
}


def get_reconstructor(
    itp: ITPKind, *, timeout: float = DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS
) -> Reconstructor:
    """Return the concrete :class:`~..reconstruction.Reconstructor` for
    ``itp``.

    Raises:
        ValueError: If ``itp`` is not one of the :class:`~..models.ITPKind`
            values with a registered reconstructor.
    """

    try:
        reconstructor_cls = _RECONSTRUCTOR_CLASSES[itp]
    except KeyError as exc:
        raise ValueError(f"no reconstructor registered for ITPKind {itp!r}") from exc
    return reconstructor_cls(timeout=timeout)


def iter_reconstructors(
    *, timeout: float = DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS
) -> Dict[ITPKind, Reconstructor]:
    """Return a mapping of every registered :class:`~..models.ITPKind` to a
    fresh concrete :class:`~..reconstruction.Reconstructor` instance."""

    return {
        itp: reconstructor_cls(timeout=timeout)
        for itp, reconstructor_cls in _RECONSTRUCTOR_CLASSES.items()
    }
