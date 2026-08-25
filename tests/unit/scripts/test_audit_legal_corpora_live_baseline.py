"""Hermetic unit tests for LCR-081 authenticated live baseline provenance."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.ops.legal_data.audit_federal_register_hf_baseline import (
    ADVERTISED_DOCUMENT_COUNT,
    PINNED_REVISION as FEDERAL_PIN,
)
from scripts.ops.legal_data.audit_legal_corpora_live_baseline import (
    FEDERAL_REPO_ID,
    GOAL_ID,
    JURISDICTION_COUNT,
    MODE_DRY_RUN,
    MODE_LIVE,
    PRODUCER,
    REPORT_SCHEMA,
    STATE_CANONICAL_PARQUET,
    STATE_EMBEDDING_PARQUET,
    STATE_PINNED_REVISION,
    STATE_REPO_ID,
    TASK_ID,
    TRANSPORT_LIVE_HTTPS,
    VIEWER_ENDPOINTS,
    WHOAMI_ENDPOINT,
    LiveBaselineAuditError,
    LiveHubTransport,
    ScriptedHubTransport,
    assert_no_path_leakage,
    assert_no_token_leakage,
    build_dry_run_receipt,
    build_receipt,
    dataset_resolve_url,
    dataset_revision_url,
    dataset_tree_url,
    datasets_server_url,
    expected_jurisdiction_codes,
    inventory_salvage_root,
    main,
    no_self_field_root_digest,
    observe_with_live_hub,
    persist_and_verify_receipt,
    require_commit_sha,
    seal_receipt,
    state_partition_path,
    validate_nested_digests,
    validate_receipt,
    write_receipt,
)
from scripts.ops.legal_data.audit_state_laws_hf_baseline import (
    JURISDICTION_CODES,
    PER_STATE_CANONICAL_TOTAL_ROWS,
    PINNED_REVISION as STATE_PIN,
    TRUNCATION_EXAMPLES,
    VIEWER_CANONICAL_ROW_COUNT,
    VIEWER_EMBEDDING_ROW_COUNT,
)


SCRIPT_TOKEN = "scripted-lcr081-token-not-an-hf-prefix"

# Independently observed Hub partition counts at the sealed pin. Tests replay
# them through Parquet footers rather than copying sealed constants into the
# observation path.
LIVE_PARTITION_ROWS: dict[str, int] = {
    "AL": 129,
    "AK": 63,
    "AZ": 9021,
    "AR": 180,
    "CA": 10,
    "CO": 5,
    "CT": 160,
    "DE": 6602,
    "DC": 62,
    "FL": 24436,
    "GA": 2,
    "HI": 4,
    "ID": 583,
    "IL": 59797,
    "IN": 4,
    "IA": 47204,
    "KS": 20677,
    "KY": 33190,
    "LA": 160,
    "ME": 154,
    "MD": 160,
    "MA": 160,
    "MI": 160,
    "MN": 288,
    "MS": 1,
    "MO": 29,
    "MT": 2,
    "NE": 115,
    "NV": 149,
    "NH": 112,
    "NJ": 152,
    "NM": 159,
    "NY": 1850,
    "NC": 141,
    "ND": 160,
    "OH": 160,
    "OK": 2,
    "OR": 727,
    "PA": 240,
    "RI": 157,
    "SC": 140,
    "SD": 160,
    "TN": 18,
    "TX": 3701,
    "UT": 153,
    "VT": 160,
    "VA": 160,
    "WA": 1,
    "WV": 1,
    "WI": 160,
    "WY": 82,
}


def _parquet_bytes(table: pa.Table) -> bytes:
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def _int_parquet(num_rows: int) -> bytes:
    return _parquet_bytes(pa.table({"n": pa.array(range(num_rows), type=pa.int32())}))


@pytest.fixture(scope="module")
def partition_parquets() -> dict[str, bytes]:
    assert sum(LIVE_PARTITION_ROWS.values()) == PER_STATE_CANONICAL_TOTAL_ROWS
    return {code: _int_parquet(rows) for code, rows in LIVE_PARTITION_ROWS.items()}


@pytest.fixture(scope="module")
def viewer_parquets() -> dict[str, bytes]:
    canonical = _parquet_bytes(
        pa.table(
            {
                "state_code": ["IA"] * VIEWER_CANONICAL_ROW_COUNT,
                "ipfs_cid": [f"canon-{index}" for index in range(VIEWER_CANONICAL_ROW_COUNT)],
            }
        )
    )
    codes = list(JURISDICTION_CODES)
    remaining = VIEWER_EMBEDDING_ROW_COUNT - len(codes)
    emb_codes = codes + (["OR"] * remaining)
    embeddings = _parquet_bytes(
        pa.table(
            {
                "state_code": emb_codes,
                "ipfs_cid": [f"emb-{index}" for index in range(VIEWER_EMBEDDING_ROW_COUNT)],
            }
        )
    )
    return {
        STATE_CANONICAL_PARQUET: canonical,
        STATE_EMBEDDING_PARQUET: embeddings,
    }


def _file(path: str, size: int = 1, blob: str = "a" * 40) -> dict[str, Any]:
    return {
        "path": path,
        "type": "file",
        "size": size,
        "oid": blob,
    }


def _state_tree_items() -> list[dict[str, Any]]:
    items = [
        _file(state_partition_path(code), size=100 + index)
        for index, code in enumerate(JURISDICTION_CODES)
    ]
    items.append(_file(STATE_CANONICAL_PARQUET, size=200))
    items.append(_file(STATE_EMBEDDING_PARQUET, size=201))
    items.append(_file("README.md", size=80, blob="c" * 40))
    for code in JURISDICTION_CODES:
        if code not in {"CA", "DC"}:
            items.append(_file(f"state_summaries/{code}.json", size=12))
    padding = 2116 - len(items)
    for index in range(padding):
        items.append(_file(f"padding/{index:04d}.bin", size=1))
    assert len(items) == 2116
    return items


def _federal_tree_items() -> list[dict[str, Any]]:
    items = [
        _file("federal_register.parquet", size=400),
        _file("metadata.json", size=120),
        _file("federal_register.jsonld", size=50),
        _file("manifest.json", size=50),
        _file("federal_register_raw/shard.json", size=10),
        _file("federal_register_gte_small.faiss", size=10),
        _file("federal_register_gte_small_metadata.parquet", size=10),
    ]
    padding = 555 - len(items)
    for index in range(padding):
        items.append(_file(f"source_recovery/pad-{index:04d}.json", size=2))
    assert len(items) == 555
    return items


def _whoami() -> dict[str, Any]:
    return {
        "name": "fixture-user",
        "type": "user",
        "id": "id-fixture",
        "email": "should-not-persist@example.invalid",
        "fullname": "Redacted Person",
        "orgs": [{"name": "justicedao", "type": "org"}],
        "auth": {
            "type": "access_token",
            "accessToken": {"displayName": "write-test", "role": "write"},
        },
    }


def _readme() -> str:
    return (
        "---\npretty_name: IPFS State Laws\n"
        "configs:\n- config_name: state_laws_canonical\n"
        "---\n# IPFS State Laws\nThe canonical corpus has 20,514 rows and "
        "17,338 embedding rows.\n"
    )


def _federal_metadata() -> dict[str, Any]:
    return {
        "documents_count": ADVERTISED_DOCUMENT_COUNT,
        "deduplicated_documents": ADVERTISED_DOCUMENT_COUNT,
        "include_full_text": False,
        "date_range": {"start_date": "1994-01-01", "end_date": "2026-03-02"},
        "partitioning": {"queried_ranges": 255},
    }


def _json_response(payload: Any, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return {"status": 200, "headers": headers or {}, "body": json.dumps(payload)}


def _bytes_response(body: bytes, status: int = 200) -> dict[str, Any]:
    return {"status": status, "headers": {}, "body": body}


def build_scripted_responses(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    *,
    state_sha: str = STATE_PIN,
    federal_sha: str = FEDERAL_PIN,
    include_dc: bool = True,
    state_tree: list[dict[str, Any]] | None = None,
    federal_parquet_rows: int = 12,
) -> dict[str, Any]:
    responses: dict[str, Any] = {}
    responses[f"GET {WHOAMI_ENDPOINT}"] = _json_response(_whoami())

    state_tree = list(state_tree) if state_tree is not None else _state_tree_items()
    if not include_dc:
        state_tree = [item for item in state_tree if "STATE-DC.parquet" not in item["path"]]
    fed_tree = _federal_tree_items()
    federal_parquet = _int_parquet(federal_parquet_rows)

    for repo, sha, tree in (
        (STATE_REPO_ID, state_sha, state_tree),
        (FEDERAL_REPO_ID, federal_sha, fed_tree),
    ):
        responses[f"GET {dataset_revision_url(repo, sha)}"] = _json_response(
            {
                "sha": sha,
                "id": repo,
                "siblings": [{"rfilename": item["path"]} for item in tree[:20]],
                "cardData": {
                    "configs": [
                        {"config_name": "state_laws_canonical"}
                    ]
                },
                "lastModified": "2026-05-31T18:49:49.000Z",
            }
        )
        responses[f"GET {dataset_tree_url(repo, sha)}"] = _json_response(tree)
        for endpoint in ("is-valid", "info", "size", "splits"):
            url = datasets_server_url(endpoint, repo, sha)
            if endpoint == "is-valid":
                responses[f"GET {url}"] = _json_response(
                    {
                        "preview": False,
                        "viewer": False,
                        "search": False,
                        "filter": False,
                        "statistics": False,
                    }
                )
            else:
                responses[f"GET {url}"] = {
                    "status": 500,
                    "headers": {},
                    "body": b'{"error":"unavailable"}',
                }

    for code, blob in partition_parquets.items():
        url = dataset_resolve_url(STATE_REPO_ID, state_sha, state_partition_path(code))
        responses[f"GET {url}"] = _bytes_response(blob)
    for path, blob in viewer_parquets.items():
        url = dataset_resolve_url(STATE_REPO_ID, state_sha, path)
        responses[f"GET {url}"] = _bytes_response(blob)
    responses[
        f"GET {dataset_resolve_url(STATE_REPO_ID, state_sha, 'README.md')}"
    ] = _bytes_response(_readme().encode("utf-8"))
    responses[
        f"GET {dataset_resolve_url(FEDERAL_REPO_ID, federal_sha, 'federal_register.parquet')}"
    ] = _bytes_response(federal_parquet)
    responses[
        f"GET {dataset_resolve_url(FEDERAL_REPO_ID, federal_sha, 'metadata.json')}"
    ] = _bytes_response(json.dumps(_federal_metadata()).encode("utf-8"))
    return responses


def _salvage_roots(tmp_path: Path) -> list[tuple[str, Path]]:
    parallel = tmp_path / "legal_scraper_parallel" / "20260518T072115Z"
    (parallel / "shard1").mkdir(parents=True, exist_ok=True)
    (parallel / "shard2").mkdir(exist_ok=True)
    (parallel / "shard3").mkdir(exist_ok=True)
    (parallel / "shard1" / "note.txt").write_text("ok\n", encoding="utf-8")
    state = tmp_path / "state_laws" / "state_laws_parquet_cid"
    state.mkdir(parents=True, exist_ok=True)
    for code in JURISDICTION_CODES:
        pq.write_table(
            pa.table({"n": [1, 2, 3]}),
            state / f"STATE-{code}.parquet",
        )
    secrets = tmp_path / "state_laws" / "secrets.json"
    secrets.write_text('{"hf_token":"should-not-be-copied"}', encoding="utf-8")
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("nope", encoding="utf-8")
    link = tmp_path / "state_laws" / "escape_link"
    if not link.exists() and not link.is_symlink():
        link.symlink_to(outside)
    federal = tmp_path / "federal_register" / "federal_register_parquet"
    federal.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"n": list(range(5))}), federal / "laws.parquet")
    return [
        ("legal_scraper_parallel", tmp_path / "legal_scraper_parallel"),
        ("state_laws", tmp_path / "state_laws"),
        ("federal_register", tmp_path / "federal_register"),
    ]


def _observe(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    transport = ScriptedHubTransport(
        build_scripted_responses(partition_parquets, viewer_parquets, **kwargs),
        token=SCRIPT_TOKEN,
    )
    return build_receipt(
        transport=transport,
        token=SCRIPT_TOKEN,
        token_source="test",
        salvage_roots=_salvage_roots(tmp_path),
        observed_at="2026-08-21T12:00:00.000Z",
        mode=MODE_LIVE,
    )


def test_jurisdiction_set_includes_all_51_and_dc() -> None:
    codes = expected_jurisdiction_codes()
    assert len(codes) == JURISDICTION_COUNT == 51
    assert "DC" in codes
    assert codes == list(JURISDICTION_CODES)


def test_scripted_observation_recomputes_sealed_state_totals(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    result = validate_receipt(
        receipt, require_live_hub=False, require_local_salvage_inventory=True
    )
    assert result["ok"] is True
    assert receipt["schema"] == REPORT_SCHEMA
    assert receipt["task_id"] == TASK_ID == "LCR-081"
    assert receipt["goal_id"] == GOAL_ID == "LCR-G143"
    assert receipt["producer"] == PRODUCER
    assert receipt["fixture_only"] is False
    assert receipt["authenticated_identity"]["name"] == "fixture-user"
    assert "email" not in receipt["authenticated_identity"]
    assert "fullname" not in receipt["authenticated_identity"]
    assert receipt["authenticated_identity"]["whoami_endpoint"] == WHOAMI_ENDPOINT
    assert receipt["state_laws"]["revision"] == STATE_PIN
    assert receipt["federal_register"]["revision"] == FEDERAL_PIN
    assert receipt["state_laws"]["counts"]["repository_files"] == 2116
    assert receipt["state_laws"]["counts"]["state_parquet_filenames"] == 51
    assert receipt["state_laws"]["counts"]["per_state_canonical_total_rows"] == 212_103
    assert receipt["state_laws"]["counts"]["viewer_canonical_rows"] == 47_204
    assert receipt["state_laws"]["viewer"]["canonical_config"]["ia_only"] is True
    assert receipt["state_laws"]["counts"]["viewer_embedding_rows"] == 17_338
    assert receipt["state_laws"]["cid_overlap"]["zero_overlap"] is True
    assert "DC" in receipt["state_laws"]["partitions"]
    assert receipt["state_laws"]["partitions"]["DC"]["num_rows"] == 62
    assert receipt["state_laws"]["partitions"]["GA"]["num_rows"] == 2
    assert all(
        part["content_sha256"] for part in receipt["state_laws"]["partitions"].values()
    )
    assert receipt["federal_register"]["parquet"]["content_sha256"]
    assert "FEDERAL_COUNT_CONTRADICTION" in {
        item["code"] for item in receipt["dispositions"]
    }
    validate_nested_digests(receipt)
    assert receipt["receipt_sha256"] == no_self_field_root_digest(receipt)
    assert receipt["state_laws"]["summaries"]["missing"] == ["CA", "DC"]
    assert receipt["federal_register"]["counts"]["advertised_documents"] == 993_703
    assert receipt["federal_register"]["counts"]["repository_files"] == 555
    assert receipt["requests"]
    assert all(item["response_sha256"] for item in receipt["requests"])
    assert receipt["local_salvage"]["secrets_copied"] is False
    assert receipt["local_salvage"]["three_shard_run_detected"] is True
    codes = {item["code"] for item in receipt["dispositions"]}
    assert "IA_ONLY_CANONICAL_VIEWER" in codes
    assert "README_ROW_COUNT_CONFLICT" in codes
    assert "FEDERAL_ADVERTISED_VS_HUB_PARQUET" in codes


def test_scripted_receipt_cannot_pass_require_live_hub(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    assert receipt["transport"] != TRANSPORT_LIVE_HTTPS
    with pytest.raises(LiveBaselineAuditError, match="fixture|urllib HTTPS"):
        validate_receipt(receipt, require_live_hub=True)


def test_dry_run_receipt_cannot_pass_require_live_hub(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    transport = ScriptedHubTransport(
        build_scripted_responses(partition_parquets, viewer_parquets),
        token=SCRIPT_TOKEN,
    )
    receipt = build_dry_run_receipt(
        transport=transport,
        salvage_roots=_salvage_roots(tmp_path),
        observed_at="2026-08-21T12:00:00.000Z",
        token=SCRIPT_TOKEN,
    )
    assert receipt["mode"] == MODE_DRY_RUN
    assert receipt["live_hub_contacted"] is False
    with pytest.raises(LiveBaselineAuditError, match="dry-run"):
        validate_receipt(receipt, require_live_hub=True)


def test_missing_dc_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    with pytest.raises(LiveBaselineAuditError, match="DC"):
        _observe(partition_parquets, viewer_parquets, tmp_path, include_dc=False)


def test_stale_pin_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    responses = build_scripted_responses(partition_parquets, viewer_parquets)
    url = dataset_revision_url(STATE_REPO_ID, STATE_PIN)
    payload = json.loads(responses[f"GET {url}"]["body"])
    payload["sha"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    responses[f"GET {url}"] = _json_response(payload)
    transport = ScriptedHubTransport(responses, token=SCRIPT_TOKEN)
    with pytest.raises(LiveBaselineAuditError, match="stale or changed pin"):
        build_receipt(
            transport=transport,
            token=SCRIPT_TOKEN,
            token_source="test",
            salvage_roots=_salvage_roots(tmp_path),
            observed_at="2026-08-21T12:00:00.000Z",
            mode=MODE_LIVE,
        )


def test_missing_response_hash_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["requests"][0]["response_sha256"] = ""
    receipt.pop("receipt_sha256", None)
    with pytest.raises(LiveBaselineAuditError, match="response_sha256"):
        validate_receipt(receipt, require_live_hub=False)


def test_token_leakage_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    assert_no_token_leakage(receipt, SCRIPT_TOKEN)
    leaked = dict(receipt)
    leaked["note"] = "hf_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    with pytest.raises(LiveBaselineAuditError, match="token leakage"):
        assert_no_token_leakage(leaked, None)


def test_fixture_only_flag_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["fixture_only"] = True
    receipt.pop("receipt_sha256", None)
    with pytest.raises(LiveBaselineAuditError, match="fixture-only"):
        validate_receipt(receipt, require_live_hub=False)


def test_contradictory_counts_without_typed_explanation_fail(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["state_laws"]["counts"]["per_state_canonical_total_rows"] = 1
    receipt["dispositions"] = [
        item
        for item in receipt["dispositions"]
        if item["code"] != "PER_STATE_TRUNCATION"
    ]
    receipt.pop("receipt_sha256", None)
    with pytest.raises(LiveBaselineAuditError, match="typed explanation|212103"):
        validate_receipt(receipt, require_live_hub=False)


def test_salvage_skips_secrets_and_symlinks(tmp_path: Path) -> None:
    roots = dict(_salvage_roots(tmp_path))
    record = inventory_salvage_root("state_laws", roots["state_laws"])
    assert record["disposition"] == "inventoried"
    assert record["skipped_secrets"] >= 1
    assert record["skipped_symlinks"] >= 1
    assert "DC" in record["state_partitions"]
    dumped = json.dumps(record)
    assert "should-not-be-copied" not in dumped
    assert "escape_link" not in dumped
    assert record["path_label"].startswith("$HOME/") or record["path_label"].startswith(
        "redacted-path:"
    )


def test_live_cli_path_actually_calls_hub(
    monkeypatch: pytest.MonkeyPatch,
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    responses = build_scripted_responses(partition_parquets, viewer_parquets)
    scripted = ScriptedHubTransport(responses, token=SCRIPT_TOKEN)
    calls: list[str] = []

    class FakeResp:
        def __init__(self, response: Any) -> None:
            self.status = response.status
            self.headers = response.headers
            self._body = response.body

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> FakeResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_open(request: Any, timeout: float | None = None) -> FakeResp:
        del timeout
        url = getattr(request, "full_url", None) or getattr(request, "get_full_url")()
        calls.append(str(url))
        response = scripted.request(request.get_method(), str(url))
        return FakeResp(response)

    monkeypatch.setenv("HF_TOKEN", SCRIPT_TOKEN)
    monkeypatch.setattr(
        "scripts.ops.legal_data.audit_legal_corpora_live_baseline.open_live_hub_url",
        fake_open,
    )
    salvage = _salvage_roots(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    argv = [
        "--require-live-hub",
        "--require-local-salvage-inventory",
        "--check",
        "--receipt",
        str(receipt_path),
    ]
    for name, path in salvage:
        argv.extend(["--salvage-root", f"{name}={path}"])
    code = main(argv)
    assert code == 0
    assert any("whoami" in url for url in calls)
    assert any("ipfs_state_laws" in url for url in calls)
    assert any("ipfs_federal_register" in url for url in calls)
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["mode"] == MODE_LIVE
    assert payload["transport"] == TRANSPORT_LIVE_HTTPS
    assert payload["live_hub_contacted"] is True
    validate_receipt(
        payload, require_live_hub=True, require_local_salvage_inventory=True
    )
    assert SCRIPT_TOKEN not in receipt_path.read_text(encoding="utf-8")
    assert "should-not-persist@example.invalid" not in receipt_path.read_text(
        encoding="utf-8"
    )


def test_cli_dry_run_cannot_satisfy_require_live_hub(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["--dry-run", "--require-live-hub", "--check"])
    captured = capsys.readouterr()
    assert code == 1
    assert "dry-run" in captured.err
    assert "require-live-hub" in captured.err


def test_observe_with_live_hub_uses_live_transport(
    monkeypatch: pytest.MonkeyPatch,
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    responses = build_scripted_responses(partition_parquets, viewer_parquets)
    scripted = ScriptedHubTransport(responses, token=SCRIPT_TOKEN)
    opened = {"count": 0}

    class FakeResp:
        def __init__(self, response: Any) -> None:
            self.status = response.status
            self.headers = response.headers
            self._body = response.body

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> FakeResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_open(request: Any, timeout: float | None = None) -> FakeResp:
        opened["count"] += 1
        url = getattr(request, "full_url", None) or request.get_full_url()
        return FakeResp(scripted.request(request.get_method(), str(url)))

    monkeypatch.setattr(
        "scripts.ops.legal_data.audit_legal_corpora_live_baseline.open_live_hub_url",
        fake_open,
    )
    receipt = observe_with_live_hub(
        salvage_roots=_salvage_roots(tmp_path),
        observed_at="2026-08-21T12:00:00.000Z",
        token=SCRIPT_TOKEN,
        token_source="test",
    )
    assert opened["count"] > 0
    assert receipt["transport"] == TRANSPORT_LIVE_HTTPS
    assert isinstance(
        LiveHubTransport(SCRIPT_TOKEN),
        LiveHubTransport,
    )
    validate_receipt(
        receipt, require_live_hub=True, require_local_salvage_inventory=True
    )


def test_write_round_trip(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    path = tmp_path / "live_baseline_provenance_receipt.json"
    write_receipt(receipt, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    validate_receipt(loaded, require_live_hub=False, require_local_salvage_inventory=True)
    assert loaded["pins"]["state_laws"] == STATE_PINNED_REVISION
    assert loaded["pins"]["federal_register"] == FEDERAL_PIN
    assert TRUNCATION_EXAMPLES["GA"] == loaded["state_laws"]["partitions"]["GA"]["num_rows"]
    persist_and_verify_receipt(
        loaded,
        tmp_path / "round_trip_check.json",
        require_live_hub=False,
        require_local_salvage_inventory=True,
    )


def test_mutable_revisions_are_rejected() -> None:
    for value in ("main", "latest", "HEAD", "", "master"):
        with pytest.raises(LiveBaselineAuditError, match="40-hex|mutable"):
            require_commit_sha(value, "revision")


def test_pagination_truncation_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    responses = build_scripted_responses(partition_parquets, viewer_parquets)
    tree_url = dataset_tree_url(STATE_REPO_ID, STATE_PIN)
    nxt = tree_url + "&cursor=truncated"
    responses[f"GET {tree_url}"] = {
        "status": 200,
        "headers": {"Link": f'<{nxt}>; rel="next"'},
        "body": json.dumps(_state_tree_items()[:20]),
    }
    transport = ScriptedHubTransport(responses, token=SCRIPT_TOKEN)
    with pytest.raises(LiveBaselineAuditError, match="pagination|missing"):
        build_receipt(
            transport=transport,
            token=SCRIPT_TOKEN,
            token_source="test",
            salvage_roots=_salvage_roots(tmp_path),
            observed_at="2026-08-21T12:00:00.000Z",
            mode=MODE_LIVE,
        )


def test_duplicate_inventory_path_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    tree = _state_tree_items()
    tree.append(dict(tree[0]))
    with pytest.raises(LiveBaselineAuditError, match="duplicate"):
        _observe(
            partition_parquets,
            viewer_parquets,
            tmp_path,
            state_tree=tree,
        )


def test_missing_inventory_metadata_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    tree = _state_tree_items()
    tree[0] = {"path": tree[0]["path"], "type": "file"}
    with pytest.raises(LiveBaselineAuditError, match="missing inventory metadata"):
        _observe(
            partition_parquets,
            viewer_parquets,
            tmp_path,
            state_tree=tree,
        )


def test_parquet_parse_failure_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    responses = build_scripted_responses(partition_parquets, viewer_parquets)
    url = dataset_resolve_url(STATE_REPO_ID, STATE_PIN, state_partition_path("DC"))
    responses[f"GET {url}"] = {"status": 200, "headers": {}, "body": b"not-a-parquet"}
    transport = ScriptedHubTransport(responses, token=SCRIPT_TOKEN)
    with pytest.raises(LiveBaselineAuditError, match="Parquet"):
        build_receipt(
            transport=transport,
            token=SCRIPT_TOKEN,
            token_source="test",
            salvage_roots=_salvage_roots(tmp_path),
            observed_at="2026-08-21T12:00:00.000Z",
            mode=MODE_LIVE,
        )


def test_viewer_omission_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    responses = build_scripted_responses(partition_parquets, viewer_parquets)
    url = datasets_server_url("splits", STATE_REPO_ID, STATE_PIN)
    del responses[f"GET {url}"]
    transport = ScriptedHubTransport(responses, token=SCRIPT_TOKEN)
    with pytest.raises(LiveBaselineAuditError, match="Viewer|scripted Hub missing"):
        build_receipt(
            transport=transport,
            token=SCRIPT_TOKEN,
            token_source="test",
            salvage_roots=_salvage_roots(tmp_path),
            observed_at="2026-08-21T12:00:00.000Z",
            mode=MODE_LIVE,
        )
    assert "splits" in VIEWER_ENDPOINTS


def test_empty_salvage_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty_root"
    empty.mkdir()
    transport = ScriptedHubTransport(
        build_scripted_responses(partition_parquets, viewer_parquets),
        token=SCRIPT_TOKEN,
    )
    with pytest.raises(LiveBaselineAuditError, match="empty salvage"):
        build_receipt(
            transport=transport,
            token=SCRIPT_TOKEN,
            token_source="test",
            salvage_roots=[("empty", empty)],
            observed_at="2026-08-21T12:00:00.000Z",
            mode=MODE_LIVE,
        )


def test_all_missing_salvage_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    transport = ScriptedHubTransport(
        build_scripted_responses(partition_parquets, viewer_parquets),
        token=SCRIPT_TOKEN,
    )
    with pytest.raises(LiveBaselineAuditError, match="empty salvage|all-missing"):
        build_receipt(
            transport=transport,
            token=SCRIPT_TOKEN,
            token_source="test",
            salvage_roots=[("missing", tmp_path / "nope")],
            observed_at="2026-08-21T12:00:00.000Z",
            mode=MODE_LIVE,
        )


def test_sampled_salvage_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["local_salvage"]["sampled"] = True
    receipt["local_salvage"]["roots"][0]["sampled"] = True
    with pytest.raises(LiveBaselineAuditError, match="sampled or truncated"):
        validate_receipt(receipt, require_live_hub=False)


def test_symlink_escape_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["local_salvage"]["symlinks_followed"] = True
    with pytest.raises(LiveBaselineAuditError, match="symlink escape"):
        validate_receipt(receipt, require_live_hub=False)


def test_stale_and_malformed_utc_fail_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["observed_at"] = "yesterday"
    with pytest.raises(LiveBaselineAuditError, match="UTC"):
        validate_receipt(receipt, require_live_hub=False)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    with pytest.raises(LiveBaselineAuditError, match="stale UTC"):
        validate_receipt(
            receipt,
            require_live_hub=False,
            require_fresh_observation=True,
            now="2099-01-01T00:00:00Z",
        )
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["observed_at"] = "2099-01-01T00:00:00Z"
    with pytest.raises(LiveBaselineAuditError, match="future UTC"):
        validate_receipt(
            receipt,
            require_live_hub=False,
            require_fresh_observation=True,
            now="2026-08-21T12:00:00.000Z",
        )


def test_absent_on_disk_receipt_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    target = tmp_path / "missing" / "receipt.json"
    monkeypatch.setattr(
        "scripts.ops.legal_data.audit_legal_corpora_live_baseline.write_receipt",
        lambda *_args, **_kwargs: target,
    )
    with pytest.raises(LiveBaselineAuditError, match="absent on-disk receipt"):
        persist_and_verify_receipt(receipt, target)


def test_altered_bytes_fail_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    path = tmp_path / "receipt.json"

    def _write_wrong(_payload: object, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('{"schema":"tampered"}\n', encoding="utf-8")
        return dest

    monkeypatch.setattr(
        "scripts.ops.legal_data.audit_legal_corpora_live_baseline.write_receipt",
        _write_wrong,
    )
    with pytest.raises(LiveBaselineAuditError, match="altered bytes"):
        persist_and_verify_receipt(receipt, path)


def test_fake_and_truncated_nested_hashes_fail_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["digests"]["state_inventory_sha256"] = "abc"
    with pytest.raises(LiveBaselineAuditError, match="fake or truncated nested hash"):
        validate_receipt(receipt, require_live_hub=False)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["digests"]["state_row_counts_sha256"] = "a" * 64
    with pytest.raises(LiveBaselineAuditError, match="row digest mismatch"):
        validate_receipt(receipt, require_live_hub=False)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["digests"]["state_inventory_sha256"] = "b" * 64
    with pytest.raises(LiveBaselineAuditError, match="inventory digest mismatch"):
        validate_receipt(receipt, require_live_hub=False)
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    receipt["receipt_sha256"] = "c" * 64
    with pytest.raises(LiveBaselineAuditError, match="root digest mismatch"):
        validate_receipt(receipt, require_live_hub=False)


def test_path_leakage_fails_closed(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    assert_no_path_leakage(receipt, _salvage_roots(tmp_path))
    leaked = dict(receipt)
    leaked["note"] = str(tmp_path / "state_laws")
    with pytest.raises(LiveBaselineAuditError, match="path leakage"):
        assert_no_path_leakage(leaked, _salvage_roots(tmp_path))


def test_seal_receipt_round_trip_keeps_nested_digests(
    partition_parquets: dict[str, bytes],
    viewer_parquets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    receipt = _observe(partition_parquets, viewer_parquets, tmp_path)
    sealed = seal_receipt(dict(receipt), SCRIPT_TOKEN)
    assert sealed["receipt_sha256"] == no_self_field_root_digest(sealed)
    validate_nested_digests(sealed)
