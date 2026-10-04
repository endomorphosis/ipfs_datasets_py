"""Resource-admitted current-source CodebaseIR feature candidate training.

The existing model registry owns numerical artifacts. This adapter owns only
captured cohort provenance, fixed split roles and current-source delivery fences.
No candidate is promoted, and no learned vector becomes a behavioral fact.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import site
import sys
import time

from .codebase_integer_profile import IntegerOffsetContract
from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources
from ..backends.process import BoundedToolRunner, ToolRunLimits
from ...optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError, LeaseTimeoutError, ResourceLane,
)

SCHEMA = "codebase-feature-training@1"
COHORT_SCHEMA = "codebase-feature-cohort@1"
RUNTIME_VERSION = "codebase_feature_v1"
ROLES = ("training", "tuning", "canary")
MAX_BYTES = 16 * 1024 * 1024
MAX_ANCESTRAL_BINDINGS = 128
POLICY = {"unknown_atoms": "reject_all_roles_requires_explicit_basis_migration",
          "tuning": "fixed_ancestral_targets_repeated_candidate_selection",
          "canary": "fixed_ancestral_targets_postfit_nonregression_gate",
          "promotion": "none", "latent_width": 8}


class CodebaseFeatureTrainingError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise CodebaseFeatureTrainingError(message)


@dataclass(frozen=True, slots=True)
class CodebaseFeatureSample:
    role: str
    contract: IntegerOffsetContract

    def __post_init__(self):
        _require(type(self.role) is str and self.role in ROLES, "unknown CodebaseIR split role")
        _require(type(self.contract) is IntegerOffsetContract, "exact integer contract required")

    @property
    def unit_id(self):
        # This profile admits exactly one function per file. Its split role
        # stays bound to the path even if the function is renamed later.
        return self.contract.path


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _implementation():
    from ..formalization.autoencoder import codebase_targets
    from ..backends import process
    paths = [Path(__file__), Path(__file__).with_name("codebase_feature_worker.py"),
             Path(features.__file__), Path(features.__file__).with_name("modal_autoencoder_cuda.py"),
             Path(features.__file__).with_name("autoencoder_runtime_registry.py"),
             Path(features.__file__).with_name("autoencoder_modality_contracts.py"),
             Path(codebase_targets.__file__), Path(process.__file__), Path(sys.executable).resolve(),
             Path(process._linux_prlimit_path())]
    paths.extend(Path(__file__).parents[1] / relative for relative in (
        "formalization/autoencoder/domain_targets.py", "software_contracts/codebase_integer_profile.py",
        "software_verification/pipeline.py", "software_verification/source_adapters.py",
        "software_verification/vc.py", "backends/smt/compiler.py"))
    return {str(path): _sha(path.read_bytes()) for path in paths}


def _validate_cohort(cohort, checkpoint=None):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ..formalization.autoencoder.codebase_targets import validate_codebase_targets
    from ..formalization.autoencoder.domain_targets import DomainTargetEnvelope
    fields = {"schema", "runtime_version", "head", "generation", "parent_version_id", "parent_artifact_sha256",
              "roles", "ancestral_roles", "feature_space_sha256", "policy", "cohort_sha256"}
    _require(type(cohort) is dict and set(cohort) == fields and cohort["schema"] == COHORT_SCHEMA,
             "closed CodebaseIR cohort provenance required")
    _require(cohort["cohort_sha256"] == features.digest({k: v for k, v in cohort.items() if k != "cohort_sha256"}),
             "cohort commitment differs")
    _require(cohort["runtime_version"] == RUNTIME_VERSION and cohort["policy"] == POLICY,
             "cohort runtime or split policy differs")
    CodebaseHead.from_dict(cohort["head"])
    _require(type(cohort["generation"]) is int and 1 <= cohort["generation"] <= 32, "bounded model generation required")
    _require((cohort["generation"] == 1) == (cohort["parent_version_id"] is None), "cohort parent/generation mismatch")
    _require((cohort["parent_version_id"] is None) == (cohort["parent_artifact_sha256"] is None), "incomplete numerical parent binding")
    _require(type(cohort["roles"]) is dict and set(cohort["roles"]) == set(ROLES), "complete split ledger required")
    units, contents = {}, {}
    for role in ROLES:
        rows = cohort["roles"][role]
        _require(type(rows) is list and 1 <= len(rows) <= 16, "bounded nonempty split required")
        for row in rows:
            if checkpoint is not None:
                checkpoint()
            _require(type(row) is dict and set(row) == {"unit_id", "contract", "source_cid", "source_sha256", "target"},
                     "closed source/target role record required")
            contract = IntegerOffsetContract.from_dict(row["contract"])
            _require(row["unit_id"] == CodebaseFeatureSample(role, contract).unit_id, "logical source selector differs")
            target = validate_codebase_targets(DomainTargetEnvelope.from_dict(row["target"]))
            _require(target.domain_id == "codebase_ir", "foreign CodebaseIR target")
            details = target.to_dict()["validation"][0]["details"]
            _require(details["binding"]["source_cid"] == row["source_cid"]
                     and details["binding"]["source_sha256"] == row["source_sha256"]
                     and features._raw(details["inputs"]["contract"]) == features._raw(row["contract"]),
                     "cohort source/contract differs from captured target")
            if role == "training":
                _require(details["inputs"]["revision"] == "snapshot:" + cohort["head"]["snapshot_cid"],
                         "training target belongs to another captured generation")
            _require(row["unit_id"] not in units and row["source_sha256"] not in contents, "duplicate source across split roles")
            units[row["unit_id"]], contents[row["source_sha256"]] = role, role
    _require(sum(len(rows) for rows in cohort["roles"].values()) <= 32, "cohort exceeds 32 source targets")
    lineage = cohort["ancestral_roles"]
    _require(type(lineage) is list and 1 <= len(lineage) <= MAX_ANCESTRAL_BINDINGS, "ancestral split ledger exceeds bound")
    previous_units, previous_contents = {}, {}
    for row in lineage:
        _require(type(row) is dict and set(row) == {"unit_id", "source_sha256", "role"} and row["role"] in ROLES,
                 "invalid ancestral split record")
        for key, seen in (("unit_id", previous_units), ("source_sha256", previous_contents)):
            _require(type(row[key]) is str and row[key], "nonempty ancestral identity required")
            _require(row[key] not in seen or seen[row[key]] == row["role"], "ancestral split leakage")
            seen[row[key]] = row["role"]
    _require(lineage == sorted(lineage, key=lambda row: (row["unit_id"], row["source_sha256"], row["role"]))
             and len({features.digest(row) for row in lineage}) == len(lineage), "canonical unique ancestral roles required")
    for role, rows in cohort["roles"].items():
        _require(all({"unit_id": row["unit_id"], "source_sha256": row["source_sha256"], "role": role} in lineage for row in rows),
                 "current source roles missing from ancestry")
    return cohort


def _parent(registry, version_id, checkpoint):
    if version_id is None:
        return None
    from ...optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    def read(identifier):
        checkpoint()
        record = registry.get_version(identifier)
        path = registry.artifact_path(record["artifact"])
        _require(path.stat().st_size <= MAX_BYTES, "CodebaseIR parent exceeds checkpoint bound")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        _require(len(raw) <= MAX_BYTES, "CodebaseIR parent grew beyond checkpoint bound")
        registry.verify_artifact(record["artifact"])
        _require(_sha(raw) == record["artifact"]["sha256"], "parent changed during read")
        saved = json.loads(raw)
        cohort = _validate_cohort(saved["report"].get("codebase_cohort"), checkpoint)
        _require(record["parent_version_id"] == cohort["parent_version_id"], "registry and cohort parent differ")
        _require(saved["report"]["feature_space_sha256"] == cohort["feature_space_sha256"] == features.digest(saved["feature_space"]),
                 "saved feature basis differs from cohort")
        for role in ("training", "tuning"):
            _require(saved["report"][role + "_targets_sha256"]
                     == features.digest([row["target"] for row in cohort["roles"][role]]),
                     "saved numerical report differs from " + role + " cohort")
        _require(saved["state"]["tuning_targets_sha256"] == saved["report"]["tuning_targets_sha256"],
                 "saved numerical state differs from fixed tuning cohort")
        return record, saved, cohort
    record, saved, cohort = read(version_id)
    cursor, cursor_saved, current = record, saved, cohort
    visited = set()
    while True:
        _require(cursor["version_id"] not in visited and len(visited) < 32, "cyclic or oversized model ancestry")
        visited.add(cursor["version_id"])
        parent_id = cursor["parent_version_id"]
        latest = [{"unit_id": row["unit_id"], "source_sha256": row["source_sha256"], "role": role}
                  for role, rows in current["roles"].items() for row in rows]
        if parent_id is None:
            expected_ancestry = latest
            _require(current["generation"] == 1, "missing ancestral model generation")
        else:
            ancestor, ancestor_saved, prior = read(parent_id)
            _require(current["generation"] == prior["generation"] + 1
                     and current["parent_artifact_sha256"] == ancestor["artifact"]["sha256"]
                     and current["feature_space_sha256"] == prior["feature_space_sha256"]
                     and cursor["variant_id"] == ancestor["variant_id"], "ordered numerical ancestry differs")
            _require(cursor_saved["report"]["base_state_sha256"] == features.digest(ancestor_saved["state"]),
                     "ancestral numerical parent differs")
            _require(current["head"]["repository_id"] == prior["head"]["repository_id"]
                     and current["head"]["generation"] >= prior["head"]["generation"], "ancestral repository generation differs")
            for role in ("tuning", "canary"):
                _require(current["roles"][role] == prior["roles"][role], "ancestral held-out cohort changed")
            expected_ancestry = [*prior["ancestral_roles"], *latest]
        _require({features.digest(row) for row in current["ancestral_roles"]}
                 == {features.digest(row) for row in expected_ancestry}, "incomplete ancestral role history")
        if parent_id is None:
            break
        cursor, cursor_saved, current = ancestor, ancestor_saved, prior
    runtime = runtimes.load_version(registry, version_id, domain="codebase_ir", version=RUNTIME_VERSION)
    _require(features.digest(runtime.feature_space) == cohort["feature_space_sha256"], "parent feature basis differs from cohort")
    return record, saved, cohort, runtime


def _run_worker(request, lease, signal, remaining, admission_timeout_seconds):
    from .codebase_feature_worker import REQUEST_SCHEMA, RESULT_SCHEMA
    request = {"schema": REQUEST_SCHEMA, **request}
    raw = features._raw(request)
    _require(len(raw) <= MAX_BYTES, "bounded numerical worker request required")
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "CUDA_VISIBLE_DEVICES": "",
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    root = Path(__file__).resolve().parents[3]
    search_roots = [str(root), site.getusersitepackages(), *site.getsitepackages()]
    bootstrap = "import json,sys;sys.path[:0]=json.loads(sys.argv[1]);from ipfs_datasets_py.logic.software_contracts.codebase_feature_worker import main;main()"
    with lease.acquire_child(lane=ResourceLane.TRAINER, cpu_slots=1, memory_mb=lease.memory_mb - 512,
            child_process_slots=1, timeout=min(admission_timeout_seconds, remaining()), cancel_event=signal,
            request_id="codebase-ir:feature-training") as child:
        duration = remaining()
        limits = ToolRunLimits(timeout_seconds=duration, cpu_seconds=max(1, math.ceil(duration)),
            memory_bytes=16 * 1024**3, resident_memory_bytes=child.memory_mb * 1024**2,
            max_input_bytes=MAX_BYTES, max_output_bytes=MAX_BYTES,
            max_workspace_bytes=4 * MAX_BYTES, max_output_files=8)
        observation = BoundedToolRunner(base_environment=environment).run(
            [str(Path(sys.executable).resolve()), "-I", "-B", "-c", bootstrap, json.dumps(search_roots)],
            input_files={"request.json": raw}, output_paths=("response.json",), limits=limits,
            cancellation=child.combined_cancellation_signal(signal))
        if observation.cancelled or signal.is_set():
            raise LeaseCancelledError("CodebaseIR numerical worker cancelled")
        if observation.timed_out:
            raise LeaseTimeoutError("CodebaseIR numerical worker deadline exceeded")
        _require(observation.ok and not observation.output_truncated and not observation.workspace_limit_exceeded
                 and observation.workspace_cleaned, "CodebaseIR numerical worker failed: " + observation.stderr[-4000:])
    remaining()
    encoded = observation.output_files.get("response.json")
    _require(encoded is not None and len(encoded) <= MAX_BYTES, "missing bounded numerical output")
    result = json.loads(encoded)
    _require(result.get("schema") == RESULT_SCHEMA and result.get("request_sha256") == features.digest(request),
             "numerical response does not bind its request")
    _require(all(result.get(key) is False for key in features.FALSE), "numerical candidate claims authority")
    _require(result["runtime"]["device"] == "cpu" and result["runtime"]["intraop_threads"] == result["runtime"]["interop_threads"] == 1,
             "numerical worker exceeded its CPU thread policy")
    return result, {"timeout_ms": math.ceil(duration * 1000), "cpu_seconds": math.ceil(duration),
                    "address_space_bytes": limits.memory_bytes, "resident_memory_bytes": limits.resident_memory_bytes,
                    "max_io_bytes": MAX_BYTES, "max_workspace_bytes": limits.max_workspace_bytes,
                    "python_search_roots": search_roots,
                    "rss_sampling_ms": 100, "workspace_cleaned": observation.workspace_cleaned}


def train_current_codebase_features(index, repository, *, expected_head, registry, directory, samples,
        parent_version_id=None, scheduler=None, parent_lease=None, cancel_event=None,
        epochs=2, learning_rate=0.02, seed=1729, timeout_seconds=120.0,
        admission_timeout_seconds=30.0, memory_mb=2048):
    """Fit an isolated 8D candidate and register it only after current-source checks.

    Training roles may change their captured bytes and add new training units.
    Tuning/canary units and exact targets stay frozen from the original cohort.
    Unknown training feature atoms require a separately declared new variant.
    Registry publication never promotes an active model or proof head.
    """
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ..formalization.autoencoder.codebase_targets import prepare_codebase_targets
    from ...optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    _require(sys.platform.startswith("linux"), "bounded CodebaseIR training requires the native Linux process guard")
    _require(type(index) is RepositoryCodebaseIndex and index.catalog is not None, "native current structural owner required")
    _require(type(expected_head) is CodebaseHead and type(registry) is AutoencoderRegistry, "canonical head and model registry required")
    _require(type(samples) in {list, tuple} and 3 <= len(samples) <= 32
             and all(type(row) is CodebaseFeatureSample for row in samples), "bounded explicit CodebaseIR cohort required")
    _require(len({row.unit_id for row in samples}) == len(samples), "duplicate logical source selection")
    _require(all(1 <= sum(row.role == role for row in samples) <= 16 for role in ROLES), "all three bounded source roles required")
    _require(type(memory_mb) is int and 2048 <= memory_mb <= 8192, "training reservation must be 2048–8192 MiB")
    _require(type(epochs) is int and 1 <= epochs <= 8, "bounded 1–8 training epochs required")
    _require(type(seed) is int and 0 <= seed < 2**31, "bounded integer seed required")
    _require(type(learning_rate) in {int, float} and math.isfinite(learning_rate) and 0 < learning_rate <= .1, "invalid learning rate")
    for value, zero_allowed in ((timeout_seconds, False), (admission_timeout_seconds, True)):
        _require(type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 300
                 and (zero_allowed or value > 0), "invalid training/admission deadline")
    directory = Path(directory)
    _require(not directory.exists(), "fresh candidate staging directory required")
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=min(admission_timeout_seconds, timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set():
                raise LeaseCancelledError("CodebaseIR feature preparation cancelled")
            value = deadline - time.monotonic()
            if value <= 0:
                raise LeaseTimeoutError("CodebaseIR feature preparation deadline exceeded")
            return value
        def observe():
            duration = remaining()
            return index.observe_current(repository, expected_head=expected_head, parent_lease=lease,
                cancel_event=signal, timeout_seconds=duration, admission_timeout_seconds=min(admission_timeout_seconds, duration),
                memory_mb=512)
        current = observe()
        implementation = _implementation()
        previous = _parent(registry, parent_version_id, remaining)
        parent_cohort = None if previous is None else previous[2]
        if parent_cohort:
            prior_head = CodebaseHead.from_dict(parent_cohort["head"])
            _require(prior_head.repository_id == expected_head.repository_id and prior_head.generation <= expected_head.generation,
                     "numerical parent belongs to another repository or future source generation")
        entries = {row.path: row for row in current.manifest.snapshot.entries}
        roles = {role: [] for role in ROLES}
        for sample in sorted(samples, key=lambda row: row.unit_id):
            remaining()
            entry = entries.get(sample.contract.path)
            _require(entry is not None and not entry.is_opaque and entry.size_bytes <= 65536, "selected training source absent/opaque/oversized")
            source = index.artifacts.get_bytes(entry.source_cid)
            _require(len(source) == entry.size_bytes, "captured source length differs")
            target = prepare_codebase_targets(source, sample.contract, revision="snapshot:" + expected_head.snapshot_cid)
            roles[sample.role].append({"unit_id": sample.unit_id, "contract": sample.contract.to_dict(),
                "source_cid": entry.source_cid, "source_sha256": _sha(source), "target": target.to_dict()})
        if parent_cohort:
            for role in ("tuning", "canary"):
                before, after = parent_cohort["roles"][role], roles[role]
                _require([{k: v for k, v in row.items() if k != "target"} for row in before]
                         == [{k: v for k, v in row.items() if k != "target"} for row in after],
                         "tuning/canary source or contract changed; explicit new lineage required")
                # Reuse the exact fixed envelopes, including original revisions.
                roles[role] = features._plain(before)
        ancestry = [] if parent_cohort is None else features._plain(parent_cohort["ancestral_roles"])
        for role, rows in roles.items():
            for row in rows:
                binding = {"unit_id": row["unit_id"], "source_sha256": row["source_sha256"], "role": role}
                if binding not in ancestry:
                    ancestry.append(binding)
        training = [row["target"] for row in roles["training"]]
        runtime = runtimes.build_codebase_feature_runtime(training, latent_width=8) if previous is None else previous[3]
        space, contract = runtime.feature_space, runtime.contract
        _require(len(space["columns"]) <= 512, "CodebaseIR feature width exceeds 512 columns")
        cohort = {"schema": COHORT_SCHEMA, "runtime_version": RUNTIME_VERSION, "head": expected_head.to_dict(),
            "generation": 1 if parent_cohort is None else parent_cohort["generation"] + 1,
            "parent_version_id": parent_version_id,
            "parent_artifact_sha256": None if previous is None else previous[0]["artifact"]["sha256"],
            "roles": roles, "ancestral_roles": sorted(ancestry, key=lambda row: (row["unit_id"], row["source_sha256"], row["role"])),
            "feature_space_sha256": features.digest(space), "policy": POLICY}
        cohort["cohort_sha256"] = features.digest(cohort)
        _validate_cohort(cohort, remaining)
        for role, rows in roles.items():
            _, _, coverage = features._matrix(space, [row["target"] for row in rows])
            _require(not any(row["unknown_atoms"] for row in coverage), role + " has unknown atoms; explicit feature-basis migration required")
        request = {"contract": contract.to_dict(), "feature_space": space, "base_state": runtime.state,
                   **{role: [row["target"] for row in rows] for role, rows in roles.items()},
                   "options": {"epochs": epochs, "latent_width": 8, "learning_rate": learning_rate,
                               "max_seconds": min(120, remaining()), "seed": seed}}
        worker, limits = _run_worker(request, lease, signal, remaining, admission_timeout_seconds)
        remaining()
        _require(_implementation() == implementation, "training implementation changed during execution")
        observe()
        result = worker["result"]
        _require(result["report"]["training_targets_sha256"] == features.digest(training)
                 and result["report"]["tuning_targets_sha256"] == features.digest(request["tuning"])
                 and result["report"]["base_state_sha256"] == (None if runtime.state is None else features.digest(runtime.state)),
                 "numerical output cohort or parent differs")
        result["report"]["codebase_cohort"] = cohort
        result["report"]["codebase_worker"] = {key: worker[key] for key in ("runtime", "canary_before", "canary_after", "canary_nonregression", "canary_gate")}
        result["report"]["codebase_resource_limits"] = limits
        result["report"]["codebase_implementation_sha256"] = implementation
        registered = None
        if worker["canary_nonregression"]:
            remaining()
            registered = features.register_feature_candidate(registry, contract, space, result, directory,
                                                             parent_version_id=parent_version_id)
        observe()
        remaining()
        return {"schema": SCHEMA, "status": "candidate_registered" if registered else "candidate_rejected",
                "head": expected_head.to_dict(), "cohort_sha256": cohort["cohort_sha256"],
                "candidate": registered, "parent_version_id": parent_version_id,
                "report": features._plain(result["report"]), "training_executed": True,
                "decoded_formulas_generated": False, "behavior_authority": False,
                "execution_authority": False, "completion_authority": False, **features.FALSE}


__all__ = ["CodebaseFeatureSample", "CodebaseFeatureTrainingError", "train_current_codebase_features"]
