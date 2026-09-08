"""Focused tests for the shared first-party State Laws release probe."""

from __future__ import annotations

import copy
import hashlib
import json
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_DATASET_REPO_ID,
)
from scripts.ops.legal_data import state_laws_release_probe as probe

REVISION = "1" * 40
RELEASE_DIGEST = "2" * 64
PARENT_DIGEST = "3" * 64
KEY_DIGEST = "4" * 64


class _FakeQueryClient:
    def __init__(self, *, warm: bool, release_prefix: str | None = None) -> None:
        self.warm = warm
        self.release_prefix = release_prefix

    def _result(self, entry_cid: str) -> dict:
        return {
            "complete": True,
            "ordered_result_cids": [entry_cid],
            "results": [{"entry_cid": entry_cid}],
            "fetch_trace": {
                "files": [
                    {
                        "cache_hit": self.warm,
                        "relative_path": "indexes/probe.parquet",
                        "size_bytes": 128,
                    }
                ]
            },
            "sparse_io": {"full_index_downloaded": False},
        }

    def bm25_search(self, query: str, *, top_k: int, jurisdiction: str) -> dict:
        assert query == "statute"
        assert top_k == 5
        return self._result(f"cid-{jurisdiction}")

    def vector_search(
        self, *, query_vector: tuple[float, ...], top_k: int, jurisdiction: str
    ) -> dict:
        assert query_vector == (1.0,)
        assert top_k == 5
        return self._result(f"cid-{jurisdiction}")

    def hybrid_search(
        self,
        query: str,
        *,
        query_vector: tuple[float, ...],
        top_k: int,
        jurisdiction: str,
    ) -> dict:
        assert query == "statute"
        assert query_vector == (1.0,)
        assert top_k == 5
        return self._result(f"cid-{jurisdiction}")

    def neighbors(self, start: str, *, limit: int) -> dict:
        assert start.startswith("cid-")
        assert limit == 16
        return self._result("cid-neighbor")


class _FakeRemoteClient:
    def __init__(
        self, *, revision: str, warm: bool, release_prefix: str | None = None
    ) -> None:
        self.revision = revision
        self.warm = warm
        self.release_prefix = release_prefix

    def bm25_search(self, query: str, *, top_k: int) -> dict:
        assert query == "law"
        assert top_k == 5
        return {
            "complete": True,
            "ordered_result_cids": [f"cid-{self.revision}"],
            "fetch_trace": {
                "files": [
                    {
                        "cache_hit": self.warm,
                        "relative_path": "indexes/bm25/probe.parquet",
                        "size_bytes": 64,
                    }
                ]
            },
            "sparse_io": {"full_index_downloaded": False},
        }


def _representatives(_verified: object) -> dict:
    return {
        "graph_starts": ("cid-AK",),
        "jurisdictions": {
            code: probe.QueryRepresentative(
                jurisdiction=code,
                entry_cid=f"cid-{code}",
                query_terms=("statute",),
                query_vector=(1.0,),
            )
            for code in probe.SORTED_JURISDICTIONS
        },
    }


