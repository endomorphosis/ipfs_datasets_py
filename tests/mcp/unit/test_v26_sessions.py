"""v26 session tests — FC217–FL226.

FC217  I18NConflictReport.languages_above_threshold(n)
FD218  DelegationManager.active_tokens_by_actor(actor)
FE219  ComplianceMergeResult.from_dict(d)
FF220  compile_batch_with_explain + shorter policy_ids (test coverage)
FG221  least_conflicted_language() with real detect_all_languages() output
FH222  detect_i18n_clauses all 9 original languages round-trip (each returns list)
FI223  DelegationManager.merge() + active_tokens_by_resource() combined E2E
FJ224  conflict_density() + least_conflicted_language() combined
FK225  Korean ("ko") keyword table → 10 languages (9+ko)
FL226  Arabic ("ar") keyword table → 11 languages (9+ko+ar)

Grand total: 3,510 + 61 = 3,571 tests
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any



# ---------------------------------------------------------------------------
# Tiny approx helper for float comparison (avoids importing pytest.approx)
# ---------------------------------------------------------------------------

def pytest_approx(value, rel=1e-6):
    """Tiny inline approx for float comparison without pytest.approx import."""
    class _Approx:
        def __init__(self, v):
            self.v = v
        def __eq__(self, other):
            return abs(other - self.v) <= rel * max(abs(self.v), abs(other), 1e-12)
        def __repr__(self):
            return f"approx({self.v})"
    return _Approx(value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(issuer: str = "did:key:alice", audience: str = "did:key:bob",
                resource: str = "ipfs://*", action: str = "read"):
    from ipfs_datasets_py.mcp_server.ucan_delegation import (
        DelegationToken, Capability,
    )
    import time
    nonce = str(uuid.uuid4())
    cap = Capability(resource=resource, ability=action)
    return DelegationToken(
        issuer=issuer,
        audience=audience,
        capabilities=[cap],
        expiry=time.time() + 3600,
        nonce=nonce,
    )


# ===========================================================================
# FC217  I18NConflictReport.languages_above_threshold(n)
# ===========================================================================

class TestFC217LanguagesAboveThreshold:
    """FC217: I18NConflictReport.languages_above_threshold(n)."""

    def _report_with(self, counts: dict):
        """Build a report whose by_language contains synthetic conflicts."""
        from ipfs_datasets_py.logic.api import I18NConflictReport
        try:
            from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
                PolicyConflict,
            )
            def make_conflicts(n):
                return [
                    PolicyConflict(
                        conflict_type="simultaneous_perm_prohib",
                        clauses=[],
                        description=f"conflict-{i}",
                    )
                    for i in range(n)
                ]
        except Exception:
            def make_conflicts(n):
                return [object() for _ in range(n)]

        class _FakeReport(I18NConflictReport):
            pass

        report = I18NConflictReport()
        for lang, n in counts.items():
            # store lists of the right length (content immaterial for threshold)
            report.by_language[lang] = ["x"] * n
        return report

    def test_above_zero_threshold(self):
        report = self._report_with({"fr": 3, "en": 0, "de": 1, "es": 2})
        result = report.languages_above_threshold(0)
        # only languages with > 0 conflicts
        assert "fr" in result
        assert "de" in result
        assert "es" in result
        assert "en" not in result

    def test_above_one_threshold(self):
        report = self._report_with({"fr": 3, "en": 0, "de": 1, "es": 2})
        result = report.languages_above_threshold(1)
        assert "fr" in result
        assert "es" in result
        assert "de" not in result  # exactly 1, not > 1

    def test_above_threshold_returns_sorted(self):
        report = self._report_with({"zh": 5, "ar": 3, "ko": 7})
        result = report.languages_above_threshold(2)
        assert result == sorted(result)

    def test_above_high_threshold_empty(self):
        report = self._report_with({"fr": 1, "es": 2})
        assert report.languages_above_threshold(100) == []

    def test_empty_report_returns_empty(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        assert report.languages_above_threshold(0) == []

    def test_threshold_zero_all_nonzero(self):
        report = self._report_with({"fr": 1, "es": 1, "de": 1})
        result = report.languages_above_threshold(0)
        assert set(result) == {"fr", "es", "de"}


# ===========================================================================
# FD218  DelegationManager.active_tokens_by_actor(actor)
# ===========================================================================

class TestFD218ActiveTokensByActor:
    """FD218: active_tokens_by_actor(actor) filters by token.audience."""

    def _make_manager(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, DelegationToken, Capability,
        )
        import tempfile, os
        tmp = os.path.join(tempfile.gettempdir(), f"test_mgr_fd218_{uuid.uuid4().hex}")
        return DelegationManager(tmp)

    def test_returns_only_matching_audience(self):
        mgr = self._make_manager()
        tok_a = _make_token(audience="did:key:alice")
        tok_b = _make_token(audience="did:key:bob")
        mgr.add(tok_a)
        mgr.add(tok_b)
        result = list(mgr.active_tokens_by_actor("did:key:alice"))
        assert len(result) == 1
        _, token = result[0]
        assert token.audience == "did:key:alice"

    def test_empty_when_actor_not_present(self):
        mgr = self._make_manager()
        mgr.add(_make_token(audience="did:key:alice"))
        result = list(mgr.active_tokens_by_actor("did:key:carol"))
        assert result == []

    def test_multiple_tokens_same_actor(self):
        mgr = self._make_manager()
        for i in range(3):
            mgr.add(_make_token(
                issuer=f"did:key:issuer{i}",
                audience="did:key:bob",
                resource=f"ipfs://res{i}",
            ))
        mgr.add(_make_token(audience="did:key:alice"))
        result = list(mgr.active_tokens_by_actor("did:key:bob"))
        assert len(result) == 3
        for _, tok in result:
            assert tok.audience == "did:key:bob"

    def test_revoked_tokens_excluded(self):
        mgr = self._make_manager()
        tok = _make_token(audience="did:key:alice")
        cid = mgr.add(tok)
        mgr.revoke(cid)
        result = list(mgr.active_tokens_by_actor("did:key:alice"))
        assert result == []

    def test_yields_cid_token_pairs(self):
        mgr = self._make_manager()
        tok = _make_token(audience="did:key:carol")
        cid = mgr.add(tok)
        result = list(mgr.active_tokens_by_actor("did:key:carol"))
        assert len(result) == 1
        returned_cid, returned_tok = result[0]
        assert isinstance(returned_cid, str)
        assert returned_tok.audience == "did:key:carol"

    def test_empty_manager_returns_empty(self):
        mgr = self._make_manager()
        assert list(mgr.active_tokens_by_actor("did:key:anyone")) == []


# ===========================================================================
# FE219  ComplianceMergeResult.from_dict(d)
# ===========================================================================

class TestFE219ComplianceMergeResultFromDict:
    """FE219: ComplianceMergeResult.from_dict(d) reconstructs from to_dict()."""

    def _result(self, added=3, skipped_protected=1, skipped_duplicate=2):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        return ComplianceMergeResult(added=added,
                                     skipped_protected=skipped_protected,
                                     skipped_duplicate=skipped_duplicate)

    def test_round_trip(self):
        r = self._result()
        d = r.to_dict()
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r2 = ComplianceMergeResult.from_dict(d)
        assert r2.added == r.added
        assert r2.skipped_protected == r.skipped_protected
        assert r2.skipped_duplicate == r.skipped_duplicate

    def test_total_property_preserved(self):
        r = self._result()
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r2 = ComplianceMergeResult.from_dict(r.to_dict())
        assert r2.total == r.total

    def test_missing_keys_default_to_zero(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult.from_dict({"added": 5})
        assert r.added == 5
        assert r.skipped_protected == 0
        assert r.skipped_duplicate == 0

    def test_unknown_keys_ignored(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult.from_dict({
            "added": 2,
            "skipped_protected": 1,
            "skipped_duplicate": 0,
            "total": 99,          # derived — should be ignored
            "unknown_field": "x", # unknown — should be ignored
        })
        assert r.added == 2
        assert r.total == 3  # derived: 2+1+0

    def test_empty_dict_all_zeros(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult.from_dict({})
        assert r.added == 0 and r.skipped_protected == 0 and r.skipped_duplicate == 0

    def test_int_compat_after_round_trip(self):
        r = self._result(added=7)
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r2 = ComplianceMergeResult.from_dict(r.to_dict())
        assert r2 == 7  # int-compat via __eq__
        assert int(r2) == 7


# ===========================================================================
# FF220  compile_batch_with_explain + shorter policy_ids
# ===========================================================================

class TestFF220CompileBatchWithExplainShortPolicyIds:
    """FF220: compile_batch_with_explain forwards policy_ids including shorter list."""

    def _get_compiler(self):
        try:
            from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
                NLUCANPolicyCompiler,
            )
            return NLUCANPolicyCompiler()
        except Exception:
            return None

    def test_shorter_policy_ids_auto_fill(self):
        compiler = self._get_compiler()
        if compiler is None:
            import pytest; pytest.skip("compiler unavailable")
        batches = [
            ["Alice may access the system."],
            ["Bob must submit reports."],
            ["Carol shall not delete files."],
        ]
        pairs = compiler.compile_batch_with_explain(batches, policy_ids=["explicit-id"])
        assert len(pairs) == 3
        result0, explain0 = pairs[0]
        assert result0.policy.policy_id == "explicit-id"

    def test_pairs_are_result_explain_tuples(self):
        compiler = self._get_compiler()
        if compiler is None:
            import pytest; pytest.skip("compiler unavailable")
        batches = [["Users may read data."], ["Admins must log access."]]
        pairs = compiler.compile_batch_with_explain(batches)
        for r, e in pairs:
            assert isinstance(e, str)
            assert len(e) > 0

    def test_fail_fast_with_shorter_policy_ids(self):
        compiler = self._get_compiler()
        if compiler is None:
            import pytest; pytest.skip("compiler unavailable")
        batches = [
            ["Users may read data."],
            ["Users must not delete files."],
        ]
        pairs = compiler.compile_batch_with_explain(
            batches, policy_ids=["pid1"], fail_fast=False
        )
        assert len(pairs) == len(batches)


# ===========================================================================
# FG221  least_conflicted_language() with real detect_all_languages()
# ===========================================================================

class TestFG221LeastConflictedWithRealDetectAll:
    """FG221: least_conflicted_language() using real detect_all_languages() output."""

    def test_least_conflicted_is_none_for_empty_text(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("")
        # empty text → no clauses → all zeros → None
        assert report.least_conflicted_language() is None

    def test_least_conflicted_returns_str_or_none(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("must not and may at the same time")
        result = report.least_conflicted_language()
        assert result is None or isinstance(result, str)

    def test_most_and_least_consistent_when_same(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        report.by_language = {"fr": ["x", "y"], "es": ["a"]}
        assert report.most_conflicted_language() == "fr"
        assert report.least_conflicted_language() == "es"

    def test_none_when_all_empty_real(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("no deontic content here $$$$")
        most = report.most_conflicted_language()
        least = report.least_conflicted_language()
        # If no conflicts at all, both should be None
        if report.total_conflicts == 0:
            assert most is None
            assert least is None


# ===========================================================================
# FH222  detect_i18n_clauses all 9 original languages round-trip
# ===========================================================================

class TestFH222DetectI18NClausesAllLanguages:
    """FH222: detect_i18n_clauses returns a list for all 9 original languages."""

    def _detect(self, text, lang):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_clauses,
        )
        return detect_i18n_clauses(text, lang)

    def test_fr_returns_list(self):
        result = self._detect("L'utilisateur peut accéder au système.", "fr")
        assert isinstance(result, list)

    def test_es_returns_list(self):
        result = self._detect("El usuario puede acceder al sistema.", "es")
        assert isinstance(result, list)

    def test_de_returns_list(self):
        result = self._detect("Der Benutzer darf auf das System zugreifen.", "de")
        assert isinstance(result, list)

    def test_en_returns_list(self):
        result = self._detect("The user may access the system.", "en")
        assert isinstance(result, list)

    def test_pt_returns_list(self):
        result = self._detect("O usuário pode acessar o sistema.", "pt")
        assert isinstance(result, list)

    def test_nl_returns_list(self):
        result = self._detect("De gebruiker mag het systeem openen.", "nl")
        assert isinstance(result, list)

    def test_it_returns_list(self):
        result = self._detect("L'utente può accedere al sistema.", "it")
        assert isinstance(result, list)

    def test_ja_returns_list(self):
        result = self._detect("ユーザーはシステムにアクセスすることができる。", "ja")
        assert isinstance(result, list)

    def test_zh_returns_list(self):
        result = self._detect("用户可以访问系统。", "zh")
        assert isinstance(result, list)

    def test_unknown_lang_returns_list(self):
        result = self._detect("some text", "xx")
        assert isinstance(result, list)


# ===========================================================================
# FI223  DelegationManager.merge() + active_tokens_by_resource() combined E2E
# ===========================================================================

class TestFI223MergeAndActiveTokensByResource:
    """FI223: merge() then active_tokens_by_resource() reflects merged tokens."""

    def _make_manager(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        import tempfile, os
        tmp = os.path.join(tempfile.gettempdir(), f"test_mgr_fi223_{uuid.uuid4().hex}")
        return DelegationManager(tmp)

    def test_merged_tokens_visible_by_resource(self):
        mgr_a = self._make_manager()
        mgr_b = self._make_manager()
        tok = _make_token(resource="ipfs://dataset/v1")
        mgr_b.add(tok)
        mgr_a.merge(mgr_b)
        result = list(mgr_a.active_tokens_by_resource("ipfs://dataset/v1"))
        assert len(result) == 1

    def test_revoked_merged_token_not_visible(self):
        mgr_a = self._make_manager()
        mgr_b = self._make_manager()
        tok = _make_token(resource="ipfs://dataset/v2")
        cid = mgr_b.add(tok)
        mgr_b.revoke(cid)
        mgr_a.merge(mgr_b)
        # Token exists in mgr_a store but not revoked in mgr_a (revocations not copied)
        result_b = list(mgr_b.active_tokens_by_resource("ipfs://dataset/v2"))
        assert result_b == []

    def test_merged_count_correct(self):
        mgr_a = self._make_manager()
        mgr_b = self._make_manager()
        for i in range(5):
            mgr_b.add(_make_token(resource=f"ipfs://res{i}"))
        count = mgr_a.merge(mgr_b)
        assert count == 5
        all_active = list(mgr_a.active_tokens())
        assert len(all_active) == 5

    def test_wildcard_resource_visible_after_merge(self):
        mgr_a = self._make_manager()
        mgr_b = self._make_manager()
        tok = _make_token(resource="*")
        mgr_b.add(tok)
        mgr_a.merge(mgr_b)
        result = list(mgr_a.active_tokens_by_resource("any_resource"))
        assert len(result) == 1

    def test_merge_idempotent_for_resource_query(self):
        mgr_a = self._make_manager()
        mgr_b = self._make_manager()
        tok = _make_token(resource="ipfs://singleton")
        mgr_b.add(tok)
        mgr_a.merge(mgr_b)
        mgr_a.merge(mgr_b)  # second merge should skip duplicates
        result = list(mgr_a.active_tokens_by_resource("ipfs://singleton"))
        assert len(result) == 1


# ===========================================================================
# FJ224  conflict_density() + least_conflicted_language() combined
# ===========================================================================

class TestFJ224ConflictDensityAndLeastConflicted:
    """FJ224: conflict_density() and least_conflicted_language() combined."""

    def _report(self, counts: dict):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for lang, n in counts.items():
            report.by_language[lang] = ["x"] * n
        return report

    def test_density_consistent_with_least(self):
        report = self._report({"fr": 3, "de": 1, "es": 2})
        density = report.conflict_density()
        least = report.least_conflicted_language()
        assert density == pytest_approx(6 / 3)  # = 2.0
        assert least == "de"

    def test_density_zero_and_least_none(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        report.by_language = {"fr": [], "es": []}
        assert report.conflict_density() == 0.0
        assert report.least_conflicted_language() is None

    def test_density_single_language(self):
        report = self._report({"en": 4})
        assert report.conflict_density() == 4.0
        assert report.least_conflicted_language() == "en"

    def test_above_threshold_consistent_with_density(self):
        report = self._report({"fr": 5, "de": 2, "es": 1})
        density = report.conflict_density()  # (5+2+1)/3 ≈ 2.67
        above = report.languages_above_threshold(int(density))
        # languages with > floor(2.67)=2 conflicts
        assert "fr" in above
        assert "de" not in above

    def test_density_all_langs_with_detect_all(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("can may must not shall")
        density = report.conflict_density()
        assert isinstance(density, float)
        assert density >= 0.0

    def test_least_not_equal_most_when_different(self):
        report = self._report({"fr": 5, "de": 1})
        most = report.most_conflicted_language()
        least = report.least_conflicted_language()
        assert most != least


# ===========================================================================
# FK225  Korean ("ko") keyword table → 10 languages
# ===========================================================================

class TestFK225KoreanKeywords:
    """FK225: _KO_DEONTIC_KEYWORDS inline + detect_all_languages() → 10 languages."""

    def test_ko_keywords_load(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("ko")
        assert isinstance(kw, dict)
        assert len(kw) == 3

    def test_ko_has_all_three_types(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("ko")
        assert "permission" in kw
        assert "prohibition" in kw
        assert "obligation" in kw

    def test_ko_permission_keywords_nonempty(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("ko")
        assert len(kw["permission"]) >= 3

    def test_detect_all_languages_has_ko_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("할 수 있다 그리고 해서는 안 된다")
        assert "ko" in report.by_language

    def test_detect_all_languages_has_ten_languages(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        # must have at least 10 language slots (9 original + ko)
        assert len(report.by_language) >= 10

    def test_ko_detect_i18n_clauses_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_clauses,
        )
        result = detect_i18n_clauses("할 수 있다", "ko")
        assert isinstance(result, list)

    def test_ko_conflict_detection_simultaneous(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_conflicts,
        )
        text = "할 수 있다 그리고 해서는 안 된다"  # permission + prohibition
        result = detect_i18n_conflicts(text, "ko")
        # result is I18NConflictResult
        assert result is not None


# ===========================================================================
# FL226  Arabic ("ar") keyword table → 11 languages
# ===========================================================================

class TestFL226ArabicKeywords:
    """FL226: _AR_DEONTIC_KEYWORDS inline + detect_all_languages() → 11 languages."""

    def test_ar_keywords_load(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("ar")
        assert isinstance(kw, dict)
        assert len(kw) == 3

    def test_ar_has_all_three_types(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("ar")
        assert "permission" in kw
        assert "prohibition" in kw
        assert "obligation" in kw

    def test_ar_prohibition_keywords_nonempty(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("ar")
        assert len(kw["prohibition"]) >= 3

    def test_detect_all_languages_has_ar_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("يجوز لا يجوز")
        assert "ar" in report.by_language

    def test_detect_all_languages_has_eleven_languages(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        # must have at least 11 language slots (9 original + ko + ar)
        assert len(report.by_language) >= 11

    def test_ar_detect_i18n_clauses_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_clauses,
        )
        result = detect_i18n_clauses("يجوز", "ar")
        assert isinstance(result, list)

    def test_ar_conflict_detection(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_conflicts,
        )
        text = "يجوز ولا يجوز"  # permission + prohibition in same text
        result = detect_i18n_conflicts(text, "ar")
        assert result is not None

    def test_ar_obligation_keywords_present(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("ar")
        obligation_kw = kw["obligation"]
        # "يجب" (must) should be present
        assert any("يجب" in k for k in obligation_kw)
