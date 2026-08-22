from __future__ import annotations

import subprocess
import sys

import pytest
from ipfs_datasets_py.logic.backends.smt.compiler import (
    INT_SORT,
    SmtTerm,
    SmtTermKind,
    term_int,
    term_symbol,
)
from ipfs_datasets_py.logic.backends.smt.incremental import (
    IncrementalSmtResult,
    IncrementalSmtStale,
    IncrementalSmtUnavailable,
    SmtCheckStatus,
    open_incremental_smt_session,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap


def _session():
    return open_incremental_smt_session(
        session_id="unit-session",
        translator_identity="sha256:" + "1" * 64,
        theory_fingerprint="sha256:" + "2" * 64,
        policy_root="sha256:" + "3" * 64,
        configuration_root="sha256:" + "4" * 64,
        environment_root="sha256:" + "5" * 64,
    )


def _bound(kind: SmtTermKind, value: int) -> SmtTerm:
    return SmtTerm(kind, arguments=(term_symbol("x"), term_int(value)))


def test_push_pop_named_assertions_and_validated_unsat_core() -> None:
    session = _session()
    session.declare_symbol("x", INT_SORT)
    session.add_named_assertion(
        "lower",
        _bound(SmtTermKind.GE, 3),
        source_ref="source:lower",
        obligation_id="obligation:range",
    )
    assert session.check().status is SmtCheckStatus.SAT
    session.push()
    session.add_named_assertion(
        "upper",
        _bound(SmtTermKind.LE, 2),
        source_ref="source:upper",
        obligation_id="obligation:range",
    )
    result = session.check()
    assert result.status is SmtCheckStatus.UNSAT
    assert result.core_validated
    assert result.unsat_core == ("lower", "upper")
    session.pop()
    assert session.check().status is SmtCheckStatus.SAT


def test_check_with_assumptions_and_model_validation() -> None:
    session = _session()
    session.declare_symbol("x", INT_SORT)
    result = session.check_with_assumptions(
        {
            "lower": _bound(SmtTermKind.GE, 10),
            "upper": _bound(SmtTermKind.LE, 11),
        }
    )
    assert result.status is SmtCheckStatus.SAT
    assert result.model_validated
    assert result.assumption_ids == ("lower", "upper")


def test_stale_session_reuse_is_rejected() -> None:
    session = _session()
    with pytest.raises(IncrementalSmtStale):
        session.assert_fresh("sha256:" + "0" * 64)


def test_cancel_and_close_are_typed() -> None:
    session = _session()
    session.cancel()
    assert session.check().status is SmtCheckStatus.CANCELLED
    session.close()
    with pytest.raises(ValueError, match="closed"):
        session.check()


def test_unqualified_provider_is_typed_unavailable() -> None:
    with pytest.raises(IncrementalSmtUnavailable):
        open_incremental_smt_session(
            session_id="cvc5-session",
            provider="cvc5",
            translator_identity="translator",
            theory_fingerprint="theory",
            policy_root="policy",
            configuration_root="configuration",
            environment_root="environment",
        )


def test_import_keeps_optional_solver_cold() -> None:
    command = (
        "import sys; "
        "import ipfs_datasets_py.logic.backends.smt.incremental; "
        "assert 'z3' not in sys.modules; assert 'cvc5' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_replay_manifest_binds_assertion_sources_and_fingerprint() -> None:
    session = _session()
    session.declare_symbol("x", INT_SORT)
    session.add_named_assertion(
        "lower",
        _bound(SmtTermKind.GE, 0),
        source_ref="source:line:1",
        obligation_id="obligation:1",
    )
    manifest = session.snapshot_or_replay_manifest()
    assert manifest["manifest_cid"].startswith("b")
    assert manifest["assertions"][0]["source_ref"] == "source:line:1"
    assert manifest["fingerprint"]["provider"] == "z3"


def test_operational_statistics_do_not_change_semantic_receipt_identity() -> None:
    common = {
        "session_id": "stable-receipt",
        "session_fingerprint": "sha256:" + "a" * 64,
        "status": SmtCheckStatus.UNSAT,
        "active_assertion_ids": ("assertion:one",),
        "unsat_core": ("assertion:one",),
        "core_validated": True,
    }
    first = IncrementalSmtResult(
        **common,
        statistics=FrozenMap({"num allocs": 10, "memory": "1.0"}),
    )
    second = IncrementalSmtResult(
        **common,
        statistics=FrozenMap({"num allocs": 999, "memory": "2.0"}),
    )
    assert first.to_dict()["statistics"] != second.to_dict()["statistics"]
    assert first.receipt_id == second.receipt_id
