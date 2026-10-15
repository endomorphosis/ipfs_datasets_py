"""Synthetic stdlib control tests; no live HTTP, SDK, ledger or corpus imports."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "scripts/ops/legal_ir/observe_uscode_cache_metadata.py"


def load_observer():
    module = types.ModuleType("_synthetic_uscode_cache_metadata_observer")
    module.__file__ = str(SOURCE)
    with SOURCE.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("bounded observer source required")
    exec(compile(raw, str(SOURCE), "exec", dont_inherit=True), module.__dict__)
    return module


class InventedHTTP:
    def __init__(self, observer, *, changed_head=False, wrong_pin=False, wrong_identity=False, oversized=False,
                 unexpected_rows=False, oversized_rows=False, viewer_failure=False, viewer_pending=False):
        self.observer = observer
        self.changed_head, self.wrong_pin = changed_head, wrong_pin
        self.wrong_identity = wrong_identity
        self.oversized, self.unexpected_rows, self.viewer_failure = oversized, unexpected_rows, viewer_failure
        self.oversized_rows, self.viewer_pending = oversized_rows, viewer_pending
        self.calls, self.head_calls = [], {}

    def __call__(self, url, *, max_bytes, timeout_seconds):
        self.calls.append(url)
        if timeout_seconds != 15:
            raise AssertionError("unexpected timeout")
        parsed = urlsplit(url)
        repository = next(repo for repo in self.observer.DATASETS.values()
                          if repo in url or parse_qs(parsed.query).get("dataset") == [repo])
        span = repository == self.observer.DATASETS["span"]
        revision = ("1" if span else "2") * 40
        status = 200
        if parsed.hostname == "huggingface.co":
            if "/revision/" not in parsed.path:
                self.head_calls[repository] = self.head_calls.get(repository, 0) + 1
                if span and self.changed_head and self.head_calls[repository] > 1:
                    revision = "3" * 40
                value = {"id": repository, "sha": revision}
            else:
                if span and self.oversized:
                    return {"status": 200, "final_url": url, "headers": {}, "body": b"x" * (max_bytes + 1)}
                value = {"id": "someone/else" if span and self.wrong_identity else repository,
                         "sha": "4" * 40 if span and self.wrong_pin else revision,
                         "cardData": {"configs": [{"config_name": "invented"}]},
                         "siblings": [
                             {"rfilename": "README.md", "size": 12, "blobId": "a" * 40},
                             {"rfilename": "autoformal/uscode/invented.parquet", "size": 19,
                              "blobId": "b" * 40, "lfs": {"sha256": "c" * 64, "size": 19, "pointerSize": 130}},
                         ]}
        elif parsed.path == "/splits":
            value = {"splits": [{"dataset": repository, "config": "invented", "split": "train"}]}
            if span and self.viewer_pending:
                value = {"splits": [], "pending": [{"config": "invented", "split": "train"}], "failed": []}
        elif parsed.path == "/rows":
            if parse_qs(parsed.query).get("length") != ["0"]:
                raise AssertionError("nonzero row request")
            if span and self.oversized_rows:
                prefix = b'{"rows":[{"row":"unexpected synthetic value"}],"padding":"'
                return {"status": 200, "final_url": url, "headers": {},
                        "body": prefix + b"x" * (max_bytes + 1 - len(prefix))}
            value = {"features": [{"name": "invented_column", "type": {"dtype": "string"}}],
                     "rows": [{"row": {"invented_column": "unexpected synthetic value"}}]
                     if span and self.unexpected_rows else [], "num_rows_total": 17, "partial": False}
            if not span and self.viewer_failure:
                status, value = 503, {"error": "synthetic Viewer unavailable"}
        else:
            raise AssertionError("unexpected URL")
        return {"status": status, "final_url": url, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(value).encode()}


class CacheMetadataObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = load_observer()

    def run_observation(self, directory, **options):
        client = InventedHTTP(self.observer, **options)
        result = self.observer.observe(Path(directory) / "observation", fetch=client, max_response_bytes=1024)
        saved = json.loads((Path(directory) / "observation/observation.json").read_text())
        self.assertEqual(result, saved)
        return result, client

    def test_success_preserves_returned_descriptors_and_unversioned_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            result, client = self.run_observation(directory)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(len(client.calls), 10)
            self.assertEqual(result["viewer_splits_probed"], 2)
            for lane in ("span", "entity"):
                record = result["datasets"][lane]
                inventory = record["sibling_inventory"]
                self.assertEqual((inventory["file_count"], inventory["declared_file_bytes"],
                                  inventory["parquet_file_count"], inventory["lfs_file_count"]), (2, 31, 1, 1))
                self.assertEqual(inventory["files"][0]["path"], "README.md")
                self.assertEqual(inventory["files"][1]["lfs"]["sha256"], "c" * 64)
                self.assertFalse(record["viewer"]["revision_bound"])
                view = record["viewer"]["views"][0]
                self.assertEqual(view["declared_num_rows_total"], 17)
                self.assertFalse(view["pinned_data_equality_verified"])
                self.assertFalse(record["main_changed_during_observation"])
            self.assertTrue(all(flag is False for flag in result["qualification"].values()))
            self.assertEqual((Path(directory) / "observation").stat().st_mode & 0o777, 0o700)
            for observation in result["http_observations"]:
                raw = (Path(directory) / "observation" / observation["raw_path"]).read_bytes()
                self.assertEqual(len(raw), observation["retained_bytes"])
                self.assertEqual(self.observer.hashlib.sha256(raw).hexdigest(), observation["retained_sha256"])

    def test_changed_main_preserves_pinned_inventory_but_fails_stability(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_observation(directory, changed_head=True)
            record = result["datasets"]["span"]
            self.assertEqual(result["status"], "partial_failed")
            self.assertTrue(record["main_changed_during_observation"])
            self.assertEqual(record["observed_revision"], "1" * 40)
            self.assertEqual(record["main_close_revision"], "3" * 40)
            self.assertEqual(record["sibling_inventory"]["file_count"], 2)
            self.assertEqual(result["errors"][0]["stage"], "main_close")

    def test_wrong_pinned_sha_is_not_an_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            result, client = self.run_observation(directory, wrong_pin=True)
            self.assertEqual(result["status"], "partial_failed")
            self.assertNotIn("sibling_inventory", result["datasets"]["span"])
            self.assertEqual(client.head_calls[self.observer.DATASETS["span"]], 2)
            self.assertIn("pinned Hub revision mismatch", result["errors"][0]["error"])
            self.assertEqual(result["datasets"]["entity"]["status"], "complete")

    def test_oversized_response_preserves_only_bounded_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_observation(directory, oversized=True)
            observation = next(row for row in result["http_observations"]
                               if row["dataset"] == "span" and row["stage"] == "pinned_revision")
            self.assertEqual(result["status"], "partial_failed")
            self.assertTrue(observation["body_truncated"])
            self.assertFalse(observation["retained_body_is_complete"])
            self.assertEqual(observation["retained_bytes"], 1024)
            self.assertEqual((Path(directory) / "observation" / observation["raw_path"]).stat().st_size, 1024)

    def test_wrong_repository_cannot_supply_the_pinned_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_observation(directory, wrong_identity=True)
            self.assertEqual(result["status"], "partial_failed")
            self.assertNotIn("sibling_inventory", result["datasets"]["span"])
            self.assertIn("Hub repository identity mismatch", result["errors"][0]["error"])

    def test_aggregate_body_budget_stops_further_fetches(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(self.observer, "MAX_TOTAL_BYTES", 500):
            result, client = self.run_observation(directory)
            self.assertEqual(result["status"], "partial_failed")
            self.assertEqual(result["retained_response_bytes"], 500)
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(sum(row.get("retained_bytes", 0) for row in result["http_observations"]), 500)

    def test_request_budget_stops_further_fetches(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(self.observer, "MAX_HTTP_REQUESTS", 2):
            result, client = self.run_observation(directory)
            self.assertEqual(result["status"], "partial_failed")
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(len(result["http_observations"]), 2)
            self.assertTrue(any("HTTP request bound exceeded" in row["error"] for row in result["errors"]))

    def test_nonempty_viewer_rows_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_observation(directory, unexpected_rows=True)
            self.assertEqual(result["status"], "partial_failed")
            self.assertEqual(result["datasets"]["span"]["viewer"]["views"], [])
            self.assertIn("zero-row Viewer request returned rows", result["errors"][0]["error"])
            self.assertNotIn("unexpected synthetic value", json.dumps(result))
            response = next(row for row in result["http_observations"]
                            if row["dataset"] == "span" and row["stage"] == "viewer_rows_metadata")
            self.assertNotIn("raw_path", response)
            self.assertFalse(response["raw_body_archived"])
            self.assertGreater(response["observed_body_bytes"], 0)
            self.assertEqual(len(response["observed_body_sha256"]), 64)
            self.assertEqual(result["accounted_response_bytes"] - result["retained_response_bytes"],
                             response["observed_body_bytes"])
            for path in (Path(directory) / "observation").rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"unexpected synthetic value", path.read_bytes())

    def test_oversized_row_response_archives_no_payload_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_observation(directory, oversized_rows=True)
            response = next(row for row in result["http_observations"]
                            if row["dataset"] == "span" and row["stage"] == "viewer_rows_metadata")
            self.assertEqual(result["status"], "partial_failed")
            self.assertTrue(response["body_truncated"])
            self.assertEqual(response["observed_body_bytes"], 1024)
            self.assertNotIn("raw_path", response)
            self.assertFalse(response["raw_body_archived"])
            self.assertEqual(result["accounted_response_bytes"] - result["retained_response_bytes"], 1024)
            for path in (Path(directory) / "observation").rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"unexpected synthetic value", path.read_bytes())

    def test_pending_split_service_declarations_prevent_completeness(self):
        with tempfile.TemporaryDirectory() as directory:
            result, client = self.run_observation(directory, viewer_pending=True)
            record = result["datasets"]["span"]
            self.assertEqual(result["status"], "partial_failed")
            self.assertEqual(record["status"], "partial_failed")
            self.assertEqual(record["viewer"]["split_population"], [])
            self.assertEqual(record["viewer"]["split_service_declarations"],
                             {"pending": [{"config": "invented", "split": "train"}], "failed": []})
            self.assertIn("Viewer reports pending or failed split metadata", result["errors"][0]["error"])
            self.assertFalse(any("/rows?" in url and "span-cache" in url for url in client.calls))

    def test_viewer_failure_retains_raw_observation_and_pinned_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_observation(directory, viewer_failure=True)
            self.assertEqual(result["status"], "partial_failed")
            self.assertEqual(result["datasets"]["entity"]["sibling_inventory"]["file_count"], 2)
            observation = next(row for row in result["http_observations"] if row.get("status") == 503)
            raw = (Path(directory) / "observation" / observation["raw_path"]).read_text()
            self.assertIn("synthetic Viewer unavailable", raw)
            self.assertFalse(result["qualification"]["viewer_revision_binding_verified"])
            self.assertFalse(result["datasets"]["entity"]["viewer"]["pinned_data_equality_verified"])

    def test_explicit_revision_replay_makes_no_main_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            client = InventedHTTP(self.observer)
            result = self.observer.observe(Path(directory) / "replay", fetch=client,
                                           span_revision="1" * 40, entity_revision="2" * 40,
                                           max_response_bytes=1024)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(client.head_calls, {})
            self.assertEqual(len(client.calls), 6)
            for record in result["datasets"].values():
                self.assertEqual(record["mode"], "explicit_revision_replay")
                self.assertEqual(record["live_head_stability"], "not_observed")
                self.assertIsNone(record["main_changed_during_observation"])

    def test_existing_output_is_never_overwritten_or_fetched(self):
        with tempfile.TemporaryDirectory() as directory:
            client = InventedHTTP(self.observer)
            sentinel = Path(directory) / "preserved.txt"
            sentinel.write_text("preserve")
            with self.assertRaises(FileExistsError):
                self.observer.observe(directory, fetch=client)
            self.assertEqual(client.calls, [])
            self.assertEqual(sentinel.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
