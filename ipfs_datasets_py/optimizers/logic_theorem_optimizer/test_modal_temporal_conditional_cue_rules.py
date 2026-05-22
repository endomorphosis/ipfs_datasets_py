"""Focused modal cue regressions for temporal vs conditional scope."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    ModalLogicFamily,
)


def test_compiler_treats_after_application_cross_reference_as_non_temporal_scope() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        (
            "After the application of subsection (f) and the preceding paragraphs "
            "of this subsection, as otherwise provided in this subsection, the "
            "Secretary shall issue guidance."
        ),
        document_id="compiler-ambiguity-after-application-cross-reference",
    )

    assert result.encoding is not None
    counts = result.encoding.modal_family_counts()
    assert counts.get(ModalLogicFamily.TEMPORAL.value, 0) == 0
    assert counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0) >= 1


def test_compiler_preserves_temporal_after_date_sequence_cue() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "After June 1, 2030, the Secretary shall issue guidance.",
        document_id="compiler-ambiguity-after-calendar-date-temporal",
    )

    assert result.encoding is not None
    counts = result.encoding.modal_family_counts()
    assert counts.get(ModalLogicFamily.TEMPORAL.value, 0) >= 1