def test_local_probe_measures_exact_51_and_real_cold_warm_seams(
    tmp_path: Path,
) -> None:
    manifest = {
        "artifacts": [
            {"relative_path": "indexes/probe.parquet"},
            {"relative_path": "indexes/not-fetched.parquet"},
        ],
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "jurisdictions": list(probe.SORTED_JURISDICTIONS),
        "key_parity": {"parent_entry_cids_sha256": KEY_DIGEST},
    }
    verified = SimpleNamespace(
        manifest_digest=RELEASE_DIGEST,
        output_root=tmp_path,
        payload=manifest,
    )
    opened = 0

    def client_factory(**kwargs: object) -> _FakeQueryClient:
        nonlocal opened
        assert kwargs["revision"] == REVISION
        assert kwargs["repo_id"] == DEFAULT_DATASET_REPO_ID
        opened += 1
        return _FakeQueryClient(warm=opened > 1)

    clock = 0

    def monotonic_ns() -> int:
        nonlocal clock
        clock += 1_000_000
        return clock

    measured = probe.run_local_release_probe(
        tmp_path,
        repo_id=DEFAULT_DATASET_REPO_ID,
        revision=REVISION,
        release_manifest_digest=RELEASE_DIGEST,
        parent_evidence_digest=PARENT_DIGEST,
        release_verifier=lambda _root: verified,
        representative_loader=_representatives,
        query_client_factory=client_factory,
        monotonic_ns=monotonic_ns,
        utc_now=lambda: "2026-08-29T12:00:00Z",
    )

    assert measured["measurement_source"] == probe.MEASUREMENT_SOURCE
    assert measured["externally_supplied"] is False
    assert measured["observed_at"] == "2026-08-29T12:00:00Z"
    assert measured["probe_bindings"]["revision"] == REVISION
    assert measured["key_sets"]["canonical_keys_sha256"] == KEY_DIGEST
    assert measured["query_canaries"]["jurisdictions"] == list(
        probe.SORTED_JURISDICTIONS
    )
    assert len(measured["query_canaries"]["jurisdictions"]) == 51
    assert "DC" in measured["query_canaries"]["jurisdictions"]
    assert measured["benchmark"]["cold"]["cache_hits"] == 0
    assert measured["benchmark"]["warm"]["cache_hits"] == 1
    assert measured["benchmark"]["cold"]["latency_ms"] == 1.0
    assert measured["benchmark"]["warm"]["latency_ms"] == 1.0
    assert measured["benchmark"]["complete_family_downloaded"] is False

    tampered = copy.deepcopy(measured)
    tampered["probe_bindings"]["revision"] = "5" * 40
    with pytest.raises(probe.StateLawsReleaseProbeBindingError, match="drifted"):
        probe.assert_first_party_measurement(
            tampered,
            repo_id=DEFAULT_DATASET_REPO_ID,
            revision=REVISION,
            release_manifest_digest=RELEASE_DIGEST,
            parent_evidence_digest=PARENT_DIGEST,
        )


def test_local_probe_times_the_successful_seed_search(tmp_path: Path) -> None:
    manifest = {
        "artifacts": [
            {"relative_path": "indexes/probe.parquet"},
            {"relative_path": "indexes/not-fetched.parquet"},
        ],
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "jurisdictions": list(probe.SORTED_JURISDICTIONS),
        "key_parity": {"parent_entry_cids_sha256": KEY_DIGEST},
    }
    verified = SimpleNamespace(
        manifest_digest=RELEASE_DIGEST,
        output_root=tmp_path,
        payload=manifest,
    )
    clock = 0
    opened = 0

    class SeedFallbackClient(_FakeQueryClient):
        def bm25_search(self, query: str, *, top_k: int, jurisdiction: str) -> dict:
            nonlocal clock
            assert top_k == 5
            if query == "empty":
                clock += 3_000_000
                payload = self._result(f"cid-{jurisdiction}")
                payload["ordered_result_cids"] = []
                payload["results"] = []
                return payload
            assert query == "statute"
            clock += 7_000_000
            return self._result(f"cid-{jurisdiction}")

    def client_factory(**_kwargs: object) -> SeedFallbackClient:
        nonlocal opened
        opened += 1
        return SeedFallbackClient(warm=opened > 1)

    representatives = _representatives(verified)
    representatives["jurisdictions"][probe.SORTED_JURISDICTIONS[0]] = (
        probe.QueryRepresentative(
            jurisdiction=probe.SORTED_JURISDICTIONS[0],
            entry_cid=f"cid-{probe.SORTED_JURISDICTIONS[0]}",
            query_terms=("empty", "statute"),
            query_vector=(1.0,),
        )
    )

    measured = probe.run_local_release_probe(
        tmp_path,
        repo_id=DEFAULT_DATASET_REPO_ID,
        revision=REVISION,
        release_manifest_digest=RELEASE_DIGEST,
        parent_evidence_digest=PARENT_DIGEST,
        release_verifier=lambda _root: verified,
        representative_loader=lambda _verified: representatives,
        query_client_factory=client_factory,
        monotonic_ns=lambda: clock,
        utc_now=lambda: "2026-08-29T12:00:00Z",
    )

    assert measured["benchmark"]["cold"]["latency_ms"] == 10.0


