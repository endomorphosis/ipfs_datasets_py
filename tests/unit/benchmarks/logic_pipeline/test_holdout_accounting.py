"""Synthetic accounting tests that never open or execute the holdout."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchmarks.logic_pipeline import holdout_reassessment as holdout
from benchmarks.logic_pipeline.contracts import (
    CacheMode,
    StageName,
    TelemetryRecord,
)


def _stage(
    stage: StageName,
    *,
    invoked: bool | None,
    cache_setup: bool = False,
    measured_invoked: bool = True,
    cache_mode: CacheMode | None = None,
    variant_id: str = "A5",
) -> object:
    identity = (
        {}
        if invoked is None
        else {"graph_invoked": invoked}
    )
    return SimpleNamespace(
        stage=stage,
        provenance=SimpleNamespace(effective_identity=identity),
        cache_setup=cache_setup,
        measured_invoked=measured_invoked,
        cache_mode=(
            CacheMode.WARM
            if cache_mode is None and cache_setup
            else cache_mode or CacheMode.COLD
        ),
        variant_id=variant_id,
    )


def _result(*stages: object) -> object:
    return SimpleNamespace(digest="synthetic-result", stages=stages)


def _setup_extractor(stage: object) -> TelemetryRecord | None:
    if not stage.cache_setup:
        return None
    return TelemetryRecord(
        wall_time_ms=2.5,
        model_calls=1,
        retries=0,
    )


def _prime_extractor(stage: object) -> object | None:
    return SimpleNamespace() if stage.cache_setup else None


def _backend_invocation_count(stage: object) -> int:
    return 1 + int(stage.measured_invoked) if stage.cache_setup else 1


def _patch_cache_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        holdout,
        "extract_symai_cache_prime_receipt",
        _prime_extractor,
    )
    monkeypatch.setattr(
        holdout,
        "extract_symai_cache_setup_telemetry",
        _setup_extractor,
    )
    monkeypatch.setattr(
        holdout,
        "symai_backend_invocation_count",
        _backend_invocation_count,
    )


def test_only_invoked_non_kernel_stages_and_warm_setup_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_accounting(monkeypatch)
    result = _result(
        _stage(StageName.COMPILER, invoked=True),
        _stage(StageName.SPACY, invoked=False),
        _stage(StageName.SYMAI, invoked=True, cache_setup=True),
        _stage(StageName.HAMMER, invoked=False),
        _stage(StageName.LEANSTRAL, invoked=True),
        _stage(StageName.KERNEL, invoked=True),
    )

    by_result, setups, backend_calls = (
        holdout._holdout_execution_accounting((result,))
    )

    # compiler + measured SyMAI + Leanstral, plus the separate warm prime.
    assert backend_calls == 4
    assert by_result == {"synthetic-result": setups}
    assert len(setups) == 1
    assert setups[0].model_calls == 1


def test_suppressed_synthetic_stage_records_do_not_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_accounting(monkeypatch)
    result = _result(
        _stage(StageName.COMPILER, invoked=False),
        _stage(StageName.SPACY, invoked=False),
        _stage(StageName.SYMAI, invoked=False),
        _stage(StageName.HAMMER, invoked=False),
        _stage(StageName.LEANSTRAL, invoked=False),
        _stage(StageName.KERNEL, invoked=False),
    )

    _by_result, setups, backend_calls = (
        holdout._holdout_execution_accounting((result,))
    )

    assert backend_calls == 0
    assert setups == ()


def test_suppressed_symai_cannot_hide_prime_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_accounting(monkeypatch)
    result = _result(
        _stage(StageName.SYMAI, invoked=False, cache_setup=True),
    )

    with pytest.raises(
        holdout.HoldoutReassessmentError,
        match="suppressed SyMAI",
    ):
        holdout._holdout_execution_accounting((result,))


def test_holdout_accounting_requires_explicit_graph_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_accounting(monkeypatch)
    result = _result(_stage(StageName.COMPILER, invoked=None))

    with pytest.raises(
        holdout.HoldoutReassessmentError,
        match="explicit graph invocation",
    ):
        holdout._holdout_execution_accounting((result,))


def test_warm_invoked_nonlegacy_symai_requires_prime_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_accounting(monkeypatch)
    result = _result(
        _stage(
            StageName.SYMAI,
            invoked=True,
            cache_mode=CacheMode.WARM,
        ),
    )

    with pytest.raises(
        holdout.HoldoutReassessmentError,
        match="omitted its cache-prime receipt",
    ):
        holdout._holdout_execution_accounting((result,))


def test_warm_legacy_symai_does_not_require_current_prime_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_accounting(monkeypatch)
    result = _result(
        _stage(
            StageName.SYMAI,
            invoked=True,
            cache_mode=CacheMode.WARM,
            variant_id="S1",
        ),
    )

    _by_result, setups, backend_calls = (
        holdout._holdout_execution_accounting((result,))
    )

    assert setups == ()
    assert backend_calls == 1


def test_warm_abort_before_measure_counts_only_the_setup_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_accounting(monkeypatch)
    result = _result(
        _stage(
            StageName.SYMAI,
            invoked=True,
            cache_setup=True,
            measured_invoked=False,
        ),
    )

    _by_result, setups, backend_calls = (
        holdout._holdout_execution_accounting((result,))
    )

    assert len(setups) == 1
    assert backend_calls == 1


def test_warm_attempted_measure_failure_counts_both_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_accounting(monkeypatch)
    result = _result(
        _stage(
            StageName.SYMAI,
            invoked=True,
            cache_setup=True,
            measured_invoked=True,
        ),
    )

    _by_result, setups, backend_calls = (
        holdout._holdout_execution_accounting((result,))
    )

    assert len(setups) == 1
    assert backend_calls == 2
