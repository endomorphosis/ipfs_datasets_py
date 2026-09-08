from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jsonschema
import pytest

from scripts.ops.legal_data import audit_state_laws_current_public_parent as audit

FIXED_NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)


def _commit_body(tree_oid: str, parent_oid: str | None = None) -> bytes:
    parent = f"parent {parent_oid}\n" if parent_oid is not None else ""
    return (
        f"tree {tree_oid}\n"
        f"{parent}"
        "author LCR Test <test@example.invalid> 0 +0000\n"
        "committer LCR Test <test@example.invalid> 0 +0000\n"
        "\n"
        "scripted evidence fixture\n"
    ).encode()


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()


def _raw(entry: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": entry["path"],
        "type": entry["kind"],
        "oid": entry["oid"],
    }
    if entry["kind"] == "file":
        result["size"] = entry["size"]
    return result


class ScriptedTransport:
    kind = "scripted"

    def __init__(
        self,
        *,
        wrong_parent: bool = False,
        page_size: int = 3,
    ) -> None:
        self.repository = audit.REPO_ID
        self.old_tree_oid = "1" * 40
        self.new_tree_oid = "2" * 40
        self.old_blobs = {
            "README.md": b"old readme\n",
            "manifest.json": b'{"generation":"old"}\n',
        }
        self.new_blobs = {
            "README.md": b"new readme\n",
            "manifest.json": b'{"generation":"new"}\n',
        }
        self.old_commit_body = _commit_body(self.old_tree_oid)
        self.old_pin = audit.git_object_oid("commit", self.old_commit_body)
        direct_parent = "f" * 40 if wrong_parent else self.old_pin
        self.new_commit_body = _commit_body(self.new_tree_oid, direct_parent)
        self.new_pin = audit.git_object_oid("commit", self.new_commit_body)

        old_entries = [
            {
                "path": "README.md",
                "kind": "file",
                "oid": audit.git_object_oid("blob", self.old_blobs["README.md"]),
                "size": len(self.old_blobs["README.md"]),
            },
            {"path": "data", "kind": "directory", "oid": _sha1("old-data-tree")},
            {"path": "data/base", "kind": "directory", "oid": _sha1("base-tree")},
            {
                "path": "data/base/a.bin",
                "kind": "file",
                "oid": _sha1("a.bin"),
                "size": 17,
            },
            {
                "path": "manifest.json",
                "kind": "file",
                "oid": audit.git_object_oid("blob", self.old_blobs["manifest.json"]),
                "size": len(self.old_blobs["manifest.json"]),
            },
            {"path": "top.txt", "kind": "file", "oid": _sha1("top.txt"), "size": 8},
        ]
        new_entries = copy.deepcopy(old_entries)
        by_path = {entry["path"]: entry for entry in new_entries}
        for path in ("README.md", "manifest.json"):
            by_path[path]["oid"] = audit.git_object_oid("blob", self.new_blobs[path])
            by_path[path]["size"] = len(self.new_blobs[path])
        by_path["data"]["oid"] = _sha1("new-data-tree")
        new_entries.extend(
            [
                {"path": "new", "kind": "directory", "oid": _sha1("new-tree")},
                {
                    "path": "new/b.bin",
                    "kind": "file",
                    "oid": _sha1("b.bin"),
                    "size": 19,
                },
            ]
        )
        self.old_entries = sorted(old_entries, key=lambda item: item["path"])
        self.new_entries = sorted(new_entries, key=lambda item: item["path"])

        root_sha = {
            self.old_pin: {
                path: audit.sha256_bytes(body) for path, body in self.old_blobs.items()
            },
            self.new_pin: {
                path: audit.sha256_bytes(body) for path, body in self.new_blobs.items()
            },
        }
        root_oids = {
            self.old_pin: {
                path: audit.git_object_oid("blob", body)
                for path, body in self.old_blobs.items()
            },
            self.new_pin: {
                path: audit.git_object_oid("blob", body)
                for path, body in self.new_blobs.items()
            },
        }
        self.contract = audit.EvidenceContract(
            repository=self.repository,
            historical_pin=self.old_pin,
            current_parent_pin=self.new_pin,
            historical_tree_oid=self.old_tree_oid,
            current_tree_oid=self.new_tree_oid,
            historical_files=4,
            historical_directories=2,
            current_files=5,
            current_directories=3,
            added_files=1,
            added_directories=1,
            modified_blob_paths=("README.md", "manifest.json"),
            root_blob_sha256=root_sha,
            root_blob_git_oids=root_oids,
        )
        self.routes: dict[str, audit.EvidenceResponse] = {}
        self._add_json(self._revision_endpoint("main"), {"sha": self.new_pin})
        self._add_json(self._revision_endpoint(self.new_pin), {"sha": self.new_pin})
        self._add_tree(self.old_pin, self.old_entries, page_size)
        self._add_tree(self.new_pin, self.new_entries, page_size)
        for revision, blobs in (
            (self.old_pin, self.old_blobs),
            (self.new_pin, self.new_blobs),
        ):
            for path, body in blobs.items():
                endpoint = self._blob_endpoint(revision, path)
                self.routes[endpoint] = audit.EvidenceResponse(
                    method="GET",
                    endpoint=endpoint,
                    status=200,
                    headers={"Content-Type": "application/octet-stream"},
                    body=body,
                )

    def _revision_endpoint(self, revision: str) -> str:
        return f"{audit.HUB_API_ROOT}/datasets/{self.repository}/revision/{revision}"

    def _tree_endpoint(self, revision: str) -> str:
        return (
            f"{audit.HUB_API_ROOT}/datasets/{self.repository}/tree/{revision}"
            "?recursive=true&expand=false&limit=1000"
        )

    def _blob_endpoint(self, revision: str, path: str) -> str:
        return f"{audit.HUB_DATASET_ROOT}/{self.repository}/resolve/{revision}/{path}"

    def _add_json(
        self, endpoint: str, payload: Any, *, link: str | None = None
    ) -> None:
        headers = {"Content-Type": "application/json"}
        if link is not None:
            headers["Link"] = f'<{link}>; rel="next"'
        self.routes[endpoint] = audit.EvidenceResponse(
            method="GET",
            endpoint=endpoint,
            status=200,
            headers=headers,
            body=json.dumps(payload, sort_keys=True).encode(),
        )

    def _add_tree(
        self, revision: str, entries: list[dict[str, Any]], page_size: int
    ) -> None:
        base = self._tree_endpoint(revision)
        pages = [
            entries[offset : offset + page_size]
            for offset in range(0, len(entries), page_size)
        ]
        for index, page in enumerate(pages):
            endpoint = base if index == 0 else f"{base}&cursor={index}"
            next_endpoint = (
                f"{base}&cursor={index + 1}" if index + 1 < len(pages) else None
            )
            self._add_json(
                endpoint,
                [_raw(entry) for entry in page],
                link=next_endpoint,
            )

    def request(self, method: str, endpoint: str) -> audit.EvidenceResponse:
        assert method == "GET"
        try:
            return self.routes[endpoint]
        except KeyError as exc:
            raise AssertionError(f"unexpected scripted endpoint: {endpoint}") from exc

    def commit_object(self, repository: str, revision: str) -> audit.EvidenceResponse:
        assert repository == self.repository
        if revision == self.old_pin:
            body = self.old_commit_body
        elif revision == self.new_pin:
            body = self.new_commit_body
        else:
            raise AssertionError(f"unexpected revision: {revision}")
        endpoint = f"{audit.HUB_DATASET_ROOT}/{repository}.git#commit={revision}"
        return audit.EvidenceResponse(
            method="GIT_CAT_FILE",
            endpoint=endpoint,
            status=200,
            headers={"Content-Type": "application/x-git-commit"},
            body=body,
        )


