"""Optional source-bound Intent advice before goal decomposition.

The prompt adapter declares that the user intends the supplied text. It does
not understand that text's executable meaning. An explicitly selected shared
feature checkpoint may reconstruct those compiler features, but cannot mint
formulas or authorize actions. Missing, untrained, and incompatible models
leave the existing planner available with the exact original instruction.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


SCHEMA = "intent-instruction-preplanning/v1"
CHECKPOINT_SCHEMA = "intent-projection-feature-checkpoint/v1"
MAX_CHECKPOINT_BYTES = 32 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_INSTRUCTION_CHARS = 65_536
AUTHORITY = {"authority": "unverified_candidate_only", "proof_authority": False,
             "execution_authority": False, "completion_authority": False,
             "omission_authority": False, "combination_semantics_verified": False}
_DOMAINS = {"security_ir", "legal_ir", "ui_ux_ir"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_STATUSES = {"fail_open_no_checkpoint", "fail_open_untrained_checkpoint",
             "fail_open_checkpoint_error", "feature_advice", "fail_open_source_policy",
             "fail_open_frontend_error"}


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _adapter_sha256():
    """Pin executable local producers, not a self-reported dataset adapter."""
    from ...formalization.autoencoder import domain_targets
    from .. import canonicalize, schema
    from ..source_adapters import prompt
    from . import compiler, decompiler, typed_compiler

    modules = (domain_targets, canonicalize, schema, prompt, compiler, decompiler, typed_compiler)
    sources = {module.__name__: _sha(Path(module.__file__).read_bytes()) for module in modules}
    sources[__name__] = _sha(Path(__file__).read_bytes())
    return _sha(_raw(sources))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate Intent checkpoint key")
        result[key] = value
    return result


def _constraints(refs):
    if type(refs) not in (tuple, list) or len(refs) > 64:
        raise ValueError("bounded constraint references required")
    result = []
    for row in refs:
        if (type(row) is not dict or set(row) != {"domain", "ref_id", "sha256"}
                or row["domain"] not in _DOMAINS
                or type(row["ref_id"]) is not str or not 0 < len(row["ref_id"]) <= 512
                or any(ord(char) < 32 for char in row["ref_id"])
                or type(row["sha256"]) is not str or not _SHA.fullmatch(row["sha256"])):
            raise ValueError("closed source-bound domain constraint reference required")
        result.append(dict(row))
    if len({_raw(row) for row in result}) != len(result):
        raise ValueError("duplicate constraint reference")
    return result


def prepare_instruction_targets(instruction: str):
    """Native deterministic declaration targets; never learned NL semantics.

    Outer whitespace is trimmed only to satisfy the existing adapter's record
    contract. The preplanning report independently binds the original bytes.
    """
    from ...formalization.autoencoder.domain_targets import prepare_intent_targets
    from ..source_adapters.prompt import PromptIntentAdapter

    if type(instruction) is not str or not instruction.strip() or len(instruction) > MAX_INSTRUCTION_CHARS:
        raise ValueError("bounded nonempty instruction required")
    adapter = PromptIntentAdapter(max_text_chars=MAX_INSTRUCTION_CHARS)
    record = adapter.make_record(instruction.strip(), source_uri="instruction:preplanning",
                                 source_revision=_sha(instruction.encode("utf-8")))
    return prepare_intent_targets(adapter.adapt(record))


def prepare_instruction_feature_targets(instruction: str):
    """Explicit structural subset with the complete semantic frontier retained.

    This constructs a new envelope. It never edits the native target's failed
    whole-document readiness or supplies a predicate for opaque natural text.
    """
    from ...formalization.autoencoder.domain_targets import build_target_envelope

    native = prepare_instruction_targets(instruction)
    wire = native.to_dict()
    allowed = {"intent-route/action-hoare/v1", "intent-route/facts/v1", "intent-route/workflow-temporal/v1"}
    selected = [row for row in wire["projections"] if row["projection_id"] in allowed]
    # A second independent native compilation must reproduce exact structured
    # rows before they enter the scoped training envelope.
    replay = prepare_instruction_targets(instruction).to_dict()
    replay_selected = [row for row in replay["projections"] if row["projection_id"] in allowed]
    if _raw(selected) != _raw(replay_selected) or not selected:
        raise ValueError("native structural projection replay differs")
    scope = {"producer": "intent-preplanning-structural-subset/v1", "status": "structural_only",
             "source_digest": native.source_digest, "native_target_sha256": native.digest,
             "selected_projection_ids": [row["projection_id"] for row in selected],
             "selected_projections_sha256": _sha(_raw(selected)),
             "native_ready_for_training": wire["ready_for_training"],
             "native_unsupported": wire["unsupported"],
             "native_validation": wire["validation"],
             "native_qualification_gaps": wire["qualification_gaps"],
             "omitted_projection_ids": [row["projection_id"] for row in wire["projections"]
                                        if row["projection_id"] not in allowed],
             "instruction_semantics_verified": False}
    return build_target_envelope(domain_id="intent_ir", source_digest=native.source_digest,
        projections=selected, validation=[{"validator_id": "intent_ir.scoped_structural_projection_replay",
            "status": "passed", "details": {key: scope[key] for key in
                ("producer", "status", "source_digest", "native_target_sha256",
                 "selected_projection_ids", "selected_projections_sha256")}}],
        qualification_gaps=["structural_prompt_wrapper_only_not_goal_semantics", scope])


def intent_code_logic_profile():
    """Use existing typed routes; backend names are possibilities, not runs."""
    from .typed_compiler import resolve_intent_route
    from ...families.registry import DEFAULT_REGISTRY
    from ...families.namespaces import BASELINE_NAMESPACES, NamespaceKind

    # These are registered model families/profiles. Registration alone does
    # not mean a prompt supplies the state/heap/trace model they need.
    for family in ("transition_system", "separation_logic", "hyperproperty"):
        if family not in DEFAULT_REGISTRY.families:
            raise ValueError("code intent family is no longer registered")
    for profile in ("tla_plus", "hyperltl"):
        BASELINE_NAMESPACES.get(NamespaceKind.PROFILE, profile)

    purposes = {
        "facts": "typed symbols and predicates",
        "intentions": "agent goals and intended outcomes",
        "norms": "obligations, permissions and prohibitions",
        "action_hoare": "code preconditions and postconditions",
        "workflows": "ordering and temporal transitions",
        "tool_permissions": "grounded tool and resource authorization",
        "safety": "state invariants",
        "liveness": "progress and termination obligations",
        "verification_condition": "obligations to be discharged by independent evidence",
    }
    routes = []
    for label, purpose in purposes.items():
        route = resolve_intent_route(label)
        routes.append({"route_id": route.route_id, "family_id": route.family_id or None,
                       "profile_id": route.profile_id or None, "property_id": route.property_id or None,
                       "view_role_id": route.view_role_id or None, "purpose": purpose,
                       "candidate_backend_ids": list(route.backend_ids), "backend_executed": False})
    return {"schema": "intent-code-logic-profile/v1", "routes": routes,
            "additional_model_requirements": [
                {"family_id": "transition_system", "profile_id": "tla_plus",
                 "requires": "explicit state variables, initial states, transitions and fairness"},
                {"family_id": "separation_logic", "profile_id": None,
                 "requires": "typed heap ownership and frame conditions"},
                {"family_id": "hyperproperty", "profile_id": "hyperltl",
                 "requires": "explicit multi-trace information-flow policy and trace semantics"}],
            "cross_domain_join_requires": ["shared symbol bindings", "compatible state and time semantics",
                                           "source-bound domain contracts", "independent proof receipts"],
            "combination_semantics_verified": False}


def load_intent_feature_checkpoint(descriptor: dict):
    """Load one pinned inert shared candidate; no training, imports from data or downloads."""
    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as shared
    from ....optimizers.logic_theorem_optimizer.autoencoder_modality_contracts import ModalityContract

    if (type(descriptor) is not dict or set(descriptor) != {"schema", "path", "sha256"}
            or descriptor["schema"] != CHECKPOINT_SCHEMA or type(descriptor["path"]) is not str
            or type(descriptor["sha256"]) is not str or not _SHA.fullmatch(descriptor["sha256"])):
        raise ValueError("closed Intent checkpoint descriptor required")
    path = Path(descriptor["path"])
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("canonical local checkpoint path required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_CHECKPOINT_BYTES:
            raise ValueError("bounded regular checkpoint required")
        raw = stream.read(MAX_CHECKPOINT_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (len(raw) > MAX_CHECKPOINT_BYTES or _sha(raw) != descriptor["sha256"]
            or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
        raise ValueError("Intent checkpoint bytes differ")
    def nonfinite(_):
        raise ValueError("nonfinite checkpoint number")
    payload = json.loads(raw, object_pairs_hook=_unique, parse_constant=nonfinite)
    if type(payload) is not dict or set(payload) != {"contract", "feature_space", "state", "report"}:
        raise ValueError("shared feature candidate package required")
    contract = ModalityContract.from_dict(payload["contract"])
    if contract.domain != "intent_ir" or contract.adapter.sha256 != _adapter_sha256():
        raise ValueError("Intent checkpoint domain or installed adapter differs")
    shared._contract(contract, payload["feature_space"])
    shared._validate_state(contract, payload["feature_space"], payload["state"])
    report = payload["report"]
    if (type(report) is not dict or report.get("contract_sha256") != contract.sha256
            or report.get("feature_space_sha256") != shared.digest(payload["feature_space"])
            or any(report.get(key) is not False for key in shared.FALSE)):
        raise ValueError("Intent training evidence differs from candidate")
    return {"contract": contract, "feature_space": payload["feature_space"],
            "state": payload["state"], "report": report, "descriptor": dict(descriptor)}


def train_intent_feature_checkpoint(training_targets, tuning_targets, output, *, projection_ids=None,
                                   epochs=3, latent_width=4, max_seconds=60.0):
    """Train the shared structural backend in an isolated Intent package.

    This is weak compiler-target feature training, not an NL-to-IR decoder.
    The shared backend controls split isolation, numerical training and reports.
    """
    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as shared
    from ..schema import INTENT_IR_SCHEMA_VERSION

    if projection_ids is None:
        common = None
        for target in list(training_targets) + list(tuning_targets):
            row = target.to_dict() if hasattr(target, "to_dict") else target
            ids = {item["projection_id"] for item in row["projections"] if item["logic_family"] is not None}
            common = ids if common is None else common & ids
        projection_ids = sorted(common or ())
    space = shared.build_feature_space("intent_ir", projection_ids, training_targets)
    contract = shared.build_native_feature_contract(space, ir_schema=INTENT_IR_SCHEMA_VERSION,
        adapter_sha256=_adapter_sha256(), latent_width=latent_width)
    output = Path(output).absolute()
    if output.exists():
        raise ValueError("fresh Intent checkpoint output required")
    result = shared.train_projection_features(contract, space, training_targets, tuning_targets,
        epochs=epochs, latent_width=latent_width, max_seconds=max_seconds)
    raw = _raw({"contract": contract.to_dict(), "feature_space": space,
                "state": result["state"], "report": result["report"]})
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Intent checkpoint exceeds bound")
    output.mkdir(parents=True)
    path = output / "candidate.json"
    with path.open("xb") as stream:
        stream.write(raw)
    descriptor = {"schema": CHECKPOINT_SCHEMA, "path": str(path.resolve()), "sha256": _sha(raw)}
    load_intent_feature_checkpoint(descriptor)
    return descriptor


def _deterministic(instruction):
    from ..source_adapters.prompt import PromptPolicyError

    base = {"status": "unavailable", "document_digest": None, "targets": None,
            "feature_targets": None,
            "native_formula_count": 0, "source_semantics_verified": False,
            "producer": "PromptIntentAdapter@1+IntentFormalizationCompiler",
            "outer_whitespace_trimmed": instruction != instruction.strip(), "error_code": None}
    try:
        target = prepare_instruction_targets(instruction)
        wire = target.to_dict()
        base.update(status="deterministic_declarations", document_digest=target.source_digest,
                    targets=wire, feature_targets=prepare_instruction_feature_targets(instruction).to_dict(),
                    native_formula_count=sum(len(row["native_formulas"]) for row in wire["projections"]))
    except PromptPolicyError:
        base.update(status="source_policy_declined", error_code="prompt_source_policy_declined")
    except Exception:
        # An optional frontend cannot stop the existing planner. Do not include
        # exception messages, which may echo sensitive prompt or filesystem data.
        base.update(status="frontend_error", error_code="intent_frontend_unavailable")
    return base


def prepare_intent_instruction(instruction: str, checkpoint_descriptor: dict | None = None,
                               constraint_refs: tuple[dict, ...] = ()) -> dict:
    """Prepare advisory evidence, leaving raw-instruction planning available."""
    if type(instruction) is not str:
        raise TypeError("instruction must be text")
    raw = instruction.encode("utf-8")
    constraints = _constraints(constraint_refs)
    deterministic = _deterministic(instruction)
    learned = {"status": "not_configured", "checkpoint_sha256": None, "inference": None,
               "decoded_formulas_generated": False, "error_code": None}
    status = "fail_open_no_checkpoint"
    if deterministic["status"] != "deterministic_declarations":
        status = ("fail_open_source_policy" if deterministic["status"] == "source_policy_declined"
                  else "fail_open_frontend_error")
        learned["status"] = "source_unavailable"
    elif checkpoint_descriptor is not None:
        try:
            from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as shared
            loaded = load_intent_feature_checkpoint(checkpoint_descriptor)
            learned["checkpoint_sha256"] = checkpoint_descriptor["sha256"]
            if loaded["state"]["completed_epochs"] < 1:
                learned["status"] = "untrained"
                status = "fail_open_untrained_checkpoint"
            else:
                inference = shared.infer_projection_features(loaded["contract"], loaded["feature_space"],
                    loaded["state"], [deterministic["feature_targets"]])
                learned.update(status="structural_feature_advice", inference=inference)
                status = "feature_advice"
        except Exception:
            learned.update(status="checkpoint_error", error_code="intent_checkpoint_unavailable")
            status = "fail_open_checkpoint_error"
    result = {"schema": SCHEMA, "instruction_sha256": _sha(raw), "instruction_bytes": len(raw),
              "status": status, "continue_planning": True, "raw_instruction_preserved": True,
              "deterministic": deterministic, "learned": learned, "constraint_refs": constraints,
              "logic_profile": intent_code_logic_profile(), "gaps": [
                  "learned_natural_language_to_intent_decoder_unavailable",
                  "deterministic_prompt_wrapper_does_not_verify_instruction_meaning",
                  "no_cross_domain_constraint_composition_or_backend_proofs_executed",
                  "feature_scores_do_not_authorize_or_complete_tasks"],
              "training_steps": 0, "provider_calls": 0, "download_calls": 0, **AUTHORITY}
    result["report_sha256"] = _sha(_raw(result))
    if len(_raw(result)) > MAX_REPORT_BYTES:
        raise ValueError("Intent advice exceeds report bound")
    return result


def validate_intent_instruction_report(report: dict, *, instruction: str,
                                       checkpoint_descriptor: dict | None = None) -> dict:
    """Validate source, deterministic replay and authority; optionally replay weights.

    Without the descriptor, numerical advice is only shape/identity checked;
    it remains explicitly advisory. Passing a descriptor replays real inference.
    """
    fields = {"schema", "instruction_sha256", "instruction_bytes", "status", "continue_planning",
              "raw_instruction_preserved", "deterministic", "learned", "constraint_refs", "logic_profile",
              "gaps", "training_steps", "provider_calls", "download_calls", "report_sha256", *AUTHORITY}
    if type(report) is not dict or set(report) != fields or len(_raw(report)) > MAX_REPORT_BYTES:
        raise ValueError("closed bounded Intent report required")
    payload = {key: value for key, value in report.items() if key != "report_sha256"}
    if report["report_sha256"] != _sha(_raw(payload)):
        raise ValueError("Intent report digest differs")
    if (report["schema"] != SCHEMA or report["status"] not in _STATUSES
            or report["instruction_sha256"] != _sha(instruction.encode("utf-8"))
            or type(report["instruction_bytes"]) is not int or report["instruction_bytes"] != len(instruction.encode("utf-8"))
            or report["continue_planning"] is not True or report["raw_instruction_preserved"] is not True
            or any(type(report[key]) is not type(value) or report[key] != value for key, value in AUTHORITY.items())
            or any(type(report[key]) is not int or report[key] != 0 for key in ("training_steps", "provider_calls", "download_calls"))):
        raise ValueError("Intent source or authority differs")
    _constraints(report["constraint_refs"])
    baseline = prepare_intent_instruction(instruction, constraint_refs=tuple(report["constraint_refs"]))
    for key in ("deterministic", "logic_profile", "gaps"):
        if _raw(report[key]) != _raw(baseline[key]):
            raise ValueError("Intent deterministic evidence differs")
    learned = report["learned"]
    if (type(learned) is not dict or set(learned) != {"status", "checkpoint_sha256", "inference", "decoded_formulas_generated", "error_code"}
            or learned["decoded_formulas_generated"] is not False):
        raise ValueError("closed advisory learned evidence required")
    if report["status"] == "feature_advice":
        from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as shared
        evidence = learned["inference"]
        expected = {"schema", "contract_sha256", "state_sha256", "feature_space_sha256", "rows", "coverage",
                    "training_executed", "decoded_formulas_generated", "representation", *shared.FALSE}
        if (learned["status"] != "structural_feature_advice" or learned["error_code"] is not None
                or type(learned["checkpoint_sha256"]) is not str or not _SHA.fullmatch(learned["checkpoint_sha256"])
                or type(evidence) is not dict or set(evidence) != expected
                or evidence["schema"] != "native-projection-feature-inference/v1"
                or any(evidence[key] is not False for key in (*shared.FALSE, "training_executed", "decoded_formulas_generated"))
                or type(evidence["rows"]) is not list or len(evidence["rows"]) != 1
                or evidence["rows"][0].get("source_digest") != report["deterministic"]["document_digest"]):
            raise ValueError("Intent inference source or authority differs")
        row = evidence["rows"][0]
        if (set(row) != {"source_digest", "latent", "reconstructed_projection_features"}
                or type(row["latent"]) is not list or not 1 <= len(row["latent"]) <= 64
                or type(row["reconstructed_projection_features"]) is not dict
                or not 1 <= len(row["reconstructed_projection_features"]) <= 64
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in row["latent"])):
            raise ValueError("Intent inference numerical row differs")
        for name, values in row["reconstructed_projection_features"].items():
            if (type(name) is not str or type(values) is not list or not 1 <= len(values) <= 4096
                    or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)):
                raise ValueError("Intent inference feature row differs")
        native_projection_ids = {item["projection_id"] for item in report["deterministic"]["feature_targets"]["projections"]}
        if (not set(row["reconstructed_projection_features"]) <= native_projection_ids
                or sum(len(values) for values in row["reconstructed_projection_features"].values()) > 4096):
            raise ValueError("Intent inference selected projection differs")
        if evidence["representation"] != "native_compiler_structural_features_not_semantic_text_embeddings":
            raise ValueError("Intent inference cannot claim semantic text generation")
        for key in ("contract_sha256", "state_sha256", "feature_space_sha256"):
            if type(evidence[key]) is not str or not _SHA.fullmatch(evidence[key].removeprefix("sha256:")):
                raise ValueError("Intent inference identity differs")
        coverage = evidence["coverage"]
        if type(coverage) is not list or len(coverage) != len(row["reconstructed_projection_features"]):
            raise ValueError("Intent inference coverage differs")
        for item in coverage:
            if (type(item) is not dict or set(item) != {"projection_id", "known_atoms", "unknown_atoms"}
                    or item["projection_id"] not in row["reconstructed_projection_features"]
                    or any(type(item[key]) is not int or not 0 <= item[key] <= 1_000_000 for key in ("known_atoms", "unknown_atoms"))):
                raise ValueError("Intent inference coverage row differs")
        if len({item["projection_id"] for item in coverage}) != len(coverage):
            raise ValueError("duplicate Intent inference coverage")
    elif learned["inference"] is not None:
        raise ValueError("fallback cannot claim inference")
    else:
        expected_states = {"fail_open_no_checkpoint": "not_configured",
                           "fail_open_untrained_checkpoint": "untrained",
                           "fail_open_checkpoint_error": "checkpoint_error",
                           "fail_open_source_policy": "source_unavailable",
                           "fail_open_frontend_error": "source_unavailable"}
        if learned["status"] != expected_states[report["status"]]:
            raise ValueError("Intent fallback status differs")
        error = "intent_checkpoint_unavailable" if report["status"] == "fail_open_checkpoint_error" else None
        if learned["error_code"] != error:
            raise ValueError("Intent fallback diagnostic differs")
        if learned["checkpoint_sha256"] is not None and (type(learned["checkpoint_sha256"]) is not str
                                                        or not _SHA.fullmatch(learned["checkpoint_sha256"])):
            raise ValueError("Intent fallback checkpoint identity differs")
    if checkpoint_descriptor is not None:
        replay = prepare_intent_instruction(instruction, checkpoint_descriptor, tuple(report["constraint_refs"]))
        if _raw(replay) != _raw(report):
            raise ValueError("Intent frozen inference replay differs")
    return report
