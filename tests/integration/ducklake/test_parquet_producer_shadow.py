"""Integration tests for Parquet producer DuckLake shadow authority (DQK-089).

Acceptance coverage:

* Every registered producer emits source, schema, snapshot, ownership, and
  parity receipts
* Existing Parquet/IPLD/CAR source byte identities do not drift
* Shadow integration consumes the current accepted DQK-081 inventory and exact
  active plan generation; stale inventory-snapshot, repository-tree, plan-root,
  or generation bindings fail closed
* A signed exact-tree inventory proves zero unowned public Parquet producers;
  waivers are reviewer-signed, path-scoped, justified, and expiring
* Shadow disagreement quarantines only the affected dataset

Hermetic: MemoryAuthorityBackend + signed DQK-081 receipts (no live DuckDB).
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

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

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.core_operations.dataset_converter import DatasetConverter
from ipfs_datasets_py.core_operations.dataset_loader import DatasetLoader
from ipfs_datasets_py.core_operations.dataset_saver import DatasetSaver
from ipfs_datasets_py.duckdb_control.inventory_refinement import (
    build_approval_receipt,
)
from ipfs_datasets_py.ducklake import adapters as ad
from ipfs_datasets_py.ducklake.adapters import (
    DOMAIN,
    OWNER_TASK_ID,
    REGISTERED_PARQUET_PRODUCERS,
    ActivePlanGenerationBinding,
    AdmittedLakeShadowAdapter,
    ParquetProducerId,
    ProducerSelectionError,
    SeedDeclarationRejectedError,
    StaleInventoryBindingError,
    UnownedProducerError,
    WaiverValidationError,
    bind_active_plan_generation,
    build_exact_tree_inventory_proof,
    build_producer_waiver,
    build_shadow_adapter,
    consume_dqk081_inventory,
    digest_bytes,
    list_registered_producers,
    prove_zero_unowned_public_parquet_producers,
    self_check,
    set_active_shadow_adapter,
    verify_producer_waiver,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

REPO_ID = "repository:sha256:test-dqk089-parquet-producer-shadow"
TREE_ID = "a" * 40
PLAN_ROOT = "sha256:" + ("11" * 32)
SNAPSHOT_CID = "sha256:" + ("22" * 32)
GENERATION_ID = "generation:dqk089-active-1"
ANALYZER_ID = "analyzer:inventory-refinement"
REVIEWER_ID = "reviewer:independent-dqk-081"


def _fresh_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return now - timedelta(minutes=1), now + timedelta(hours=2)


def _valid_receipt(
    *,
    snapshot_cid: str = SNAPSHOT_CID,
    tree_id: str = TREE_ID,
    plan_root: str = PLAN_ROOT,
    active_plan_root: str | None = None,
    accepted_plan_root: str | None = None,
    unresolved_gap_count: int = 0,
) -> dict[str, Any]:
    issued, expires = _fresh_window()
    active = active_plan_root if active_plan_root is not None else plan_root
    accepted = accepted_plan_root if accepted_plan_root is not None else plan_root
    return build_approval_receipt(
        repository_id=REPO_ID,
        repository_tree_id=tree_id,
        inventory_snapshot_cid=snapshot_cid,
        base_plan_root_cid=plan_root,
        accepted_plan_root_cid=accepted,
        active_plan_root_cid=active,
        reviewer_id=REVIEWER_ID,
        analyzer_id=ANALYZER_ID,
        unresolved_gap_count=unresolved_gap_count,
        issued_at=issued,
        expires_at=expires,
    )


def _active_generation(
    *,
    generation_id: str = GENERATION_ID,
    plan_root: str = PLAN_ROOT,
    tree_id: str = TREE_ID,
) -> ActivePlanGenerationBinding:
    return bind_active_plan_generation(
        generation_id=generation_id,
        plan_root_cid=plan_root,
        repository_tree_id=tree_id,
        database_identity="db:test-dqk089",
    )


def _adapter(**kwargs: Any) -> AdmittedLakeShadowAdapter:
    receipt = kwargs.pop("receipt", None) or _valid_receipt()
    generation = kwargs.pop("generation", None) or _active_generation()
    return build_shadow_adapter(
        refinement_receipt=receipt,
        active_generation=generation,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Install / registry
# ---------------------------------------------------------------------------


def test_self_check_and_closed_producer_registry() -> None:
    report = self_check()
    assert report["ok"] is True
    assert report["owner_task_id"] == OWNER_TASK_ID
    assert report["domain"] == DOMAIN
    assert report["mode"] == "shadow"
    assert report["seed_declarations_authorize"] is False
    assert report["legacy_is_authority_in_shadow"] is True
    assert report["disagreement_quarantines_dataset_only"] is True
    producers = list_registered_producers()
    assert len(producers) == 6
    assert set(producers) == set(REGISTERED_PARQUET_PRODUCERS)
    for name in (
        "dataset_loader",
        "dataset_saver",
        "dataset_converter",
        "knowledge_graphs_parquet_storage",
        "jsonl_to_parquet",
        "ipfs_parquet_to_car",
    ):
        assert name in producers


# ---------------------------------------------------------------------------
# DQK-081 inventory binding (fail closed)
# ---------------------------------------------------------------------------


def test_consume_current_accepted_dqk081_inventory() -> None:
    receipt = _valid_receipt()
    generation = _active_generation()
    binding = consume_dqk081_inventory(receipt, active_generation=generation)
    assert binding.inventory_snapshot_cid == SNAPSHOT_CID
    assert binding.repository_tree_id == TREE_ID
    assert binding.accepted_plan_root_cid == PLAN_ROOT
    assert binding.active_plan_root_cid == PLAN_ROOT
    assert binding.active_plan_generation_id == GENERATION_ID
    assert binding.approval_gate_task_id == "DQK-081"
    assert binding.seed_declaration is False
    assert binding.refinement_receipt_cid == receipt["receipt_cid"]


def test_stale_inventory_snapshot_fails_closed() -> None:
    receipt = _valid_receipt()
    generation = _active_generation()
    with pytest.raises(StaleInventoryBindingError, match="inventory.snapshot"):
        consume_dqk081_inventory(
            receipt,
            active_generation=generation,
            expected_inventory_snapshot_cid="sha256:" + ("33" * 32),
        )


def test_stale_repository_tree_fails_closed() -> None:
    receipt = _valid_receipt()
    generation = _active_generation()
    other_tree = "b" * 40
    with pytest.raises(StaleInventoryBindingError, match="repository-tree|tree"):
        consume_dqk081_inventory(
            receipt,
            active_generation=generation,
            expected_repository_tree_id=other_tree,
        )


def test_stale_plan_root_fails_closed() -> None:
    receipt = _valid_receipt()
    generation = _active_generation()
    other_plan = "sha256:" + ("44" * 32)
    with pytest.raises(StaleInventoryBindingError, match="plan"):
        consume_dqk081_inventory(
            receipt,
            active_generation=generation,
            expected_accepted_plan_root_cid=other_plan,
        )


def test_stale_generation_fails_closed() -> None:
    receipt = _valid_receipt()
    generation = _active_generation()
    with pytest.raises(StaleInventoryBindingError, match="generation"):
        consume_dqk081_inventory(
            receipt,
            active_generation=generation,
            expected_generation_id="generation:other",
        )


def test_generation_plan_root_mismatch_fails_closed() -> None:
    receipt = _valid_receipt()
    generation = _active_generation(plan_root="sha256:" + ("55" * 32))
    with pytest.raises(StaleInventoryBindingError):
        consume_dqk081_inventory(receipt, active_generation=generation)


def test_seed_declaration_cannot_authorize() -> None:
    receipt = _valid_receipt()
    generation = _active_generation()
    with pytest.raises(SeedDeclarationRejectedError):
        consume_dqk081_inventory(
            receipt,
            active_generation=generation,
            seed_marker="seed_declaration",
        )
    seeded = dict(receipt)
    seeded["seed_declaration"] = True
    with pytest.raises(SeedDeclarationRejectedError):
        consume_dqk081_inventory(seeded, active_generation=generation)


def test_adapter_assert_binding_current_rejects_stale() -> None:
    adapter = _adapter()
    adapter.assert_binding_current(
        inventory_snapshot_cid=SNAPSHOT_CID,
        repository_tree_id=TREE_ID,
        plan_root_cid=PLAN_ROOT,
        generation_id=GENERATION_ID,
    )
    with pytest.raises(StaleInventoryBindingError):
        adapter.assert_binding_current(
            inventory_snapshot_cid="sha256:" + ("66" * 32)
        )
    with pytest.raises(StaleInventoryBindingError):
        adapter.assert_binding_current(repository_tree_id="c" * 40)
    with pytest.raises(StaleInventoryBindingError):
        adapter.assert_binding_current(plan_root_cid="sha256:" + ("77" * 32))
    with pytest.raises(StaleInventoryBindingError):
        adapter.assert_binding_current(generation_id="generation:stale")


# ---------------------------------------------------------------------------
# Exact-tree inventory + waivers
# ---------------------------------------------------------------------------


def test_exact_tree_inventory_proves_zero_unowned() -> None:
    adapter = _adapter()
    proof = adapter.exact_tree_proof
    assert proof.zero_unowned is True
    assert proof.unowned_public_paths == ()
    assert proof.signature.startswith("sha256:")
    assert proof.proof_cid.startswith("sha256:")
    public = {
        p.module_path for p in REGISTERED_PARQUET_PRODUCERS.values() if p.public
    }
    assert set(proof.public_producer_paths) == public


def test_unowned_public_producer_fails_without_waiver() -> None:
    binding = consume_dqk081_inventory(
        _valid_receipt(), active_generation=_active_generation()
    )
    owned = (
        "ipfs_datasets_py/core_operations/dataset_loader.py",
        # intentionally omit others
    )
    with pytest.raises(UnownedProducerError, match="unowned public"):
        build_exact_tree_inventory_proof(binding=binding, owned_paths=owned)


def test_waiver_is_reviewer_signed_path_scoped_justified_expiring() -> None:
    waiver = build_producer_waiver(
        path="ipfs_datasets_py/core_operations/dataset_saver.py",
        producer_id="dataset_saver",
        reviewer_id="reviewer:path-owner",
        justification="Legacy saver retained during canary; ownership tracked.",
        repository_tree_id=TREE_ID,
    )
    verified = verify_producer_waiver(
        waiver,
        path="ipfs_datasets_py/core_operations/dataset_saver.py",
        repository_tree_id=TREE_ID,
    )
    assert verified.reviewer_id == "reviewer:path-owner"
    assert verified.path.endswith("dataset_saver.py")
    assert len(verified.justification) >= 8

    # Wrong path scope fails closed.
    with pytest.raises(WaiverValidationError, match="path"):
        verify_producer_waiver(
            waiver,
            path="ipfs_datasets_py/other/unrelated.py",
        )

    # Expired waiver fails closed.
    issued = datetime.now(timezone.utc) - timedelta(days=3)
    expired = build_producer_waiver(
        path="ipfs_datasets_py/core_operations/dataset_saver.py",
        producer_id="dataset_saver",
        reviewer_id="reviewer:path-owner",
        justification="Expired waiver must not authorize ownership.",
        repository_tree_id=TREE_ID,
        issued_at=issued,
        expires_at=issued + timedelta(hours=1),
    )
    with pytest.raises(WaiverValidationError, match="expired"):
        verify_producer_waiver(expired)

    # Tampered signature fails closed.
    bad = dict(waiver)
    bad["justification"] = "tampered justification that is long enough"
    with pytest.raises(WaiverValidationError, match="signature"):
        verify_producer_waiver(bad)


def test_waiver_covers_unowned_paths_in_exact_tree_proof() -> None:
    binding = consume_dqk081_inventory(
        _valid_receipt(), active_generation=_active_generation()
    )
    public_paths = tuple(
        p.module_path for p in REGISTERED_PARQUET_PRODUCERS.values() if p.public
    )
    owned = public_paths[:-1]
    missing = public_paths[-1]
    waiver = build_producer_waiver(
        path=missing,
        producer_id="waived-producer",
        reviewer_id="reviewer:path-owner",
        justification="Temporary path-scoped waiver during inventory canary.",
        repository_tree_id=TREE_ID,
    )
    proof = prove_zero_unowned_public_parquet_producers(
        repository_tree_id=TREE_ID,
        inventory_snapshot_cid=SNAPSHOT_CID,
        public_producer_paths=public_paths,
        owned_paths=owned,
        waivers=(waiver,),
    )
    assert proof.zero_unowned is True
    assert waiver["waiver_cid"] in proof.waiver_cids


# ---------------------------------------------------------------------------
# Every producer emits full receipt set; identities preserved
# ---------------------------------------------------------------------------


def test_every_registered_producer_emits_full_receipt_bundle() -> None:
    adapter = _adapter()
    bundles = adapter.integrate_all_registered()
    assert len(bundles) == len(REGISTERED_PARQUET_PRODUCERS)
    for bundle in bundles:
        assert bundle.source.receipt_cid.startswith("sha256:")
        assert bundle.schema_receipt.receipt_cid.startswith("sha256:")
        assert bundle.snapshot.receipt_cid.startswith("sha256:")
        assert bundle.ownership.receipt_cid.startswith("sha256:")
        assert bundle.parity.receipt_cid.startswith("sha256:")
        assert bundle.parity.matched is True
        assert bundle.source_byte_identity_preserved is True
        assert bundle.mode == "shadow"
        assert bundle.legacy_is_authority is True
        assert bundle.quarantined is False
        body = bundle.to_dict()
        assert body["source"]["schema"].endswith("source-receipt@1")
        assert body["schema_receipt"]["schema"].endswith("schema-receipt@1")
        assert body["snapshot"]["schema"].endswith("snapshot-receipt@1")
        assert body["ownership"]["schema"].endswith("ownership-receipt@1")
        assert "parity" in body


def test_parquet_ipld_car_byte_identities_do_not_drift(tmp_path: Path) -> None:
    adapter = _adapter()
    parquet_bytes = b"PAR1" + b"\x00" * 64 + b"PAR1"
    car_bytes = b"\x0a" + b"car-payload-identity-bytes-001"
    ipld_bytes = b"\x12\x20" + hashlib.sha256(b"node").digest()

    cases = (
        (ParquetProducerId.JSONL_TO_PARQUET, parquet_bytes, "parquet"),
        (ParquetProducerId.IPFS_PARQUET_TO_CAR, car_bytes, "car"),
        (ParquetProducerId.KG_PARQUET_STORAGE, ipld_bytes, "parquet"),
    )
    for producer, raw, kind in cases:
        digest = digest_bytes(raw)
        # Write raw bytes to disk to prove re-read identity.
        path = tmp_path / f"{producer.value}.bin"
        path.write_bytes(raw)
        assert digest_bytes(path.read_bytes()) == digest

        bundle = adapter.shadow_project(
            producer_id=producer,
            dataset_id=f"identity:{producer.value}",
            source_uri=str(path),
            source_digest=digest,
            source_kind=kind,
            pre_source_digest=digest,
            operation_id=f"op:identity:{producer.value}",
        )
        assert bundle.source.source_digest == digest
        assert bundle.source_byte_identity_preserved is True

        # Re-project with same digest succeeds; drift fails.
        again = adapter.shadow_project(
            producer_id=producer,
            dataset_id=f"identity:{producer.value}",
            source_uri=str(path),
            source_digest=digest,
            source_kind=kind,
            pre_source_digest=digest,
            operation_id=f"op:identity-again:{producer.value}",
        )
        assert again.source.source_digest == digest

        drifted = digest_bytes(raw + b"x")
        with pytest.raises(ad.ParquetProducerShadowError, match="identity drifted"):
            adapter.shadow_project(
                producer_id=producer,
                dataset_id=f"identity:{producer.value}",
                source_uri=str(path),
                source_digest=drifted,
                source_kind=kind,
                pre_source_digest=digest,
                operation_id=f"op:identity-drift:{producer.value}",
            )


# ---------------------------------------------------------------------------
# Disagreement quarantines only affected dataset
# ---------------------------------------------------------------------------


def test_shadow_disagreement_quarantines_only_affected_dataset() -> None:
    adapter = _adapter()
    # Healthy dataset A.
    good = adapter.shadow_project(
        producer_id=ParquetProducerId.DATASET_SAVER,
        dataset_id="ds-healthy",
        source_uri="file:///tmp/healthy.parquet",
        source_digest=digest_bytes(b"healthy-bytes"),
        source_kind="parquet",
        operation_id="op:healthy",
    )
    assert good.quarantined is False
    assert good.parity.matched is True

    # Disagreeing dataset B.
    bad = adapter.shadow_project(
        producer_id=ParquetProducerId.DATASET_SAVER,
        dataset_id="ds-bad",
        source_uri="file:///tmp/bad.parquet",
        source_digest=digest_bytes(b"bad-bytes"),
        source_kind="parquet",
        operation_id="op:bad",
        force_parity_mismatch=True,
    )
    assert bad.quarantined is True
    assert bad.parity.matched is False
    assert bad.quarantine_id

    # Only ds-bad is quarantined.
    open_bad = adapter.open_quarantines_for("ds-bad")
    open_good = adapter.open_quarantines_for("ds-healthy")
    assert len(open_bad) >= 1
    assert open_good == ()

    all_open = list(
        adapter.authority_port.backend.list_open_quarantine(adapter.authority_port.domain)
    )
    assert all(q.key == "ds-bad" for q in all_open)

    # Healthy dataset can still be projected after B is quarantined.
    again = adapter.shadow_project(
        producer_id=ParquetProducerId.DATASET_LOADER,
        dataset_id="ds-healthy",
        source_uri="file:///tmp/healthy.parquet",
        source_digest=digest_bytes(b"healthy-bytes"),
        source_kind="parquet",
        operation_id="op:healthy-2",
    )
    assert again.quarantined is False
    assert again.parity.matched is True


# ---------------------------------------------------------------------------
# Producer entrypoint hooks (legacy path still works)
# ---------------------------------------------------------------------------


def test_dataset_saver_and_converter_hooks_emit_shadow_when_active() -> None:
    """Sync entrypoints so sealed validators without anyio still pass."""
    adapter = _adapter()
    set_active_shadow_adapter(adapter)
    try:
        saver = DatasetSaver()
        save_result = saver.save_sync(
            dataset={"rows": [1]},
            destination="/tmp/dqk089-out.parquet",
            format="parquet",
        )
        assert save_result["status"] == "success"
        assert "ducklake_shadow" in save_result
        shadow = save_result["ducklake_shadow"]
        assert shadow["producer_id"] == "dataset_saver"
        assert shadow["source"]["receipt_cid"].startswith("sha256:")
        assert shadow["parity"]["matched"] is True

        converter = DatasetConverter()
        convert_result = converter.convert_sync(
            source="/tmp/in.json",
            target_format="parquet",
        )
        assert convert_result["status"] == "success"
        assert "ducklake_shadow" in convert_result
        assert convert_result["ducklake_shadow"]["producer_id"] == "dataset_converter"
    finally:
        set_active_shadow_adapter(None)


def test_dataset_loader_hook_is_noop_without_adapter() -> None:
    set_active_shadow_adapter(None)
    loader = DatasetLoader()
    # Without HF datasets this returns error — still must not crash on shadow path.
    result = loader.load_sync(source="not-a-real-dataset", format="json")
    assert result["status"] in {"success", "error"}
    assert "ducklake_shadow" not in result


def test_unknown_producer_selection_fails_closed() -> None:
    adapter = _adapter()
    with pytest.raises(ProducerSelectionError, match="unknown parquet producer"):
        adapter.select_producer("not_a_registered_producer")
