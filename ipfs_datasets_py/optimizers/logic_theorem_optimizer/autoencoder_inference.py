"""Resumable qualification passes on immutable weights, without an optimizer.

This route opens no model registry, publishes no weights and does not enqueue
training. Its inference gate and full qualification checks are shared with the
candidate verifier. Capacity changes affect dispatch, never pass identities.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path

from . import autoencoder_incremental_training as inc


def _pass(candidate, version, sample, validation, directory, timeout):
    from .autoencoder_candidate_qualification import qualify_candidate
    from ...huggingface.autoencoder_span_attempts import _receipt
    from ...huggingface.autoencoder_incremental import _proofs, _qualified
    directory = Path(directory)
    receipt_path, seal_path = directory / "qualification.json", directory / "inference-seal.json"
    if seal_path.exists():
        seal = json.loads(seal_path.read_bytes())
        raw = receipt_path.read_bytes()
        if seal != {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}:
            raise ValueError("retained inference evidence changed")
        receipt = json.loads(raw)
    else:
        if directory.exists():
            raise ValueError("incomplete inference pass requires explicit recovery")
        qualify_candidate(candidate, version, [sample], directory,
            heldout_samples=validation, model_config={"compute_device": "python"},
            lake_timeout_seconds=timeout)
        raw = receipt_path.read_bytes()
        receipt = json.loads(raw)
        inc._write(seal_path, {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    artifact = {key: candidate[key] for key in ("sha256", "bytes")}
    _receipt(receipt, version, artifact)
    if (receipt["sample_set_sha256"] != inc._sha({"training": [sample], "heldout": validation})
            or receipt["requested_model_config"] != {"compute_device": "python"}
            or receipt.get("execution_path") != "inference"
            or receipt.get("execution_gate_applied") is not True
            or receipt.get("training_executed") is not False):
        raise ValueError("inference evidence differs from requested route or samples")
    if ([row["source"] for row in receipt["rows"] if row["split"] == "training"] != [sample]
            or [row["source"] for row in receipt["rows"] if row["split"] == "heldout"] != validation):
        raise ValueError("inference rows differ from requested samples")
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != receipt["source_sha256"][key]
           for key, path in receipt["source_files"].items()):
        raise ValueError("inference producer source changed")
    if receipt["qualified"]:
        _qualified(receipt, {"version_id": version, "artifact": artifact})
        _proofs(receipt, read_local=True)
    return {"receipt": str(receipt_path), "qualification_sha256": hashlib.sha256(raw).hexdigest(),
            "qualified": receipt["qualified"], "gate_results": receipt["gate_results"],
            "execution_path": "inference", "training_executed": False,
            "admitted": False, "formalized": False}


def run_inference_cycle(config, cli, *, executor_factory=None, pass_function=_pass,
                        capacity_callback=None):
    """Local-only inference: never fall through to training or publication."""
    from .autoencoder_capacity import execution_capacity_plan, execution_envelope
    if config.get("execution_mode") != "inference":
        raise ValueError("inference route requires the inference execution gate")
    if (not config.get("input_jsonl") or not config.get("validation_jsonl")
            or any(config.get(key) for key in ("repository_id", "publish_repository", "arrow_feature_weights", "shared_targets"))):
        raise ValueError("inference requires local input/validation and cannot publish or accept training artifacts")
    sources = {"native": cli._pin(), "orchestration": cli.orchestration_hashes()}
    records, validation = cli.local_records(config["input_jsonl"]), cli.local_records(config["validation_jsonl"])
    if not 1 <= len(validation) <= 32:
        raise ValueError("inference requires one to 32 disjoint tuning-validation rows")
    samples = [row["sample"] for row in records if int(row["record_id"].removeprefix("sha256:"), 16)
               % config.get("shard_count", 1) == config.get("shard_index", 0)]
    heldout = [row["sample"] for row in validation]
    checkpoint = Path(config["checkpoint"])
    if checkpoint.is_symlink() or not checkpoint.is_file():
        raise ValueError("inference requires a regular complete local checkpoint")
    candidate = {"path": str(checkpoint.resolve()), "sha256": cli._sha(checkpoint), "bytes": checkpoint.stat().st_size}
    if checkpoint.resolve() == cli.PINNED.resolve() and candidate["sha256"] != cli.PINNED_SHA:
        raise ValueError("protected restart12 checkpoint changed")
    version = "inference-" + candidate["sha256"]
    state = Path(config["state_directory"]) / "inference"
    state.mkdir(parents=True, exist_ok=True)
    binding = {"candidate": candidate, "sources": sources, "validation": heldout,
               "lake_timeout_seconds": config["lake_timeout_seconds"], "execution_path": "inference"}
    binding_path = state / "binding.json"
    if binding_path.exists() and json.loads(binding_path.read_bytes()) != binding:
        raise ValueError("inference checkpoint, source or validation policy changed; new state required")
    if not binding_path.exists():
        inc._write(binding_path, binding)
    rows, pending = [], []
    for sample in samples:
        directory = state / "passes" / inc._sha(sample)
        args = (candidate, version, sample, heldout, directory, config["lake_timeout_seconds"])
        if (directory / "inference-seal.json").exists():
            rows.append(pass_function(*args))
        else:
            pending.append(args)
    plans, dispatched = [], 0
    while pending and dispatched < config["max_batches"]:
        plan = (capacity_callback or (lambda **limits: execution_capacity_plan("inference", **limits)))(
            max_workers=config.get("max_parallel_workers", config["workers"]),
            memory_budget_mb=config["memory_mb"],
            cpu_budget=config.get("reserved_cpu_slots", execution_envelope(
                "inference", config.get("max_parallel_workers", config["workers"]))["cpu_slots"]),
            process_budget=config.get("reserved_child_process_slots"),
            pending_count=min(len(pending), config["max_batches"] - dispatched))
        plans.append(plan)
        if plan["workers"] == 0:
            break
        wave = pending[:plan["workers"]]
        factory = executor_factory or (lambda **kw: ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn"), **kw))
        with factory(max_workers=len(wave)) as executor:
            futures = [executor.submit(pass_function, *args) for args in wave]
            rows.extend(future.result() for future in futures)
        pending = pending[len(wave):]
        dispatched += len(wave)
    if (cli._sha(checkpoint) != candidate["sha256"]
            or {"native": cli._pin(), "orchestration": cli.orchestration_hashes()} != sources):
        raise ValueError("inference weights or producer changed during execution")
    result = {"schema": "autoencoder-inference-cycle/v1", "execution_path": "inference",
              "training_executed": False, "training": None, "weight_publications": [],
              "input_count": len(samples), "inference": rows, "dispatched_pass_count": dispatched,
              "pending_pass_count": len(pending), "capacity_plans": plans, "source_hashes": sources,
              "candidate": candidate, "temperature": 0, "admitted": False, "formalized": False,
              "promotion_performed": False, "heldout_canary": False}
    cli._write(config["cycle_receipt"], result)
    return result


from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewedInferenceParentRuntime:
    """Trusted in-process composition; never decoded from an execution packet."""
    owner: object
    source_guard: object
    asset_policy_guard: object
    current_admission_provider: object
    deadline_monotonic: float
    current_training_admission_provider: object = None
    context_policy_guard: object = None
    typed_structure_profile: object = None
    candidate_syntax_profile: object = None

    def __post_init__(self):
        import math
        if (self.owner is None or any(not callable(value) for value in
                (self.source_guard, self.asset_policy_guard, self.current_admission_provider))
                or type(self.deadline_monotonic) not in (int, float)
                or not math.isfinite(self.deadline_monotonic)):
            raise ValueError("original admitted owner and explicit live reviewed parent callbacks required")
        _validate_parent_typed_structure_profile(self.typed_structure_profile)
        _validate_parent_candidate_syntax_profile(self.candidate_syntax_profile)
        context_callbacks = (self.current_training_admission_provider, self.context_policy_guard)
        if any(callback is not None for callback in context_callbacks) and not all(map(callable, context_callbacks)):
            raise ValueError("rich heldout context requires both live original parent callbacks")



def _validate_parent_typed_structure_profile(value):
    if value is not None:
        from .legal_ir_semantic_metrics import CANONICAL_TYPED_STRUCTURE_PROFILE
        if type(value) is not str or value != CANONICAL_TYPED_STRUCTURE_PROFILE:
            raise ValueError("explicit trusted parent typed-structure profile required")


def _parent_typed_structure_source_pins():
    from . import legal_ir_semantic_metrics as metrics
    from ...logic.syntax_core import ast as ast_owner, contracts, signatures
    from ...logic.families import namespaces
    from .autoencoder_daemon_invocation_contracts import describe
    root = Path(__file__).resolve().parents[3]
    modules = ((metrics, "optimizers/logic_theorem_optimizer/legal_ir_semantic_metrics.py"),
        (ast_owner, "logic/syntax_core/ast.py"), (contracts, "logic/syntax_core/contracts.py"),
        (signatures, "logic/syntax_core/signatures.py"), (namespaces, "logic/families/namespaces.py"))
    pins = {}
    for module, relative in modules:
        path = root / "ipfs_datasets_py" / relative
        if (Path(module.__file__).resolve() != path or module.__spec__.origin != str(path)):
            raise ValueError("canonical parent typed-structure owner origin differs")
        pins[str(path)] = describe(path, 4 * 1024**2)["sha256"]
    return pins


def _build_parent_typed_structure_audit(cycle, request, cycle_reference, request_sha256, source_pins):
    """Content-bound audit DATA; only the original parent can publish it."""
    from . import autoencoder_training_worker as worker
    from . import legal_ir_semantic_metrics as metrics
    def read(descriptor):
        return worker._parse_json(worker._reviewed_decoder_artifact(
            worker.CheckpointArtifact.from_dict(descriptor), limit=REVIEWED_EVALUATION_OUTPUT_LIMIT))
    rows = read(request["rows_artifact"])
    evaluation = read(cycle["output_artifacts"]["evaluation"])
    generation = read(cycle["output_artifacts"]["generation"])
    payload = evaluation.get("compiler_artifact", {}).get("reviewed_source_span_producer_evaluation", {})
    if (type(rows) is not list or not rows or worker._json_bytes(payload.get("reference_population")) != worker._json_bytes(rows)
            or worker._json_bytes(payload.get("configuration", {}).get("checkpoint_declarations")) != worker._json_bytes(request["checkpoint_declarations"])):
        raise ValueError("parent typed-structure reference population/checkpoint differs from request")
    outputs = payload.get("producer_outputs")
    last = generation.get("last_call")
    if type(last) is not dict:
        raise ValueError("parent typed-structure requires an observed generation call")
    raw = last.get("raw_generation_outputs")
    join_scope = "complete_raw_generation_rows"
    if raw is None:
        exception = last.get("exception_type")
        if (last.get("completed") is not False or type(exception) is not str or not 0 < len(exception) <= 128
                or payload.get("producer_exception_type") != exception
                or last.get("entry_pair_match") is not True or last.get("exit_pair_match") is not True
                or last.get("closeout_exception_type") is not None or type(outputs) is not list
                or any(type(row) is not dict or row.get("outcome") != "error" or row.get("candidate") is not None for row in outputs)):
            raise ValueError("parent typed-structure batch error lacks original generation evidence")
        # Bind the recorded failed callback; do not invent token rows or a body.
        raw = outputs
        join_scope = "recorded_batch_exception_without_raw_generation_rows"
    elif last.get("completed") is not True:
        raise ValueError("parent typed-structure raw rows require a completed generation call")
    arguments = payload.get("producer_arguments")
    if any(type(values) is not list or len(values) != len(rows) for values in (outputs, raw, arguments)):
        raise ValueError("parent typed-structure requires the complete ordered output population")
    cases = []
    for row, output, emitted, argument in zip(rows, outputs, raw, arguments, strict=True):
        if (type(output) is not dict or set(output) != {"id", "candidate", "outcome"}
                or type(emitted) is not dict or not {"id", "candidate", "outcome"} <= set(emitted)
                or type(argument) is not dict or set(argument) != {"id", "source_text", "context"}
                or row["id"] != output["id"] or row["id"] != emitted["id"] or row["id"] != argument["id"]
                or worker._json_bytes(argument["source_text"]) != worker._json_bytes(row["source_text"])
                or worker._json_bytes({key: emitted[key] for key in ("id", "candidate", "outcome")}) != worker._json_bytes(output)):
            raise ValueError("parent typed-structure source/output join differs")
        cases.append(dict(case_id=row["id"], reference=row["canonical_ir"], candidate=output["candidate"], outcome=output["outcome"]))
    exact = metrics.evaluate_complete_norm_payloads(cases)
    if (worker._json_bytes(exact) != worker._json_bytes(evaluation.get("metrics", {}).get("complete_norm_payload"))
            or worker._json_bytes(exact) != worker._json_bytes(payload.get("comparison"))):
        raise ValueError("parent typed-structure original metric observation differs")
    report = metrics.evaluate_complete_norm_typed_structure(cases)
    return dict(schema="reviewed-original-parent-typed-structure-audit/v1",
        profile=metrics.CANONICAL_TYPED_STRUCTURE_PROFILE, request_sha256=request_sha256,
        child_cycle_artifact=dict(path=cycle_reference.path, sha256=cycle_reference.sha256, bytes=cycle_reference.bytes),
        rows_artifact=request["rows_artifact"], original_output_artifacts=cycle["output_artifacts"],
        implementation_sha256=source_pins, generation_join_scope=join_scope, report=report, original_child_artifacts_modified=False,
        scope="canonical_formula_wire_and_signature_only", native_proof_verified=False,
        legal_meaning_verified=False, current_admission_authority_granted=False, model_reexecuted=False)


def _validate_parent_candidate_syntax_profile(value):
    if value is not None:
        from ...logic.autoformal import legal_norm_content_adjudication_v1 as candidates
        if type(value) is not str or value not in (candidates.CANDIDATE_SYNTAX_PROFILE_V2,
                                                  candidates.CANDIDATE_SYNTAX_PROFILE_V3):
            raise ValueError('explicit trusted parent candidate-syntax profile required')


def _parent_candidate_syntax_source_pins():
    from ...logic.autoformal import legal_norm_content_adjudication_v1 as candidates
    from ...logic.autoformal import legal_relational_norm_v1 as relational, corpus_contracts
    from .autoencoder_daemon_invocation_contracts import describe
    root = Path(__file__).resolve().parents[3]
    modules = ((candidates, 'logic/autoformal/legal_norm_content_adjudication_v1.py'),
        (relational, 'logic/autoformal/legal_relational_norm_v1.py'),
        (corpus_contracts, 'logic/autoformal/corpus_contracts.py'))
    pins = _parent_typed_structure_source_pins()
    for module, relative in modules:
        path = root / 'ipfs_datasets_py' / relative
        if Path(module.__file__).resolve() != path or module.__spec__.origin != str(path):
            raise ValueError('canonical parent candidate-syntax owner origin differs')
        pins[str(path)] = describe(path, 4 * 1024**2)['sha256']
    # Existing owners retain their own transitive identity fences. Bind their
    # actual canonical source closure as DATA, never a model or asset profile.
    for path, digest in {**candidates._pins(), **relational._mixed_owners()[-1]}.items():
        resolved = Path(path)
        if (resolved.resolve() != resolved or not resolved.is_relative_to(root / 'ipfs_datasets_py')
                or describe(resolved, 4 * 1024**2)['sha256'] != digest
                or path in pins and pins[path] != digest):
            raise ValueError('canonical parent candidate-syntax source closure differs')
        pins[path] = digest
    if not 0 < len(pins) <= 256:
        raise ValueError('bounded parent candidate-syntax source closure required')
    return pins


def _check_parent_audit_storage(usage, wires):
    if any(len(wire) > REVIEWED_EVALUATION_OUTPUT_LIMIT for wire in wires):
        raise ValueError("parent audit exceeds existing output bound")
    if usage["total_attempt_charged_bytes"] + sum(map(len, wires)) > usage["attempt_limit_bytes"]:
        raise ValueError("parent audits exceed original storage promise")


def _check_parent_audit_inputs(request, reference, *, candidate=False):
    from . import autoencoder_training_worker as worker
    worker._reviewed_decoder_artifact(worker.CheckpointArtifact.from_dict(request["rows_artifact"]),
        limit=REVIEWED_EVALUATION_OUTPUT_LIMIT, load=False)
    worker._reviewed_decoder_artifact(reference, limit=4 * 1024**2, load=False)
    if candidate:
        worker._reviewed_decoder_artifact(worker.CheckpointArtifact.from_dict(request["source_contexts_artifact"]),
            limit=4 * 1024**2, load=False)


def _build_parent_candidate_syntax_audit(cycle, request, cycle_reference, request_sha256,
                                        source_pins, candidate_syntax_profile):
    """Build content-bound DATA after the original parent's child wait.

    This helper alone proves neither an actual wait nor current eligibility.
    The original owner publishes only after its existing FINISH, wait, current
    admission, quota, source and final artifact checks have all succeeded.
    """
    from . import autoencoder_training_worker as worker
    from .legal_ir_semantic_metrics import evaluate_complete_norm_candidate_syntax
    _validate_parent_candidate_syntax_profile(candidate_syntax_profile)
    if candidate_syntax_profile is None or 'source_contexts_artifact' not in request:
        raise ValueError('parent candidate-syntax requires an explicit profile and independent context artifact')
    # Reuse the established complete source/output/generation/checkpoint join,
    # including the recorded batch-exception path. No child artifact is edited.
    base = _build_parent_typed_structure_audit(cycle, request, cycle_reference, request_sha256, source_pins)
    def read(descriptor, limit=REVIEWED_EVALUATION_OUTPUT_LIMIT):
        return worker._parse_json(worker._reviewed_decoder_artifact(
            worker.CheckpointArtifact.from_dict(descriptor), limit=limit))
    rows = read(request['rows_artifact'])
    evaluation = read(cycle['output_artifacts']['evaluation'])
    contexts = read(request['source_contexts_artifact'], 4 * 1024**2)
    if (type(contexts) is not dict or set(contexts) != {'profile', 'selection_context', 'rows'}
            or contexts['profile'] != 'reviewed-source-selection-context/v2'
            or type(contexts['rows']) is not list or len(contexts['rows']) != len(rows)):
        raise ValueError('parent candidate-syntax requires complete independent source contexts')
    known = {}
    for row, context in zip(rows, contexts['rows'], strict=True):
        if (type(context) is not dict or set(context) != {'id', 'unit_id', 'governing_context', 'source_binding'}
                or context['id'] != row['id'] or context['unit_id'] != row['unit_id']):
            raise ValueError('parent candidate-syntax source context/order/unit differs')
        known[row['id']] = dict(known_source_binding=context['source_binding'],
            known_governing_context=context['governing_context'],
            known_selection_context=contexts['selection_context'])
    outputs = evaluation['compiler_artifact']['reviewed_source_span_producer_evaluation']['producer_outputs']
    cases = [dict(case_id=r['id'], reference=r['canonical_ir'], candidate=o['candidate'], outcome=o['outcome'])
             for r, o in zip(rows, outputs, strict=True)]
    report = evaluate_complete_norm_candidate_syntax(cases, known_candidate_inputs=known,
                                                    candidate_syntax_profile=candidate_syntax_profile)
    return dict(base, schema='reviewed-original-parent-candidate-syntax-audit/v1',
        profile=candidate_syntax_profile, report=report,
        source_contexts_artifact=request['source_contexts_artifact'],
        scope='complete_candidate_syntax_and_declared_source_context_selection_only',
        semantic_selection_supported=False, source_fidelity_proved=False)

def _reviewed_evaluation_lifecycle_source_sha256(*, rich_context=False):
    """Fixed lifecycle source identity; no configurable importer/entry point."""
    root = Path(__file__).resolve().parents[3]
    relative = ("scripts/ops/legal_ir/run_incremental_autoencoders.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_inference.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_process.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_process_worker.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_worker.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/existing_resource_scheduler.py")
    if rich_context:
        optimizer = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/"
        relative += tuple(optimizer + name for name in (
            "legal_structured_retrieval.py", "legal_joint_retrieval.py", "legal_formula_codec.py",
            "legal_ir_grammar_decoder.py", "legal_ir_evaluation_artifacts.py"))
        relative += ("ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",)
    from .autoencoder_daemon_invocation_contracts import describe
    return {str(root / path): describe(root / path, 1024 * 1024)["sha256"] for path in relative}


def _check_reviewed_evaluation_lifecycle(request):
    if request["lifecycle_source_sha256"] != _reviewed_evaluation_lifecycle_source_sha256(
            rich_context="training_context" in request):
        raise ValueError("fixed reviewed evaluation lifecycle source changed")


REVIEWED_EVALUATION_OUTPUT_LIMIT = 32 * 1024**2


REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA = "reviewed-source-evaluation-request/v11"


def _check_reviewed_generation_policy(request, policy):
    """Match new-profile load/producer callbacks to the original request DATA."""
    if "generation_policy" not in request:
        return
    from . import autoencoder_training_worker as worker
    generation = worker._reviewed_decoder_generation_policy(request["generation_policy"])
    digest_omitted = request["schema"] == REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA
    qwen2 = digest_omitted or request["schema"] in ("reviewed-source-evaluation-request/v9", "reviewed-source-evaluation-request/v10")
    producer_schema = ("reviewed-decoder-digest-omitted-source-producer-policy/v1" if digest_omitted else
        "reviewed-decoder-source-producer-policy/v4" if qwen2 else "reviewed-decoder-source-producer-policy/v3")
    load_schema = "reviewed-local-digest-omitted-decoder-load-policy/v1" if digest_omitted else "reviewed-local-decoder-load-policy/v2"
    if digest_omitted and generation["schema"] != worker.REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA:
        raise ValueError("v11 callback requires the digest-omitted generation policy")
    if not digest_omitted and generation["schema"] == worker.REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA:
        raise ValueError("digest-omitted callback policy requires explicit v11 request")
    if type(policy) is not dict:
        raise ValueError("generation policy callback must be an ordinary mapping")
    asset_names = ("recipe_artifact", "model_config_artifact", "tokenizer_artifact", "license_artifact")
    if policy.get("schema") == load_schema:
        expected = {"schema": load_schema, "backend_identity": request["backend_identity"],
            "assets": [request["assets"][name] for name in (*asset_names, "model_checkpoint", "optimizer_checkpoint")],
            "producer_pins": request["source_sha256"], "admission_inputs_sha256": request["admission_inputs_sha256"],
            "max_model_bytes": request["max_model_bytes"], "device": "cpu", "dtype": "bfloat16",
            "load_requested": True, "restore_requested": True, "training_requested": False,
            "downloads_requested": False, "resource_grant_requested": False,
            "runtime_profile": request["runtime_profile"], "admission_profile": request["admission_profile"]}
    elif policy.get("schema") == producer_schema:
        context = worker._parse_json(worker._reviewed_decoder_artifact(
            worker.CheckpointArtifact.from_dict(request["source_contexts_artifact"]), limit=4 * 1024**2))
        expected = {"schema": producer_schema, "backend_identity": request["backend_identity"],
            "assets": [request["assets"][name] for name in asset_names],
            "model_checkpoint": request["assets"]["model_checkpoint"], "optimizer_checkpoint": request["assets"]["optimizer_checkpoint"],
            "source_contexts_sha256": worker._digest(worker._json_bytes(context)),
            "admission_inputs_sha256": request["admission_inputs_sha256"], "max_source_tokens": request["max_source_tokens"],
            "max_output_tokens": request["max_output_tokens"], "operation": request["operation"],
            "training_requested": False, "restore_requested": False, "admission_profile": request["admission_profile"],
            "generation_policy": generation}
        if qwen2:
            expected["runtime_profile"] = request["runtime_profile"]
    else:
        raise ValueError("generation policy callback schema differs from the original request")
    if digest_omitted:
        if policy.get("schema") == load_schema:
            expected["target_codec"] = worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC
        else:
            expected["output_derivation"] = {"schema": "reviewed-digest-omitted-output-assembly/v1",
                "target_codec": worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC,
                "only_computed_field": "typed_expression.content_digest", "other_default_filling": False}
    if worker._json_bytes(policy) != worker._json_bytes(expected):
        raise ValueError("generation policy differs from the original request")


def _check_reviewed_evaluation_outputs(cycle, request):
    """Check the closed output set against its original child byte descriptors.

    Call after caller-owned completion callbacks. This authenticates local
    artifacts observed by this execution; it grants no semantic authority and
    does not authenticate a coordinated rewrite before the first observation.
    """
    from . import autoencoder_training_worker as worker
    paths = {name: str(Path(request["output_directory"]) / (name + ".json"))
             for name in ("evaluation", "loader", "generation")}
    descriptors = cycle.get("output_artifacts")
    if (type(descriptors) is not dict or set(descriptors) != set(paths)
            or cycle.get("inference") != {"profile": request["schema"], **paths}):
        raise ValueError("reviewed output artifacts must bind the exact closed output paths")
    for name, path in paths.items():
        reference = worker.CheckpointArtifact.from_dict(descriptors[name])
        if reference.path != path:
            raise ValueError("reviewed output artifact path differs from original request")
        worker._reviewed_decoder_artifact(reference, limit=REVIEWED_EVALUATION_OUTPUT_LIMIT, load=False)
    if "generation_policy" in request:
        generation = worker._parse_json(worker._reviewed_decoder_artifact(
            worker.CheckpointArtifact.from_dict(descriptors["generation"]), limit=REVIEWED_EVALUATION_OUTPUT_LIMIT))
        commitment = generation.get("input_commitment") if type(generation) is dict else None
        policy_keys = {"schema", "backend_identity", "assets", "model_checkpoint", "optimizer_checkpoint",
            "source_contexts_sha256", "admission_inputs_sha256", "max_source_tokens", "max_output_tokens",
            "operation", "training_requested", "restore_requested", "admission_profile", "generation_policy"}
        digest_omitted = request["schema"] == REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA
        qwen2 = digest_omitted or request["schema"] in ("reviewed-source-evaluation-request/v9", "reviewed-source-evaluation-request/v10")
        if digest_omitted:
            policy_keys.add("output_derivation")
        if qwen2:
            policy_keys.add("runtime_profile")
        if (type(generation) is not dict or generation.get("schema") != ("reviewed-decoder-digest-omitted-source-producer-observation/v1" if digest_omitted else "reviewed-decoder-source-producer-observation/v4" if qwen2 else "reviewed-decoder-source-producer-observation/v3") or
                type(commitment) is not dict or not policy_keys <= set(commitment)):
            raise ValueError("generation output must commit the explicit profiled producer policy")
        if digest_omitted:
            from ...logic.autoformal import training_cycle_inputs as inputs
            if (set(commitment) != policy_keys | {"source_sha256", "exposure_sha256", "supplied_context_supported"}
                    or commitment["source_sha256"] != request["source_sha256"]
                    or commitment["supplied_context_supported"] != "empty_permitted_and_retrieved_only"):
                raise ValueError("v11 source-only commitment population or scope differs")
            exposure = worker._parse_json(worker._reviewed_decoder_artifact(
                worker.CheckpointArtifact.from_dict(request["exposure_artifact"]), limit=4 * 1024**2))
            if commitment["exposure_sha256"] != worker._digest(inputs._reviewed_wire(exposure)):
                raise ValueError("v11 exposure commitment differs from original request")
        _check_reviewed_generation_policy(request, {key: commitment[key] for key in policy_keys})
        if digest_omitted:
            from ...logic.autoformal import training_cycle_inputs as inputs
            expected = "reviewed-decoder-digest-omitted-producer/v1:" + worker._digest(inputs._reviewed_wire(commitment))
        else:
            expected = ("reviewed-decoder-qwen2-profiled-producer/v1:" if qwen2 else "reviewed-decoder-profiled-producer/v1:") + worker._digest(worker._json_bytes(commitment))
        if generation.get("input_profile_id") != expected:
            raise ValueError("generation output profile identity differs from its full commitment")
        if digest_omitted:
            loader = worker._parse_json(worker._reviewed_decoder_artifact(
                worker.CheckpointArtifact.from_dict(descriptors["loader"]), limit=REVIEWED_EVALUATION_OUTPUT_LIMIT))
            _check_digest_omitted_loader_output(loader, request)
            _check_digest_omitted_generation_outputs(generation, request)


def _read_reviewed_evaluation_request(request_artifact):
    """Authenticate bounded DATA; no model construction or grant decoding."""
    import re
    from . import autoencoder_training_worker as worker
    reference = worker.CheckpointArtifact.from_dict(request_artifact)
    raw = worker._reviewed_decoder_artifact(reference, limit=4 * 1024**2)
    value = worker._parse_json(raw)
    fields = {"schema", "request_id", "operation", "heldout_evaluation_purpose", "allow_fictional_fixture",
        "assets", "backend_identity", "source_sha256", "lifecycle_source_sha256", "admission_inputs_sha256", "admission_transport_artifact",
        "source_contexts_artifact", "rows_artifact", "split_manifest_artifact", "exposure_artifact",
        "compiler_commit", "checkpoint_declarations", "max_source_tokens", "max_output_tokens", "max_model_bytes",
        "attempt_directory", "output_directory"}
    if type(value) is not dict or value.get("schema") not in (
            "reviewed-source-evaluation-request/v1", "reviewed-source-evaluation-request/v2",
            "reviewed-source-evaluation-request/v3", "reviewed-source-evaluation-request/v4",
            "reviewed-source-evaluation-request/v5", "reviewed-source-evaluation-request/v6",
            "reviewed-source-evaluation-request/v7", "reviewed-source-evaluation-request/v8", "reviewed-source-evaluation-request/v9", "reviewed-source-evaluation-request/v10", REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA):
        raise ValueError("closed reviewed source evaluation DATA request required")
    rich_context = value["schema"] in ("reviewed-source-evaluation-request/v2", "reviewed-source-evaluation-request/v4", "reviewed-source-evaluation-request/v6", "reviewed-source-evaluation-request/v8", "reviewed-source-evaluation-request/v10")
    mixed_admission = value["schema"] in ("reviewed-source-evaluation-request/v3", "reviewed-source-evaluation-request/v4", "reviewed-source-evaluation-request/v5", "reviewed-source-evaluation-request/v6", "reviewed-source-evaluation-request/v7", "reviewed-source-evaluation-request/v8", "reviewed-source-evaluation-request/v9", "reviewed-source-evaluation-request/v10", REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA)
    explicit_runtime = value["schema"] in ("reviewed-source-evaluation-request/v5", "reviewed-source-evaluation-request/v6", "reviewed-source-evaluation-request/v7", "reviewed-source-evaluation-request/v8", "reviewed-source-evaluation-request/v9", "reviewed-source-evaluation-request/v10", REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA)
    explicit_generation = value["schema"] in ("reviewed-source-evaluation-request/v7", "reviewed-source-evaluation-request/v8", "reviewed-source-evaluation-request/v9", "reviewed-source-evaluation-request/v10", REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA)
    if explicit_generation:
        fields.add("generation_policy")
    if explicit_runtime:
        fields.add("runtime_profile")
    if mixed_admission:
        fields.add("admission_profile")
    if rich_context:
        fields.add("training_context")
    if (set(value) != fields
            or type(value["request_id"]) is not str or not 0 < len(value["request_id"]) <= 128
            or any(character in value["request_id"] for character in "\r\n\0")
            or value["operation"] not in ("hparam_selection", "heldout_evaluation")
            or type(value["allow_fictional_fixture"]) is not bool):
        raise ValueError("closed reviewed source evaluation DATA request required")
    digest_omitted = value["schema"] == REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA
    qwen2 = digest_omitted or value["schema"] in ("reviewed-source-evaluation-request/v9", "reviewed-source-evaluation-request/v10")
    if explicit_generation:
        policy = worker._reviewed_decoder_generation_policy(value["generation_policy"])
        if policy["schema"] != (worker.REVIEWED_DIGEST_OMITTED_GENERATION_POLICY_SCHEMA if digest_omitted else "reviewed-decoder-generation-policy/v2" if qwen2 else "reviewed-decoder-generation-policy/v1"):
            raise ValueError("generation policy version differs from request profile")
    if explicit_runtime and (type(value["runtime_profile"]) is not str or
            value["runtime_profile"] != ("builtin-qwen2-bfloat16/v1" if qwen2 else "builtin-llama-bfloat16/v1")):
        raise ValueError("explicit built-in Llama/BF16 runtime profile required")
    if mixed_admission and (type(value["admission_profile"]) is not str
            or value["admission_profile"] != worker.REVIEWED_MIXED_ADMISSION_PROFILE):
        raise ValueError("explicit mixed-sort admission V3 request profile required")
    identity = value.get("backend_identity")
    if digest_omitted:
        if (type(identity) is not dict or set(identity) != {"backend_id", "implementation_sha256", "checkpoint_format", "target_codec", "source_conditioned", "pretrained"}
                or identity.get("target_codec") != worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC
                or identity.get("checkpoint_format") != "torch-weights-only-digest-omitted-reviewed-state-pair/v1"
                or type(identity.get("backend_id")) is not str
                or re.fullmatch(r"torch-digest-omitted-reviewed-decoder/v1:[0-9a-f]{64}", identity["backend_id"]) is None
                or type(identity.get("implementation_sha256")) is not str
                or re.fullmatch(r"[0-9a-f]{64}", identity["implementation_sha256"]) is None
                or identity.get("source_conditioned") is not True or type(identity.get("pretrained")) is not bool):
            raise ValueError("v11 requires exact digest-omitted backend identity, not an old pair/objective")
    elif type(identity) is dict and identity.get("target_codec") == "complete-reviewed-norm-digest-omitted-json/v1":
        raise ValueError("digest-omitted objective requires explicit v11 request")
    from . import legal_span_consumer_binding as consumer
    heldout = value["operation"] == "heldout_evaluation"
    heldout_purpose = (consumer.REVIEWED_V3_HELDOUT_CONTEXT_PURPOSE if rich_context and mixed_admission else
                       consumer.REVIEWED_HELDOUT_CONTEXT_PURPOSE if rich_context else
                       consumer.REVIEWED_HELDOUT_PURPOSE if heldout else None)
    if (rich_context and not heldout) or value["heldout_evaluation_purpose"] != heldout_purpose:
        raise ValueError("explicit frozen evaluation purpose required; no training relabelling")
    if type(value["lifecycle_source_sha256"]) is not dict:
        raise ValueError("fixed reviewed lifecycle source map required")
    _check_reviewed_evaluation_lifecycle(value)
    asset_names = {"recipe_artifact", "model_config_artifact", "tokenizer_artifact", "license_artifact",
                   "model_checkpoint", "optimizer_checkpoint"}
    if type(value["assets"]) is not dict or set(value["assets"]) != asset_names:
        raise ValueError("six exact local decoder artifact descriptors required")
    for item in (*value["assets"].values(), *(value[name] for name in
            ("admission_transport_artifact", "source_contexts_artifact", "rows_artifact", "split_manifest_artifact", "exposure_artifact"))):
        worker.CheckpointArtifact.from_dict(item)
    if rich_context:
        context = value["training_context"]
        artifacts = ("admission_transport_artifact", "rows_artifact", "exposure_artifact", "retrieval_rows_artifact")
        digests = ("admission_inputs_sha256", "context_inputs_sha256")
        base_context_fields = {"profile", *artifacts, *digests}
        if qwen2:
            base_context_fields.add("context_budget_profile")
            if (type(context) is not dict or type(context.get("context_budget_profile")) is not str or
                    context["context_budget_profile"] not in {worker.REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE,
                        worker.REVIEWED_QWEN2_EXPANDED_CONTEXT_BUDGET_PROFILE} or
                    context["context_budget_profile"] != policy["context_budget_profile"] or
                    context.get("transport") not in ("shared_json_v2", "shared_json_v3")):
                raise ValueError("explicit Qwen2 lossless complete-context budget required")
        shared_transport = (type(context) is dict and "transport" in context)
        if (type(context) is not dict
                or set(context) != (base_context_fields | {"transport"} if shared_transport else base_context_fields)
                or (shared_transport and (not mixed_admission or context["transport"] not in ("shared_json_v1", "shared_json_v2", "shared_json_v3")))
                or context["profile"] != (consumer.REVIEWED_V3_HELDOUT_CONTEXT_PROFILE if mixed_admission
                                          else consumer.REVIEWED_HELDOUT_CONTEXT_PROFILE)
                or any(type(context[name]) is not str or re.fullmatch(r"[0-9a-f]{64}", context[name]) is None
                       for name in digests)
                or context["admission_inputs_sha256"] == value["admission_inputs_sha256"]):
            raise ValueError("closed independently committed TRAIN context required")
        for name in artifacts:
            worker.CheckpointArtifact.from_dict(context[name])
    if (type(value["admission_inputs_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value["admission_inputs_sha256"]) is None
            or type(value["source_sha256"]) is not dict or set(value["source_sha256"]) != worker.REVIEWED_DECODER_SOURCE_NAMES
            or any(type(pin) is not str or re.fullmatch(r"[0-9a-f]{64}", pin) is None for pin in value["source_sha256"].values())):
        raise ValueError("exact source and current admission commitments required")
    if mixed_admission and value["source_sha256"] != worker._reviewed_decoder_source_pins(
            admission_profile=value["admission_profile"]):
        raise ValueError("mixed-sort admission V3 request source map differs")
    if digest_omitted and identity["implementation_sha256"] != value["source_sha256"]["worker"]:
        raise ValueError("v11 backend implementation differs from current worker Source")
    for name, low, high in (("max_source_tokens", 3, 65536), ("max_output_tokens", 2, 65536),
                            ("max_model_bytes", 1, 2*1024**3 if qwen2 else worker.MAX_REVIEWED_DECODER_STATE_BYTES)):
        if type(value[name]) is not int or not low <= value[name] <= high:
            raise ValueError("finite reviewed evaluation limit required: " + name)
    attempt, output = Path(value["attempt_directory"]), Path(value["output_directory"])
    for path in (attempt, output):
        if not path.is_absolute() or path != path.resolve(strict=False):
            raise ValueError("ordinary absolute reviewed attempt/output paths required")
    if not attempt.is_dir() or output.parent != attempt or output == attempt:
        raise ValueError("reviewed output must be a fresh direct child of the existing owned attempt")
    return reference, raw, value


def _execute_reviewed_evaluation_request(request_artifact, *, parent_client):
    """Fixed offline child entry; all effect callbacks cross the original parent."""
    parent_client.execution_guard()
    from . import autoencoder_training_worker as worker
    from ...logic.autoformal import training_cycle_inputs as inputs
    from . import legal_span_consumer_binding as consumer
    reference, request_raw, request = _read_reviewed_evaluation_request(request_artifact)
    if Path(request["output_directory"]).exists():
        raise ValueError("reviewed evaluation output already exists; no replay or retry")

    class ReadOnlyArtifacts:
        def __init__(self):
            self._byte_references = {}
        def bind_transport(self, transport):
            # The authenticated existing v2 transport supplies full references;
            # its registry protocol subsequently offers only {sha256,bytes}.
            # Refuse ambiguous physical paths rather than invent a new lookup.
            if type(transport) is not dict or type(transport.get("byte_leaves")) is not list:
                raise ValueError("complete pinned byte-preserving admission transport required")
            for leaf in transport["byte_leaves"]:
                if type(leaf) is dict and leaf.get("kind") == "artifact_bytes":
                    item = worker.CheckpointArtifact.from_dict(leaf["artifact"])
                    key = (item.sha256, item.bytes)
                    if key in self._byte_references and self._byte_references[key] != item:
                        raise ValueError("ambiguous physical path for pinned admission byte artifact")
                    self._byte_references[key] = item
        def resolve(self, descriptor):
            if type(descriptor) is dict and set(descriptor) == {"sha256", "bytes"}:
                key = (descriptor["sha256"], descriptor["bytes"])
                if key not in self._byte_references:
                    raise ValueError("admission artifact is absent from the authenticated transport")
                return self._byte_references[key]
            return worker.CheckpointArtifact.from_dict(descriptor)
        def artifact_path(self, descriptor):
            return Path(self.resolve(descriptor).path)
        def read_artifact(self, descriptor, *, max_bytes):
            return worker._reviewed_decoder_artifact(self.resolve(descriptor), limit=max_bytes)

    registry = ReadOnlyArtifacts()
    def read_json(descriptor, *, artifact_registry=registry):
        raw = artifact_registry.read_artifact(descriptor, max_bytes=inputs.MAX_REVIEWED_ARTIFACT_BYTES)
        return worker._parse_json(raw)
    def replay_admission(specification, acknowledge, artifact_registry):
        expected = specification["admission_inputs_sha256"]
        acknowledged = acknowledge(expected)
        if acknowledged != expected:
            raise ValueError("original parent current admission digest differs")
        transport = read_json(specification["admission_transport_artifact"], artifact_registry=artifact_registry)
        artifact_registry.bind_transport(transport)
        restored = inputs._reviewed_restore_admission(artifact_registry, transport)
        if consumer.reviewed_admission_inputs_sha256(restored) != acknowledged:
            raise ValueError("pinned local admission transport differs from original parent snapshot")
        return restored
    def current_admission():
        return replay_admission(request, parent_client.current_admission_digest, registry)
    def execution_guard():
        parent_client.execution_guard()
        _check_reviewed_evaluation_lifecycle(request)
        if worker._reviewed_decoder_artifact(reference, limit=4 * 1024**2) != request_raw:
            raise ValueError("reviewed request DATA changed")

    rows, manifest, exposure, contexts = (read_json(request[name]) for name in
        ("rows_artifact", "split_manifest_artifact", "exposure_artifact", "source_contexts_artifact"))
    heldout = request["operation"] == "heldout_evaluation"
    admission = current_admission()
    canonical_sha = lambda value: hashlib.sha256(inputs._reviewed_wire(value)).hexdigest()
    mixed_admission = request["schema"] in ("reviewed-source-evaluation-request/v3", "reviewed-source-evaluation-request/v4", "reviewed-source-evaluation-request/v5", "reviewed-source-evaluation-request/v6", "reviewed-source-evaluation-request/v7", "reviewed-source-evaluation-request/v8", "reviewed-source-evaluation-request/v9", "reviewed-source-evaluation-request/v10", REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA)
    prepare_binding = (consumer.prepare_reviewed_source_span_consumer_binding_v3 if mixed_admission
                       else consumer.prepare_reviewed_source_span_consumer_binding_v2)
    binding = prepare_binding(rows,
        expected_rows_sha256=canonical_sha(rows), split_manifest=manifest,
        expected_split_manifest_sha256=canonical_sha(manifest), admission_inputs=admission,
        expected_admission_inputs_sha256=request["admission_inputs_sha256"], exposure_records=exposure,
        expected_exposure_sha256=canonical_sha(exposure), operation=request["operation"],
        allow_fictional_fixture=request["allow_fictional_fixture"], allow_heldout_evaluation=heldout,
        heldout_evaluation_purpose=request["heldout_evaluation_purpose"])
    if binding.receipt()["status"] != "ready":
        raise ValueError("current reviewed evaluator binding is blocked before model loading")
    context_options = {}
    if "training_context" in request:
        context = request["training_context"]
        training_registry = ReadOnlyArtifacts()

        def current_training_admission():
            return replay_admission(context, parent_client.current_training_admission_digest, training_registry)

        training_rows, training_exposure, retrieval_rows = (read_json(context[name]) for name in
            ("rows_artifact", "exposure_artifact", "retrieval_rows_artifact"))
        training_binding = prepare_binding(training_rows,
            expected_rows_sha256=canonical_sha(training_rows), split_manifest=manifest,
            expected_split_manifest_sha256=canonical_sha(manifest), admission_inputs=current_training_admission(),
            expected_admission_inputs_sha256=context["admission_inputs_sha256"], exposure_records=training_exposure,
            expected_exposure_sha256=canonical_sha(training_exposure), operation="training",
            allow_fictional_fixture=request["allow_fictional_fixture"])
        if training_binding.receipt()["status"] != "ready":
            raise ValueError("current reviewed TRAIN context binding is blocked before model loading")
        query_rows = [{"id": row["id"], "source_text": row["source_text"]} for row in rows]

        def current_context_inputs():
            return {"binding": training_binding, "training_rows": training_rows, "split_manifest": manifest,
                "admission_inputs": current_training_admission(), "exposure_records": training_exposure,
                "query_rows": query_rows, "retrieval_rows": retrieval_rows}

        context_options = {"context_profile": context["profile"], "current_context_inputs_provider": current_context_inputs,
            "expected_context_inputs_sha256": context["context_inputs_sha256"],
            "context_policy_guard": parent_client.context_policy_guard}
        if "transport" in context:
            context_options["context_transport"] = context["transport"]
    execution_guard()
    assets = {name: worker.CheckpointArtifact.from_dict(value) for name, value in request["assets"].items()}
    digest_omitted = request["schema"] == REVIEWED_DIGEST_OMITTED_EVALUATION_REQUEST_SCHEMA
    load_runtime = (worker.load_local_reviewed_decoder_digest_omitted_runtime_v1 if digest_omitted else
                    worker.load_local_reviewed_decoder_runtime_v3 if mixed_admission
                    else worker.load_local_reviewed_decoder_runtime)
    load_options = {"admission_profile": request["admission_profile"]} if mixed_admission else {}
    if "runtime_profile" in request:
        load_options["runtime_profile"] = request["runtime_profile"]
    runtime, load_receipt = load_runtime(registry=registry,
        current_admission_provider=current_admission, execution_guard=execution_guard,
        asset_policy_guard=parent_client.asset_policy_guard, **assets,
        expected_backend_identity=request["backend_identity"], expected_source_sha256=request["source_sha256"],
        expected_admission_inputs_sha256=request["admission_inputs_sha256"], max_model_bytes=request["max_model_bytes"],
        **load_options)
    make_producer = (worker.make_reviewed_decoder_digest_omitted_source_producer_v1 if digest_omitted else
                     worker.make_reviewed_decoder_source_producer_v3 if mixed_admission
                     else worker.make_reviewed_decoder_source_producer)
    generation_options = ({"generation_policy": request["generation_policy"]} if "generation_policy" in request else {})
    producer = make_producer(runtime, binding=binding, rows=rows,
        split_manifest=manifest, exposure_records=exposure, source_contexts=contexts,
        expected_source_contexts_sha256=canonical_sha(contexts),
        expected_admission_inputs_sha256=request["admission_inputs_sha256"],
        backend_identity=request["backend_identity"], assets=tuple(assets[name] for name in
            ("recipe_artifact", "model_config_artifact", "tokenizer_artifact", "license_artifact")),
        model_checkpoint=assets["model_checkpoint"], optimizer_checkpoint=assets["optimizer_checkpoint"],
        max_source_tokens=request["max_source_tokens"], max_output_tokens=request["max_output_tokens"],
        allow_heldout_evaluation=heldout, **context_options, **generation_options)
    artifact = producer.evaluate(compiler_commit=request["compiler_commit"],
                                 checkpoint_declarations=request["checkpoint_declarations"])
    execution_guard()
    directory = Path(request["output_directory"])
    directory.mkdir(mode=0o700)
    output_artifacts = {}
    for name, value in (("evaluation.json", artifact.to_dict()), ("loader.json", load_receipt),
                        ("generation.json", producer.observation())):
        raw = worker._json_bytes(value)
        if len(raw) > REVIEWED_EVALUATION_OUTPUT_LIMIT:
            raise ValueError("reviewed output artifact exceeds fixed byte bound")
        output_artifacts[name.removesuffix(".json")] = worker._write_exclusive(directory / name, raw)
    cycle = {"schema": "reviewed-source-evaluation-cycle/v1", "request_sha256": reference.sha256,
        "completed": True, "execution_path": "inference", "input_count": len(rows), "training": None,
        "training_executed": False, "weight_publications": [], "admitted": False,
        "inference": {"profile": request["schema"], "evaluation": str(directory / "evaluation.json"),
            "loader": str(directory / "loader.json"), "generation": str(directory / "generation.json")},
        "output_artifacts": output_artifacts,
        "current_admission_sha256": request["admission_inputs_sha256"],
        "model_quality_qualified": False, "legal_meaning_verified": False, "proof_authority": False,
        "convergence_proved": False, "corpus_admitted": False, "parent_channel": parent_client.observation()}
    if context_options:
        cycle.update(current_training_admission_sha256=context["admission_inputs_sha256"],
                     context_inputs_sha256=context["context_inputs_sha256"])
    execution_guard()
    worker._write_exclusive(directory / "cycle.json", worker._json_bytes(cycle))
    return cycle


def run_reviewed_source_inference_cycle(config, cli, *, owner, source_guard, asset_policy_guard,
        current_admission_provider, deadline_monotonic, current_training_admission_provider=None,
        context_policy_guard=None, typed_structure_profile=None, candidate_syntax_profile=None):
    """One original-owner child, with live parent callbacks and no new grant."""
    import math
    import os
    import select
    import socket
    import subprocess
    import sys
    import time
    from . import autoencoder_campaign_process as processes
    from .autoencoder_daemon_resources import DaemonResourceReservation, _process, _group_usage
    from .autoencoder_daemon_invocation import _terminate
    from .autoencoder_daemon_invocation_contracts import describe, execution_environment, verify
    if (config.get("execution_mode") != "inference" or not isinstance(owner, DaemonResourceReservation)
            or not getattr(owner, "_entered", False) or getattr(owner, "_owner_pid", None) != os.getpid()
            or any(not callable(value) for value in (source_guard, asset_policy_guard, current_admission_provider))
            or type(deadline_monotonic) not in (int, float) or not math.isfinite(deadline_monotonic)
            or time.monotonic() >= deadline_monotonic):
        raise ValueError("original already-admitted reviewed parent runtime and remaining deadline required")
    if any(config.get(name) for name in ("input_jsonl", "validation_jsonl", "repository_id", "publish_repository",
                                        "arrow_feature_weights", "shared_targets", "feature_input_manifest")):
        raise ValueError("reviewed evaluation request cannot mix legacy inputs, training or publication")
    _validate_parent_typed_structure_profile(typed_structure_profile)
    audit_source_pins = None if typed_structure_profile is None else _parent_typed_structure_source_pins()
    _validate_parent_candidate_syntax_profile(candidate_syntax_profile)
    candidate_source_pins = (None if candidate_syntax_profile is None else _parent_candidate_syntax_source_pins())
    source_guard()
    reference, raw, request = _read_reviewed_evaluation_request(config["reviewed_evaluation_request"])
    checked_asset_policy = asset_policy_guard
    if "generation_policy" in request:
        def checked_asset_policy(policy):
            _check_reviewed_generation_policy(request, policy)
            decision = asset_policy_guard(policy)
            _check_reviewed_generation_policy(request, policy)
            return decision
    context = request.get("training_context")
    context_callbacks = {}
    last_context_policy = None
    if context is not None:
        if not callable(current_training_admission_provider) or not callable(context_policy_guard):
            raise ValueError("rich heldout context requires both live original parent callbacks")

        def authorize_context(policy):
            nonlocal last_context_policy
            if (policy.get("context_profile") != context["profile"]
                    or policy.get("operation") != "heldout_evaluation"
                    or policy.get("context_inputs_sha256") != context["context_inputs_sha256"]
                    or policy.get("training_admission_inputs_sha256") != context["admission_inputs_sha256"]
                    or policy.get("training_requested") is not False or policy.get("heldout_requested") is not True):
                raise ValueError("context policy differs from the pinned rich heldout request")
            _check_reviewed_context_transport_policy(context, policy)
            snapshot = json.dumps(policy, sort_keys=True, separators=(",", ":"), allow_nan=False)
            decision = context_policy_guard(policy)
            if decision is None:
                last_context_policy = snapshot
            return decision

        context_callbacks = {"current_training_admission_provider": current_training_admission_provider,
            "context_policy_guard": authorize_context}
    original_source_guard = source_guard
    def source_guard():
        original_source_guard()
        _check_reviewed_evaluation_lifecycle(request)
        if audit_source_pins is not None and _parent_typed_structure_source_pins() != audit_source_pins:
            raise ValueError("parent typed-structure audit implementation changed")
        if candidate_source_pins is not None and _parent_candidate_syntax_source_pins() != candidate_source_pins:
            raise ValueError("parent candidate-syntax audit implementation changed")
    source_guard()
    python_dependency_prefix = sys.prefix
    from . import autoencoder_campaign_process_worker as bootstrap_protocol
    if Path(bootstrap_protocol.__file__).resolve() != processes.WORKER_SCRIPT.resolve():
        raise ValueError("fixed reviewed dependency bootstrap source differs")
    python_dependency_paths = list(bootstrap_protocol._reviewed_dependency_paths(python_dependency_prefix))
    dependency_paths_raw = json.dumps(python_dependency_paths, ensure_ascii=True, separators=(",", ":"))
    child_environment = execution_environment()
    child_environment.update(IPFS_AUTO_INSTALL="false", IPFS_DATASETS_AUTO_INSTALL="0",
        IPFS_KIT_AUTO_INSTALL_DEPS="0", IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS="0",
        IPFS_DATASETS_RUN_NATIVE_LEAN="0", TOKENIZERS_PARALLELISM="false",
        PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    attempt = Path(request["attempt_directory"])
    if Path(config["state_directory"]) != attempt or Path(request["output_directory"]).exists():
        raise ValueError("configured reviewed state must be the existing owned attempt with fresh outputs")
    owner.check_usage(attempt_directory=attempt)
    original_parent = _process(os.getpid())
    if original_parent is None:
        raise ValueError("original reviewed parent process identity unavailable")
    owner_identity = {key: original_parent[key] for key in ("pid", "birth")}
    bootstrap = describe(processes.WORKER_SCRIPT, 1024 * 1024)
    network = describe(processes.NETWORK_SCRIPT, 1024 * 1024)
    ready_read, ready_write = os.pipe()
    release_read, release_write = os.pipe()
    guard_parent, guard_child = socket.socketpair()
    process = server = child_identity = None
    callback_fd = None
    released = waited = False
    started = time.monotonic()
    try:
        with (attempt / "reviewed-worker.log").open("xb") as log:
            source_guard()
            verify(bootstrap, 1024 * 1024)
            verify(network, 1024 * 1024)
            process = subprocess.Popen([sys.executable, "-I", "-S", "-B", str(processes.WORKER_SCRIPT),
                "--reviewed-source-evaluation", reference.path, reference.sha256, str(reference.bytes),
                str(ready_write), str(release_read), str(guard_child.fileno()), str(owner_identity["pid"]),
                str(owner_identity["birth"]), repr(deadline_monotonic), network["sha256"], python_dependency_prefix, dependency_paths_raw],
                cwd=attempt, env=child_environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, pass_fds=(ready_write, release_read, guard_child.fileno()))
            os.close(ready_write)
            ready_write = None
            os.close(release_read)
            release_read = None
            guard_child.close()
            observed = _process(process.pid)
            if observed is None or observed["parent_pid"] != os.getpid() or observed["group_pid"] != process.pid:
                raise ValueError("reviewed child must be the original isolated Popen group")
            child_identity = {key: observed[key] for key in ("pid", "birth")}
            if callable(getattr(owner, "attach_child", None)):
                owner.attach_child(process.pid)
            owner.check_usage(attempt_directory=attempt, child_pid=process.pid)
            ready = b""
            while not ready.endswith(b"\n"):
                source_guard()
                if time.monotonic() >= deadline_monotonic or process.poll() is not None:
                    raise ValueError("reviewed child did not reach the original bounded READY barrier")
                readable, _, _ = select.select([ready_read], [], [], min(.1, deadline_monotonic - time.monotonic()))
                if readable:
                    block = os.read(ready_read, processes.MAX_READY_BYTES + 1 - len(ready))
                    if not block:
                        raise ValueError("reviewed READY pipe closed before release")
                    ready += block
                    if len(ready) > processes.MAX_READY_BYTES or ready.count(b"\n") > 1:
                        raise ValueError("reviewed READY frame exceeds fixed bound")
            message = json.loads(ready)
            expected_fields = {"schema", "identity", "owner_pid", "owner_birth", "request_sha256", "canonical_root", "network_guard", "python_dependency_prefix", "python_dependency_paths"}
            if (type(message) is not dict or set(message) != expected_fields
                    or message["schema"] != "reviewed-source-evaluation-ready/v1"
                    or message["identity"] != {**child_identity, "group_pid": process.pid}
                    or message["owner_pid"] != owner_identity["pid"] or str(message["owner_birth"]) != str(owner_identity["birth"])
                    or message["request_sha256"] != reference.sha256
                    or message["canonical_root"] != str(processes.WORKER_SCRIPT.resolve().parents[3])
                    or message["python_dependency_prefix"] != python_dependency_prefix
                    or message["python_dependency_paths"] != python_dependency_paths
                    or message["network_guard"] != {"mechanism": "linux_seccomp", "denied_syscalls":
                        ["socket", "connect", "sendto", "sendmsg", "sendmmsg"], "socket_denial_verified": True}):
                raise ValueError("reviewed original child READY/source/offline identity differs")
            source_guard()
            callback_fd = guard_parent.detach()
            server = processes._ReviewedParentCallbackServer(callback_fd, owner=owner,
                child_identity=child_identity, owner_identity=owner_identity, request_sha256=reference.sha256,
                deadline=deadline_monotonic, source_guard=source_guard, asset_policy_guard=checked_asset_policy,
                current_admission_provider=current_admission_provider, **context_callbacks)
            if os.write(release_write, b"RUN\n") != 4:
                raise ValueError("original reviewed child RUN release incomplete")
            released = True
            next_parent_guard = time.monotonic()
            while process.poll() is None:
                now = time.monotonic()
                if now >= deadline_monotonic:
                    raise TimeoutError("reviewed evaluation exceeded the original parent deadline")
                source_guard()
                # A hung child cannot postpone observing cancellation by
                # withholding RPC requests. This is the same original owner,
                # not a new lease or global census at each callback/step.
                if now >= next_parent_guard:
                    server._guard_parent()
                    next_parent_guard = now + .25
                if not server.finished:
                    server.poll()
                time.sleep(.01)
            returncode = process.wait()
            waited = True
            if returncode != 0:
                raise RuntimeError("reviewed evaluation child failed with exit " + str(returncode))
            if not server.finished:
                raise ValueError("reviewed child exited without original-parent FINISH acknowledgement")
            if _group_usage(child_identity)["live_processes"]:
                raise ValueError("reviewed child returned with live descendants")
            source_guard()
            owner.check_usage(attempt_directory=attempt)
            from . import autoencoder_training_worker as worker
            cycle_path = Path(request["output_directory"]) / "cycle.json"
            cycle_reference = worker.CheckpointArtifact(str(cycle_path), cli._sha(cycle_path), cycle_path.stat().st_size)
            cycle = worker._parse_json(worker._reviewed_decoder_artifact(cycle_reference, limit=32 * 1024**2))
            if (cycle.get("schema") != "reviewed-source-evaluation-cycle/v1" or cycle.get("request_sha256") != reference.sha256
                    or cycle.get("completed") is not True or cycle.get("execution_path") != "inference"
                    or cycle.get("training_executed") is not False or cycle.get("weight_publications") != []
                    or any(cycle.get(flag) is not False for flag in ("admitted", "model_quality_qualified",
                        "legal_meaning_verified", "proof_authority", "convergence_proved", "corpus_admitted"))):
                raise ValueError("reviewed child cycle receipt differs from original request")
            if context is not None and (cycle.get("current_training_admission_sha256") != context["admission_inputs_sha256"]
                    or cycle.get("context_inputs_sha256") != context["context_inputs_sha256"]):
                raise ValueError("reviewed child TRAIN context receipt differs from original request")
            audit_wire = candidate_audit_wire = None
            if audit_source_pins is not None or candidate_source_pins is not None:
                _check_reviewed_evaluation_outputs(cycle, request)
                server._guard_parent()
                if audit_source_pins is not None:
                    audit = _build_parent_typed_structure_audit(cycle, request, cycle_reference, reference.sha256,
                        worker._parse_json(worker._json_bytes(audit_source_pins)))
                    audit_wire = worker._json_bytes(audit)
                if candidate_source_pins is not None:
                    audit = _build_parent_candidate_syntax_audit(cycle, request, cycle_reference, reference.sha256,
                        worker._parse_json(worker._json_bytes(candidate_source_pins)), candidate_syntax_profile)
                    candidate_audit_wire = worker._json_bytes(audit)
                wires = [wire for wire in (audit_wire, candidate_audit_wire) if wire is not None]
                usage = owner.check_usage(attempt_directory=attempt)
                _check_parent_audit_storage(usage, wires)
                server._guard_parent()
            # Historical child output cannot substitute for a fresh mapping
            # supplied by the original parent after writes/FINISH/actual wait.
            # No timestamp is refreshed and no global registry-head claim made.
            from . import legal_span_consumer_binding as consumer
            server._guard_parent()
            if context is not None and (last_context_policy is None
                    or context_policy_guard(json.loads(last_context_policy)) is not None):
                raise ValueError("fresh original TRAIN context policy acknowledgement required after child completion")
            final_admission = current_admission_provider()
            if consumer.reviewed_admission_inputs_sha256(final_admission) != request["admission_inputs_sha256"]:
                raise ValueError("current original parent admission changed after child completion")
            if context is not None:
                final_training_admission = current_training_admission_provider()
                if consumer.reviewed_admission_inputs_sha256(final_training_admission) != context["admission_inputs_sha256"]:
                    raise ValueError("current original parent TRAIN admission changed after child completion")
            server._guard_parent()
            callbacks = server.observation()
            if callbacks.get("finished") is not True or callbacks.get("closed") is not True:
                raise ValueError("original reviewed FINISH callback channel did not close normally")
            # No caller-owned callback may run between the final byte checks
            # and writing the parent receipt. Recheck the child receipt too:
            # a final admission/source callback can otherwise replace it.
            _check_reviewed_evaluation_outputs(cycle, request)
            worker._reviewed_decoder_artifact(cycle_reference, limit=REVIEWED_EVALUATION_OUTPUT_LIMIT, load=False)
            audit_reference = candidate_audit_reference = None
            if audit_wire is not None or candidate_audit_wire is not None:
                _check_parent_audit_inputs(request, reference, candidate=candidate_audit_wire is not None)
            if audit_wire is not None:
                audit_path = Path(request["output_directory"]) / "typed-structure-audit.json"
                worker._write_exclusive(audit_path, audit_wire)
                audit_reference = dict(path=str(audit_path), sha256=worker._digest(audit_wire), bytes=len(audit_wire))
                worker._reviewed_decoder_artifact(worker.CheckpointArtifact.from_dict(audit_reference),
                    limit=REVIEWED_EVALUATION_OUTPUT_LIMIT, load=False)
            if candidate_audit_wire is not None:
                audit_path = Path(request["output_directory"]) / "candidate-syntax-audit.json"
                worker._write_exclusive(audit_path, candidate_audit_wire)
                candidate_audit_reference = dict(path=str(audit_path),
                    sha256=worker._digest(candidate_audit_wire), bytes=len(candidate_audit_wire))
                worker._reviewed_decoder_artifact(worker.CheckpointArtifact.from_dict(candidate_audit_reference),
                    limit=REVIEWED_EVALUATION_OUTPUT_LIMIT, load=False)
            parent_path = Path(request["output_directory"]) / "parent-cycle.json"
            report = {**cycle, "schema": "reviewed-source-evaluation-parent/v1", "completed": True,
                "receipt": str(cycle_path), "child_cycle_artifact": {"path": cycle_reference.path,
                    "sha256": cycle_reference.sha256, "bytes": cycle_reference.bytes},
                "parent_receipt": str(parent_path), "original_owner_reservation_id": owner.reservation_id,
                "python_dependency_prefix": python_dependency_prefix, "python_dependency_paths": python_dependency_paths,
                "original_child_waited": True, "original_child_identity": child_identity,
                "parent_callbacks": callbacks, "parent_FINISH_acknowledged": True,
                "parent_current_admission_rechecked_after_wait": True,
                "parent_output_artifacts_rechecked_after_wait": True,
                "elapsed_seconds": time.monotonic() - started, "resource_release_performed": False}
            if audit_reference is not None:
                report.update(schema="reviewed-source-evaluation-parent/v2",
                    typed_structure_profile=typed_structure_profile, typed_structure_audit_artifact=audit_reference,
                    parent_typed_structure_audit_after_wait=True, parent_current_admission_rechecked_after_audit=True)
            if candidate_audit_reference is not None:
                report.update(schema="reviewed-source-evaluation-parent/v3",
                    candidate_syntax_profile=candidate_syntax_profile,
                    candidate_syntax_audit_artifact=candidate_audit_reference,
                    parent_candidate_syntax_audit_after_wait=True,
                    parent_current_admission_rechecked_after_candidate_audit=True)
            if context is not None:
                report.update(parent_current_training_admission_rechecked_after_wait=True,
                              parent_context_policy_rechecked_after_wait=True)
            worker._write_exclusive(parent_path, worker._json_bytes(report))
            directory_fd = os.open(parent_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return report
    finally:
        if process is not None and (not waited or child_identity is not None and _group_usage(child_identity)["live_processes"]):
            _terminate(process, child_identity)
            process.wait()
        if server is not None:
            server.close()
        elif callback_fd is not None:
            os.close(callback_fd)
        for descriptor in (ready_read, ready_write, release_read, release_write):
            if descriptor is not None:
                os.close(descriptor)
        guard_parent.close()
        guard_child.close()


def _check_reviewed_context_transport_policy(context, policy):
    """Bind shared DATA encoding/expansion to the independently pinned request.

    The original parent still decides whether the complete policy is permitted;
    this check never supplies that decision or replaces current review replay.
    """
    if type(context) is not dict or type(policy) is not dict:
        raise ValueError("ordinary context transport policy mappings required")
    if "transport" in context:
        from ...logic.autoformal import training_cycle_inputs as inputs
        from . import autoencoder_training_worker as worker
        qwen2 = "context_budget_profile" in context
        if (qwen2 and (type(context["context_budget_profile"]) is not str or
                       context["context_budget_profile"] not in {worker.REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE,
                           worker.REVIEWED_QWEN2_EXPANDED_CONTEXT_BUDGET_PROFILE} or
                       context["transport"] not in ("shared_json_v2", "shared_json_v3") or
                       policy.get("context_budget_profile") != context["context_budget_profile"])):
            raise ValueError("Qwen2 context budget differs from the pinned request")
        if not qwen2 and "context_budget_profile" in policy:
            raise ValueError("context budget requires explicit request opt-in")
        if (context["transport"] not in ("shared_json_v1", "shared_json_v2", "shared_json_v3")
                or policy.get("schema") != ("reviewed-decoder-rich-context-use-policy/v3" if qwen2 else "reviewed-decoder-rich-context-use-policy/v2")
                or policy.get("context_transport") != context["transport"]
                or policy.get("max_expanded_context_bytes") != inputs.REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES
                or type(policy.get("max_expanded_context_bytes")) is not int
                or policy.get("shared_context_schema") != (inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V3
                    if context["transport"] == "shared_json_v3" else inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2
                    if context["transport"] == "shared_json_v2" else inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA)
                or policy.get("max_context_bytes") != worker.REVIEWED_GENERATION_CONTEXT_MAX_BYTES
                or type(policy.get("max_context_bytes")) is not int
                or policy.get("max_context_tokens") != (worker.REVIEWED_QWEN2_EXPANDED_CONTEXT_MAX_TOKENS
                    if qwen2 and context["context_budget_profile"] == worker.REVIEWED_QWEN2_EXPANDED_CONTEXT_BUDGET_PROFILE
                    else worker.REVIEWED_QWEN2_CONTEXT_MAX_TOKENS if qwen2 else worker.REVIEWED_GENERATION_CONTEXT_MAX_TOKENS)
                or type(policy.get("max_context_tokens")) is not int):
            raise ValueError("shared context transport policy differs from the pinned request")
    elif any(name in policy for name in ("context_transport", "max_expanded_context_bytes", "shared_context_schema")):
        raise ValueError("shared context transport requires explicit request opt-in")



def _check_digest_omitted_loader_output(loader, request):
    """Check the selected loader's saved DATA, never infer asset authority."""
    from . import autoencoder_training_worker as worker
    asset_names = ("recipe_artifact", "model_config_artifact", "tokenizer_artifact", "license_artifact", "model_checkpoint", "optimizer_checkpoint")
    expected = {"schema": "reviewed-local-digest-omitted-decoder-runtime-load/v1",
        "target_codec": worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC,
        "expected_backend_identity": request["backend_identity"], "loaded_backend_identity": request["backend_identity"],
        "producer_pins": request["source_sha256"], "artifacts": [request["assets"][name] for name in asset_names],
        "runtime_profile": request["runtime_profile"], "device": "cpu", "dtype": "bfloat16",
        "checkpoint_restored": True, "matched_pair": True, "load_performed": True, "restore_performed": True,
        "training_performed": False, "downloads_performed": False, "resource_granted": False,
        "automatic_old_source_checkpoint_migration": False, "old_objective_checkpoint_migration_performed": False,
        "license_bytes_are_permission": False, "pretrained_quality_verified": False, "legal_meaning_verified": False,
        "proof_authority": False, "convergence_proved": False, "corpus_admitted": False}
    if (type(loader) is not dict or not set(expected) <= set(loader)
            or worker._json_bytes({key: loader[key] for key in expected}) != worker._json_bytes(expected)
            or type(loader.get("optimizer_steps")) is not int or not 0 <= loader["optimizer_steps"] <= 10**9
            or ("explicit_source_epoch_migration_performed" in loader and loader["explicit_source_epoch_migration_performed"] is not False)):
        raise ValueError("v11 saved loader identity, pair or scope differs")


