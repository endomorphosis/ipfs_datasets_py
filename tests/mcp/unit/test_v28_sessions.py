"""v28 session tests — FW237–GF246.

FW237  Swedish text → detect_i18n_clauses("sv") + detect_all_languages() E2E
FX238  Russian text → detect_i18n_clauses("ru") + detect_all_languages() E2E
FY239  detect_all_languages() all 13 original slots are list-typed (non-None)
FZ240  conflict_density() with synthetic fully-populated 13-language report
GA241  Greek ("el") keyword table → 14 languages
GB242  Turkish ("tr") keyword table → 15 languages
GC243  Hindi ("hi") keyword table → 16 languages
GD244  languages_above_threshold(n) with many slots populated
GE245  active_tokens_by_actor() + revoke() + active_token_count combined
GF246  Full pipeline E2E: detect_all_languages() → I18NConflictReport → compile_batch()

Grand total: 3,633 + 62 = 3,695 tests
"""

from __future__ import annotations

import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Tiny approx helper (no pytest dependency)
# ---------------------------------------------------------------------------

def pytest_approx(value, rel=1e-6):
    class _Approx:
        def __init__(self, v):
            self.v = v
        def __eq__(self, other):
            return abs(other - self.v) <= rel * max(abs(self.v), abs(other), 1e-12)
        def __repr__(self):
            return f"approx({self.v})"
    return _Approx(value)


# ---------------------------------------------------------------------------
# FW237 — Swedish text E2E
# ---------------------------------------------------------------------------

class TestFW237SwedishE2E:
    """FW237: Swedish deontic text → detect_i18n_clauses("sv") returns list."""

    def _detector(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_clauses, _load_i18n_keywords,
        )
        return detect_i18n_clauses, _load_i18n_keywords

    def test_sv_keywords_loaded(self):
        _, load = self._detector()
        kw = load("sv")
        assert isinstance(kw, dict)
        assert len(kw) == 3

    def test_sv_permission_keywords_present(self):
        _, load = self._detector()
        kw = load("sv")
        assert "permission" in kw
        assert any("får" in k for k in kw["permission"])

    def test_sv_prohibition_keyword_present(self):
        _, load = self._detector()
        kw = load("sv")
        assert "prohibition" in kw
        assert any("får inte" in k or "förbjudet" in k for k in kw["prohibition"])

    def test_sv_obligation_keyword_present(self):
        _, load = self._detector()
        kw = load("sv")
        assert "obligation" in kw
        assert any("måste" in k or "ska" in k for k in kw["obligation"])

    def test_detect_sv_returns_list(self):
        detect, _ = self._detector()
        result = detect("Det är förbjudet att läsa dokumentet.", "sv")
        assert isinstance(result, list)

    def test_detect_all_has_sv_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("får inte")
        assert "sv" in report.by_language
        assert isinstance(report.by_language["sv"], list)


# ---------------------------------------------------------------------------
# FX238 — Russian text E2E
# ---------------------------------------------------------------------------

class TestFX238RussianE2E:
    """FX238: Russian deontic text → detect_i18n_clauses("ru") returns list."""

    def _detector(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_clauses, _load_i18n_keywords,
        )
        return detect_i18n_clauses, _load_i18n_keywords

    def test_ru_keywords_loaded(self):
        _, load = self._detector()
        kw = load("ru")
        assert isinstance(kw, dict)
        assert len(kw) == 3

    def test_ru_permission_keyword_present(self):
        _, load = self._detector()
        kw = load("ru")
        assert "можно" in kw.get("permission", [])

    def test_ru_prohibition_keyword_present(self):
        _, load = self._detector()
        kw = load("ru")
        assert "запрещено" in kw.get("prohibition", [])

    def test_ru_obligation_keyword_present(self):
        _, load = self._detector()
        kw = load("ru")
        assert "должен" in kw.get("obligation", [])

    def test_detect_ru_returns_list(self):
        detect, _ = self._detector()
        result = detect("Пользователь должен соблюдать правила.", "ru")
        assert isinstance(result, list)

    def test_detect_all_has_ru_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("запрещено использование")
        assert "ru" in report.by_language
        assert isinstance(report.by_language["ru"], list)