def test_production_shaped_descriptor_discovery_binds_real_key_parity(
    tmp_path: Path,
) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    artifacts: list[dict[str, object]] = []
    entry_cids: list[str] = []
    for code in probe.SORTED_JURISDICTIONS:
        entry_cid = f"cid-{code}"
        entry_cids.append(entry_cid)
        chunk_relative = f"data/corpus/jurisdiction={code}/part-00000.parquet"
        vector_relative = f"indexes/vectors/jurisdiction={code}/part-00000.parquet"
        chunk = tmp_path / chunk_relative
        vector = tmp_path / vector_relative
        chunk.parent.mkdir(parents=True, exist_ok=True)
        vector.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.Table.from_pylist(
                [
                    {
                        "body": "Statute duties and remedies",
                        "entry_cid": entry_cid,
                    }
                ]
            ),
            chunk,
        )
        pq.write_table(
            pa.Table.from_pylist([{"embedding": [1.0], "entry_cid": entry_cid}]),
            vector,
        )
        artifacts.extend(
            [
                {
                    "family": "corpus",
                    "metadata": {
                        "jurisdiction_code": code,
                        "stage": "canonical_chunks",
                    },
                    "relative_path": chunk_relative,
                },
                {"family": "vectors", "relative_path": vector_relative},
            ]
        )
    graph_relative = "indexes/graph/adjacency/out/part-00000.parquet"
    graph = tmp_path / graph_relative
    graph.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist([{"entry_cid": entry_cids[0], "pointers": []}]),
        graph,
    )
    artifacts.append({"family": "graph_adjacency_out", "relative_path": graph_relative})
    key_digest = probe._canonical_digest({"parent_entry_cids": sorted(entry_cids)})
    manifest = {
        "artifacts": artifacts,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "jurisdictions": list(probe.SORTED_JURISDICTIONS),
        "key_parity": {"parent_entry_cids_sha256": key_digest},
    }
    verified = SimpleNamespace(
        manifest_digest=RELEASE_DIGEST,
        output_root=tmp_path,
        payload=manifest,
    )
    opened = 0

    def client_factory(**_kwargs: object) -> _FakeQueryClient:
        nonlocal opened
        opened += 1
        return _FakeQueryClient(warm=opened > 1)

    tick = 0

    def monotonic_ns() -> int:
        nonlocal tick
        tick += 1_000_000
        return tick

    measured = probe.run_local_release_probe(
        tmp_path,
        repo_id=DEFAULT_DATASET_REPO_ID,
        revision=REVISION,
        release_manifest_digest=RELEASE_DIGEST,
        parent_evidence_digest=PARENT_DIGEST,
        release_verifier=lambda _root: verified,
        query_client_factory=client_factory,
        monotonic_ns=monotonic_ns,
        utc_now=lambda: "2026-08-29T12:00:00Z",
    )

    assert measured["key_sets"]["canonical_keys_sha256"] == key_digest
    assert measured["key_sets"]["passed"] is True


