from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.backends.smt.compiler import (
    SmtTerm,
    SmtTermKind,
    term_and,
    term_false,
    term_int,
    term_not,
    term_symbol,
)
from ipfs_datasets_py.logic.backends.smt.incremental import IncrementalSmtUnavailable
from ipfs_datasets_py.logic.backends.smt.interpolation import (
    FRAGMENT_CHECKER,
    INTERPOLATION_INTERFACE,
    INTERPOLATION_RECEIPT_SCHEMA,
    InterpolationBounds,
    InterpolationError,
    InterpolationStatus,
    ValidatedInterpolantReceipt,
    admit_interpolant,
    compute_and_validate_interpolant,
    probe_interpolation_support,
)


def _range(symbol: str, lower: int, upper: int) -> SmtTerm:
    value = term_symbol(symbol)
    return term_and(
        SmtTerm(SmtTermKind.GE, arguments=(value, term_int(lower))),
        SmtTerm(SmtTermKind.LE, arguments=(value, term_int(upper))),
    )


def _le(symbol: str, upper: int) -> SmtTerm:
    return SmtTerm(SmtTermKind.LE, arguments=(term_symbol(symbol), term_int(upper)))


def _disjoint_unsat() -> tuple[SmtTerm, SmtTerm]:
    return _range("x", 0, 10), _range("x", 20, 30)


def test_exact_provider_theory_support_is_probed() -> None:
    qualified = probe_interpolation_support(provider="cvc5", theory="QF_LIA")
    z3_solver = probe_interpolation_support(provider="z3", theory="QF_LIA")
    other_theory = probe_interpolation_support(provider="cvc5", theory="AUFLIA")
    missing = probe_interpolation_support(provider="mathsat", theory="QF_LIA")

    assert qualified.provider == "cvc5"
    assert qualified.theory == "QF_LIA"
    assert qualified.theory_qualified is True
    assert qualified.provider_qualified is True
    assert qualified.independent_validator == "z3"
    if qualified.provider_installed:
        assert qualified.interpolation_api is True
        assert qualified.interpolation_api_name == "Solver.getInterpolant"
        assert qualified.provider_version not in {"", "unavailable"}
        assert qualified.qualified is qualified.independent_validator_installed
    else:
        assert qualified.qualified is False
        assert "not installed" in qualified.reason

    assert z3_solver.provider_qualified is False
    assert z3_solver.qualified is False
    if z3_solver.provider_installed:
        assert "not qualified interpolation support" in z3_solver.reason
    else:
        assert "not installed" in z3_solver.reason
    assert other_theory.theory_qualified is False
    assert other_theory.qualified is False
    assert missing.provider_installed is False
    assert missing.qualified is False
    assert missing.interpolation_api is False