# ---------------------------------------------------------------------------
# FY239 — all 13 original slots are list-typed
# ---------------------------------------------------------------------------

class TestFY239All13SlotsListTyped:
    """FY239: detect_all_languages() all 13 original slots are list instances."""

    _ORIGINAL_13 = ("fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh", "ko", "ar", "sv", "ru")

    def test_all_original_13_slots_present(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        for lang in self._ORIGINAL_13:
            assert lang in report.by_language, f"Missing slot: {lang}"

    def test_all_original_13_slots_are_list(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        for lang in self._ORIGINAL_13:
            assert isinstance(report.by_language[lang], list), (
                f"Slot {lang!r} is not a list: {type(report.by_language[lang])}"
            )

    def test_all_original_13_slots_not_none(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        for lang in self._ORIGINAL_13:
            assert report.by_language[lang] is not None

    def test_empty_text_all_slots_empty_list(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("")
        for lang in self._ORIGINAL_13:
            assert report.by_language[lang] == []

    def test_conflict_density_with_13_denominator(self):
        from ipfs_datasets_py.logic.api import detect_all_languages, I18NConflictReport
        report = detect_all_languages("")
        # All slots empty → density == 0.0
        assert report.conflict_density() == 0.0

    def test_total_conflicts_zero_for_empty_text(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("")
        assert report.total_conflicts == 0


# ---------------------------------------------------------------------------
# FZ240 — conflict_density() with synthetic 13-lang populated report
# ---------------------------------------------------------------------------

class TestFZ240ConflictDensitySynthetic13:
    """FZ240: conflict_density() with synthetic 13-lang populated report."""

    def _make_report(self, counts: dict):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import PolicyConflict
        r = I18NConflictReport()
        for lang, n in counts.items():
            r.by_language[lang] = [
                PolicyConflict(conflict_type="simultaneous_perm_prohib", action=f"act_{i}")
                for i in range(n)
            ]
        return r

    def test_density_zero_for_empty(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        r = I18NConflictReport()
        assert r.conflict_density() == 0.0

    def test_density_single_lang_one_conflict(self):
        r = self._make_report({"fr": 1})
        # 1 conflict / 1 language slot
        assert r.conflict_density() == pytest_approx(1.0)

    def test_density_13_langs_each_one_conflict(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import PolicyConflict
        langs = ("fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh", "ko", "ar", "sv", "ru")
        r = I18NConflictReport()
        for lang in langs:
            r.by_language[lang] = [PolicyConflict("simultaneous_perm_prohib", "act")]
        assert r.conflict_density() == pytest_approx(1.0)

    def test_density_scales_correctly(self):
        r = self._make_report({"fr": 3, "es": 3, "de": 3})
        # 9 / 3 = 3.0
        assert r.conflict_density() == pytest_approx(3.0)

    def test_density_mixed_empty_and_nonempty(self):
        r = self._make_report({"fr": 2, "es": 0, "de": 1})
        # 3 / 3 = 1.0
        assert r.conflict_density() == pytest_approx(1.0)

    def test_density_13_langs_varied(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import PolicyConflict
        langs = ("fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh", "ko", "ar", "sv", "ru")
        r = I18NConflictReport()
        total = 0
        for i, lang in enumerate(langs):
            count = i % 3  # 0,1,2,0,1,2...
            r.by_language[lang] = [
                PolicyConflict("simultaneous_perm_prohib", "act") for _ in range(count)
            ]
            total += count
        expected = total / 13
        assert r.conflict_density() == pytest_approx(expected)


# ---------------------------------------------------------------------------
# GA241 — Greek keyword table → 14 languages
# ---------------------------------------------------------------------------

class TestGA241GreekKeywords:
    """GA241: _EL_DEONTIC_KEYWORDS + detect_all_languages() → 14 languages."""

    def test_el_keywords_load(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("el")
        assert isinstance(kw, dict)
        assert set(kw.keys()) >= {"permission", "prohibition", "obligation"}

    def test_el_permission_keyword(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("el")
        assert any("μπορεί" in k or "επιτρέπεται" in k for k in kw.get("permission", []))

    def test_el_prohibition_keyword(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("el")
        assert any("απαγορεύεται" in k for k in kw.get("prohibition", []))

    def test_el_obligation_keyword(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("el")
        assert any("πρέπει" in k or "υποχρεούται" in k for k in kw.get("obligation", []))

    def test_detect_el_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_clauses
        result = detect_i18n_clauses("Απαγορεύεται η πρόσβαση.", "el")
        assert isinstance(result, list)

    def test_detect_all_has_el_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("απαγορεύεται")
        assert "el" in report.by_language
        assert isinstance(report.by_language["el"], list)

    def test_detect_all_at_least_14_langs(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert len(report.by_language) >= 14


# ---------------------------------------------------------------------------
# GB242 — Turkish keyword table → 15 languages
# ---------------------------------------------------------------------------

class TestGB242TurkishKeywords:
    """GB242: _TR_DEONTIC_KEYWORDS + detect_all_languages() → 15 languages."""

    def test_tr_keywords_load(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("tr")
        assert isinstance(kw, dict)
        assert set(kw.keys()) >= {"permission", "prohibition", "obligation"}

    def test_tr_permission_keyword(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("tr")
        assert any("yapabilir" in k or "izinlidir" in k for k in kw.get("permission", []))

    def test_tr_prohibition_keyword(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("tr")
        assert any("yasaktır" in k or "yapamaz" in k for k in kw.get("prohibition", []))

    def test_tr_obligation_keyword(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("tr")
        assert any("zorundadır" in k or "gereklidir" in k for k in kw.get("obligation", []))

    def test_detect_tr_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_clauses
        result = detect_i18n_clauses("Kullanıcı zorundadır.", "tr")
        assert isinstance(result, list)

    def test_detect_all_has_tr_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("yasaktır")
        assert "tr" in report.by_language
        assert isinstance(report.by_language["tr"], list)

    def test_detect_all_at_least_15_langs(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert len(report.by_language) >= 15


# ---------------------------------------------------------------------------
# GC243 — Hindi keyword table → 16 languages
# ---------------------------------------------------------------------------

class TestGC243HindiKeywords:
    """GC243: _HI_DEONTIC_KEYWORDS + detect_all_languages() → 16 languages."""

    def test_hi_keywords_load(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("hi")
        assert isinstance(kw, dict)
        assert set(kw.keys()) >= {"permission", "prohibition", "obligation"}

    def test_hi_permission_keyword(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("hi")
        assert any("अनुमति है" in k or "अधिकार है" in k for k in kw.get("permission", []))

    def test_hi_prohibition_keyword(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("hi")
        assert any("प्रतिबंधित है" in k or "निषिद्ध है" in k for k in kw.get("prohibition", []))

    def test_hi_obligation_keyword(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("hi")
        assert any("करना होगा" in k or "अनिवार्य है" in k for k in kw.get("obligation", []))

    def test_detect_hi_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_clauses
        result = detect_i18n_clauses("यह अनिवार्य है।", "hi")
        assert isinstance(result, list)

    def test_detect_all_has_hi_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("प्रतिबंधित है")
        assert "hi" in report.by_language
        assert isinstance(report.by_language["hi"], list)

    def test_detect_all_at_least_16_langs(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert len(report.by_language) >= 16


# ---------------------------------------------------------------------------
# GD244 — languages_above_threshold(n) with many slots
# ---------------------------------------------------------------------------

class TestGD244LanguagesAboveThresholdManySlots:
    """GD244: languages_above_threshold(n) with many slots populated."""

    def _make_report_with_13_langs(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import PolicyConflict
        langs = ("fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh", "ko", "ar", "sv", "ru")
        r = I18NConflictReport()
        for i, lang in enumerate(langs):
            # Vary counts: 0, 1, 2, 0, 1, 2, ...
            count = i % 3
            r.by_language[lang] = [
                PolicyConflict("simultaneous_perm_prohib", "act") for _ in range(count)
            ]
        return r

    def test_threshold_0_returns_languages_with_conflicts(self):
        r = self._make_report_with_13_langs()
        above_0 = r.languages_above_threshold(0)
        with_conflicts = sorted(r.languages_with_conflicts)
        assert above_0 == with_conflicts

    def test_threshold_1_subset_of_threshold_0(self):
        r = self._make_report_with_13_langs()
        above_0 = set(r.languages_above_threshold(0))
        above_1 = set(r.languages_above_threshold(1))
        assert above_1 <= above_0

    def test_threshold_100_empty(self):
        r = self._make_report_with_13_langs()
        assert r.languages_above_threshold(100) == []

    def test_threshold_sorted_output(self):
        r = self._make_report_with_13_langs()
        result = r.languages_above_threshold(0)
        assert result == sorted(result)

    def test_threshold_exact_boundary(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import PolicyConflict
        r = I18NConflictReport()
        r.by_language["fr"] = [PolicyConflict("simultaneous_perm_prohib", "act")]
        r.by_language["es"] = []
        # threshold(0) → ["fr"]; threshold(1) → [] because > 1 required
        assert r.languages_above_threshold(0) == ["fr"]
        assert r.languages_above_threshold(1) == []

    def test_threshold_all_same_count(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import PolicyConflict
        r = I18NConflictReport()
        for lang in ("fr", "es", "de"):
            r.by_language[lang] = [PolicyConflict("simultaneous_perm_prohib", "act")]
        assert set(r.languages_above_threshold(0)) == {"fr", "es", "de"}
        assert r.languages_above_threshold(1) == []


# ---------------------------------------------------------------------------
# GE245 — active_tokens_by_actor + revoke + active_token_count combined
# ---------------------------------------------------------------------------

class TestGE245ActiveTokensByActorRevokeCombined:
    """GE245: active_tokens_by_actor() + revoke() + active_token_count combined."""

    def _make_manager(self):
        import tempfile, os
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, DelegationToken, Capability,
        )
        td = tempfile.mkdtemp()
        mgr = DelegationManager(os.path.join(td, "store.json"))
        return mgr, DelegationToken, Capability

    def _make_token(self, TokenCls, CapCls, audience: str, resource: str = "docs/*"):
        return TokenCls(
            issuer="did:key:issuer",
            audience=audience,
            capabilities=[CapCls(resource=resource, ability="tools/invoke")],
            expiry=time.time() + 3600,
            nonce=uuid.uuid4().hex,
        )

    def test_revoke_removes_from_active_tokens_by_actor(self):
        mgr, Tok, Cap = self._make_manager()
        t = self._make_token(Tok, Cap, "alice")
        cid = mgr.add(t)
        assert any(c == cid for c, _ in mgr.active_tokens_by_actor("alice"))
        mgr.revoke(cid)
        assert not any(c == cid for c, _ in mgr.active_tokens_by_actor("alice"))

    def test_active_token_count_decreases_after_revoke(self):
        mgr, Tok, Cap = self._make_manager()
        t1 = self._make_token(Tok, Cap, "bob")
        t2 = self._make_token(Tok, Cap, "bob")
        mgr.add(t1)
        cid2 = mgr.add(t2)
        count_before = mgr.active_token_count
        mgr.revoke(cid2)
        assert mgr.active_token_count == count_before - 1

    def test_revoke_all_by_actor_yields_empty(self):
        mgr, Tok, Cap = self._make_manager()
        t = self._make_token(Tok, Cap, "carol")
        cid = mgr.add(t)
        mgr.revoke(cid)
        result = list(mgr.active_tokens_by_actor("carol"))
        assert result == []

    def test_revoke_one_actor_does_not_affect_another(self):
        mgr, Tok, Cap = self._make_manager()
        t_alice = self._make_token(Tok, Cap, "alice")
        t_dave = self._make_token(Tok, Cap, "dave")
        cid_alice = mgr.add(t_alice)
        mgr.add(t_dave)
        mgr.revoke(cid_alice)
        assert not any(True for _ in mgr.active_tokens_by_actor("alice"))
        assert any(True for _ in mgr.active_tokens_by_actor("dave"))

    def test_active_token_count_consistent_with_by_actor_sum(self):
        mgr, Tok, Cap = self._make_manager()
        actors = ["eve", "frank", "grace"]
        for actor in actors:
            for _ in range(3):
                mgr.add(self._make_token(Tok, Cap, actor))
        total_from_actors = sum(
            1 for actor in actors for _ in mgr.active_tokens_by_actor(actor)
        )
        assert mgr.active_token_count >= total_from_actors  # wildcard may differ

    def test_active_token_count_after_multiple_revokes(self):
        mgr, Tok, Cap = self._make_manager()
        cids = [mgr.add(self._make_token(Tok, Cap, "henry")) for _ in range(5)]
        for cid in cids[:3]:
            mgr.revoke(cid)
        assert mgr.active_token_count == 2


# ---------------------------------------------------------------------------
# GF246 — Full pipeline E2E: detect_all_languages() → compile_batch()
# ---------------------------------------------------------------------------

class TestGF246FullPipelineE2E:
    """GF246: Full E2E: detect_all_languages() → I18NConflictReport → compile_batch()."""

    def test_detect_all_languages_returns_i18n_report(self):
        from ipfs_datasets_py.logic.api import detect_all_languages, I18NConflictReport
        report = detect_all_languages("Alice may read. Alice must not read.")
        assert isinstance(report, I18NConflictReport)

    def test_report_has_fr_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("Alice peut lire.")
        assert "fr" in report.by_language

    def test_total_conflicts_is_int(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert isinstance(report.total_conflicts, int)
        assert report.total_conflicts >= 0

    def test_compile_batch_from_report_languages(self):
        """compile_batch accepts language names from report as policy IDs."""
        from ipfs_datasets_py.logic.api import detect_all_languages
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import NLUCANPolicyCompiler
        report = detect_all_languages("Alice may read.")
        lang_slots = list(report.by_language.keys())
        # Build one batch per language slot (all same sentences)
        sentences_list = [["Alice may read."] for _ in lang_slots]
        policy_ids = lang_slots
        compiler = NLUCANPolicyCompiler(issuer_did="did:key:pipeline_test")
        results = compiler.compile_batch(sentences_list, policy_ids=policy_ids)
        assert len(results) == len(lang_slots)

    def test_pipeline_end_to_end_no_exception(self):
        """Full pipeline should not raise."""
        from ipfs_datasets_py.logic.api import detect_all_languages
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import NLUCANPolicyCompiler
        try:
            report = detect_all_languages("Alice must not share documents.")
            compiler = NLUCANPolicyCompiler(issuer_did="did:key:e2e")
            results = compiler.compile_batch(
                [["Alice must not share documents."]] * len(report.by_language)
            )
            assert isinstance(results, list)
        except (ImportError, ModuleNotFoundError):
            pass  # optional dependency missing


# ---------------------------------------------------------------------------
# Collect all tests
# ---------------------------------------------------------------------------

_ALL_TEST_CLASSES = [
    TestFW237SwedishE2E,
    TestFX238RussianE2E,
    TestFY239All13SlotsListTyped,
    TestFZ240ConflictDensitySynthetic13,
    TestGA241GreekKeywords,
    TestGB242TurkishKeywords,
    TestGC243HindiKeywords,
    TestGD244LanguagesAboveThresholdManySlots,
    TestGE245ActiveTokensByActorRevokeCombined,
    TestGF246FullPipelineE2E,
]


def _run_all_tests():
    passed = failed = skipped = 0
    for cls in _ALL_TEST_CLASSES:
        inst = cls()
        methods = [m for m in dir(inst) if m.startswith("test_")]
        for method in methods:
            try:
                getattr(inst, method)()
                passed += 1
            except Exception as exc:
                print(f"  FAIL  {cls.__name__}.{method}: {exc}")
                failed += 1
    print(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped")
    return failed == 0


if __name__ == "__main__":
    import sys
    ok = _run_all_tests()
    sys.exit(0 if ok else 1)