def test_pinned_viewer_probe_is_bounded_revision_bound_and_payload_redacted() -> None:
    calls: list[tuple[str, int, float]] = []
    manifest = {
        "artifacts": [
            {
                "media_type": "application/vnd.apache.parquet",
                "relative_path": "data/corpus/part-000000.parquet",
                "row_count": 51,
            },
            {
                "media_type": "application/vnd.apache.parquet",
                "relative_path": "data/bm25/documents/part-000000.parquet",
                "row_count": 11,
            },
            {
                "media_type": "application/vnd.apache.parquet",
                "relative_path": "data/bm25/postings/part-000000.parquet",
                "row_count": 12,
            },
            {
                "media_type": "application/vnd.apache.parquet",
                "relative_path": "data/vectors/part-000000.parquet",
                "row_count": 8,
            },
            {
                "media_type": "application/vnd.apache.parquet",
                "relative_path": "data/graph/nodes/part-000000.parquet",
                "row_count": 10,
            },
            {
                "config_name": probe.DEFAULT_CONFIG_NAME,
                "media_type": "application/vnd.apache.parquet",
                "relative_path": "indexes/bm25_document_chunks.parquet",
                "row_count": 999,
            },
        ],
        "configs": {
            "canonical_chunks": {"config_digest": "5" * 64},
            "default": probe.DEFAULT_CONFIG_NAME,
            "local_staging_only": True,
        },
        "corpus": {"row_count": 51},
        "counts": {"corpus_documents": 51},
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "jurisdictions": list(probe.SORTED_JURISDICTIONS),
        "key_parity": {"parent_entry_cids_sha256": KEY_DIGEST},
    }
    manifest_digest = probe._canonical_digest(manifest)

    def fetch(url: str, *, max_bytes: int, timeout: float) -> dict:
        calls.append((url, max_bytes, timeout))
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        assert parsed.scheme == "https"
        assert parsed.netloc == "datasets-server.huggingface.co"
        assert query["dataset"] == [DEFAULT_DATASET_REPO_ID]
        assert "revision" not in query
        endpoint = parsed.path.rsplit("/", 1)[-1]
        if endpoint in {"info", "size"}:
            assert query["config"] == [probe.DEFAULT_CONFIG_NAME]
        else:
            assert "config" not in query
        payloads = {
            "is-valid": {
                "viewer": True,
                "preview": True,
                "search": False,
                "filter": False,
                "statistics": False,
                "private_payload": "not retained",
            },
            "info": {
                "dataset_info": {
                    "config_name": probe.DEFAULT_CONFIG_NAME,
                    "splits": {"train": {"num_examples": 51}},
                },
                "partial": False,
                "pending": [],
                "failed": [],
            },
            "size": {
                "size": {
                    "config": {
                        "config": probe.DEFAULT_CONFIG_NAME,
                        "num_bytes": 1_024,
                        "num_rows": 51,
                    },
                    "splits": [{"config": probe.DEFAULT_CONFIG_NAME, "split": "train"}],
                },
                "partial": False,
                "pending": [],
                "failed": [],
            },
            "splits": {
                "splits": [{"config": probe.DEFAULT_CONFIG_NAME, "split": "train"}],
                "pending": [],
                "failed": [],
            },
        }
        body = json.dumps(payloads[endpoint]).encode()
        return {
            "body": body,
            "headers": {"X-Revision": REVISION},
            "status": 200,
        }

    measured = probe.run_pinned_viewer_probe(
        repo_id=DEFAULT_DATASET_REPO_ID,
        revision=REVISION,
        verified_manifest=manifest,
        release_manifest_digest=manifest_digest,
        viewer_fetch=fetch,
        max_bytes=4_096,
        timeout=3.0,
    )

    assert len(calls) == len(probe.VIEWER_ENDPOINTS)
    assert all(bound == 4_096 and timeout == 3.0 for _, bound, timeout in calls)
    assert measured["pinned_revision"] == REVISION
    assert measured["jurisdictions"] == list(probe.SORTED_JURISDICTIONS)
    assert measured["manifest_binding"]["expected_rows"] == 51
    assert measured["manifest_binding"]["default_matched_artifact_count"] == 1
    assert measured["manifest_binding"]["manifest_default_data_files"] == [
        {"path": "data/corpus/part-*.parquet", "split": "train"}
    ]
    assert measured["manifest_binding"]["default_data_files"] == [
        {
            "path": (
                f"data/state_laws/sha256-{manifest_digest}/data/corpus/part-*.parquet"
            ),
            "split": "train",
        }
    ]
    assert "not retained" not in json.dumps(measured)
    assert all(
        set(item)
        == {
            "endpoint",
            "response_bytes",
            "response_sha256",
            "semantic",
            "status",
            "x_revision",
        }
        for item in measured["responses"]
    )

    def missing_header(url: str, *, max_bytes: int, timeout: float) -> dict:
        response = fetch(url, max_bytes=max_bytes, timeout=timeout)
        response["headers"] = {}
        return response

    with pytest.raises(probe.StateLawsReleaseProbeViewerError, match="requested pin"):
        probe.run_pinned_viewer_probe(
            repo_id=DEFAULT_DATASET_REPO_ID,
            revision=REVISION,
            verified_manifest=manifest,
            release_manifest_digest=manifest_digest,
            viewer_fetch=missing_header,
        )

    def bogus_header(url: str, *, max_bytes: int, timeout: float) -> dict:
        response = fetch(url, max_bytes=max_bytes, timeout=timeout)
        response["headers"] = {"x-revision": "9" * 40}
        return response

    with pytest.raises(probe.StateLawsReleaseProbeViewerError, match="requested pin"):
        probe.run_pinned_viewer_probe(
            repo_id=DEFAULT_DATASET_REPO_ID,
            revision=REVISION,
            verified_manifest=manifest,
            release_manifest_digest=manifest_digest,
            viewer_fetch=bogus_header,
        )