def test_live_qf_lia_interpolant_is_independently_validated() -> None:
    partition_a, partition_b = _disjoint_unsat()
    capability = probe_interpolation_support(provider="cvc5", theory="QF_LIA")
    receipt = compute_and_validate_interpolant(partition_a, partition_b)
    producer_ready = (
        capability.provider_installed
        and capability.provider_qualified
        and capability.interpolation_api
        and capability.theory_qualified
    )
    if not producer_ready:
        assert receipt.interpolant is None
        assert receipt.status in {
            InterpolationStatus.FALLBACK,
            InterpolationStatus.UNAVAILABLE,
        }
        assert receipt.schema == INTERPOLATION_RECEIPT_SCHEMA
        assert receipt.interface == INTERPOLATION_INTERFACE
        assert receipt.receipt_cid.startswith("b")
        if receipt.status is InterpolationStatus.FALLBACK:
            assert receipt.fallback_kind == "validated_unsat_core"
            assert receipt.fallback_validated is True
            assert receipt.fallback_receipt.startswith("b")
            assert set(receipt.fallback_core) <= {"partition-a", "partition-b"}
            assert receipt.fallback_core
        else:
            assert receipt.fallback_validated is False
            assert receipt.fallback_kind == ""
        return

    assert receipt.status is InterpolationStatus.VALIDATED
    assert receipt.interpolant is not None
    assert set(receipt.interpolant_vocabulary) <= {"x"}
    assert set(receipt.interpolant_vocabulary) <= set(receipt.shared_vocabulary)
    assert receipt.a_implies_i is True
    assert receipt.i_and_b_unsat is True
    assert receipt.shared_vocabulary_ok is True
    assert receipt.identity_ok is True
    assert receipt.bounds_ok is True
    assert receipt.admission_checks_passed is True
    assert receipt.a_implies_i_receipt.startswith("b")
    assert receipt.i_and_b_unsat_receipt.startswith("b")
    assert receipt.receipt_cid.startswith("b")
    assert receipt.partition_a_cid.startswith("b")
    assert receipt.partition_b_cid.startswith("b")
    assert receipt.interpolant_cid.startswith("b")
    assert receipt.schema == INTERPOLATION_RECEIPT_SCHEMA
    assert receipt.interface == INTERPOLATION_INTERFACE
    assert receipt.provider == "cvc5"
    assert receipt.theory == "QF_LIA"
    assert receipt.interpolation_api is True
    assert receipt.fallback_kind == ""
    assert receipt.interpolant is not None

    admitted = admit_interpolant(
        partition_a,
        partition_b,
        receipt.interpolant,
        provider=receipt.provider,
        provider_version=receipt.provider_version,
        interpolation_api=receipt.interpolation_api,
        independent_validator_version=receipt.independent_validator_version,
    )
    assert admitted.status is InterpolationStatus.VALIDATED
    assert admitted.receipt_cid == receipt.receipt_cid


def test_admitted_interpolant_identity_is_stable() -> None:
    partition_a, partition_b = _disjoint_unsat()
    interpolant = _le("x", 15)
    first = admit_interpolant(partition_a, partition_b, interpolant)
    second = admit_interpolant(partition_a, partition_b, interpolant)
    assert first.status is InterpolationStatus.VALIDATED
    assert first.receipt_cid == second.receipt_cid
    assert first.partition_a_cid == second.partition_a_cid
    assert first.interpolant_cid == second.interpolant_cid
    assert first.identity_ok is True
    assert first.checks() == {
        "a_implies_i": True,
        "bounds": True,
        "i_and_b_unsat": True,
        "identity": True,
        "shared_vocabulary": True,
    }

    other = admit_interpolant(partition_a, partition_b, _le("x", 10))
    assert other.status is InterpolationStatus.VALIDATED
    assert other.receipt_cid != first.receipt_cid
    assert other.partition_a_cid == first.partition_a_cid


def test_invalid_vocabulary_is_rejected_without_fabrication() -> None:
    receipt = admit_interpolant(*_disjoint_unsat(), _le("y", 0))
    assert receipt.status is InterpolationStatus.INVALID
    assert receipt.shared_vocabulary_ok is False
    assert receipt.interpolant is not None
    assert "y" in receipt.interpolant_vocabulary
    assert "y" not in receipt.shared_vocabulary
    assert receipt.a_implies_i is False
    assert receipt.i_and_b_unsat is False
    assert "shared vocabulary" in receipt.reason


def test_invalid_implication_is_rejected() -> None:
    receipt = admit_interpolant(*_disjoint_unsat(), _le("x", 5))
    assert receipt.status is InterpolationStatus.INVALID
    assert receipt.shared_vocabulary_ok is True
    assert receipt.bounds_ok is True
    assert receipt.a_implies_i is False
    assert receipt.reason == "A does not imply I"
    assert receipt.a_implies_i_receipt.startswith("b")


def test_invalid_i_and_b_unsat_is_rejected() -> None:
    receipt = admit_interpolant(*_disjoint_unsat(), _le("x", 30))
    assert receipt.status is InterpolationStatus.INVALID
    assert receipt.a_implies_i is True
    assert receipt.i_and_b_unsat is False
    assert receipt.reason == "I and B is not unsatisfiable"
    assert receipt.i_and_b_unsat_receipt.startswith("b")


