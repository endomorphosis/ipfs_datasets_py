"""Independent review regressions for current property evidence accounting."""

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as profile
from ipfs_datasets_py.logic.software_contracts.codebase_integer_verification import CodebaseIntegerVerifier
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import CodebasePropertyCache
from .test_codebase_current import repository, scheduler, current_index, publish


def test_unavailable_solvers_do_not_claim_native_replay(repository, scheduler, current_index, tmp_path, monkeypatch):
    owner, _, _ = scheduler
    index, _, _ = current_index
    head = publish(index, repository, owner, "initial").head
    verifier = CodebaseIntegerVerifier(index, CodebasePropertyCache(tmp_path / "history"))
    original = profile.shutil.which
    monkeypatch.setattr(profile.shutil, "which", lambda name: None if name in {"z3", "cvc5"} else original(name))
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", lambda *a, **k: pytest.fail("unavailable checker was launched"))
    result = verifier.verify(repository, expected_head=head,
                             contract=profile.IntegerOffsetContract("counter.py", "increment", "n", 1),
                             scheduler=owner)
    assert result["status"] == "unavailable"
    assert result["solver_check_attempted"] is True
    assert result["solver_replayed"] is False
    assert all(observation["status"] == "unavailable" and not observation["verdict"]
               for observation in result["checks"]["solvers"])
    assert result["cache_binding"] is None and result["cache_history_hit"] is False
    assert result["kernel_checked"] is result["completion_authority"] is False
    assert not tuple(verifier.cache._cache.index_root.rglob("*.json"))
    assert owner.snapshot()["active_lease_count"] == 0


def test_unsupported_source_never_claims_checker_attempt(repository, scheduler, current_index, tmp_path, monkeypatch):
    owner, _, _ = scheduler
    index, _, _ = current_index
    (repository / "counter.py").write_text("def increment(n):\n    return n + 1\n")
    head = publish(index, repository, owner, "initial").head
    verifier = CodebaseIntegerVerifier(index, CodebasePropertyCache(tmp_path / "history"))
    monkeypatch.setattr(profile, "execute_integer_offset", lambda *a, **k: pytest.fail("unsupported source executed"))
    result = verifier.verify(repository, expected_head=head,
                             contract=profile.IntegerOffsetContract("counter.py", "increment", "n", 1),
                             scheduler=owner)
    assert result["status"] == "unsupported"
    assert result["solver_check_attempted"] is False
    assert result["solver_replayed"] is False
    assert result["checks"] is None
    assert result["cache_binding"] is None
    assert owner.snapshot()["active_lease_count"] == 0


@pytest.mark.parametrize("offset,forged_status", [(1, "refuted"), (2, "proved")])
def test_terminal_claim_must_agree_with_both_fresh_native_verdicts(
    repository, scheduler, current_index, tmp_path, monkeypatch, offset, forged_status,
):
    from ipfs_datasets_py.logic.software_contracts.codebase_integer_verification import CodebaseVerificationError

    owner, _, _ = scheduler
    index, _, _ = current_index
    head = publish(index, repository, owner, "initial").head
    verifier = CodebaseIntegerVerifier(index, CodebasePropertyCache(tmp_path / "history"))
    native = profile.execute_integer_offset

    def contradictory(*args, **kwargs):
        result = native(*args, **kwargs)
        assert result["status"] in {"proved", "refuted"}
        assert result["status"] != forged_status
        return {**result, "status": forged_status}

    monkeypatch.setattr(profile, "execute_integer_offset", contradictory)
    with pytest.raises(CodebaseVerificationError, match="verdict"):
        verifier.verify(repository, expected_head=head,
                        contract=profile.IntegerOffsetContract("counter.py", "increment", "n", offset),
                        scheduler=owner)
    assert not tuple(verifier.cache._cache.index_root.rglob("*.json"))
    assert owner.snapshot()["active_lease_count"] == 0
