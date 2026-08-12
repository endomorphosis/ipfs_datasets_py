"""Acceptance vectors for producer-bound exact source admission (DSS-006)."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    RepositoryState,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.source import (
    PRODUCER_BOUND_SOURCE_INTERFACE,
    SourceAdmissionError,
    SourceBindingMismatchError,
    SourceCorruptError,
    SourceFailureKind,
    SourceUnavailableError,
    SourceWrongStateError,
    VerifiedSourceMaterialization,
    line_col_to_byte_offset,
    read_required_source,
    read_source_span,
    source_slice,
    span_to_byte_offsets,
)


REPO = "repo:source-example"


def _make_symbol(
    qualified_name: str,
    source: str,
    *,
    module_path: str = "pkg/mod.py",
    namespace: str = "pkg",
    kind: SymbolKind | str = SymbolKind.FUNCTION,
    span: SourceSpan | None | bool = True,
) -> tuple[SymbolRecord, bytes]:
    raw = source.encode("utf-8")
    node = ast.parse(source).body[0]
    short = qualified_name.rsplit(".", 1)[-1]
    stable = stable_symbol_id(REPO, "python", module_path, qualified_name, kind, namespace)
    sig = {"parameters": [], "return": None}
    version = symbol_version_cid(stable, node, sig, (), {})
    if span is True:
        resolved_span = SourceSpan(
            module_path,
            getattr(node, "lineno", 1),
            getattr(node, "col_offset", 0),
            getattr(node, "end_lineno", getattr(node, "lineno", 1)),
            getattr(node, "end_col_offset", 0),
        )
    elif span is False:
        resolved_span = None
    else:
        resolved_span = span
    record = SymbolRecord(
        stable,
        version,
        REPO,
        "python",
        module_path,
        qualified_name,
        kind,
        namespace,
        cid_for_bytes(raw),
        resolved_span,
        AnalysisConfidence.EXACT,
        sig,
        (),
        {},
        {},
        normalized_ast=node,
    )
    return record, raw


@dataclass
class _SealedView:
    """Minimal ProducerBoundSourceView for tests (no Path fallback)."""

    state: RepositoryState
    blobs: dict[str, bytes] = field(default_factory=dict)
    fail_second_read: bool = False
    _reads: dict[str, int] = field(default_factory=dict)

    @property
    def state_cid(self) -> str:
        return self.state.state_cid

    @property
    def symbols(self):
        return self.state.symbols

    @property
    def edges(self):
        return self.state.edges

    @property
    def artifacts(self):
        return self.state.artifacts

    @property
    def repository_id(self) -> str:
        return self.state.repository_id

    def symbol(self, stable_symbol_id: str) -> SymbolRecord:
        for item in self.state.symbols:
            if item.stable_id == stable_symbol_id:
                return item
        raise KeyError(stable_symbol_id)

    def read_source_blob(self, source_cid: str) -> bytes:
        count = self._reads.get(source_cid, 0)
        self._reads[source_cid] = count + 1
        if self.fail_second_read and count >= 1:
            # TOCTOU: return different bytes on second read.
            return b"mutated-after-first-read!!!!"
        try:
            return self.blobs[source_cid]
        except KeyError as exc:
            raise KeyError(source_cid) from exc


def _view_for(symbol: SymbolRecord, raw: bytes, **kwargs: object) -> _SealedView:
    state = RepositoryState(
        repository_id=REPO, symbols=(symbol,), artifacts=(), edges=()
    )
    assert symbol.source_cid is not None
    return _SealedView(
        state=state,
        blobs={symbol.source_cid: raw},
        **kwargs,  # type: ignore[arg-type]
    )


def test_interface_constant() -> None:
    assert PRODUCER_BOUND_SOURCE_INTERFACE == "ProducerBoundSource@1"


def test_read_required_source_binds_exact_bytes_and_span() -> None:
    source = "def add(value: int) -> int:\n    return value + 1\n"
    symbol, raw = _make_symbol("pkg.add", source)
    view = _view_for(symbol, raw)

    materialization = read_required_source(
        view,
        symbol.stable_id,
        expected_producer_state_cid=view.state_cid,
    )

    assert isinstance(materialization, VerifiedSourceMaterialization)
    assert materialization.source_bytes == raw
    assert materialization.source_cid == symbol.source_cid
    assert materialization.producer_state_cid == view.state_cid
    assert materialization.stable_symbol_id == symbol.stable_id
    evidence = materialization.evidence
    assert evidence.source_slice_path == symbol.module_path
    assert evidence.start_offset == 0
    assert evidence.end_offset == len(raw) or evidence.end_offset <= len(raw)
    # Span bytes are the exact slice.
    assert materialization.span_bytes == raw[evidence.start_offset : evidence.end_offset]
    # Evidence is serializable and self-verifying.
    assert evidence.from_dict(evidence.to_dict()) == evidence
    # Full-file span when offsets cover whole blob is acceptable; AST span is tighter.
    assert evidence.start_offset >= 0
    assert evidence.end_offset >= evidence.start_offset


def test_source_slice_ref_without_bytes() -> None:
    source = "def tip() -> None:\n    pass\n"
    symbol, raw = _make_symbol("pkg.tip", source)
    view = _view_for(symbol, raw)

    ref = source_slice(
        view,
        symbol.stable_id,
        expected_producer_state_cid=view.state_cid,
    )
    assert ref.source_cid == symbol.source_cid
    assert ref.producer_state_cid == view.state_cid
    assert ref.source_slice_path == "pkg/mod.py"
    assert "source_bytes" not in ref.to_dict()


def test_wrong_producer_state_requires_rescan() -> None:
    source = "def f():\n    return 1\n"
    symbol, raw = _make_symbol("pkg.f", source)
    view = _view_for(symbol, raw)
    other_state = cid_for_bytes(b"other-producer-state")

    with pytest.raises(SourceWrongStateError) as excinfo:
        read_required_source(
            view,
            symbol.stable_id,
            expected_producer_state_cid=other_state,
        )
    assert excinfo.value.requires_rescan is True
    assert SourceFailureKind.WRONG_STATE.value in str(excinfo.value)


def test_missing_symbol_is_unavailable() -> None:
    source = "def f():\n    return 1\n"
    symbol, raw = _make_symbol("pkg.f", source)
    view = _view_for(symbol, raw)
    missing = cid_for_bytes(b"no-such-symbol")

    with pytest.raises(SourceUnavailableError) as excinfo:
        read_required_source(
            view,
            missing,
            expected_producer_state_cid=view.state_cid,
        )
    assert excinfo.value.requires_rescan is True


def test_missing_blob_is_unavailable() -> None:
    source = "def f():\n    return 1\n"
    symbol, raw = _make_symbol("pkg.f", source)
    state = RepositoryState(
        repository_id=REPO, symbols=(symbol,), artifacts=(), edges=()
    )
    view = _SealedView(state=state, blobs={})  # no blob registered

    with pytest.raises(SourceUnavailableError) as excinfo:
        read_required_source(
            view,
            symbol.stable_id,
            expected_producer_state_cid=view.state_cid,
        )
    assert excinfo.value.requires_rescan is True


def test_corrupt_bytes_fail_cid_reverify() -> None:
    source = "def f():\n    return 1\n"
    symbol, raw = _make_symbol("pkg.f", source)
    state = RepositoryState(
        repository_id=REPO, symbols=(symbol,), artifacts=(), edges=()
    )
    assert symbol.source_cid is not None
    view = _SealedView(
        state=state,
        blobs={symbol.source_cid: b"not-the-bytes-that-hash-to-source-cid"},
    )

    with pytest.raises(SourceCorruptError) as excinfo:
        read_required_source(
            view,
            symbol.stable_id,
            expected_producer_state_cid=view.state_cid,
        )
    assert excinfo.value.requires_rescan is True
    assert SourceFailureKind.CORRUPT.value in str(excinfo.value)


def test_toctou_second_read_mismatch() -> None:
    source = "def f():\n    return 1\n"
    symbol, raw = _make_symbol("pkg.f", source)
    view = _view_for(symbol, raw, fail_second_read=True)

    with pytest.raises(SourceBindingMismatchError) as excinfo:
        read_required_source(
            view,
            symbol.stable_id,
            expected_producer_state_cid=view.state_cid,
        )
    assert excinfo.value.requires_rescan is True
    assert "TOCTOU" in str(excinfo.value)


def test_injected_reader_without_view_method() -> None:
    source = "def f():\n    return 42\n"
    symbol, raw = _make_symbol("pkg.f", source)
    state = RepositoryState(
        repository_id=REPO, symbols=(symbol,), artifacts=(), edges=()
    )
    assert symbol.source_cid is not None
    blobs = {symbol.source_cid: raw}

    def reader(cid: str) -> bytes:
        return blobs[cid]

    materialization = read_required_source(
        state,
        symbol.stable_id,
        expected_producer_state_cid=state.state_cid,
        read_source_blob=reader,
    )
    assert materialization.source_bytes == raw


def test_no_path_fallback_when_reader_missing() -> None:
    source = "def f():\n    return 1\n"
    symbol, raw = _make_symbol("pkg.f", source)
    state = RepositoryState(
        repository_id=REPO, symbols=(symbol,), artifacts=(), edges=()
    )

    with pytest.raises(SourceUnavailableError) as excinfo:
        read_required_source(
            state,
            symbol.stable_id,
            expected_producer_state_cid=state.state_cid,
        )
    assert "Path" in str(excinfo.value) or "read_source_blob" in str(excinfo.value)


def test_span_offsets_bind_ast_span() -> None:
    source = "def target():\n    return 2\n"
    symbol, raw = _make_symbol("pkg.target", source)
    assert symbol.span is not None
    start, end = span_to_byte_offsets(raw, symbol.span)
    assert 0 <= start < end <= len(raw)
    slice_text = raw[start:end].decode("utf-8")
    assert "def target" in slice_text

    view = _view_for(symbol, raw)
    materialization = read_required_source(
        view,
        symbol.stable_id,
        expected_producer_state_cid=view.state_cid,
    )
    assert materialization.evidence.start_offset == start
    assert materialization.evidence.end_offset == end
    assert materialization.span_bytes == raw[start:end]


def test_full_blob_when_span_absent() -> None:
    source = "def bare():\n    return 0\n"
    symbol, raw = _make_symbol("pkg.bare", source, span=False)
    view = _view_for(symbol, raw)

    materialization = read_required_source(
        view,
        symbol.stable_id,
        expected_producer_state_cid=view.state_cid,
    )
    assert materialization.evidence.start_offset == 0
    assert materialization.evidence.end_offset == len(raw)
    assert materialization.span_bytes == raw


def test_read_source_span_helper_reverifies() -> None:
    source = "def g():\n    return 3\n"
    symbol, raw = _make_symbol("pkg.g", source)
    assert symbol.source_cid is not None
    span_bytes = read_source_span(
        raw, symbol.span, expected_source_cid=symbol.source_cid
    )
    start, end = span_to_byte_offsets(raw, symbol.span)
    assert span_bytes == raw[start:end]

    with pytest.raises(SourceCorruptError):
        read_source_span(b"wrong", symbol.span, expected_source_cid=symbol.source_cid)


def test_line_col_to_byte_offset_basics() -> None:
    data = b"ab\ncd\nef"
    assert line_col_to_byte_offset(data, 1, 0) == 0
    assert line_col_to_byte_offset(data, 1, 2) == 2
    assert line_col_to_byte_offset(data, 2, 0) == 3
    assert line_col_to_byte_offset(data, 3, 1) == 7
    with pytest.raises(SourceUnavailableError):
        line_col_to_byte_offset(data, 99, 0)


def test_span_path_mismatch_is_binding_error() -> None:
    source = "def f():\n    return 1\n"
    symbol, raw = _make_symbol(
        "pkg.f",
        source,
        span=SourceSpan("other/path.py", 1, 0, 2, 10),
    )
    view = _view_for(symbol, raw)

    with pytest.raises(SourceBindingMismatchError) as excinfo:
        read_required_source(
            view,
            symbol.stable_id,
            expected_producer_state_cid=view.state_cid,
        )
    assert SourceFailureKind.BINDING_MISMATCH.value in str(excinfo.value)


def test_materialization_rejects_forged_bytes_post_construction() -> None:
    source = "def f():\n    return 1\n"
    symbol, raw = _make_symbol("pkg.f", source)
    view = _view_for(symbol, raw)
    good = read_required_source(
        view,
        symbol.stable_id,
        expected_producer_state_cid=view.state_cid,
    )
    with pytest.raises(SourceCorruptError):
        VerifiedSourceMaterialization(
            evidence=good.evidence,
            source_bytes=b"forged-payload-not-matching-cid",
        )


def test_never_uses_path_read_even_if_file_exists(tmp_path: Path) -> None:
    """Ambient filesystem must not be consulted for exact source."""
    source = "def f():\n    return 1\n"
    symbol, raw = _make_symbol("pkg.f", source, module_path="pkg/mod.py")
    # Place a misleading file on disk that would be wrong if Path were used.
    target = tmp_path / "pkg" / "mod.py"
    target.parent.mkdir(parents=True)
    target.write_text("def f():\n    return 999  # filesystem trap\n", encoding="utf-8")
    state = RepositoryState(
        repository_id=REPO, symbols=(symbol,), artifacts=(), edges=()
    )

    with pytest.raises(SourceUnavailableError):
        read_required_source(
            state,
            symbol.stable_id,
            expected_producer_state_cid=state.state_cid,
        )
    # Even with cwd pointing at the trap, sealed reader is required.
    assert symbol.source_cid is not None
    materialization = read_required_source(
        state,
        symbol.stable_id,
        expected_producer_state_cid=state.state_cid,
        read_source_blob=lambda cid: raw if cid == symbol.source_cid else b"",
    )
    assert materialization.source_bytes == raw
    assert b"999" not in materialization.source_bytes