def test_bounds_check_rejects_oversized_terms() -> None:
    receipt = admit_interpolant(
        *_disjoint_unsat(),
        _le("x", 15),
        bounds=InterpolationBounds(max_term_nodes=1),
    )
    assert receipt.status is InterpolationStatus.INVALID
    assert receipt.bounds_ok is False
    assert "max_term_nodes" in receipt.reason
    assert receipt.a_implies_i is False


def test_compute_bounds_check_rejects_oversized_partitions() -> None:
    receipt = compute_and_validate_interpolant(
        *_disjoint_unsat(),
        bounds=InterpolationBounds(max_term_nodes=1),
    )
    assert receipt.status is InterpolationStatus.INVALID
    assert receipt.interpolant is None
    assert receipt.bounds_ok is False
    assert "max_term_nodes" in receipt.reason


def test_unqualified_theory_is_typed_unsupported() -> None:
    receipt = compute_and_validate_interpolant(
        *_disjoint_unsat(),
        theory="AUFLIA",
    )
    assert receipt.status is InterpolationStatus.UNSUPPORTED
    assert receipt.interpolant is None
    assert receipt.fallback_validated is False
    capability = probe_interpolation_support(provider="cvc5", theory="AUFLIA")
    assert capability.theory_qualified is False
    assert capability.qualified is False


def test_solver_availability_is_not_interpolation_support() -> None:
    capability = probe_interpolation_support(provider="z3", theory="QF_LIA")
    assert capability.qualified is False
    assert capability.provider_qualified is False
    receipt = compute_and_validate_interpolant(*_disjoint_unsat(), provider="z3")
    assert receipt.interpolant is None
    assert receipt.status is InterpolationStatus.FALLBACK
    assert receipt.fallback_kind == "validated_unsat_core"
    assert receipt.fallback_validated is True
    assert receipt.fallback_receipt.startswith("b")
    assert set(receipt.fallback_core) <= {"partition-a", "partition-b"}
    assert receipt.fallback_core
    if capability.provider_installed:
        assert "not qualified interpolation support" in receipt.reason
    else:
        assert "not installed" in receipt.reason


def test_unavailable_interpolation_uses_validated_unsat_core_fallback() -> None:
    receipt = compute_and_validate_interpolant(
        *_disjoint_unsat(),
        provider="mathsat",
    )
    assert receipt.status is InterpolationStatus.FALLBACK
    assert receipt.interpolant is None
    assert receipt.interpolation_api is False
    assert receipt.fallback_kind == "validated_unsat_core"
    assert receipt.fallback_validated is True
    assert receipt.fallback_receipt.startswith("b")
    assert receipt.schema == INTERPOLATION_RECEIPT_SCHEMA
    assert receipt.receipt_cid.startswith("b")
    assert "not installed" in receipt.reason


def test_unavailable_providers_without_validator_stay_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _blocked(**_kwargs: object) -> object:
        raise IncrementalSmtUnavailable("blocked independent validator")

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.backends.smt.interpolation.open_incremental_smt_session",
        _blocked,
    )
    receipt = compute_and_validate_interpolant(*_disjoint_unsat(), provider="absent")
    # Z3 may be absent while the local QF_LIA fragment checker can still
    # validate an unsat-core fallback.  That is typed fallback authority, not
    # an interpolant.
    assert receipt.interpolant is None
    assert "not installed" in receipt.reason
    assert receipt.status is InterpolationStatus.FALLBACK
    assert receipt.fallback_kind == "validated_unsat_core"
    assert receipt.fallback_validated is True
    assert receipt.fallback_receipt.startswith("b")
    assert set(receipt.fallback_core) <= {"partition-a", "partition-b"}
    assert receipt.independent_validator in {"z3", FRAGMENT_CHECKER}