def _collect(transport: ScriptedTransport) -> dict[str, Any]:
    return audit.collect_evidence(
        transport,
        verifier_clock=lambda: FIXED_NOW,
        contract=transport.contract,
    )


def _reself(receipt: dict[str, Any]) -> None:
    receipt[audit.RECEIPT_SELF_DIGEST_FIELD] = audit.sha256_canonical(
        {
            key: value
            for key, value in receipt.items()
            if key != audit.RECEIPT_SELF_DIGEST_FIELD
        }
    )


def test_production_contract_keeps_historical_and_current_roles_distinct() -> None:
    contract = audit.DEFAULT_CONTRACT
    assert contract.historical_pin == ("42f0546acc7c6cd55627eaf51fb820d5613b9021")
    assert contract.current_parent_pin == ("78cba0ed86c3971a7b90620c6df167af8a1a6fb2")
    assert contract.historical_pin != contract.current_parent_pin
    assert contract.historical_paths == 2_878
    assert contract.current_paths == 3_231
    assert contract.added_paths == 353
    assert contract.added_files == 232
    assert contract.added_directories == 121
    assert contract.modified_blob_paths == ("README.md", "manifest.json")


def test_schema_is_valid_and_seals_lcr084_live_constants() -> None:
    schema = audit._load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["properties"]["task_id"]["const"] == "LCR-084"
    assert schema["properties"]["mode"]["const"] == "live"
    assert schema["properties"]["fixture_only"]["const"] is False
    assert (
        schema["properties"]["delta"]["properties"]["added_path_count"]["const"] == 353
    )
    assert schema["properties"]["delta"]["properties"]["deleted_paths"]["const"] == []
    assert audit.CANONICAL_RECEIPT_RELPATH.as_posix() == (
        "docs/reports/legal_corpora_reindex/"
        "state_laws_current_public_parent_evidence.json"
    )


