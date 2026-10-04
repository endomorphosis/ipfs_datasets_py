"""Authored registry forgeries cannot erase captured feature-cohort ancestry."""
from contextlib import ExitStack, contextmanager
import copy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.codebase_targets import prepare_codebase_targets
from ipfs_datasets_py.logic.software_contracts import codebase_feature_training as training
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from .test_codebase_current import repository, scheduler, current_index
from .test_codebase_feature_training import prepared, train


@pytest.fixture(scope="module")
def native_lineage(tmp_path_factory):
    """Run one real admitted fit; all adversarial descendants reuse its tensors."""
    root = tmp_path_factory.mktemp("native-feature-lineage")
    with ExitStack() as stack:
        source = repository.__wrapped__(root)
        budget = stack.enter_context(contextmanager(scheduler.__wrapped__)(root))
        index = stack.enter_context(contextmanager(current_index.__wrapped__)(root))
        setup = stack.enter_context(contextmanager(prepared.__wrapped__)(source, budget, index, root))
        fitted = train(setup, source, budget, root, epochs=1)
        assert fitted["status"] == "candidate_registered"
        registry = setup[3]
        version = registry.get_version(fitted["candidate"]["version_id"])
        saved = json.loads(registry.artifact_path(version["artifact"]).read_bytes())
        assert training._parent(registry, version["version_id"], lambda: None)[0] == version
        yield registry, version, saved


def _seal_cohort(saved):
    cohort = saved["report"]["codebase_cohort"]
    cohort["cohort_sha256"] = features.digest({key: value for key, value in cohort.items() if key != "cohort_sha256"})


def _latest(cohort):
    return [{"unit_id": row["unit_id"], "source_sha256": row["source_sha256"], "role": role}
            for role, rows in cohort["roles"].items() for row in rows]


def _ancestry(cohort, prior=()):
    rows = {features.digest(row): row for row in [*prior, *_latest(cohort)]}
    cohort["ancestral_roles"] = sorted(rows.values(), key=lambda row: (row["unit_id"], row["source_sha256"], row["role"]))


def _hash_reports(saved):
    cohort = saved["report"]["codebase_cohort"]
    saved["report"]["training_targets_sha256"] = features.digest([row["target"] for row in cohort["roles"]["training"]])
    tuning = features.digest([row["target"] for row in cohort["roles"]["tuning"]])
    saved["report"]["tuning_targets_sha256"] = saved["state"]["tuning_targets_sha256"] = tuning


def _derived(saved, parent):
    child = copy.deepcopy(saved)
    cohort = child["report"]["codebase_cohort"]
    cohort["generation"] += 1
    cohort["parent_version_id"] = parent["version_id"]
    cohort["parent_artifact_sha256"] = parent["artifact"]["sha256"]
    child["report"]["base_state_sha256"] = features.digest(saved["state"])
    _seal_cohort(child)
    return child


def _register(registry, base, saved, directory, parent_id=None):
    directory.mkdir()
    path = directory / "candidate.json"
    raw = features._raw(saved)
    path.write_bytes(raw)
    artifact = registry.stage_artifact(path, hashlib.sha256(raw).hexdigest())
    receipt = registry.register_version("lineage-fixture:" + features.digest([artifact, parent_id]),
        base["variant_id"], artifact, base["metadata"], parent_version_id=parent_id)
    return registry.get_version(receipt["version_id"])


def _replace_row_source(row, cohort, *, rename=None):
    original = IntegerOffsetContract.from_dict(row["contract"])
    contract = (original if rename is None else IntegerOffsetContract(
        original.path, rename, original.parameter, original.offset))
    body = (f"# authored successor fixture\ndef {contract.function_name}({contract.parameter}: int) -> int:\n"
            f"    return {contract.parameter} + {contract.offset}\n").encode()
    target = prepare_codebase_targets(body, contract, revision="snapshot:" + cohort["head"]["snapshot_cid"]).to_dict()
    binding = target["validation"][0]["details"]["binding"]
    row.update(unit_id=contract.path, contract=contract.to_dict(), source_cid=binding["source_cid"],
               source_sha256=binding["source_sha256"], target=target)


def test_native_root_retains_exact_source_roles_and_training_receipt(native_lineage):
    registry, version, saved = native_lineage
    record, restored, cohort, runtime = training._parent(registry, version["version_id"], lambda: None)
    assert record == version and restored == saved
    assert cohort == saved["report"]["codebase_cohort"]
    assert runtime.training_report == saved["report"]
    assert runtime.state == saved["state"]