def test_unavailable_providers_without_any_checker_stay_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _blocked(**_kwargs: object) -> object:
        raise IncrementalSmtUnavailable("blocked independent validator")

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.backends.smt.interpolation.open_incremental_smt_session",
        _blocked,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.backends.smt.interpolation._qf_lia_sat",
        lambda *_args, **_kwargs: None,
    )
    receipt = compute_and_validate_interpolant(*_disjoint_unsat(), provider="absent")
    assert receipt.status is InterpolationStatus.UNAVAILABLE
    assert receipt.interpolant is None
    assert receipt.fallback_validated is False
    assert receipt.fallback_kind == ""
    assert "not installed" in receipt.reason
    assert "unsat-core fallback unavailable" in receipt.reason


def test_installed_provider_without_interpolation_api_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = SimpleNamespace(__version__="1.0.0", Solver=type("Solver", (), {}))
    real_load = probe_interpolation_support.__globals__["_load_module"]

    def _load(name: str) -> object | None:
        if name == "cvc5":
            return fake
        return real_load(name)

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.backends.smt.interpolation._load_module",
        _load,
    )
    capability = probe_interpolation_support(provider="cvc5", theory="QF_LIA")
    assert capability.provider_installed is True
    assert capability.interpolation_api is False
    assert capability.qualified is False
    receipt = compute_and_validate_interpolant(*_disjoint_unsat())
    assert receipt.interpolant is None
    assert receipt.status is InterpolationStatus.FALLBACK
    assert receipt.fallback_validated is True
    assert "no interpolation API" in receipt.reason


def test_noncallable_provider_interpolation_attribute_is_not_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = SimpleNamespace(
        __version__="1.0.0",
        Solver=type("Solver", (), {"getInterpolant": object()}),
    )
    real_load = probe_interpolation_support.__globals__["_load_module"]

    def _load(name: str) -> object | None:
        if name == "cvc5":
            return fake
        return real_load(name)

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.backends.smt.interpolation._load_module",
        _load,
    )
    capability = probe_interpolation_support(provider="cvc5", theory="QF_LIA")
    assert capability.provider_installed is True
    assert capability.interpolation_api is False
    assert capability.qualified is False


def test_non_linear_terms_are_rejected_outside_qualified_qf_lia() -> None:
    x = term_symbol("x")
    y = term_symbol("y")
    nonlinear_a = SmtTerm(
        SmtTermKind.LE,
        arguments=(
            SmtTerm(SmtTermKind.MUL, arguments=(x, y)),
            term_int(1),
        ),
    )
    receipt = compute_and_validate_interpolant(nonlinear_a, _le("x", 0))
    assert receipt.status is InterpolationStatus.INVALID
    assert receipt.interpolant is None
    assert receipt.bounds_ok is False
    assert "outside the qualified QF_LIA fragment" in receipt.reason
    assert "non-linear multiplication" in receipt.reason


def test_jointly_satisfiable_partitions_do_not_admit_an_interpolant() -> None:
    receipt = compute_and_validate_interpolant(_range("x", 0, 1), _range("y", 2, 3), provider="z3")
    assert receipt.interpolant is None
    assert receipt.status is InterpolationStatus.UNAVAILABLE
    assert receipt.fallback_validated is False
    assert "jointly satisfiable" in receipt.reason


def test_validated_receipt_requires_interpolant_and_all_checks() -> None:
    with pytest.raises(InterpolationError, match="validated receipt requires an interpolant"):
        ValidatedInterpolantReceipt(
            status=InterpolationStatus.VALIDATED,
            partition_a_cid="baaaaaaaa",
            partition_b_cid="bbbbbbbbb",
            shared_vocabulary=(),
            interpolant=None,
            interpolant_vocabulary=(),
            provider="cvc5",
            provider_version="1.3.3",
            theory="QF_LIA",
        )
    with pytest.raises(InterpolationError, match="all admission checks"):
        ValidatedInterpolantReceipt(
            status=InterpolationStatus.VALIDATED,
            partition_a_cid="baaaaaaaa",
            partition_b_cid="bbbbbbbbb",
            shared_vocabulary=("x",),
            interpolant=_le("x", 10),
            interpolant_vocabulary=("x",),
            provider="cvc5",
            provider_version="1.3.3",
            theory="QF_LIA",
            a_implies_i=True,
            i_and_b_unsat=True,
            shared_vocabulary_ok=True,
            identity_ok=True,
            bounds_ok=False,
        )