def test_scripted_transport_exercises_pagination_delta_roots_and_self_digest() -> None:
    transport = ScriptedTransport(page_size=3)
    receipt = _collect(transport)

    assert receipt["mode"] == "scripted"
    assert receipt["fixture_only"] is True
    assert receipt["pins"]["historical_baseline"]["role"] == (
        "sealed_historical_evidence_only"
    )
    assert receipt["pins"]["current_public_parent"]["role"] == (
        "optimistic_parent_and_rollback_only"
    )
    assert receipt["commits"]["exact_direct_ancestry"] is True
    assert receipt["inventories"]["historical_baseline"]["page_count"] == 2
    assert receipt["inventories"]["current_public_parent"]["page_count"] == 3
    assert receipt["delta"]["added_path_count"] == 2
    assert receipt["delta"]["added_file_count"] == 1
    assert receipt["delta"]["added_directory_count"] == 1
    assert receipt["delta"]["deleted_paths"] == []
    assert receipt["delta"]["modified_blob_paths"] == [
        "README.md",
        "manifest.json",
    ]
    assert receipt["root_blobs"]["count"] == 4
    assert receipt["current_corpus_non_acceptance"]["current_corpus_accepted"] is False
    assert receipt["current_corpus_non_acceptance"]["authorizes_hub_mutation"] is False
    assert receipt["receipt_sha256"] == audit.sha256_canonical(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )


def test_scripted_receipt_can_never_pass_canonical_live_validation() -> None:
    receipt = _collect(ScriptedTransport())
    with pytest.raises(audit.PublicParentEvidenceError):
        audit.validate_receipt(receipt, require_live=False)


def test_transport_kind_string_cannot_spoof_live_evidence() -> None:
    transport = ScriptedTransport()
    transport.kind = audit.LiveHubTransport.kind
    receipt = _collect(transport)
    assert receipt["mode"] == "scripted"
    assert receipt["fixture_only"] is True


def test_duplicate_json_keys_are_rejected() -> None:
    with pytest.raises(audit.PublicParentEvidenceError, match="duplicate JSON"):
        audit._strict_json_loads(b'{"sha":"first","sha":"second"}', "fixture")


def test_mutable_main_drift_fails_before_tree_collection() -> None:
    transport = ScriptedTransport()
    endpoint = transport._revision_endpoint("main")
    transport._add_json(endpoint, {"sha": transport.old_pin})
    with pytest.raises(
        audit.PublicParentEvidenceError, match="mutable main did not resolve"
    ):
        _collect(transport)


def test_raw_commit_object_hash_is_not_trusted_from_transport() -> None:
    transport = ScriptedTransport()
    transport.new_commit_body += b"forged"
    with pytest.raises(audit.PublicParentEvidenceError, match="does not hash"):
        _collect(transport)


def test_exact_direct_parent_is_required_even_for_self_consistent_commit() -> None:
    transport = ScriptedTransport(wrong_parent=True)
    with pytest.raises(audit.PublicParentEvidenceError, match="not the direct child"):
        _collect(transport)


def test_pagination_loop_fails_closed() -> None:
    transport = ScriptedTransport()
    endpoint = transport._tree_endpoint(transport.old_pin)
    response = transport.routes[endpoint]
    transport.routes[endpoint] = audit.EvidenceResponse(
        method=response.method,
        endpoint=response.endpoint,
        status=response.status,
        headers={
            "Content-Type": "application/json",
            "Link": f'<{endpoint}>; rel="next"',
        },
        body=response.body,
    )
    with pytest.raises(audit.PublicParentEvidenceError, match="pagination loop"):
        _collect(transport)


def test_pagination_cannot_switch_immutable_revision() -> None:
    transport = ScriptedTransport()
    endpoint = transport._tree_endpoint(transport.old_pin)
    response = transport.routes[endpoint]
    wrong = transport._tree_endpoint(transport.new_pin)
    transport.routes[endpoint] = audit.EvidenceResponse(
        method=response.method,
        endpoint=response.endpoint,
        status=response.status,
        headers={
            "Content-Type": "application/json",
            "Link": f'<{wrong}>; rel="next"',
        },
        body=response.body,
    )
    with pytest.raises(audit.PublicParentEvidenceError, match="immutable revision"):
        _collect(transport)


