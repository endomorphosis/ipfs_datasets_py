"""Offline regression coverage for reconciling local and upstream legal collectors.

Run directly with Python's unittest runner; no full-package imports or collection jobs.
"""
from __future__ import annotations
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

COLLECTORS = Path(__file__).resolve().parents[3] / "ipfs_datasets_py/processors/legal_scrapers/national_collectors"
sys.path.insert(0, str(COLLECTORS))
import common
import archive_fallbacks as af
import world_lib as wl
import collect_ad as ad
import collect_dz as dz
import collect_gh as gh
import collect_jm as jm
import collect_sn as sn
import collect_tn as tn
import collect_tz as tz


def decision(allowed=True):
    return SimpleNamespace(allowed=allowed, reason="test_policy", rule="/private", host="example.gov")


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.no_network = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden in offline tests"))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)

    def test_common_guard_blocks_before_send(self):
        guard = Mock(check=Mock(return_value=decision(False)))
        with patch.object(common, "_rg", guard), patch("requests.Session.send") as send:
            with self.assertRaises(common.RobotsBlockedFetch):
                common._RobotsSession().send(SimpleNamespace(url="https://example.gov/private"))
            send.assert_not_called()
            guard.report_blocked.assert_called_once()

    def test_common_guard_waits_before_allowed_send(self):
        guard = Mock(check=Mock(return_value=decision()))
        with patch.object(common, "_rg", guard), patch("requests.Session.send", return_value="ok"):
            self.assertEqual(common._RobotsSession().send(SimpleNamespace(url="https://example.gov/law")), "ok")
            guard.wait_send.assert_called_once()

    def test_missing_guard_fails_closed(self):
        for module in (common, af):
            with self.subTest(module=module.__name__), patch.object(module, "_rg", None):
                with self.assertRaises(module.RobotsBlockedFetch):
                    module._robots_gate("https://example.gov/law")

    def test_portable_root_aliases_match_guards_and_helpers(self):
        hub = COLLECTORS.parent / "hub_dataset_scripts/endomorphosis__legal_scrapers/scrapers"
        for directory in (COLLECTORS, hub):
            for variable in ("LEGAL_CORPORA_ROOT", "IPFS_DATASETS_LEGAL_CORPORA_ROOT"):
                with tempfile.TemporaryDirectory() as td:
                    env = os.environ.copy()
                    env.pop("LEGAL_CORPORA_ROOT", None)
                    env.pop("IPFS_DATASETS_LEGAL_CORPORA_ROOT", None)
                    env[variable] = td
                    env["PYTHONDONTWRITEBYTECODE"] = "1"
                    code = "import sys; sys.path.insert(0, sys.argv[1]); import common, robots_guard; assert str(common.ROOT) == sys.argv[2]; assert common.ROOT == robots_guard.ROOT"
                    subprocess.run([sys.executable, "-c", code, str(directory), td], env=env, check=True, capture_output=True)

    def test_upstream_write_once_safety_retained(self):
        with tempfile.TemporaryDirectory() as td, patch.object(common, "ROOT", Path(td)), patch.object(common, "_WRITE_ONCE_LOG", str(Path(td)/"writes.log")):
            existing = Path(td)/"tn/instruments/example.json"
            existing.parent.mkdir(parents=True)
            existing.write_text('{"original":true}')
            dest = common.write_instrument("tn", {"id":"example", "text":"new"})
            self.assertNotEqual(existing, dest)
            self.assertEqual(existing.read_text(), '{"original":true}')
            self.assertEqual(json.loads(dest.read_text())["text"], "new")

    def test_cdx_policy_denial_does_not_change_scheme(self):
        session = Mock()
        session.get.side_effect = af.RobotsBlockedFetch("blocked")
        with patch.object(af,"session",return_value=session), patch.object(af,"_sleep_wayback"):
            result = af.search_wayback_machine("https://example.gov/private",limit=1)
        self.assertEqual(result, [])
        self.assertEqual(session.get.call_count, 1)

    def test_warc_origin_denied_before_request(self):
        guard = Mock(check_archived_copy=Mock(return_value=decision(False)))
        with patch.object(af, "_rg", guard), patch.object(af, "session") as session:
            result = af.fetch_common_crawl_warc({"filename": "record.warc.gz", "length": 100, "original": "https://example.gov/private"})
        self.assertEqual(result["error"], "robots_blocked")
        session.assert_not_called()

    def test_warc_requires_origin_for_guard(self):
        with patch.object(af, "session") as session:
            result = af.fetch_common_crawl_warc({"filename": "record.warc.gz", "length": 100})
        self.assertEqual(result["error"], "missing_original_url")
        session.assert_not_called()

    def test_warc_bounded_retry_preserves_origin_guard(self):
        guard = Mock(check_archived_copy=Mock(return_value=decision()))
        session = Mock()
        session.get.side_effect = [SimpleNamespace(status_code=503, content=b""), SimpleNamespace(status_code=206, content=b"WARC")]
        with patch.object(af, "_rg", guard), patch.object(af, "session", return_value=session), patch.object(af, "_sleep_cc"), patch.object(af, "_parse_warc_http", return_value=(200, "text/plain", b"law text")):
            result = af.fetch_common_crawl_warc({"filename": "record.warc.gz", "offset": 12, "length": 100, "original": "https://example.gov/law"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args.kwargs["headers"]["Range"], "bytes=12-111")
        guard.check_archived_copy.assert_called_once()

    def test_warc_robots_exception_is_not_retried(self):
        session = Mock()
        session.get.side_effect = af.RobotsBlockedFetch("blocked")
        with patch.object(af, "_rg", Mock(check_archived_copy=Mock(return_value=decision()))), patch.object(af, "session", return_value=session), patch.object(af, "_sleep_cc"):
            result = af.fetch_common_crawl_warc({"filename": "record.warc.gz", "length": 100, "original": "https://example.gov/law"})
        self.assertEqual(result["error"], "robots_blocked")
        self.assertEqual(session.get.call_count, 1)

    def test_wayback_curl_blocked_before_spawn(self):
        with patch.object(af, "_robots_blocked", return_value=decision(False)), patch.object(af, "_sleep_wayback"), patch("subprocess.run") as run:
            self.assertEqual(af.get_wayback_content("https://example.gov/private")["error"], "robots_blocked")
        run.assert_not_called()

    def test_wayback_https_redirect_each_hop_guarded(self):
        def response(status, location="", body=b"law text"):
            return SimpleNamespace(returncode=0, stderr=b"", stdout=body+f"\n__HTTP_STATUS__{status}\n__CONTENT_TYPE__text/plain\n__URL_EFFECTIVE__\n__REDIRECT_URL__{location}".encode())
        with patch.object(af, "WAYBACK_WEB", "https://web.archive.org/web"), patch.object(af, "_robots_blocked", return_value=None) as gate, patch.object(af, "_sleep_wayback"), patch("subprocess.run", side_effect=[response(302,"https://web.archive.org/web/20260101000000id_/https://example.gov/law"),response(200)]) as run:
            result = af.get_wayback_content("https://example.gov/law")
        self.assertEqual(result["status"], "success")
        self.assertEqual(gate.call_count, 2)
        self.assertTrue(all(c.args[0][-1].startswith("https://") for c in run.call_args_list))

    def test_live_defaults_are_bounded_and_tls_hold_retained(self):
        with patch.dict(os.environ, {"LEGAL_CONNECT_TIMEOUT":"999", "LEGAL_READ_TIMEOUT":"999", "LEGAL_HTTP_RETRIES":"999", "NO_INSECURE_TLS":"1"}), patch.object(wl, "_robots_get", return_value="ok") as get, patch.object(wl.time, "sleep"):
            self.assertEqual(wl.live_get("https://example.gov/law", verify=False), "ok")
        self.assertEqual(get.call_args.kwargs["timeout"], (60,180))
        self.assertTrue(get.call_args.kwargs["verify"])

    def test_live_robots_failure_stops_fallbacks(self):
        with patch.object(wl, "live_get", side_effect=wl.RobotsBlockedFetch("blocked")), patch.object(af, "get_wayback_content") as wayback:
            result = wl.fetch_official("https://example.gov/private")
        self.assertIn("robots_blocked", result["error"])
        wayback.assert_not_called()

    def test_wayback_pdf_bytes_retained_for_ocr(self):
        with patch.object(wl, "live_get", side_effect=RuntimeError("offline")), patch.object(af, "get_wayback_content", return_value={"status":"success", "content":b"%PDF-image", "content_type":"application/pdf"}), patch.object(wl,"pdf_to_text",return_value=""):
            result = wl.fetch_official("https://example.gov/law.pdf")
        self.assertEqual(result["content"], b"%PDF-image")
        self.assertEqual(result["method"], "wayback_pdf_bytes")
        self.assertEqual(result["status"], "error")

    def test_ad_document_representations_deduplicate(self):
        self.assertEqual(ad._document_key("https://documents.bopa.ad/bopa-documents/260001/html/law.html"),ad._document_key("https://documents.bopa.ad/bopa-documents/260001/pdf/law.pdf?x=1"))
        self.assertEqual(ad._content_fingerprint("Article 1\n law"),ad._content_fingerprint("Article 1 law"))

    def test_ad_pdf_discovery_official_only_deduped(self):
        rows=[{"original":"https://www.bopa.ad/issue.pdf"}, {"original":"http://bopa.ad/issue.pdf#anchor"}, {"original":"https://evilbopa.ad/issue.pdf"}]
        with patch.object(ad,"cdx_urls",return_value=rows):
            self.assertEqual(len(ad.discover_pdf_issues()),1)

    def test_ad_html_then_pdf_fallback(self):
        with patch.object(ad,"fetch_official",side_effect=[{"status":"error"},{"status":"success","text":"Article 1 law","method":"http_pdf"}]) as fetch:
            self.assertEqual(ad.fetch_doc_text("https://documents.bopa.ad/law.html","https://documents.bopa.ad/law.pdf")[1],"https://documents.bopa.ad/law.pdf")
        self.assertEqual(fetch.call_count,2)

    def test_ad_api_uses_guarded_shared_http(self):
        response=SimpleNamespace(status_code=200,content=b"[]",json=lambda:[])
        with patch.object(ad,"http_get",return_value=response) as get:
            self.assertEqual(ad.api_get_q("/api/test",{"code":"public-test-code","date":"2026-01-01"}),[])
        self.assertIn("date=2026-01-01",get.call_args.args[0])

    def test_ad_combined_main_content_deduplication(self):
        text="Article 1 A law with sufficient text. "*10
        with tempfile.TemporaryDirectory() as td, patch.object(ad,"ROOT",Path(td)), patch.object(ad,"setup_log"), patch.object(ad,"existing_ids",return_value=set()), patch.object(ad,"discover_bulletins",return_value=[{"year":2026,"num":"1"}]), patch.object(ad,"docs_for_bulletin",return_value=[{"nomDocument":"law","sumari":"A law"}]), patch.object(ad,"fetch_doc_text",return_value=(text,"https://documents.bopa.ad/law.html","http_html")), patch.object(ad,"discover_pdf_issues",return_value=[("issue","https://bopa.ad/issue.pdf")]), patch.object(ad,"fetch_official",return_value={"status":"success","text":text}), patch.object(ad,"save_instrument",return_value=True) as save, patch.object(ad,"append_catalog"), patch.object(ad,"write_summary"):
            ad.main()
        self.assertEqual(save.call_count,1)

    def test_dz_cdx_and_generated_issues_combined(self):
        with patch.object(dz,"cdx_urls",return_value=[]), patch.object(dz,"jo_urls",return_value=[("F2026001","http://www.joradp.dz/FTP/jo-francais/2026/F2026001.pdf","Issue 1")]):
            items=dz.discover()
        self.assertTrue(any(i[0]=="F2026001" for i in items))
        self.assertGreater(len(items),1)  # Constitution/code seeds are also retained.

    def test_dz_probe_does_not_monkeypatch_shared_live_get(self):
        original=wl.live_get
        with patch.object(af,"get_wayback_content",return_value={"status":"error"}), patch.object(dz,"fetch_official",return_value={"status":"success"}) as fetch:
            self.assertEqual(dz.fetch_joradp("http://www.joradp.dz/TRV/FCivil.pdf")["status"],"success")
        self.assertIs(wl.live_get,original)
        self.assertEqual(fetch.call_args.kwargs["live_retries"],1)

    def test_gh_known_dspace_live_hold(self):
        with patch.object(gh,"http_get") as live, patch.object(gh,"_archive_official",return_value={"status":"error"}) as archive:
            gh.get_official("https://ir.parliament.gh/bitstream/a.pdf")
        live.assert_not_called();archive.assert_called_once()

    def test_gh_epanel_no_live_even_with_guarded_archives(self):
        with patch.object(gh,"http_get") as live, patch.object(gh,"_archive_official",return_value={"status":"error"}):
            gh.get_official("https://www.parliament.gh/epanel/docs/bills/a.pdf")
        live.assert_not_called()

    def test_gh_quality_shell_and_short_text_rejected(self):
        self.assertTrue(gh.is_dspace_shell("DSpace Repository :: Home"))
        self.assertFalse(gh.is_act_like("AN ACT short"))
        self.assertTrue(gh.is_act_like("AN ACT\n"+"law "*1000))

    def test_jm_session_guarded_and_nonlaw_filter_combined(self):
        self.assertIsInstance(jm._session(),common._RobotsSession)
        self.assertFalse(jm._is_law_pdf("https://moj.gov.jm/sites/default/files/docs/job-description.pdf"))
        self.assertTrue(jm._is_law_pdf("https://moj.gov.jm/sites/default/files/laws/Companies-Act.pdf"))

    def test_sn_archives_live_only_no_wayback_timestamp(self):
        with patch.object(sn,"fetch_official",return_value={"status":"error"}) as fetch, patch.object(sn,"live_get",side_effect=RuntimeError("offline")), patch.object(af,"get_wayback_content") as wayback:
            sn.fetch_sn("https://www.archives.sn/api/fichiers/1",wayback_ts="20260101000000",wayback=False,allow_ocr=False)
        self.assertFalse(fetch.call_args.kwargs["wayback"])
        wayback.assert_not_called()

    def test_tn_preserves_both_discovery_strategies_and_timestamp(self):
        with patch.object(tn,"discover_jort_lake",return_value=[("lake","https://lake.jort.tn/issue.pdf","pdf")]), patch.object(tn,"discover_legislation_cdx",return_value=[("generic","http://legislation.tn/sites/default/files/issue.pdf","cdx_pdf")]), patch.object(tn,"discover_official_cdx",return_value=[("official","http://legislation.tn/sites/default/files/issue.pdf","20260101000000")]):
            items=tn.discover()
        self.assertEqual(len(items),2)
        self.assertEqual(items[1][2:],("official_cdx","20260101000000"))

    def test_tn_timestamp_fetch_routed_to_official_archive(self):
        with patch.object(tn,"fetch_tn",return_value={"status":"error"}) as fetch:
            tn.fetch_item("http://legislation.tn/sites/default/files/issue.pdf","official_cdx",timestamp="20260101000000")
        self.assertEqual(fetch.call_args.kwargs["ts"],"20260101000000")

    def test_tz_discovery_retains_official_download_cdx(self):
        response=SimpleNamespace(status_code=404,text="")
        hit={"original":"https://oagmis.oag.go.tz/portal/acts/1/download","timestamp":"20260101000000"}
        with tempfile.TemporaryDirectory() as td, patch.object(tz,"ROOT",Path(td)), patch.object(tz,"live_get",return_value=response), patch.object(tz,"_json_get",return_value=None), patch.object(tz,"cdx_urls",side_effect=lambda prefix,**kw:[hit] if "oagmis" in prefix else []):
            rows=tz.discover()
        self.assertTrue(any(r.get("wayback_ts")=="20260101000000" for r in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
