"""Operation-scoped reuse of fully replayed source-bound CodebaseIR lineage.

The inherited lineage conditions remain explicit below.  Immutable canonical
target bytes are the cache identity; a digest alone never authorizes a hit.
This additive profile never edits a checkpoint producer, mutates an owner,
observes a checkout, fits weights, or replaces the coordinator's final fences.
The context is bounded and belongs to exactly one caller operation.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_modality_contracts import ModalityContract
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from . import codebase_source_training as training
from .codebase_inventory_targets import CodebaseInventoryLimits, InventorySeal, prepare_inventory_target, seal_inventory
from .codebase_ir_targets import CodebaseTargetLimits

PROFILE = "source_bound_inventory_lineage_reuse_v1"
MAX_HISTORICAL_SEAL_BYTES = 48 * 1024 * 1024
# These are the complete local files containing the reviewed inherited
# algorithm.  They are a compatibility guard, not a transitive attestation.
REFERENCE_SHA256 = {
    training.__name__: "aea5fa8803ae6b6dde7c4e71b81f68a7f95257b3a5d76cea693ee13e66710aa0",
    runtimes.__name__: "ca31983a5f514c7f5cf8b1b9250ef92e1beb13c0a2305381aac575931e79b4ac",
}
# The reviewed frozen 8D producer keeps the inherited lineage body unchanged,
# and adds exact numerical diagnostic replay. Its runtime is independently
# pinned; accepting the training file alone would leave its new import unbound.
_REVIEWED_8D_PRODUCER_MIGRATION = (
    "aea5fa8803ae6b6dde7c4e71b81f68a7f95257b3a5d76cea693ee13e66710aa0",
    "e459766bed0c990660334eaf264b6c46fc29e229d49ae8c416bdfc7ca142c317",
    "32dc798bfe81a587412c3d86431c368a5a83e27660870ca6de6f107a1e855146",
)
_require = training._require
_wire = training._wire


@dataclass(slots=True)
class InventoryLineageCounters:
    reference_guard_file_hashes: int = 0
    candidate_native_reads: int = 0
    candidate_cache_hits: int = 0
    runtime_constructor_validations: int = 0
    completed_run_metadata_replays: int = 0
    target_native_validations: int = 0
    target_validation_cache_hits: int = 0
    binding_cache_reads: int = 0
    target_preparations: int = 0
    target_preparation_cache_hits: int = 0
    current_seal_reuses: int = 0
    historical_seal_reads: int = 0
    historical_seal_reuses: int = 0
    cache_retained_bytes: int = 0
    cache_retained_bytes_high_water: int = 0
    historical_seal_retained_bytes: int = 0
    historical_seal_retained_bytes_high_water: int = 0

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _reference_guard(counters):
    for module in (training, runtimes):
        actual = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        counters.reference_guard_file_hashes += 1
        expected = REFERENCE_SHA256[module.__name__]
        migration = (module is training
                     and expected == _REVIEWED_8D_PRODUCER_MIGRATION[0]
                     and actual == _REVIEWED_8D_PRODUCER_MIGRATION[1])
        _require(actual == expected or migration,
                 "inventory lineage reuse requires the reviewed native reference producer")
        if migration:
            runtime_sha = hashlib.sha256(Path(training.runtimes.__file__).read_bytes()).hexdigest()
            _require(training.runtimes.__name__ ==
                     "ipfs_datasets_py.optimizers.logic_theorem_optimizer.codebase_runtime_8d"
                     and runtime_sha == _REVIEWED_8D_PRODUCER_MIGRATION[2],
                     "inventory lineage reuse requires the reviewed native reference runtime")


class InventoryLineageContext:
    """Private operation material; it grants no current or proof authority."""

    def __init__(self, index, registry, limits, *, current_seal=None, checkpoint=None):
        training._native_owners(index, registry)
        _require(type(limits) is training.CodebaseFeatureTrainingLimits, "native lineage limits required")
        _require(current_seal is None or type(current_seal) is InventorySeal,
                 "exact borrowed current inventory seal required")
        _require(checkpoint is None or callable(checkpoint), "operation checkpoint callback required")
        self.index, self.registry, self.limits = index, registry, limits
        self.current_seal = current_seal
        self.checkpoint = checkpoint or (lambda: None)
        self.max_cache_bytes = limits.max_ancestry_bytes + limits.max_target_bytes
        self.counters = InventoryLineageCounters()
        _reference_guard(self.counters)
        self._candidates = {}
        self._targets = {}
        self._bindings = {}
        self._prepared = {}
        self._historical_seal = None
        self._pins = training._pins()

    def _retain(self, size):
        _require(type(size) is int and size >= 0, "finite retained cache byte count required")
        total = self.counters.cache_retained_bytes + size
        _require(total <= self.max_cache_bytes, "operation lineage cache exceeds its serialized byte bound")
        self.counters.cache_retained_bytes = total
        self.counters.cache_retained_bytes_high_water = max(
            self.counters.cache_retained_bytes_high_water, total)

    def read_candidate(self, version_id):
        self.checkpoint()
        if version_id in self._candidates:
            self.counters.candidate_cache_hits += 1
            row_raw, saved_raw, row, saved = self._candidates[version_id]
            _require(_wire(row) == row_raw and _wire(saved) == saved_raw,
                     "operation candidate snapshot was mutated")
            return row, saved
        _require(len(self._candidates) < self.limits.max_ancestry, "oversized operation candidate ancestry")
        row, saved = training._read_candidate(self.registry, version_id, self.limits)
        self.counters.candidate_native_reads += 1
        row_raw, saved_raw = _wire(row), _wire(saved)
        size = len(version_id.encode("utf-8")) + len(row_raw) + len(saved_raw)
        self._retain(size)
        self._candidates[version_id] = (row_raw, saved_raw, row, saved)
        self.checkpoint()
        return row, saved

    def validate_runtime_candidate(self, row, saved):
        """The source-bound branch of native load_version, without rereading.

        Every row/artifact has already passed the unchanged native candidate
        reader.  The native runtime constructor still checks the contract,
        adapter, feature space, projections, optimizer, and complete state.
        """
        self.checkpoint()
        descriptor = runtimes.describe_runtime("codebase_ir", runtimes.CODEBASE_SOURCE_FEATURE_VERSION)
        runtimes._require("load_version" in descriptor["capabilities"], "runtime lacks registry load_version")
        runtimes._require("decoder_head_sha256" not in row["metadata"],
                          "codebase feature runtime does not accept formal decoder artifacts")
        contract = ModalityContract.from_dict(saved["contract"])
        runtimes._require(row["variant_id"] == contract.variant_id, "registry variant differs from candidate contract")
        manifest = self.registry.get_variant(row["variant_id"])["manifest"]
        runtimes._require(manifest == contract.registry_manifest(), "registry modality manifest differs from candidate")
        feature_metadata = {"contract_sha256": contract.sha256,
                            "training_purpose": "feature_pretraining", **features.FALSE}
        if row["metadata"] != feature_metadata or any(
                row["metadata"].get(name) is not False for name in features.FALSE):
            runtimes._source_bound_completed_run_metadata(self.registry, row, saved, contract)
            self.counters.completed_run_metadata_replays += 1
        report, state = saved["report"], saved["state"]
        runtimes._require(report["contract_sha256"] == contract.sha256
            and report["feature_space_sha256"] == features.digest(saved["feature_space"])
            and all(report.get(key) is False for key in features.FALSE), "candidate report identity or authority differs")
        parent_id = row["parent_version_id"]
        if parent_id is None:
            runtimes._require(report["base_state_sha256"] is None, "resumed candidate lacks a registry parent")
        else:
            parent, parent_saved = self.read_candidate(parent_id)
            runtimes._require(parent["variant_id"] == row["variant_id"], "parent belongs to another variant")
            runtimes._require(features.digest(parent_saved["state"]) == report["base_state_sha256"],
                              "candidate numerical parent differs from registry parent")
        runtime = runtimes.open_runtime("codebase_ir", runtimes.CODEBASE_SOURCE_FEATURE_VERSION,
            contract=contract, feature_space=saved["feature_space"], state=state)
        runtime._parent_version_id = row["version_id"]
        runtime._training_report = runtimes._copy(report)
        self.counters.runtime_constructor_validations += 1
        self.checkpoint()
        return runtime

    def validated(self, target):
        self.checkpoint()
        if type(target) is dict:
            target = DomainTargetEnvelope.from_dict(target)
        _require(type(target) is DomainTargetEnvelope, "native immutable target required")
        raw = target.canonical_bytes
        if raw in self._targets:
            self.counters.target_validation_cache_hits += 1
            return self._targets[raw]
        # Native replay is retained for each distinct complete target envelope.
        checked = training._targets_adapter().validate_codebase_targets(target)
        self.counters.target_native_validations += 1
        checked_raw = checked.canonical_bytes
        _require(checked_raw == raw, "native replay target identity differs")
        details = checked.to_dict()["validation"][0]["details"]
        binding_raw = _wire({**details["source_binding"], "authored_contracts": details["authored_contracts"]})
        # Account both canonical-byte lookup keys and their retained payloads.
        self._retain(2 * len(checked_raw) + len(binding_raw))
        self._targets[checked_raw] = checked
        self._bindings[checked_raw] = binding_raw
        self.checkpoint()
        return checked

    def batch(self, values, limits):
        _require(type(values) in {list, tuple} and 1 <= len(values) <= limits.max_targets,
                 "bounded target batch required")
        _require(len(_wire([item.to_dict() if hasattr(item, "to_dict") else item for item in values]))
                 <= limits.max_target_bytes, "target batch byte bound exceeded")
        return [self.validated(value) for value in values]

    def binding(self, target):
        target = self.validated(target)
        self.counters.binding_cache_reads += 1
        return json.loads(self._bindings[target.canonical_bytes])

    def identity(self, target):
        binding = self.binding(target)
        return {"repository_id": binding["head"]["repository_id"], "path": binding["path"],
                "source_digest": binding["content_sha256"]}

    def split_check(self, train, tune, canary, history):
        identities = [[self.identity(target) for target in batch] for batch in (train, tune, canary)]
        def paths(rows):
            return {(row["repository_id"], row["path"]) for row in rows}
        def digests(rows):
            return {row["source_digest"] for row in rows}
        left = [*history, *identities[0]]
        _require(not paths(left) & paths(identities[1] + identities[2])
            and not digests(left) & digests(identities[1] + identities[2])
            and not paths(identities[1]) & paths(identities[2])
            and not digests(identities[1]) & digests(identities[2]),
            "ancestral content/path train/tune/canary leakage")

    def seal(self, head):
        self.checkpoint()
        if self.current_seal is not None and head == self.current_seal.head:
            self.counters.current_seal_reuses += 1
            return self.current_seal
        if self._historical_seal is not None and head == self._historical_seal.head:
            self.counters.historical_seal_reuses += 1
            return self._historical_seal
        # Keep only one historical inventory.  Release it before reading the
        # next one; the borrowed current inventory is accounted by the caller.
        self._historical_seal = None
        self.counters.historical_seal_retained_bytes = 0
        seal = seal_inventory(self.index, expected_head=head, checkpoint=self.checkpoint)
        self.counters.historical_seal_reads += 1
        counts = seal.counters
        size = counts.manifest_bytes + counts.publication_receipt_bytes + counts.source_bytes + counts.ast_bytes
        _require(size <= MAX_HISTORICAL_SEAL_BYTES, "historical inventory exceeds its retained byte bound")
        self._historical_seal = seal
        self.counters.historical_seal_retained_bytes = size
        self.counters.historical_seal_retained_bytes_high_water = max(
            self.counters.historical_seal_retained_bytes_high_water, size)
        self.checkpoint()
        return seal

    def prepare(self, head, path, contracts=()):
        self.checkpoint()
        key = _wire({"head": head.to_dict(), "path": path,
                     "contracts": [item.to_dict() for item in contracts]})
        if key in self._prepared:
            self.counters.target_preparation_cache_hits += 1
            return self._targets[self._prepared[key]]
        # The inherited lineage producer always used default target limits.
        # A borrowed scanner seal may apply narrower inference-only limits.
        seal = self.seal(head)
        if seal.limits != CodebaseTargetLimits() or seal.inventory_limits != CodebaseInventoryLimits():
            seal = replace(seal, limits=CodebaseTargetLimits(), inventory_limits=CodebaseInventoryLimits())
        target = prepare_inventory_target(seal, path, contracts)
        self.counters.target_preparations += 1
        target = self.validated(target)
        self._retain(len(key) + len(target.canonical_bytes))
        self._prepared[key] = target.canonical_bytes
        self.checkpoint()
        return target

    def release_historical_seals(self):
        """Release captured history before the caller allocates worker streams."""
        self._historical_seal = None
        self.counters.historical_seal_retained_bytes = 0


@dataclass(frozen=True, slots=True)
class InventoryLineageResult:
    chain: list
    context: InventoryLineageContext
    counters: dict


def replay_inventory_lineage(index, registry, version_id, limits, *, current_seal=None, checkpoint=None):
    """Replay every inherited native condition with operation-local reuse."""
    context = InventoryLineageContext(index, registry, limits, current_seal=current_seal, checkpoint=checkpoint)
    chain = _lineage(index, registry, version_id, limits, context)
    context.checkpoint()
    _reference_guard(context.counters)
    return InventoryLineageResult(chain, context, context.counters.to_dict())


def _lineage(index, registry, version_id, limits, context):
    """The inherited native lineage body; only operation helpers differ.

    The whole-file reference guard above closes this explicit algorithm to
    the reviewed native producer.  The unchanged native diagnostic routine
    still checks recorded vectors, coverage, losses, state and authority.
    """
    chain, seen, total = [], set(), 0
    current = version_id
    while current is not None:
        context.checkpoint()
        _require(current not in seen and len(chain) < limits.max_ancestry, "cyclic or oversized model ancestry")
        seen.add(current)
        row, saved = context.read_candidate(current)
        total += row["artifact"]["bytes"]
        _require(total <= limits.max_ancestry_bytes, "ancestry bytes exceed bound")
        context.validate_runtime_candidate(row, saved)
        provenance = saved["report"].get("codebase_provenance")
        _require(type(provenance) is dict and set(provenance) == training._PROVENANCE_FIELDS
                 and provenance["schema"] == training.PROVENANCE_SCHEMA
                 and all(provenance[key] is False for key in training._FALSE), "closed nonauthoritative CodebaseIR lineage required")
        _require(provenance["parent_version_id"] == row["parent_version_id"]
                 and provenance["contract_sha256"] == saved["state"]["contract_sha256"]
                 and provenance["feature_space_sha256"] == features.digest(saved["feature_space"])
                 and provenance["implementation"] == context._pins, "lineage model/producer binding differs")
        selections = training._selections(
            [training.CodebaseTrainingSelection.from_dict(item) for item in provenance["selections"]], limits)
        head = CodebaseHead.from_dict(provenance["head"])
        train = context.batch(provenance["training_targets"], limits)
        tune = context.batch(provenance["tuning_targets"], limits)
        canary = context.batch(provenance["canary_targets"], limits)
        replay = context.batch(provenance["replay_targets"], limits)
        history = provenance["ancestral_training"]
        _require(type(history) is list and len(history) <= limits.max_training_history
                 and all(type(item) is dict and set(item) == {"repository_id", "path", "source_digest"} for item in history),
                 "bounded closed training history required")
        context.split_check(train, tune, canary, history)
        _require(saved["report"]["training_targets_sha256"] == features.digest([item.to_dict() for item in train])
                 and saved["report"]["tuning_targets_sha256"] == features.digest([item.to_dict() for item in tune])
                 and saved["state"]["tuning_targets_sha256"] == saved["report"]["tuning_targets_sha256"]
                 and saved["state"]["optimizer_config"]["learning_rate"] == saved["report"]["configuration"]["learning_rate"],
                 "training/tuning target inventories differ from native report")
        request = training._request(provenance, saved["report"]["configuration"])
        _require(saved["report"].get("codebase_request_sha256") == features.digest(request), "training request digest differs")
        if row["parent_version_id"] is not None:
            completion = registry.get_run_completion(row["metadata"]["producer_run"])
            _require(completion is not None and completion["candidate_version"] == row
                     and completion["run"]["spec"] == request, "native completed run belongs to another source/cohort request")
        monitor = provenance["canary_monitoring"]
        _require(type(monitor) is dict and set(monitor) == {"before", "after", "purpose", "used_for_selection"}
            and monitor["purpose"] == "repeated_post_selection_diagnostic_not_unseen_qualification"
            and monitor["used_for_selection"] is False, "canary selection/qualification policy differs")
        training._diagnostic(monitor["after"], canary, saved["state"], saved["state"]["contract_sha256"], saved["feature_space"])
        training._diagnostic(provenance["replay_monitoring"], replay, saved["state"], saved["state"]["contract_sha256"], saved["feature_space"])
        receipt = saved["report"].get("codebase_worker_receipt")
        _require(type(receipt) is dict and set(receipt) == {"executable_sha256", "worker_sha256", "input_sha256",
            "output_sha256", "elapsed_ms", "returncode", "workspace_cleaned", "limits", "memory_enforcement",
            "source_execution_attested"} and receipt["returncode"] == 0 and receipt["workspace_cleaned"] is True
            and receipt["source_execution_attested"] is False and type(receipt["elapsed_ms"]) is int
            and receipt["elapsed_ms"] >= 0 and receipt["memory_enforcement"] == "sampled_process_tree_rss_with_possible_overshoot"
            and all(type(receipt[key]) is str and re.fullmatch(r"[0-9a-f]{64}", receipt[key])
                    for key in ("executable_sha256", "worker_sha256", "input_sha256", "output_sha256")),
            "native worker receipt binding/authority differs")
        current_train = []
        evaluation_bindings = []
        current_evaluation = {"tune": [], "canary": []}
        for selection in selections:
            context.checkpoint()
            target = context.prepare(head, selection.path, selection.contracts)
            if selection.role == "train":
                current_train.append(target)
            else:
                evaluation_bindings.append({"role": selection.role, "binding": context.binding(target)})
                current_evaluation[selection.role].append(target)
        _require(provenance["current_evaluation_bindings"] == evaluation_bindings, "current evaluation source refs differ")
        for role, fixed in (("tune", tune), ("canary", canary)):
            _require([context.identity(target) for target in current_evaluation[role]] == [context.identity(target) for target in fixed]
                     and [target.to_dict()["projections"] for target in current_evaluation[role]] == [target.to_dict()["projections"] for target in fixed],
                     "fixed evaluation source/features differ from captured observations")
        present = {context.binding(target)["content_sha256"] for target in current_train}
        expected_train = [*current_train, *(target for target in replay if context.binding(target)["content_sha256"] not in present)]
        _require([item.to_dict() for item in train] == [item.to_dict() for item in expected_train],
                 "current source/replay training membership differs")
        chain.append((row, saved, provenance, train, tune, canary, replay))
        current = row["parent_version_id"]
    for child, parent in zip(chain, chain[1:]):
        context.checkpoint()
        _, saved, provenance, train, tune, canary, replay = child
        _, parent_saved, parent_provenance, parent_train, parent_tune, parent_canary, parent_replay = parent
        expected_history = sorted({features.digest(item): item for item in
            [*parent_provenance["ancestral_training"], *(context.identity(item) for item in parent_train)]}.values(),
            key=lambda item: (item["repository_id"], item["path"], item["source_digest"]))
        _require(provenance["ancestral_training"] == expected_history
                 and [x.to_dict() for x in tune] == [x.to_dict() for x in parent_tune]
                 and [x.to_dict() for x in canary] == [x.to_dict() for x in parent_canary]
                 and [x.to_dict() for x in replay] == [x.to_dict() for x in parent_replay]
                 and provenance["selections"] == parent_provenance["selections"]
                 and saved["contract"] == parent_saved["contract"]
                 and saved["feature_space"] == parent_saved["feature_space"]
                 and saved["report"]["base_state_sha256"] == features.digest(parent_saved["state"])
                 and provenance["continuation"] == "exact_frozen_basis_adam_resume", "ancestral continuation differs")
        training._diagnostic(provenance["canary_monitoring"]["before"], canary, parent_saved["state"],
                    parent_saved["state"]["contract_sha256"], saved["feature_space"])
    root = chain[-1]
    _require(root[2]["ancestral_training"] == [] and root[2]["continuation"] == "fresh_feature_basis",
             "root lineage cannot claim inherited training")
    _require([target.to_dict() for target in root[3]] == [target.to_dict() for target in root[6]]
        and all(context.binding(target)["head"] == root[2]["head"] for target in [*root[4], *root[5]]),
        "root replay/evaluation cohort differs from its captured source head")
    _require(root[2]["canary_monitoring"]["before"] is None, "fresh root cannot claim inherited canary execution")
    return chain