@pytest.mark.parametrize(
    ("endpoint", "mutation", "message"),
    (
        ("info", {"partial": True}, "info is not explicitly complete"),
        ("size", {"partial": True}, "size is not explicitly complete"),
        ("size", {"size": {"config": []}}, "config-scoped result"),
        ("splits", {"pending": None}, "pending is not explicitly empty"),
        ("splits", {"failed": [{"kind": "job"}]}, "failed/pending work"),
    ),
)
def test_viewer_semantics_reject_partial_or_malformed_production_payloads(
    endpoint: str,
    mutation: dict[str, object],
    message: str,
) -> None:
    payloads: dict[str, dict[str, object]] = {
        "info": {
            "dataset_info": {
                "config_name": probe.DEFAULT_CONFIG_NAME,
                "splits": {"train": {"num_examples": 51}},
            },
            "failed": [],
            "partial": False,
            "pending": [],
        },
        "size": {
            "failed": [],
            "partial": False,
            "pending": [],
            "size": {
                "config": {
                    "config": probe.DEFAULT_CONFIG_NAME,
                    "num_bytes": 1_024,
                    "num_rows": 51,
                },
                "splits": [{"config": probe.DEFAULT_CONFIG_NAME, "split": "train"}],
            },
        },
        "splits": {
            "failed": [],
            "pending": [],
            "splits": [{"config": probe.DEFAULT_CONFIG_NAME, "split": "train"}],
        },
    }
    payloads[endpoint].update(mutation)

    with pytest.raises(probe.StateLawsReleaseProbeViewerError, match=message):
        probe._viewer_semantic_summary(
            endpoint,
            payloads[endpoint],
            expected_rows=51,
        )


def test_mapping_manifest_viewer_rows_fail_closed_on_artifact_drift() -> None:
    base = {
        "artifacts": [
            {
                "media_type": "application/vnd.apache.parquet",
                "relative_path": "data/corpus/part-000000.parquet",
                "row_count": 7,
            }
        ],
        "configs": {
            "canonical_chunks": {"config_digest": "5" * 64},
            "default": probe.DEFAULT_CONFIG_NAME,
            "local_staging_only": True,
        },
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "jurisdictions": list(probe.SORTED_JURISDICTIONS),
        "key_parity": {"parent_entry_cids_sha256": KEY_DIGEST},
    }
    binding = probe._viewer_manifest_contract(
        base,
        release_manifest_digest=probe._canonical_digest(base),
    )
    assert binding["manifest_default_data_files"] == [
        {"path": "data/corpus/part-*.parquet", "split": "train"}
    ]
    assert binding["default_data_files"] == [
        {
            "path": (
                f"data/state_laws/sha256-{probe._canonical_digest(base)}/"
                "data/corpus/part-*.parquet"
            ),
            "split": "train",
        }
    ]
    assert binding["expected_rows"] == 7

    malformed = []
    missing_config = copy.deepcopy(base)
    missing_config["configs"].pop("canonical_chunks")
    malformed.append(missing_config)
    unsafe = copy.deepcopy(base)
    unsafe["artifacts"][0]["relative_path"] = "data/../escape.parquet"
    malformed.append(unsafe)
    unmatched = copy.deepcopy(base)
    unmatched["artifacts"][0]["relative_path"] = "indexes/default.parquet"
    malformed.append(unmatched)
    missing_rows = copy.deepcopy(base)
    missing_rows["artifacts"][0].pop("row_count")
    malformed.append(missing_rows)

    for manifest in malformed:
        with pytest.raises(probe.StateLawsReleaseProbeViewerError):
            probe._viewer_manifest_contract(
                manifest,
                release_manifest_digest=probe._canonical_digest(manifest),
            )


