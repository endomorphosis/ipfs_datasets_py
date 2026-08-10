"""Unit tests for streaming proof-cache migration adapters (DQK-026).

Acceptance coverage:

* Imports are idempotent and bounded
* Ambiguous key/TTL/trust mappings quarantine rather than guess
* Whole-file JSON rewrites cease after promotion
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.logic.backends.cache_protocol import CachePolarity
from ipfs_datasets_py.logic.backends.results import ResultStatus
from ipfs_datasets_py.logic.common.duckdb_proof_migration import (
    DEFAULT_BATCH_SIZES,
    PROOF_MIGRATION_INTERFACE,
    PROOF_MIGRATION_SCHEMA_VERSION,
    AuthorityMode,
    ImportDisposition,
    MemoryProofMigrationBackend,
    MigrationStatus,
    ProofCacheFamily,
    ProofCacheMigrator,
    ProofMigrationError,
    ProofMigrationQuarantineError,
    batch_size_for,
    detect_proof_cache_family,
    differential_read,
    normalize_legacy_record,
    original_byte_digest,
    source_digest_for_path,
    translate_status,
    translate_trust,
    translate_ttl,
)
from ipfs_datasets_py.logic.common.duckdb_proof_store import (
    ProofTrustLevel,
    UnifiedProofKey,
    build_duckdb_proof_store,
)
from ipfs_datasets_py.logic.common.duckdb_proof_migration import RawLegacyRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, data: str | bytes | dict | list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(
            json.dumps(data, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    elif isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _common_cache(*entries: dict) -> dict:
    return {
        "schema_version": "proof-cache-v1",
        "entries": list(entries),
        "written_at": 1_700_000_000.0,
    }


def _common_entry(
    *,
    cid: str = "cid-a",
    formula: str = "P(x)",
    prover: str = "z3",
    status: str = "proved",
    result: dict | None = None,
    timestamp: float = 1_700_000_000.0,
) -> dict:
    return {
        "cid": cid,
        "formula_str": formula,
        "prover_name": prover,
        "result": result if result is not None else {"status": status, "ok": True},
        "timestamp": timestamp,
        "hit_count": 0,
        "status": status,
    }


def _hammer_entry(
    *,
    obligation: str = "sha256:" + ("a" * 64),
    status: str = "proved",
    trust: str = "non_trusted",
    kernel_accepted: bool = False,
    deterministic_trusted: bool = False,
) -> dict:
    premise = "sha256:" + ("b" * 64)
    return {
        "key": {
            "obligation_digest": obligation,
            "selected_premise_digests": [premise],
            "translation_version_digest": "sha256:" + ("c" * 64),
            "solver_identities_digest": "sha256:" + ("d" * 64),
            "lean_toolchain_identity_digest": "sha256:" + ("e" * 64),
            "theorem_registry_digest": "sha256:" + ("f" * 64),
            "policy_digest": "sha256:" + ("1" * 64),
            "resource_budget_digest": "sha256:" + ("2" * 64),
            "schema_version": "hammer-proof-obligation-key-v1",
        },
        "outcome": {
            "status": status,
            "trust": trust,
            "payload": {"steps": 3},
            "kernel_accepted": kernel_accepted,
            "deterministic_trusted": deterministic_trusted,
            "atp_claimed_proof": not kernel_accepted and not deterministic_trusted,
            "authority": "z3",
            "schema_version": "hammer-proof-outcome-v1",
        },
        "created_at": 1_700_000_000.0,
        "accessed_at": 1_700_000_000.0,
    }


def _integration_entry(
    *,
    formula_hash: str = "fh-1",
    prover: str = "lean",
    status: str = "proved",
    ttl: int = 3600,
) -> dict:
    return {
        "formula_hash": formula_hash,
        "prover": prover,
        "result_data": {"status": status, "proof": "…"},
        "timestamp": 1_700_000_000.0,
        "ttl": ttl,
        "hit_count": 1,
        "metadata": {},
        "status": status,
    }


def _legal_record(
    *,
    profile: str = "gdpr-core",
    proved: bool = True,
) -> dict:
    source_digest = "sha256:" + ("3" * 64)
    artifact_digest = "sha256:" + ("4" * 64)
    content_digest = "sha256:" + ("5" * 64)
    receipts = []
    if proved:
        receipts.append(
            {
                "status": "proved",
                "declaration_id": "decl-1",
                "authority": "theorem_proof",
            }
        )
    return {
        "schema_version": "legal-proof-record/v1",
        "source_id": "decl-1",
        "source_digest": source_digest,
        "profile": profile,
        "artifact": {
            "declaration_id": "decl-1",
            "declaration_digest": source_digest,
            "digest": artifact_digest,
        },
        "artifact_digest": artifact_digest,
        "artifact_cid": "bafylegalartifact0001",
        "content_digest": content_digest,
        "content_cid": "bafylegalcontent0001",
        "jurisdiction": "eu",
        "theorem_receipts": receipts,
    }


def _migrator(
    tmp_path: Path | None = None,
) -> tuple[ProofCacheMigrator, MemoryProofMigrationBackend]:
    backend = MemoryProofMigrationBackend()
    store = build_duckdb_proof_store(max_entries=256)
    return ProofCacheMigrator(store=store, backend=backend), backend


# ---------------------------------------------------------------------------
# Interface / detection / batch bounds
# ---------------------------------------------------------------------------


def test_interface_pins() -> None:
    migrator, _ = _migrator()
    assert migrator.interface == PROOF_MIGRATION_INTERFACE
    assert migrator.schema_version == PROOF_MIGRATION_SCHEMA_VERSION
    assert set(DEFAULT_BATCH_SIZES) == {
        "common",
        "tdfol",
        "cec",
        "integration",
        "hammers",
        "legal_ir",
        "external_provers",
    }
    assert all(size > 0 for size in DEFAULT_BATCH_SIZES.values())


def test_detect_family_from_schema_and_path() -> None:
    assert (
        detect_proof_cache_family(
            "cache.json",
            payload={"schema_version": "hammer-proof-obligation-cache-v1"},
        )
        is ProofCacheFamily.HAMMERS
    )
    assert (
        detect_proof_cache_family(
            "x.json",
            payload={"schema_version": "legal-proof-record/v1"},
        )
        is ProofCacheFamily.LEGAL_IR
    )
    assert (
        detect_proof_cache_family("tdfol_cache.json") is ProofCacheFamily.TDFOL
    )
    assert (
        detect_proof_cache_family("integration/proof_cache.json")
        is ProofCacheFamily.INTEGRATION
    )
    assert (
        detect_proof_cache_family("x.bin", explicit="external_provers")
        is ProofCacheFamily.EXTERNAL_PROVERS
    )


def test_batch_size_for_bounds() -> None:
    assert batch_size_for(ProofCacheFamily.COMMON) == DEFAULT_BATCH_SIZES["common"]
    assert batch_size_for("hammers", 7) == 7
    with pytest.raises(ProofMigrationError):
        batch_size_for(ProofCacheFamily.CEC, 0)


# ---------------------------------------------------------------------------
# Original-byte digests
# ---------------------------------------------------------------------------


def test_original_byte_digest_matches_exact_bytes(tmp_path: Path) -> None:
    payload = b'{"entries":[{"cid":"x"}]}\n'
    path = _write(tmp_path / "cache.json", payload)
    assert source_digest_for_path(path) == original_byte_digest(payload)
    assert source_digest_for_path(path) == _sha256_file(path)


def test_import_retains_source_byte_digest(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "common.json",
        _common_cache(_common_entry()),
    )
    migrator, backend = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.COMMON,
        idempotency_key="digest-1",
        batch_size=10,
    )
    assert receipt.source_digest == _sha256_file(path)
    assert receipt.accepted_count == 1
    assert receipt.status == MigrationStatus.COMPLETED.value


# ---------------------------------------------------------------------------
# Family adapters: common, tdfol, cec, integration, hammers, legal, external
# ---------------------------------------------------------------------------


def test_import_common_tdfol_cec_external(tmp_path: Path) -> None:
    families = [
        ProofCacheFamily.COMMON,
        ProofCacheFamily.TDFOL,
        ProofCacheFamily.CEC,
        ProofCacheFamily.EXTERNAL_PROVERS,
    ]
    for family in families:
        path = _write(
            tmp_path / f"{family.value}.json",
            _common_cache(
                _common_entry(cid=f"cid-{family.value}", prover=family.value)
            ),
        )
        migrator, _ = _migrator()
        receipt = migrator.import_path(
            path,
            family=family,
            idempotency_key=f"k-{family.value}",
        )
        assert receipt.accepted_count == 1, family
        assert receipt.family == family.value
        assert receipt.quarantined_count == 0


def test_import_integration_cache(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "integration.json",
        {"entries": [_integration_entry(), _integration_entry(formula_hash="fh-2")]},
    )
    migrator, _ = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.INTEGRATION,
        idempotency_key="int-1",
        batch_size=1,
    )
    assert receipt.accepted_count == 2
    assert receipt.batches_committed >= 2


def test_import_hammer_cache(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "hammers.json",
        {
            "schema_version": "hammer-proof-obligation-cache-v1",
            "entries": [
                _hammer_entry(),
                _hammer_entry(
                    obligation="sha256:" + ("9" * 64),
                    trust="trusted",
                    kernel_accepted=True,
                ),
            ],
        },
    )
    migrator, backend = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.HAMMERS,
        idempotency_key="hammer-1",
    )
    assert receipt.accepted_count == 2
    assert receipt.quarantined_count == 0
    # Trusted kernel entry lands at independently_checkable.
    digests = list(backend.list_accepted_digests(receipt.job_id))
    assert len(digests) == 2


def test_import_legal_ir_directory(tmp_path: Path) -> None:
    root = tmp_path / "legal_cache"
    records = root / "records"
    records.mkdir(parents=True)
    rec = _legal_record()
    _write(records / "bafylegalcontent0001.json", rec)
    _write(
        root / "index.json",
        {
            "interface": "LegalProofCache@1",
            "schema_version": "legal-proof-index/v1",
            "record_cids": ["bafylegalcontent0001"],
            "profiles": {"gdpr-core": "bafylegalcontent0001"},
            "source_digests": {},
        },
    )
    migrator, _ = _migrator()
    receipt = migrator.import_path(
        root,
        family=ProofCacheFamily.LEGAL_IR,
        idempotency_key="legal-1",
    )
    assert receipt.accepted_count == 1
    assert receipt.family == "legal_ir"


# ---------------------------------------------------------------------------
# Idempotent and bounded imports
# ---------------------------------------------------------------------------


def test_import_is_idempotent(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "common.json",
        _common_cache(_common_entry(), _common_entry(cid="cid-b", formula="Q(y)")),
    )
    migrator, backend = _migrator()
    first = migrator.import_path(
        path,
        family=ProofCacheFamily.COMMON,
        idempotency_key="idem-1",
        batch_size=1,
    )
    second = migrator.import_path(
        path,
        family=ProofCacheFamily.COMMON,
        idempotency_key="idem-1",
        batch_size=1,
    )
    assert first.accepted_count == 2
    assert second.status == MigrationStatus.SKIPPED_IDEMPOTENT.value
    assert second.receipt_id == first.receipt_id or second.accepted_count == first.accepted_count
    # Store size does not grow on re-import.
    assert migrator.store.stats()["writes"] == 2


def test_import_is_bounded_by_batch_and_max_entries(tmp_path: Path) -> None:
    entries = [
        _common_entry(cid=f"cid-{i}", formula=f"F{i}()")
        for i in range(5)
    ]
    path = _write(tmp_path / "bounded.json", _common_cache(*entries))
    backend = MemoryProofMigrationBackend()
    store = build_duckdb_proof_store(max_entries=256)
    migrator = ProofCacheMigrator(
        store=store,
        backend=backend,
        max_entries_per_job=3,
    )
    with pytest.raises(ProofMigrationError, match="max_entries_per_job"):
        migrator.import_path(
            path,
            family=ProofCacheFamily.COMMON,
            idempotency_key="bound-1",
            batch_size=2,
        )


def test_batch_size_commits_incrementally(tmp_path: Path) -> None:
    entries = [_common_entry(cid=f"c{i}", formula=f"G{i}()") for i in range(4)]
    path = _write(tmp_path / "batches.json", _common_cache(*entries))
    migrator, backend = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.COMMON,
        idempotency_key="batch-1",
        batch_size=2,
    )
    assert receipt.accepted_count == 4
    assert receipt.batches_committed == 2
    cursor = backend.get_cursor(receipt.job_id)
    assert cursor is not None
    assert cursor.next_record_index == 4


# ---------------------------------------------------------------------------
# Ambiguous key / TTL / trust → quarantine
# ---------------------------------------------------------------------------


def test_ambiguous_status_boolean_quarantines() -> None:
    with pytest.raises(ProofMigrationQuarantineError):
        translate_status(True)


def test_unknown_status_quarantines() -> None:
    with pytest.raises(ProofMigrationQuarantineError):
        translate_status("maybe-proved")


def test_trusted_without_kernel_quarantines() -> None:
    with pytest.raises(ProofMigrationQuarantineError):
        translate_trust("trusted", kernel_accepted=False, deterministic_trusted=False)


def test_authoritative_trust_cannot_be_inferred() -> None:
    with pytest.raises(ProofMigrationQuarantineError):
        translate_trust(ProofTrustLevel.AUTHORITATIVE)


def test_ambiguous_ttl_negative_exceeds_positive_quarantines() -> None:
    with pytest.raises(ProofMigrationQuarantineError):
        translate_ttl(positive_ttl=10, negative_ttl=100)


def test_mixed_single_and_partial_dual_ttl_quarantines() -> None:
    with pytest.raises(ProofMigrationQuarantineError):
        translate_ttl(family_ttl=3600, positive_ttl=100)


def test_conflicting_integration_ttl_quarantined(tmp_path: Path) -> None:
    entry = _integration_entry(ttl=100)
    entry["metadata"] = {"ttl": 200}
    path = _write(tmp_path / "bad_ttl.json", {"entries": [entry]})
    migrator, backend = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.INTEGRATION,
        idempotency_key="ttl-q",
    )
    assert receipt.accepted_count == 0
    assert receipt.quarantined_count == 1
    rejects = list(backend.list_rejects(receipt.job_id))
    assert rejects[0].disposition == ImportDisposition.QUARANTINED.value
    assert "ttl" in rejects[0].reason.lower()


def test_hammer_conflicting_key_digests_quarantined(tmp_path: Path) -> None:
    entry = _hammer_entry()
    entry["key"]["ir_digest"] = "sha256:" + ("0" * 64)
    # obligation_digest differs from ir_digest → quarantine
    path = _write(
        tmp_path / "bad_key.json",
        {"schema_version": "hammer-proof-obligation-cache-v1", "entries": [entry]},
    )
    migrator, backend = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.HAMMERS,
        idempotency_key="key-q",
    )
    assert receipt.quarantined_count == 1
    assert receipt.accepted_count == 0
    rejects = list(backend.list_rejects(receipt.job_id))
    assert rejects[0].disposition == ImportDisposition.QUARANTINED.value


def test_trusted_hammer_without_kernel_quarantined(tmp_path: Path) -> None:
    entry = _hammer_entry(trust="trusted", kernel_accepted=False)
    path = _write(
        tmp_path / "bad_trust.json",
        {"schema_version": "hammer-proof-obligation-cache-v1", "entries": [entry]},
    )
    migrator, backend = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.HAMMERS,
        idempotency_key="trust-q",
    )
    assert receipt.quarantined_count == 1
    rejects = list(backend.list_rejects(receipt.job_id))
    assert "trusted" in rejects[0].reason.lower() or "kernel" in rejects[0].reason.lower()


def test_common_missing_prover_quarantined(tmp_path: Path) -> None:
    entry = _common_entry()
    del entry["prover_name"]
    path = _write(tmp_path / "no_prover.json", _common_cache(entry))
    migrator, backend = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.COMMON,
        idempotency_key="prov-q",
    )
    assert receipt.quarantined_count == 1
    assert receipt.accepted_count == 0


def test_legal_index_cid_only_quarantined(tmp_path: Path) -> None:
    # Index with bare CIDs and no records/ directory → quarantine, not guess.
    path = _write(
        tmp_path / "index_only.json",
        {
            "interface": "LegalProofCache@1",
            "schema_version": "legal-proof-index/v1",
            "record_cids": ["bafyonlycid"],
            "profiles": {},
            "source_digests": {},
        },
    )
    migrator, backend = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.LEGAL_IR,
        idempotency_key="legal-q",
    )
    # record_cids expands to string values → quarantined
    assert receipt.accepted_count == 0
    assert receipt.quarantined_count + receipt.rejected_count >= 1


def test_translate_ttl_polarity_projection() -> None:
    pos = translate_ttl(entry_ttl=1000, polarity=CachePolarity.POSITIVE)
    assert pos.positive_ttl_seconds == 1000.0
    assert pos.source == "single_positive"
    neg = translate_ttl(entry_ttl=30, polarity=CachePolarity.NEGATIVE)
    assert neg.negative_ttl_seconds == 30.0
    assert neg.source == "single_negative"


def test_translate_status_aliases() -> None:
    assert translate_status("proved") is ResultStatus.PROVED
    assert translate_status("unsat") is ResultStatus.UNSATISFIABLE
    assert translate_status("timeout") is ResultStatus.TIMEOUT


# ---------------------------------------------------------------------------
# Differential reads / parity
# ---------------------------------------------------------------------------


def test_differential_read_and_parity_receipt(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "parity.json",
        _common_cache(
            _common_entry(cid="p1"),
            _common_entry(cid="p2", formula="R(z)"),
        ),
    )
    migrator, backend = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.COMMON,
        idempotency_key="parity-1",
        emit_parity=True,
    )
    assert receipt.accepted_count == 2
    parities = list(backend.list_parity())
    assert len(parities) == 1
    parity = parities[0]
    assert parity.matched is True
    assert parity.matched_count == 2
    assert parity.missing_in_store == 0
    assert parity.source_digest == receipt.source_digest


def test_differential_read_detects_missing(tmp_path: Path) -> None:
    store = build_duckdb_proof_store()
    # Build a normalized entry without writing it.
    raw = RawLegacyRecord(
        record_index=0,
        line_number=1,
        payload=_common_entry(cid="missing-1"),
        original_bytes_digest="sha256:" + ("a" * 64),
    )
    normalized = normalize_legacy_record(raw, family=ProofCacheFamily.COMMON)
    parity, comparisons = differential_read(
        legacy_entries=[normalized],
        store=store,
        family=ProofCacheFamily.COMMON,
        source_path="x.json",
        source_digest="sha256:" + ("b" * 64),
    )
    assert parity.missing_in_store == 1
    assert parity.matched is False
    assert comparisons[0].reason == "missing_in_store"


# ---------------------------------------------------------------------------
# Whole-file JSON rewrites cease after promotion
# ---------------------------------------------------------------------------


def test_whole_file_json_rewrite_allowed_before_promotion(tmp_path: Path) -> None:
    migrator, _ = _migrator()
    path = tmp_path / "legacy.json"
    migrator.write_legacy_json(
        path,
        _common_cache(_common_entry()),
        family=ProofCacheFamily.COMMON,
    )
    assert path.is_file()
    assert "proof-cache-v1" in path.read_text(encoding="utf-8")


def test_whole_file_json_rewrite_forbidden_after_promotion(tmp_path: Path) -> None:
    migrator, _ = _migrator()
    migrator.promote(ProofCacheFamily.COMMON, mode=AuthorityMode.PROMOTED)
    path = tmp_path / "legacy.json"
    with pytest.raises(ProofMigrationError, match="whole-file JSON rewrite forbidden"):
        migrator.write_legacy_json(
            path,
            _common_cache(_common_entry()),
            family=ProofCacheFamily.COMMON,
        )
    assert not path.exists()


def test_promotion_is_per_family(tmp_path: Path) -> None:
    migrator, _ = _migrator()
    migrator.promote(ProofCacheFamily.HAMMERS)
    # Hammers blocked…
    with pytest.raises(ProofMigrationError):
        migrator.write_legacy_json(
            tmp_path / "h.json",
            {"schema_version": "hammer-proof-obligation-cache-v1", "entries": []},
            family=ProofCacheFamily.HAMMERS,
        )
    # …common still allowed.
    migrator.write_legacy_json(
        tmp_path / "c.json",
        _common_cache(),
        family=ProofCacheFamily.COMMON,
    )
    assert (tmp_path / "c.json").is_file()


def test_export_only_mode_also_forbids_rewrite(tmp_path: Path) -> None:
    migrator, _ = _migrator()
    migrator.promote(ProofCacheFamily.TDFOL, mode=AuthorityMode.EXPORT_ONLY)
    with pytest.raises(ProofMigrationError):
        migrator.assert_json_rewrite_allowed(ProofCacheFamily.TDFOL, path="x.json")


def test_import_still_works_after_promotion(tmp_path: Path) -> None:
    """Promotion forbids rewrites, not one-shot streaming imports."""

    path = _write(tmp_path / "still.json", _common_cache(_common_entry(cid="post")))
    migrator, _ = _migrator()
    migrator.promote(ProofCacheFamily.COMMON)
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.COMMON,
        idempotency_key="post-promo",
    )
    assert receipt.accepted_count == 1
    with pytest.raises(ProofMigrationError):
        migrator.write_legacy_json(
            path,
            _common_cache(),
            family=ProofCacheFamily.COMMON,
        )


# ---------------------------------------------------------------------------
# Rejects retain provenance
# ---------------------------------------------------------------------------


def test_rejects_retain_source_provenance(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "mixed.json",
        _common_cache(
            _common_entry(cid="ok"),
            {"cid": "bad", "formula_str": "X", "result": {"status": "proved"}},
            # missing prover → quarantine
        ),
    )
    migrator, backend = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.COMMON,
        idempotency_key="rej-1",
    )
    assert receipt.accepted_count == 1
    assert receipt.quarantined_count == 1
    rejects = list(backend.list_rejects(receipt.job_id))
    assert len(rejects) == 1
    assert rejects[0].source_digest == receipt.source_digest
    assert rejects[0].record_index == 1
    assert rejects[0].source_path


# ---------------------------------------------------------------------------
# Store integration: accepted entries are lookup-able
# ---------------------------------------------------------------------------


def test_accepted_entries_are_lookupable_in_store(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "lookup.json",
        _common_cache(_common_entry(cid="lookup-1", formula="Lookup(x)")),
    )
    migrator, _ = _migrator()
    receipt = migrator.import_path(
        path,
        family=ProofCacheFamily.COMMON,
        idempotency_key="lookup-1",
    )
    assert receipt.accepted_count == 1
    # Rebuild the expected key the same way the adapter does.
    raw = RawLegacyRecord(
        record_index=0,
        line_number=1,
        payload=_common_entry(cid="lookup-1", formula="Lookup(x)"),
    )
    normalized = normalize_legacy_record(raw, family=ProofCacheFamily.COMMON)
    found = migrator.store.get(normalized.key)
    assert found is not None
    assert found.status is ResultStatus.PROVED
    assert found.trust_level is ProofTrustLevel.NONE


def test_hammer_key_lifts_to_unified_proof_key() -> None:
    entry = _hammer_entry(kernel_accepted=True, trust="trusted")
    raw = RawLegacyRecord(record_index=0, line_number=1, payload=entry)
    normalized = normalize_legacy_record(raw, family=ProofCacheFamily.HAMMERS)
    assert isinstance(normalized.key, UnifiedProofKey)
    assert normalized.trust_level is ProofTrustLevel.INDEPENDENTLY_CHECKABLE
    dims = normalized.key.dimension_map()
    assert "ir" in dims and "solver" in dims and "toolchain" in dims