def test_silent_early_pagination_termination_fails_exact_counts() -> None:
    transport = ScriptedTransport()
    endpoint = transport._tree_endpoint(transport.old_pin)
    response = transport.routes[endpoint]
    transport.routes[endpoint] = audit.EvidenceResponse(
        method=response.method,
        endpoint=response.endpoint,
        status=response.status,
        headers={"Content-Type": "application/json"},
        body=response.body,
    )
    with pytest.raises(
        audit.PublicParentEvidenceError, match="historical files drifted"
    ):
        _collect(transport)


def test_duplicate_path_across_pages_fails_closed() -> None:
    transport = ScriptedTransport(page_size=3)
    base = transport._tree_endpoint(transport.old_pin)
    second = f"{base}&cursor=1"
    response = transport.routes[second]
    payload = json.loads(response.body)
    payload[0] = _raw(transport.old_entries[0])
    transport._add_json(second, payload)
    with pytest.raises(audit.PublicParentEvidenceError, match="duplicate tree path"):
        _collect(transport)


def test_independent_root_blob_hash_rejects_changed_bytes() -> None:
    transport = ScriptedTransport()
    endpoint = transport._blob_endpoint(transport.new_pin, "README.md")
    response = transport.routes[endpoint]
    transport.routes[endpoint] = audit.EvidenceResponse(
        method=response.method,
        endpoint=response.endpoint,
        status=response.status,
        headers=response.headers,
        body=response.body + b"tamper",
    )
    with pytest.raises(audit.PublicParentEvidenceError, match="SHA-256 mismatch"):
        _collect(transport)


def test_recomputed_outer_digest_does_not_hide_inventory_tampering() -> None:
    transport = ScriptedTransport()
    receipt = _collect(transport)
    receipt["inventories"]["current_public_parent"]["entries"][0]["oid"] = "a" * 40
    _reself(receipt)
    with pytest.raises(audit.PublicParentEvidenceError, match="entry digest mismatch"):
        audit._validate_against_contract(
            receipt,
            contract=transport.contract,
            now=FIXED_NOW,
            require_live=False,
            validate_schema=False,
        )


def test_recomputed_outer_digest_does_not_weaken_non_acceptance() -> None:
    transport = ScriptedTransport()
    receipt = _collect(transport)
    receipt["current_corpus_non_acceptance"]["authorizes_publication"] = True
    _reself(receipt)
    with pytest.raises(
        audit.PublicParentEvidenceError, match="non-acceptance was weakened"
    ):
        audit._validate_against_contract(
            receipt,
            contract=transport.contract,
            now=FIXED_NOW,
            require_live=False,
            validate_schema=False,
        )


def test_page_request_response_hashes_are_cross_linked() -> None:
    transport = ScriptedTransport()
    receipt = _collect(transport)
    page = receipt["inventories"]["historical_baseline"]["pages"][0]
    page["response_sha256"] = "0" * 64
    receipt["inventories"]["historical_baseline"]["pages_sha256"] = (
        audit.sha256_canonical(receipt["inventories"]["historical_baseline"]["pages"])
    )
    _reself(receipt)
    with pytest.raises(
        audit.PublicParentEvidenceError, match="request/response hash mismatch"
    ):
        audit._validate_against_contract(
            receipt,
            contract=transport.contract,
            now=FIXED_NOW,
            require_live=False,
            validate_schema=False,
        )


def test_verifier_owned_timestamp_is_strict_and_fresh() -> None:
    transport = ScriptedTransport()
    receipt = _collect(transport)
    assert receipt["observed_at_utc"] == "2026-08-29T12:00:00.000Z"
    with pytest.raises(audit.PublicParentEvidenceError, match="stale"):
        audit._validate_against_contract(
            receipt,
            contract=transport.contract,
            now=FIXED_NOW + timedelta(seconds=audit.MAX_EVIDENCE_AGE_SECONDS + 1),
            require_live=False,
            validate_schema=False,
        )
    with pytest.raises(audit.PublicParentEvidenceError, match="future"):
        audit._validate_against_contract(
            receipt,
            contract=transport.contract,
            now=FIXED_NOW - timedelta(milliseconds=1),
            require_live=False,
            validate_schema=False,
        )


def test_cli_requires_an_explicit_read_only_mode() -> None:
    with pytest.raises(SystemExit) as exc:
        audit.main([])
    assert exc.value.code == 2