def test_remote_probe_uses_candidate_prefix_and_public_measurements(
    tmp_path: Path,
) -> None:
    manifest = {
        "artifacts": [
            {"relative_path": "indexes/probe.parquet"},
            {"relative_path": "indexes/not-fetched.parquet"},
        ],
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "jurisdictions": list(probe.SORTED_JURISDICTIONS),
        "key_parity": {"parent_entry_cids_sha256": KEY_DIGEST},
    }
    verified = SimpleNamespace(
        manifest_digest=RELEASE_DIGEST,
        output_root=tmp_path,
        payload=manifest,
    )
    cache_opens: dict[str, int] = {}
    remote_kwargs: list[dict[str, object]] = []

    def client_factory(**kwargs: object) -> _FakeQueryClient:
        cache = str(kwargs["cache_dir"])
        cache_opens[cache] = cache_opens.get(cache, 0) + 1
        prefix = kwargs.get("release_prefix")
        if prefix is not None:
            remote_kwargs.append(dict(kwargs))
        return _FakeQueryClient(
            warm=cache_opens[cache] > 1,
            release_prefix=str(prefix) if prefix is not None else None,
        )

    clock = 0

    def monotonic_ns() -> int:
        nonlocal clock
        clock += 1_000_000
        return clock

    measured = probe.run_remote_release_probe(
        tmp_path,
        repo_id=DEFAULT_DATASET_REPO_ID,
        revision=REVISION,
        release_manifest_digest=RELEASE_DIGEST,
        parent_evidence_digest=PARENT_DIGEST,
        release_verifier=lambda _root: verified,
        representative_loader=_representatives,
        query_client_factory=client_factory,
        monotonic_ns=monotonic_ns,
        utc_now=lambda: "2026-08-29T12:00:00Z",
    )

    expected_prefix = f"data/state_laws/sha256-{RELEASE_DIGEST}"
    assert remote_kwargs
    assert all(item["manifest_path"] == "manifest.json" for item in remote_kwargs)
    assert all(item["release_prefix"] == expected_prefix for item in remote_kwargs)
    assert measured["remote_sparse_queries_executed"] is True
    assert measured["remote_query_trace"]["release_prefix"] == expected_prefix
    assert measured["benchmark"]["cold"]["cache_hits"] == 0
    assert measured["benchmark"]["warm"]["cache_hits"] == 1
    assert (
        measured["benchmark"]["local_ordered_cids_sha256"]
        == measured["benchmark"]["public_ordered_cids_sha256"]
    )


def test_external_measurement_cannot_cross_first_party_trust_boundary() -> None:
    external = {
        "externally_supplied": True,
        "measurement_source": "operator_json",
        "observed_at": "2026-08-29T12:00:00Z",
        "probe_bindings": probe.release_probe_bindings(
            repo_id=DEFAULT_DATASET_REPO_ID,
            revision=REVISION,
            release_manifest_digest=RELEASE_DIGEST,
            parent_evidence_digest=PARENT_DIGEST,
        ),
    }
    with pytest.raises(
        probe.StateLawsReleaseProbeBindingError, match="internally observed"
    ):
        probe.assert_first_party_measurement(
            external,
            repo_id=DEFAULT_DATASET_REPO_ID,
            revision=REVISION,
            release_manifest_digest=RELEASE_DIGEST,
            parent_evidence_digest=PARENT_DIGEST,
        )