def _check_digest_omitted_generation_outputs(generation, request):
    """Verify saved raw/derived pairs without changing either observed value.

    This is a post-generation consistency check of this execution's bytes, not
    producer authenticity before the first observation or semantic authority.
    It never decodes tokens, supplies reference facts, or resolves dependencies.
    """
    from . import autoencoder_training_worker as worker
    from ...logic.autoformal import training_cycle_inputs as inputs

    def need(ok, message):
        if not ok:
            raise ValueError(message)

    need(type(generation) is dict, "v11 saved generation mapping required")
    call = generation.get("last_call")
    need(type(call) is dict, "v11 saved generation call required")
    raw, outputs, derived = (call.get(name) for name in ("raw_generation_outputs", "producer_outputs", "output_derivation"))
    need(type(raw) is list and 0 < len(raw) and type(outputs) is list and type(derived) is list
         and len(raw) == len(outputs) == len(derived), "v11 exact saved output population required")
    contexts = worker._parse_json(worker._reviewed_decoder_artifact(
        worker.CheckpointArtifact.from_dict(request["source_contexts_artifact"]), limit=4 * 1024**2))
    need(type(contexts) is dict and type(contexts.get("rows")) is list and contexts["rows"]
         and all(type(row) is dict and type(row.get("id")) is str and row["id"]
                 and type(row.get("unit_id")) is str and row["unit_id"] for row in contexts["rows"]),
         "v11 ordered source population with id/unit_id required")
    expected = [(row["id"], row["unit_id"]) for row in contexts["rows"]]
    need(len({item[0] for item in expected}) == len(expected) and len(raw) == len(expected),
         "v11 saved output population differs from ordered source context")
    seen = set()
    for pair, item, output, proof in zip(expected, raw, outputs, derived, strict=True):
        need(type(item) is dict and set(item) == {"id", "unit_id", "outcome", "candidate", "generated_token_ids", "generated_text", "reason"}
             and type(output) is dict and set(output) == {"id", "outcome", "candidate"}
             and type(proof) is dict and set(proof) == {"id", "raw_model_text_sha256", "assembled_full_target_sha256", "outcome", "computed_field", "other_fields_repaired"},
             "v11 closed raw/assembled/derivation rows required")
        need(type(item["id"]) is str and item["id"] and item["id"] not in seen
             and type(item["unit_id"]) is str and item["unit_id"], "v11 unique saved output identities required")
        need((item["id"], item["unit_id"]) == pair,
             "v11 saved output order or id/unit_id differs from ordered source context")
        seen.add(item["id"])
        need(type(item["outcome"]) is str and item["outcome"] in {"complete", "abstained", "incomplete", "invalid"}
             and proof["id"] == output["id"] == item["id"] and proof["outcome"] == output["outcome"] == item["outcome"],
             "v11 saved disposition or identity differs")
        tokens, text = item["generated_token_ids"], item["generated_text"]
        need(type(tokens) is list and 1 <= len(tokens) <= request["max_output_tokens"]
             and all(type(token) is int and 0 <= token < 2**31 for token in tokens)
             and (text is None or type(text) is str), "v11 exact raw token/text evidence required")
        need(proof["computed_field"] == "typed_expression.content_digest" and proof["other_fields_repaired"] is False
             and proof["raw_model_text_sha256"] == (None if text is None else worker._digest(text.encode("utf-8"))),
             "v11 raw text or derivation commitment differs")
        need(inputs._reviewed_wire(output["candidate"]) == inputs._reviewed_wire(item["candidate"]),
             "v11 producer candidate differs from saved generation")
        if item["outcome"] == "complete":
            need(type(text) is str and type(item["candidate"]) is dict and item["reason"] is None,
                 "v11 complete output requires exact raw body and full candidate")
            assembled = inputs.assemble_reviewed_decoder_digest_omitted_target(text,
                target_codec=worker.REVIEWED_DIGEST_OMITTED_TARGET_CODEC)
            need(inputs._reviewed_wire(assembled) == inputs._reviewed_wire(item["candidate"]),
                 "v11 saved candidate differs from strict raw-wire assembly")
            expected = worker._digest(inputs._reviewed_wire(item["candidate"]))
        else:
            need(item["candidate"] is None and type(item["reason"]) is str and item["reason"],
                 "v11 noncomplete output must retain its absent candidate and reason")
            expected = None
        need(proof["assembled_full_target_sha256"] == expected, "v11 assembled candidate commitment differs")