def test_fallback_receipt_cannot_fabricate_an_interpolant() -> None:
    with pytest.raises(InterpolationError, match="must not fabricate"):
        ValidatedInterpolantReceipt(
            status=InterpolationStatus.FALLBACK,
            partition_a_cid="baaaaaaaa",
            partition_b_cid="bbbbbbbbb",
            shared_vocabulary=("x",),
            interpolant=_le("x", 10),
            interpolant_vocabulary=("x",),
            provider="z3",
            provider_version="4.15.4",
            theory="QF_LIA",
            fallback_kind="validated_unsat_core",
            fallback_receipt="bcore",
            fallback_validated=True,
        )
    with pytest.raises(InterpolationError, match="validated fallback authority"):
        ValidatedInterpolantReceipt(
            status=InterpolationStatus.FALLBACK,
            partition_a_cid="baaaaaaaa",
            partition_b_cid="bbbbbbbbb",
            shared_vocabulary=("x",),
            interpolant=None,
            interpolant_vocabulary=(),
            provider="z3",
            provider_version="4.15.4",
            theory="QF_LIA",
        )


def test_malformed_requests_are_rejected() -> None:
    with pytest.raises(InterpolationError, match="partition_a"):
        compute_and_validate_interpolant(None, _range("x", 0, 1))  # type: ignore[arg-type]
    with pytest.raises(InterpolationError, match="positive integer"):
        InterpolationBounds(timeout_ms=0)
    with pytest.raises(InterpolationError, match="unsupported interpolation receipt schema"):
        ValidatedInterpolantReceipt(
            status=InterpolationStatus.UNAVAILABLE,
            partition_a_cid="baaaaaaaa",
            partition_b_cid="bbbbbbbbb",
            shared_vocabulary=(),
            interpolant=None,
            interpolant_vocabulary=(),
            provider="cvc5",
            provider_version="unavailable",
            theory="QF_LIA",
            schema="validated-craig-interpolant/v0",
        )


def test_import_keeps_optional_solver_cold() -> None:
    command = (
        "import sys; "
        "import ipfs_datasets_py.logic.backends.smt.interpolation; "
        "assert 'z3' not in sys.modules; assert 'cvc5' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_fragment_checker_admits_interpolant_when_z3_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _blocked(**_kwargs: object) -> object:
        raise IncrementalSmtUnavailable("blocked independent validator")

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.backends.smt.interpolation.open_incremental_smt_session",
        _blocked,
    )
    receipt = admit_interpolant(*_disjoint_unsat(), _le("x", 15))
    assert receipt.status is InterpolationStatus.VALIDATED
    assert receipt.independent_validator == FRAGMENT_CHECKER
    assert receipt.a_implies_i is True
    assert receipt.i_and_b_unsat is True
    assert receipt.shared_vocabulary_ok is True
    assert receipt.identity_ok is True
    assert receipt.bounds_ok is True
    assert receipt.a_implies_i_receipt.startswith("b")
    assert receipt.i_and_b_unsat_receipt.startswith("b")
    rejected = admit_interpolant(*_disjoint_unsat(), _le("x", 5))
    assert rejected.status is InterpolationStatus.INVALID
    assert rejected.a_implies_i is False
    assert rejected.reason == "A does not imply I"


def test_constant_false_interpolant_is_admitted_when_a_is_unsat() -> None:
    partition_a = term_and(_le("x", 1), term_not(_le("x", 1)))
    partition_b = _range("y", 0, 3)
    receipt = admit_interpolant(partition_a, partition_b, term_false())
    assert receipt.status is InterpolationStatus.VALIDATED
    assert receipt.interpolant_vocabulary == ()
    assert receipt.shared_vocabulary == ()
    assert receipt.shared_vocabulary_ok is True
    assert receipt.a_implies_i is True
    assert receipt.i_and_b_unsat is True