def test_dual_pin_probe_queries_both_pins_and_replays_forward_switch(
    tmp_path: Path,
) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    previous = "6" * 40
    opens: list[str] = []
    cache_opens: dict[str, int] = {}

    def client_factory(**kwargs: object) -> _FakeRemoteClient:
        revision = str(kwargs["revision"])
        cache = str(kwargs["cache_dir"])
        opens.append(revision)
        cache_opens[cache] = cache_opens.get(cache, 0) + 1
        return _FakeRemoteClient(
            revision=revision,
            warm=cache_opens[cache] > 1,
            release_prefix=(
                str(kwargs["release_prefix"])
                if kwargs.get("release_prefix") is not None
                else None
            ),
        )

    sink = pa.BufferOutputStream()
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "legacy-cid-one",
                    "name": "District law",
                    "state_code": "DC",
                    "text": "The law governs this section.",
                },
                {
                    "ipfs_cid": "legacy-cid-two",
                    "name": "Another title",
                    "state_code": "DC",
                    "text": "A person shall comply with state law.",
                },
            ]
        ),
        sink,
    )
    legacy_body = sink.getvalue().to_pybytes()
    legacy_fetches: list[dict[str, object]] = []

    def legacy_fetcher(**kwargs: object) -> dict[str, object]:
        legacy_fetches.append(dict(kwargs))
        return {
            "body": legacy_body,
            "relative_path": probe.LEGACY_PIN_PROBE_PATH,
            "revision": previous,
            "sha256": hashlib.sha256(legacy_body).hexdigest(),
            "size_bytes": len(legacy_body),
            "status": 200,
        }

    clock = 0

    def monotonic_ns() -> int:
        nonlocal clock
        clock += 1_000_000
        return clock

    measured = probe.run_dual_pin_probe(
        tmp_path / "dual-pin-cache",
        repo_id=DEFAULT_DATASET_REPO_ID,
        new_revision=REVISION,
        previous_revision=previous,
        release_manifest_digest=RELEASE_DIGEST,
        parent_evidence_digest=PARENT_DIGEST,
        query_client_factory=client_factory,
        legacy_pin_fetcher=legacy_fetcher,
        monotonic_ns=monotonic_ns,
        utc_now=lambda: "2026-08-29T12:00:00Z",
    )

    assert opens == [REVISION, REVISION, REVISION]
    assert len(legacy_fetches) == 1
    assert legacy_fetches[0]["revision"] == previous
    assert legacy_fetches[0]["relative_path"] == probe.LEGACY_PIN_PROBE_PATH
    assert measured["new"]["revision"] == REVISION
    assert measured["new"]["release_prefix"] == (
        f"data/state_laws/sha256-{RELEASE_DIGEST}"
    )
    assert measured["previous"]["revision"] == previous
    assert measured["previous"]["release_prefix"] == "state_laws_parquet_cid"
    assert measured["previous"]["layout"] == "legacy_state_parquet_v1"
    assert measured["previous"]["artifact_path"] == probe.LEGACY_PIN_PROBE_PATH
    assert measured["previous"]["row_count"] == 2
    assert measured["previous"]["cold"]["bytes"] == len(legacy_body)
    assert measured["previous"]["warm"]["bytes"] == 0
    assert measured["new"]["cold"]["bytes"] == 64
    assert measured["new"]["warm"]["bytes"] == 0
    assert measured["switch"] == {
        "back_to_new": True,
        "bounded": True,
        "deletion_performed": False,
        "forward_replay_latency_ms": 1.0,
        "recoverable": True,
        "remote_mutation_performed": False,
        "to_previous": True,
    }
    assert measured["probe_bindings"]["previous_revision"] == previous


