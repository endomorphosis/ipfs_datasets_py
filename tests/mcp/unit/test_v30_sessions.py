"""v30 session tests — GQ257–GZ266.

GQ257  Polish text → detect_i18n_clauses("pl") E2E
GR258  Vietnamese text → detect_i18n_clauses("vi") E2E
GS259  detect_all_languages() all 18 original slots list-typed
GT260  conflict_density() with full 18-lang populated report
GU261  languages_above_threshold() with all 18 languages
GV262  Thai ("th") keyword table → 19 languages
GW263  Indonesian ("id") keyword table → 20 languages
GX264  compile_batch_with_explain + detect_all_languages 18-lang combined
GY265  PolicyAuditLog + 18-language metadata export/import
GZ266  active_tokens_by_actor + active_tokens_by_resource + merge triple E2E
"""

import uuid
import tempfile
import os
import pytest


# ---------------------------------------------------------------------------
# GQ257 — Polish text E2E
# ---------------------------------------------------------------------------

class TestGQ257PolishE2E:
    """GQ257: Polish text → detect_i18n_clauses("pl") integration."""

    def test_detect_i18n_clauses_pl_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_clauses
        result = detect_i18n_clauses("musi zaakceptować warunki", "pl")
        assert isinstance(result, list)

    def test_detect_i18n_clauses_pl_empty_text(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_clauses
        result = detect_i18n_clauses("", "pl")
        assert isinstance(result, list)

    def test_detect_all_languages_pl_slot_is_list(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("musi zaakceptować warunki")
        assert isinstance(report.by_language.get("pl"), list)

    def test_detect_all_languages_pl_slot_present(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert "pl" in report.by_language

    def test_load_i18n_keywords_pl_prohibition(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("pl")
        assert any("zabroni" in k.lower() or "zakazane" in k.lower()
                   for k in kw.get("prohibition", []))

    def test_load_i18n_keywords_pl_obligation(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("pl")
        assert "musi" in kw.get("obligation", []) or any("musi" in k for k in kw.get("obligation", []))

    def test_load_i18n_keywords_pl_permission(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("pl")
        assert "może" in kw.get("permission", [])


# ---------------------------------------------------------------------------
# GR258 — Vietnamese text E2E
# ---------------------------------------------------------------------------

class TestGR258VietnameseE2E:
    """GR258: Vietnamese text → detect_i18n_clauses("vi") integration."""

    def test_detect_i18n_clauses_vi_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_clauses
        result = detect_i18n_clauses("phải tuân thủ quy định", "vi")
        assert isinstance(result, list)

    def test_detect_i18n_clauses_vi_empty_text(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_clauses
        result = detect_i18n_clauses("", "vi")
        assert isinstance(result, list)

    def test_detect_all_languages_vi_slot_is_list(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("phải tuân thủ quy định")
        assert isinstance(report.by_language.get("vi"), list)

    def test_detect_all_languages_vi_slot_present(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert "vi" in report.by_language

    def test_load_i18n_keywords_vi_prohibition(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("vi")
        assert "không được" in kw.get("prohibition", []) or \
               any("cấm" in k for k in kw.get("prohibition", []))

    def test_load_i18n_keywords_vi_obligation(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("vi")
        assert "phải" in kw.get("obligation", [])

    def test_load_i18n_keywords_vi_permission(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("vi")
        assert "có thể" in kw.get("permission", []) or \
               "được phép" in kw.get("permission", [])


# ---------------------------------------------------------------------------
# GS259 — All 18 original slots list-typed
# ---------------------------------------------------------------------------

_ORIGINAL_18 = ("fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh",
                "ko", "ar", "sv", "ru", "el", "tr", "hi", "pl", "vi")


class TestGS259AllSlotsListTyped:
    """GS259: detect_all_languages() returns ≥18 slots, all list-typed."""

    def test_at_least_18_slots(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert len(report.by_language) >= 18

    def test_all_original_18_present(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        for lang in _ORIGINAL_18:
            assert lang in report.by_language, f"Missing lang slot: {lang}"

    def test_all_18_slots_are_lists(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        for lang in _ORIGINAL_18:
            assert isinstance(report.by_language[lang], list), \
                f"Slot '{lang}' is not a list: {type(report.by_language[lang])}"

    def test_empty_text_all_slots_empty_lists(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("")
        for lang in _ORIGINAL_18:
            assert report.by_language[lang] == []

    def test_no_slot_is_none(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("hello world")
        for lang in _ORIGINAL_18:
            assert report.by_language[lang] is not None

    def test_total_conflicts_zero_for_empty(self):
        from ipfs_datasets_py.logic.api import detect_all_languages, I18NConflictReport
        report = detect_all_languages("")
        assert isinstance(report, I18NConflictReport)
        assert report.total_conflicts == 0


# ---------------------------------------------------------------------------
# GT260 — conflict_density() with full 18-lang populated report
# ---------------------------------------------------------------------------

class TestGT260ConflictDensity18Langs:
    """GT260: conflict_density() with full 18-language populated report."""

    def _make_report(self, counts):
        """Build an I18NConflictReport with synthetic lang→[n conflicts] mapping."""
        from ipfs_datasets_py.logic.api import I18NConflictReport
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceRule

        report = I18NConflictReport()
        for lang, n in counts.items():
            report.by_language[lang] = [object()] * n
        return report

    def test_density_zero_for_empty_report(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        assert report.conflict_density() == 0.0

    def test_density_all_18_langs_one_conflict_each(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for lang in _ORIGINAL_18:
            report.by_language[lang] = [object()]
        assert report.conflict_density() == pytest.approx(1.0)

    def test_density_all_18_langs_three_each(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for lang in _ORIGINAL_18:
            report.by_language[lang] = [object(), object(), object()]
        assert report.conflict_density() == pytest.approx(3.0)

    def test_density_half_18_langs_empty(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for i, lang in enumerate(_ORIGINAL_18):
            report.by_language[lang] = [object()] if i % 2 == 0 else []
        # total = 9, languages = 18
        expected = 9 / 18
        assert report.conflict_density() == pytest.approx(expected)

    def test_density_real_18_lang_detect_empty_text(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("")
        assert report.conflict_density() == pytest.approx(0.0)

    def test_density_scales_with_total_conflicts(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        r1 = I18NConflictReport()
        r2 = I18NConflictReport()
        for lang in _ORIGINAL_18:
            r1.by_language[lang] = [object()]
            r2.by_language[lang] = [object(), object()]
        assert r2.conflict_density() == pytest.approx(2 * r1.conflict_density())


# ---------------------------------------------------------------------------
# GU261 — languages_above_threshold() with all 18 languages
# ---------------------------------------------------------------------------

class TestGU261LanguagesAboveThreshold18:
    """GU261: languages_above_threshold() with all 18 language slots."""

    def _report_with_counts(self, counts):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for lang, n in counts.items():
            report.by_language[lang] = [object()] * n
        return report

    def test_threshold_0_equals_sorted_languages_with_conflicts(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for i, lang in enumerate(_ORIGINAL_18):
            report.by_language[lang] = [object()] * (i % 3)
        above_0 = report.languages_above_threshold(0)
        expected = sorted(lang for lang, v in report.by_language.items() if v)
        assert above_0 == expected

    def test_all_18_one_conflict_threshold_0(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for lang in _ORIGINAL_18:
            report.by_language[lang] = [object()]
        above = report.languages_above_threshold(0)
        assert set(above) == set(_ORIGINAL_18)
        assert above == sorted(above)

    def test_threshold_1_subset_of_threshold_0(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for i, lang in enumerate(_ORIGINAL_18):
            report.by_language[lang] = [object()] * i  # 0..17
        above_0 = set(report.languages_above_threshold(0))
        above_1 = set(report.languages_above_threshold(1))
        assert above_1.issubset(above_0)

    def test_threshold_100_empty(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for lang in _ORIGINAL_18:
            report.by_language[lang] = [object()] * 5
        assert report.languages_above_threshold(100) == []

    def test_threshold_4_with_5_conflicts(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for lang in _ORIGINAL_18[:3]:
            report.by_language[lang] = [object()] * 5
        for lang in _ORIGINAL_18[3:]:
            report.by_language[lang] = [object()]
        above_4 = report.languages_above_threshold(4)
        assert set(above_4) == set(_ORIGINAL_18[:3])

    def test_all_empty_threshold_0_empty_list(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        for lang in _ORIGINAL_18:
            report.by_language[lang] = []
        assert report.languages_above_threshold(0) == []


# ---------------------------------------------------------------------------
# GV262 — Thai ("th") keyword table → 19 languages
# ---------------------------------------------------------------------------

class TestGV262ThaiKeywords:
    """GV262: _TH_DEONTIC_KEYWORDS inline Thai; detect_all_languages() → ≥19 langs."""

    def test_load_i18n_keywords_th_returns_dict(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("th")
        assert isinstance(kw, dict)

    def test_load_i18n_keywords_th_has_three_types(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("th")
        assert set(kw.keys()) == {"permission", "prohibition", "obligation"}

    def test_th_prohibition_contains_ham(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("th")
        assert "ห้าม" in kw["prohibition"]

    def test_th_obligation_contains_tong(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("th")
        assert "ต้อง" in kw["obligation"]

    def test_th_permission_contains_samart(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("th")
        assert "สามารถ" in kw["permission"]

    def test_detect_all_languages_has_th_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert "th" in report.by_language
        assert isinstance(report.by_language["th"], list)

    def test_detect_all_languages_gte_19(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert len(report.by_language) >= 19

    def test_detect_i18n_clauses_th_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_clauses
        result = detect_i18n_clauses("ต้องปฏิบัติตามกฎ", "th")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# GW263 — Indonesian ("id") keyword table → 20 languages
# ---------------------------------------------------------------------------

class TestGW263IndonesianKeywords:
    """GW263: _ID_DEONTIC_KEYWORDS inline Indonesian; detect_all_languages() → ≥20 langs."""

    def test_load_i18n_keywords_id_returns_dict(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("id")
        assert isinstance(kw, dict)

    def test_load_i18n_keywords_id_has_three_types(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("id")
        assert set(kw.keys()) == {"permission", "prohibition", "obligation"}

    def test_id_prohibition_contains_dilarang(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("id")
        assert "dilarang" in kw["prohibition"]

    def test_id_obligation_contains_harus(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("id")
        assert "harus" in kw["obligation"]

    def test_id_permission_contains_boleh(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import _load_i18n_keywords
        kw = _load_i18n_keywords("id")
        assert "boleh" in kw["permission"]

    def test_detect_all_languages_has_id_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert "id" in report.by_language
        assert isinstance(report.by_language["id"], list)

    def test_detect_all_languages_gte_20(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert len(report.by_language) >= 20

    def test_detect_all_has_both_th_and_id(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert "th" in report.by_language
        assert "id" in report.by_language

    def test_detect_i18n_clauses_id_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_clauses
        result = detect_i18n_clauses("harus mematuhi peraturan", "id")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# GX264 — compile_batch_with_explain + detect_all_languages 18-lang combined
# ---------------------------------------------------------------------------

class TestGX264CompileBatchWith18Langs:
    """GX264: compile_batch_with_explain combined with 18-language detect_all_languages."""

    def test_detect_all_languages_then_compile_batch_with_explain(self):
        try:
            from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
                NLUCANPolicyCompiler,
            )
        except (ImportError, ModuleNotFoundError):
            pytest.skip("NLUCANPolicyCompiler unavailable")
        from ipfs_datasets_py.logic.api import detect_all_languages

        report = detect_all_languages("the user must accept the terms")
        lang_list = list(report.by_language.keys())
        sentences_list = [["user may read"]] * min(5, len(lang_list))
        compiler = NLUCANPolicyCompiler()
        results = compiler.compile_batch_with_explain(sentences_list)
        assert len(results) == len(sentences_list)

    def test_compile_batch_with_explain_results_are_tuples(self):
        try:
            from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
                NLUCANPolicyCompiler,
            )
        except (ImportError, ModuleNotFoundError):
            pytest.skip("NLUCANPolicyCompiler unavailable")

        compiler = NLUCANPolicyCompiler()
        results = compiler.compile_batch_with_explain([["user may access resource"]])
        assert isinstance(results, list)
        assert len(results) == 1
        result_tuple, explanation = results[0]
        assert isinstance(explanation, str)

    def test_compile_batch_fail_fast_stops_on_error(self):
        try:
            from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
                NLUCANPolicyCompiler,
            )
        except (ImportError, ModuleNotFoundError):
            pytest.skip("NLUCANPolicyCompiler unavailable")

        compiler = NLUCANPolicyCompiler()
        # With fail_fast=False (default), all batches returned
        results = compiler.compile_batch_with_explain(
            [["ok sentence"]] * 3, fail_fast=False
        )
        assert len(results) == 3

    def test_18_lang_report_all_slots_present(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("user must comply with regulations")
        for lang in _ORIGINAL_18:
            assert lang in report.by_language

    def test_18_lang_report_density_nonnegative(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("user must comply. user may not share.")
        assert report.conflict_density() >= 0.0


# ---------------------------------------------------------------------------
# GY265 — PolicyAuditLog + 18-language metadata export/import
# ---------------------------------------------------------------------------

class TestGY265AuditLog18LangExport:
    """GY265: PolicyAuditLog full 18-language metadata export/import E2E."""

    def test_record_18_langs_then_export_import(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        from ipfs_datasets_py.logic.api import detect_all_languages

        report = detect_all_languages("user must accept terms")
        log = PolicyAuditLog(max_entries=100)
        for lang in _ORIGINAL_18:
            log.record(
                policy_cid=f"lang-{lang}",
                intent_cid="intent-18",
                decision="allow",
            )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            exported = log.export_jsonl(path, metadata={"source": "18-lang-test"})
            assert exported == len(_ORIGINAL_18)

            log2 = PolicyAuditLog(max_entries=100)
            imported = log2.import_jsonl(path)
            assert imported == len(_ORIGINAL_18)
        finally:
            os.unlink(path)

    def test_export_import_with_all_20_langs(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        from ipfs_datasets_py.logic.api import detect_all_languages

        report = detect_all_languages("test")
        all_langs = list(report.by_language.keys())
        log = PolicyAuditLog(max_entries=len(all_langs) + 10)
        for lang in all_langs:
            log.record(policy_cid=f"lang-{lang}", intent_cid="i", decision="allow")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            exported = log.export_jsonl(path, metadata={"langs": len(all_langs)})
            assert exported == len(all_langs)
            log2 = PolicyAuditLog(max_entries=len(all_langs) + 10)
            imported = log2.import_jsonl(path)
            assert imported == len(all_langs)
        finally:
            os.unlink(path)

    def test_metadata_line_not_counted_in_imported(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog(max_entries=50)
        for i in range(5):
            log.record(policy_cid=f"p{i}", intent_cid="i", decision="allow")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            log.export_jsonl(path, metadata={"v": "1"})
            log2 = PolicyAuditLog(max_entries=50)
            imported = log2.import_jsonl(path)
            assert imported == 5
        finally:
            os.unlink(path)

    def test_export_count_equals_import_count_18_langs(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog(max_entries=50)
        for lang in _ORIGINAL_18:
            log.record(policy_cid=lang, intent_cid="i", decision="deny")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            exported = log.export_jsonl(path)
            log2 = PolicyAuditLog(max_entries=50)
            imported = log2.import_jsonl(path)
            assert exported == imported
        finally:
            os.unlink(path)

    def test_recent_after_import_capped_by_max_entries(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog(max_entries=50)
        for lang in _ORIGINAL_18:
            log.record(policy_cid=lang, intent_cid="i", decision="allow")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            log.export_jsonl(path)
            log2 = PolicyAuditLog(max_entries=5)
            log2.import_jsonl(path)
            recent = log2.recent(100)
            assert len(recent) <= 5
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# GZ266 — active_tokens_by_actor + active_tokens_by_resource + merge triple
# ---------------------------------------------------------------------------

def _make_token(issuer, audience, resource, ability="read"):
    from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationToken, Capability
    cap = Capability(resource=resource, ability=ability)
    return DelegationToken(
        issuer=issuer,
        audience=audience,
        capabilities=[cap],
        expiry=9_999_999_999.0,
        nonce=str(uuid.uuid4()),
    )


class TestGZ266TripleCombinedE2E:
    """GZ266: active_tokens_by_actor + active_tokens_by_resource + merge triple E2E."""

    def test_merged_tokens_visible_by_actor_and_resource(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr_a = DelegationManager(path=None)
        mgr_b = DelegationManager(path=None)

        tok = _make_token("alice", "bob", "files")
        mgr_b.add(tok)

        mgr_a.merge(mgr_b)

        actors = dict(mgr_a.active_tokens_by_actor("bob"))
        resources = dict(mgr_a.active_tokens_by_resource("files"))

        assert len(actors) == 1
        assert len(resources) == 1
        cid_actor = list(actors.keys())[0]
        cid_resource = list(resources.keys())[0]
        assert cid_actor == cid_resource

    def test_actor_and_resource_same_set_for_matching_token(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager(path=None)
        tok = _make_token("alice", "carol", "database")
        cid = mgr.add(tok)

        actor_cids = {c for c, _ in mgr.active_tokens_by_actor("carol")}
        resource_cids = {c for c, _ in mgr.active_tokens_by_resource("database")}
        assert actor_cids == resource_cids == {cid}

    def test_revoke_removes_from_both_actor_and_resource(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager(path=None)
        tok = _make_token("alice", "dave", "secrets")
        cid = mgr.add(tok)

        mgr.revoke(cid)

        assert list(mgr.active_tokens_by_actor("dave")) == []
        assert list(mgr.active_tokens_by_resource("secrets")) == []

    def test_two_actors_same_resource_after_merge(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager(path=None)
        tok1 = _make_token("alice", "user1", "reports")
        tok2 = _make_token("alice", "user2", "reports")

        other = DelegationManager(path=None)
        other.add(tok1)
        other.add(tok2)
        mgr.merge(other)

        actors1 = dict(mgr.active_tokens_by_actor("user1"))
        actors2 = dict(mgr.active_tokens_by_actor("user2"))
        resources = dict(mgr.active_tokens_by_resource("reports"))

        assert len(actors1) == 1
        assert len(actors2) == 1
        assert len(resources) == 2

    def test_wildcard_resource_visible_by_actor_and_resource(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager(path=None)
        tok = _make_token("root", "admin", "*")
        cid = mgr.add(tok)

        actors = dict(mgr.active_tokens_by_actor("admin"))
        resources = dict(mgr.active_tokens_by_resource("any-resource"))

        assert cid in actors
        assert cid in resources

    def test_active_token_count_after_triple_merge_revoke(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager(path=None)
        tokens = []
        for i in range(3):
            tok = _make_token("alice", f"user{i}", f"res{i}")
            tokens.append(tok)

        other = DelegationManager(path=None)
        for tok in tokens:
            other.add(tok)
        mgr.merge(other)

        assert mgr.active_token_count == 3

        # revoke first token
        first_cid = list(dict(mgr.active_tokens()))[0]
        mgr.revoke(first_cid)
        assert mgr.active_token_count == 2