def test_current_ledger_cannot_erase_an_earlier_training_source(native_lineage, tmp_path):
    registry, version, saved = native_lineage
    forged = _derived(saved, version)
    cohort = forged["report"]["codebase_cohort"]
    _replace_row_source(cohort["roles"]["training"][0], cohort)
    _ancestry(cohort)  # Self-consistent latest roles, but the previous bytes vanish.
    _hash_reports(forged)
    _seal_cohort(forged)
    candidate = _register(registry, version, forged, tmp_path / "incomplete", version["version_id"])
    with pytest.raises(training.CodebaseFeatureTrainingError, match="incomplete ancestral"):
        training._parent(registry, candidate["version_id"], lambda: None)


def test_descendant_cannot_swap_tuning_and_canary_roles(native_lineage, tmp_path):
    registry, version, saved = native_lineage
    forged = _derived(saved, version)
    cohort = forged["report"]["codebase_cohort"]
    roles = cohort["roles"]
    roles["tuning"], roles["canary"] = roles["canary"], roles["tuning"]
    _ancestry(cohort)
    _hash_reports(forged)
    _seal_cohort(forged)
    candidate = _register(registry, version, forged, tmp_path / "swapped-roles", version["version_id"])
    with pytest.raises(training.CodebaseFeatureTrainingError, match="held-out cohort"):
        training._parent(registry, candidate["version_id"], lambda: None)


def test_descendant_cannot_change_heldout_source_with_recomputed_commitments(native_lineage, tmp_path):
    registry, version, saved = native_lineage
    forged = _derived(saved, version)
    cohort = forged["report"]["codebase_cohort"]
    _replace_row_source(cohort["roles"]["canary"][0], cohort)
    _ancestry(cohort, saved["report"]["codebase_cohort"]["ancestral_roles"])
    _hash_reports(forged)
    _seal_cohort(forged)
    candidate = _register(registry, version, forged, tmp_path / "heldout-edit", version["version_id"])
    with pytest.raises(training.CodebaseFeatureTrainingError, match="held-out cohort"):
        training._parent(registry, candidate["version_id"], lambda: None)


def test_role_row_cannot_point_to_another_valid_native_target(native_lineage, tmp_path):
    registry, version, saved = native_lineage
    forged = copy.deepcopy(saved)
    rows = forged["report"]["codebase_cohort"]["roles"]["training"]
    rows[0]["target"], rows[1]["target"] = rows[1]["target"], rows[0]["target"]
    _hash_reports(forged)
    _seal_cohort(forged)
    candidate = _register(registry, version, forged, tmp_path / "swapped-targets")
    with pytest.raises(training.CodebaseFeatureTrainingError, match="source/contract differs"):
        training._parent(registry, candidate["version_id"], lambda: None)


@pytest.mark.parametrize("field", ["training_targets_sha256", "tuning_targets_sha256"])
def test_every_ancestor_report_must_bind_its_exact_targets(native_lineage, tmp_path, field):
    registry, version, saved = native_lineage
    forged_root = copy.deepcopy(saved)
    forged_root["report"][field] = "0" * 64
    wrong_parent = _register(registry, version, forged_root, tmp_path / "bad-parent")
    child = _derived(forged_root, wrong_parent)
    _hash_reports(child)  # The leaf is correct; its ancestor's report is not.
    _seal_cohort(child)
    candidate = _register(registry, version, child, tmp_path / "leaf", wrong_parent["version_id"])
    with pytest.raises(training.CodebaseFeatureTrainingError, match="numerical report differs from (training|tuning) cohort"):
        training._parent(registry, candidate["version_id"], lambda: None)


def test_function_rename_at_stable_path_cannot_move_a_source_between_roles(native_lineage, tmp_path):
    registry, version, saved = native_lineage
    forged = _derived(saved, version)
    cohort = forged["report"]["codebase_cohort"]
    moved = cohort["roles"]["training"].pop(0)
    old_path = moved["unit_id"]
    _replace_row_source(moved, cohort, rename="renamed_for_canary")
    assert moved["unit_id"] == old_path
    cohort["roles"]["canary"].append(moved)
    _ancestry(cohort, saved["report"]["codebase_cohort"]["ancestral_roles"])
    _hash_reports(forged)
    _seal_cohort(forged)
    candidate = _register(registry, version, forged, tmp_path / "renamed", version["version_id"])
    with pytest.raises(training.CodebaseFeatureTrainingError, match="ancestral split leakage"):
        training._parent(registry, candidate["version_id"], lambda: None)