def test_post_publication_probe_derives_exact_51_from_verified_receipts(
    tmp_path: Path,
) -> None:
    descriptors: list[dict] = []
    large_receipt_size = 0
    for code in probe.SORTED_JURISDICTIONS:
        relative = f"receipts/scrape/jurisdiction-{code}.json"
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source_checksum = hashlib.sha256(f"source-{code}".encode()).hexdigest()
        content_hashes = ["a" * 64] * 31_000 if code == "AR" else []
        target.write_text(
            json.dumps(
                {
                    "content_hashes": content_hashes,
                    "discovered": len(content_hashes),
                    "duplicates": 0,
                    "excluded": 0,
                    "failed_final": 0,
                    "fetched": len(content_hashes),
                    "frontier_closed": True,
                    "jurisdiction": code,
                    "observation_time": "2026-08-10T12:00:00Z",
                    "official_source_url": f"https://example.gov/{code}",
                    "payload": {},
                    "quarantined": 0,
                    "receipt_id": f"receipt-{code}",
                    "relative_path": relative,
                    "release_point": "2026-08-10",
                    "schema_version": "state-laws-local-release/v1",
                    "source_authority_class": "official",
                    "source_checksum": source_checksum,
                    "source_software_version": "test-producer@1",
                    "start_urls": [f"https://example.gov/{code}"],
                    "verification_result": "verified",
                }
            ),
            encoding="utf-8",
        )
        size_bytes = target.stat().st_size
        if code == "AR":
            large_receipt_size = size_bytes
        descriptors.append(
            {
                "metadata": {
                    "jurisdiction_code": code,
                    "receipt_kind": "source_receipt",
                },
                "relative_path": relative,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "size_bytes": size_bytes,
            }
        )
    assert probe.DEFAULT_MAX_QUERY_BYTES < large_receipt_size
    assert large_receipt_size <= probe.DEFAULT_MAX_SOURCE_RECEIPT_BYTES
    verified = SimpleNamespace(
        manifest_digest=RELEASE_DIGEST,
        output_root=tmp_path,
        payload={
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "jurisdictions": list(probe.SORTED_JURISDICTIONS),
            "source_receipts": {"artifacts": descriptors, "row_count": 51},
        },
    )
    dependencies = {
        "public_benchmark": "7" * 64,
        "public_canary": "8" * 64,
        "rollback_rehearsal": PARENT_DIGEST,
    }
    measured = probe.run_post_publication_audit_probe(
        tmp_path,
        repo_id=DEFAULT_DATASET_REPO_ID,
        revision=REVISION,
        release_manifest_digest=RELEASE_DIGEST,
        parent_evidence_digest=PARENT_DIGEST,
        dependency_digests=dependencies,
        currentness_disclaimer=(
            "Timestamps are not a claim of legal currentness; consult the official source."
        ),
        release_verifier=lambda _root: verified,
        utc_now=lambda: "2026-08-29T12:00:00Z",
    )

    assert measured["source_receipts"]["count"] == 51
    assert measured["source_receipts"]["jurisdictions"] == list(
        probe.SORTED_JURISDICTIONS
    )
    assert measured["update_checkpoints"]["completion_basis"] == "source_frontier"
    assert measured["manifests"]["remote_manifest_digest"] == RELEASE_DIGEST
    assert measured["dependency_digests"] == dependencies
    assert measured["upstream_changes"] == []


def test_source_receipt_reader_rejects_declared_and_actual_hard_cap(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "not-opened.json"
    with pytest.raises(
        probe.StateLawsReleaseProbeError, match="descriptor exceeded the audit hard cap"
    ):
        probe._read_source_receipt_json(
            absent,
            declared_size=probe.DEFAULT_MAX_SOURCE_RECEIPT_BYTES + 1,
        )

    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.truncate(probe.DEFAULT_MAX_SOURCE_RECEIPT_BYTES + 1)
    with pytest.raises(
        probe.StateLawsReleaseProbeError, match="artifact exceeded the audit hard cap"
    ):
        probe._read_source_receipt_json(
            oversized,
            declared_size=probe.DEFAULT_MAX_SOURCE_RECEIPT_BYTES,
        )
