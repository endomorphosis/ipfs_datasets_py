"""Opt-in selected normative decoding of retained source-only native caches.

This adapter authenticates saved producer records without executing an encoder.
It preserves checkpoint/preprocessing bytes and the original replay API. Recorded
consistency is not producer execution attestation, holdout or proof admission.
Archived producer files have an explicit bounded historical hardlink policy;
checkpoints, caches and current library owners retain the single-link fence.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import stat
import sys
from time import monotonic

from . import contextual_legal_ir_runtime as contextual
from . import normative_legal_ir_runtime as normative

SCHEMA = "normative-retained-source-cache-runtime-plan/v1"
DECODER_CONTRACT_ID = "normative-retained-source-cache-legal-ir/v1"
MATCHED_PARAGRAPH_SHUFFLE_REQUEST_SCHEMA = "normative-retained-cache-matched-paragraph-shuffle-request/v1"
_AUTOENCODER_NAMES = normative.SOURCE_OWNER_NAMES + (
    "normative_cached_legal_ir_runtime", "fresh_scalar_source_inputs",
    "fresh_scalar_source_inputs_single", "authored_scalar_holdout",
    "dimension_source_inputs", "source_embeddings_768", "source_embeddings_768_complete",
    "gte_multilingual_profile")
_OPTIMIZER_NAMES = ("autoencoder_embedding_runtime", "autoencoder_embedding_production",
                    "autoencoder_corpus_manifest", "autoencoder_training_worker")
SOURCE_OWNER_NAMES = _AUTOENCODER_NAMES + _OPTIMIZER_NAMES
MAX_REFERENCE_BYTES = contextual.MAX_REFERENCE_BYTES
NormativeCachedLegalRuntimeError = contextual.ContextualLegalRuntimeError
_REPORT_FIELDS = {"schema", "complete", "dimension", "plan_sha256", "source_rows_sha256",
    "sealed_comparison_sha256", "asset_config", "producer_files", "producer_pin_scope",
    "vectors", "native_production", "source_artifact", "representation", "receipt_count",
    "encoder_executed", "batch_size", "max_seconds", "elapsed_seconds", "deadline_cooperative",
    "native_forward_interruptible", "production_sha256", "admitted", "qualified", "formalized",
    "roundtrip_ok", "proof_authority", "source_semantics_verified", "training_executed",
    "target_access", "targets_attached", "downloads_performed", "teacher_checkpoint_loaded",
    "historical_linguistic_teacher_modified", "encoder_context_increased", "transforms_fitted",
    "checkpoint_promoted"}


def source_owner_paths():
    """Fixed current Python owners; archived producer paths are never imported."""
    directory = Path(__file__).parent
    optimizer = directory.parents[2] / "optimizers" / "logic_theorem_optimizer"
    return {**{name: str(directory / (name + ".py")) for name in _AUTOENCODER_NAMES},
            **{name: str(optimizer / (name + ".py")) for name in _OPTIMIZER_NAMES}}


def _module_name(name):
    if name in _OPTIMIZER_NAMES:
        return "ipfs_datasets_py.optimizers.logic_theorem_optimizer." + name
    return __package__ + "." + name


def _verify_origins(options):
    for name in SOURCE_OWNER_NAMES:
        module = sys.modules.get(_module_name(name))
        if module is not None:
            contextual._require(getattr(module, "__file__", None) == options["pins"]["source:" + name]["path"],
                                "loaded cached-input source owner origin differs")
    # The reference producer creates this profile with spec_from_file_location
    # without placing it in sys.modules. Check the actual retained object too.
    reference = sys.modules.get(_module_name("source_embeddings_768"))
    if reference is not None:
        contextual._require(getattr(getattr(reference, "_PROFILE", None), "__file__", None) ==
            options["pins"]["source:gte_multilingual_profile"]["path"], "loaded cached-input profile owner origin differs")


def _historical_witness(path):
    contextual._require(str(Path(path).resolve(strict=True)) == path, "historical path became a filesystem alias")
    info = os.lstat(path)
    contextual._require(stat.S_ISREG(info.st_mode) and 1 <= info.st_nlink <= 128,
                        "historical evidence must be a regular file with bounded observed links")
    return contextual._identity(info) + (info.st_nlink,)


def _historical_read(pin):
    before = _historical_witness(pin["path"])
    contextual._require(before[3] == pin["bytes"], "historical byte count differs")
    fd = os.open(pin["path"], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        def identity():
            info = os.fstat(fd)
            return contextual._identity(info) + (info.st_nlink,)
        contextual._require(identity() == before, "historical evidence changed before open")
        count, digest = 0, hashlib.sha256()
        while True:
            block = os.read(fd, min(1024 * 1024, pin["bytes"] - count + 1))
            if not block:
                break
            count += len(block)
            contextual._require(count <= pin["bytes"], "historical evidence grew while read")
            digest.update(block)
        contextual._require(identity() == before == _historical_witness(pin["path"]),
                            "historical evidence changed while read")
        contextual._require(count == pin["bytes"] and digest.hexdigest() == pin["sha256"],
                            "historical bytes/SHA256 differ")
        return before
    finally:
        os.close(fd)


def _historical_fence(options):
    for name, pin in options["historical_pins"].items():
        contextual._require(list(_historical_read(pin)) == options["historical_witnesses"][name],
                            "historical evidence generation changed across closing fence")
    contextual._require(all(list(_historical_witness(pin["path"])) == options["historical_witnesses"][name]
        for name, pin in options["historical_pins"].items()), "historical evidence changed across final identity fence")



def _joint_identity_fence(options, witnesses):
    contextual._require(all(contextual._witness(pin["path"]) == witnesses[name]
        for name, pin in options["pins"].items()), "current input/source changed across historical closing fence")
    contextual._require(all(list(_historical_witness(pin["path"])) == options["historical_witnesses"][name]
        for name, pin in options["historical_pins"].items()), "historical evidence changed across joint closing fence")
    _verify_origins(options)


def _closing_fence(options, witnesses):
    contextual._fence(options["pins"], witnesses)
    _historical_fence(options)
    _joint_identity_fence(options, witnesses)


def _representation(dimension):
    if dimension == 384:
        producer = importlib.import_module(_module_name("autoencoder_embedding_runtime"))
        return dict(kind="native_gte_small_semantic_embedding", dimension=384, semantic_embedding=True,
            model_id="thenlper/gte-small", revision=producer.PINNED_REVISION, device="cpu", dtype="float32",
            experiment_token_limit=512, actual_forward_tokens_verified=True)
    complete = importlib.import_module(_module_name("source_embeddings_768_complete"))
    return dict(kind="native_gte_multilingual_semantic_embedding", dimension=768, semantic_embedding=True,
        profile_id=complete.PROFILE_ID, device="cpu", dtype="float32", experiment_token_limit=512,
        historical_profile_token_limit=8192, cached_profile_relabelled=False, actual_forward_tokens_verified=True)


def _reject_targets(value):
    pending = [value]
    forbidden = {"target", "targets", "gold", "gold_rows", "reference_rows", "reference_labels", "teacher_logits", "target_ids", "references", "teacher_predictions"}
    while pending:
        item = pending.pop()
        if type(item) is dict:
            contextual._require(not forbidden.intersection(item), "retained source receipt must exclude gold/targets")
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)


def _report_header(report, dimension):
    contextual._require(type(report) is dict and set(report) == _REPORT_FIELDS,
                        "closed retained native production report required")
    _reject_targets(report)
    contextual._require(type(report["dimension"]) is int and report["dimension"] == dimension
        and type(report["receipt_count"]) is int and report["receipt_count"] == 216
        and type(report["batch_size"]) is int and report["batch_size"] == 4,
        "exact native width, receipt count and historical batch required")
    for name in ("max_seconds", "elapsed_seconds"):
        contextual._require(type(report[name]) in (int, float) and math.isfinite(report[name])
            and (0 < report[name] <= 600 if name == "max_seconds" else 0 <= report[name]),
            "finite bounded historical timing required")
    contextual._require(report["deadline_cooperative"] is True and report["native_forward_interruptible"] is False,
                        "historical cooperative deadline observations required")
    contextual._require(type(report["producer_pin_scope"]) is str and report["producer_pin_scope"] ==
        "named local producers; caller freezes transitive import closure", "historical producer pin scope differs")
    contextual._require(type(report["producer_files"]) is dict and 1 <= len(report["producer_files"]) <= 16,
                        "bounded historical producer pins required")
    for path, digest in report["producer_files"].items():
        contextual._text(path, 4096, "historical producer path")
        contextual._require(contextual._hash(digest), "historical producer SHA256 required")
    if dimension == 768:
        contextual._require(report["source_artifact"] is None, "unexpected native768 source artifact")



def _native768_record(plan, report):
    native = report["native_production"]
    fields = {"schema", "assets", "source_rows", "vectors", "token_rows", "forward_observations",
        "complete_checkpoint_loading", "dense_path_verification", "implementation", "execution_profile",
        "historical_profile_token_limit", "experiment_token_limit", "cached_profile_relabelled", "forward_validation"}
    contextual._require(type(native) is dict and set(native) == fields
        and native["schema"] == "fresh-bounded-native768-production/v1", "closed retained native768 receipt required")
    contextual._require(contextual._raw(native["execution_profile"]) == contextual._raw(dict(batch_size=4,
        device="cpu", dtype="float32", pooling="cls", normalization="l2", max_tokens_including_special_tokens=512,
        attention_implementation="eager")), "exact historical native768 execution profile required")
    contextual._require(type(native["experiment_token_limit"]) is int and native["experiment_token_limit"] == 512
        and type(native["historical_profile_token_limit"]) is int and native["historical_profile_token_limit"] == 8192
        and native["cached_profile_relabelled"] is False, "typed native768 token budgets required")
    contextual._require(contextual._raw(native["source_rows"]) == contextual._raw(plan["source_inputs"]),
                        "typed native768 source rows differ")
    complete = importlib.import_module(_module_name("source_embeddings_768_complete"))
    bounded = importlib.import_module(_module_name("dimension_source_inputs"))
    contextual._require(contextual._raw(native["implementation"]) == contextual._raw(complete._implementation()),
                        "typed native768 implementation binding differs")
    profile, assets = complete.reference._PROFILE, native["assets"]
    asset_fields = {"schema", "status", "profile_id", "model_revision", "code_revision", "model_directory",
        "code_directory", "manifest_sha256", "files", "model_numerics_verified", "proof_authority", "unavailable_reasons"}
    contextual._require(type(assets) is dict and set(assets) == asset_fields
        and assets["schema"] == profile.RECEIPT_SCHEMA and assets["status"] == "available"
        and assets["profile_id"] == profile.PROFILE_ID and assets["model_revision"] == profile.MODEL_REV
        and assets["code_revision"] == profile.CODE_REV and assets["model_directory"] == report["asset_config"]["model_directory"]
        and assets["code_directory"] == report["asset_config"]["code_directory"]
        and assets["manifest_sha256"] == report["asset_config"]["expected_manifest_sha256"]
        and assets["model_numerics_verified"] is False and assets["proof_authority"] is False
        and contextual._raw(assets["unavailable_reasons"]) == contextual._raw([]),
        "recorded native768 asset/profile identity differs")
    contextual._require(type(assets["files"]) is list and len(assets["files"]) == 7,
                        "recorded complete native768 asset inventory required")
    seen = set()
    for item in assets["files"]:
        contextual._require(type(item) is dict and set(item) == {"relative_to", "path", "bytes", "sha256"}
            and item["relative_to"] in ("model", "code") and type(item["path"]) is str
            and item["path"] and not Path(item["path"]).is_absolute()
            and item["path"] == str(Path(item["path"])) and ".." not in Path(item["path"]).parts
            and type(item["bytes"]) is int and item["bytes"] > 0 and contextual._hash(item["sha256"]),
            "closed recorded native768 asset entry required")
        identity = (item["relative_to"], item["path"])
        contextual._require(identity not in seen, "unique recorded native768 asset entries required")
        seen.add(identity)
    recorded_assets = {(item["relative_to"], item["path"]):
        {key: item[key] for key in ("bytes", "sha256")} for item in assets["files"]}
    contextual._require(set(recorded_assets) == set(profile.PUBLISHED_ASSETS) and all(
        contextual._raw(recorded_assets[key]) == contextual._raw(profile.PUBLISHED_ASSETS[key])
        for key in recorded_assets), "recorded native768 published asset bytes/hash identities differ")
    loading = native["complete_checkpoint_loading"]
    loading_fields = {"architecture", "tensor_count", "tensor_names", "missing_keys", "unexpected_keys",
        "mismatched_keys", "error_msgs", "classifier_loaded", "classifier_logits_used_for_dense_embedding"}
    contextual._require(type(loading) is dict and set(loading) == loading_fields
        and loading["architecture"] == "NewForTokenClassification" and type(loading["tensor_count"]) is int
        and loading["tensor_count"] == 138 and type(loading["tensor_names"]) is list
        and len(loading["tensor_names"]) == 138 and all(type(name) is str for name in loading["tensor_names"])
        and len(set(loading["tensor_names"])) == 138
        and {"classifier.weight", "classifier.bias"} <= set(loading["tensor_names"])
        and all(name.startswith("new.") or name in {"classifier.weight", "classifier.bias"} for name in loading["tensor_names"])
        and all(contextual._raw(loading[name]) == contextual._raw([]) for name in
            ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"))
        and loading["classifier_loaded"] is True and loading["classifier_logits_used_for_dense_embedding"] is False,
        "recorded complete native768 loading differs")
    tokens = native["token_rows"]
    contextual._require(type(tokens) is list and len(tokens) == 216, "complete native768 token rows required")
    for token in tokens:
        contextual._require(type(token) is dict and set(token) == {"input_ids", "attention_mask"}
            and type(token["input_ids"]) is list and 1 <= len(token["input_ids"]) <= 512
            and all(type(value) is int and value >= 0 for value in token["input_ids"])
            and contextual._raw(token["attention_mask"]) == contextual._raw([1] * len(token["input_ids"])),
            "typed untruncated native768 token IDs/mask required")
    contextual._require(contextual._raw(native["dense_path_verification"]) == contextual._raw(dict(
        encoder_and_complete_hidden_states_bitwise_equal=True, evaluation_mode=True,
        probe_tokens=len(tokens[0]["input_ids"]), scope="first admitted source; source used only, no targets")),
        "recorded native768 dense path verification differs")
    validation = bounded.validate_forward_observations(native)
    contextual._require(contextual._raw(native["forward_validation"]) == contextual._raw(validation),
                        "typed native768 forward validation differs")
    for event in native["forward_observations"]:
        contextual._require(type(event["sources"]) is list and all(type(row) is dict
            and set(row) == {"id", "source_sha256", "active_token_count", "token_input_sha256"}
            and type(row["active_token_count"]) is int for row in event["sources"]),
            "typed native768 forward source count required")
    expected = [dict(id=row["id"], source_sha256=hashlib.sha256(row["source_text"].encode("utf-8")).hexdigest(),
        vector=value, token_count=len(token["input_ids"]),
        token_input_sha256=hashlib.sha256(json.dumps(token["input_ids"], sort_keys=True,
            separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest())
        for row, value, token in zip(plan["source_inputs"], native["vectors"], tokens)]
    contextual._require(contextual._raw(report["vectors"]) == contextual._raw(expected),
                        "typed native768 report vector binding differs")


def _capture(request, *, checkpoint_pin, preprocessing_pin, donor_checkpoint_pin, source_cache_pin,
        source_plan_pin, production_pin, source_owner_pins, row_ids, deadline_seconds, max_reference_bytes):
    normative._validate_request(request, _decoder_contract_id=DECODER_CONTRACT_ID)
    contextual._require(type(source_owner_pins) is dict and set(source_owner_pins) == set(SOURCE_OWNER_NAMES),
                        "exact retained-cache current source closure required")
    options = normative._capture(request, _decoder_contract_id=DECODER_CONTRACT_ID,
        checkpoint_pin=checkpoint_pin, preprocessing_pin=preprocessing_pin, donor_checkpoint_pin=donor_checkpoint_pin,
        source_inputs_pin=source_cache_pin, source_contexts_pin=source_cache_pin,
        source_owner_pins={name: source_owner_pins[name] for name in normative.SOURCE_OWNER_NAMES},
        row_ids=row_ids, deadline_seconds=deadline_seconds, max_reference_bytes=max_reference_bytes)
    for name in SOURCE_OWNER_NAMES:
        maximum = 1024 * 1024 if name == "autoencoder_training_worker" else 512 * 1024
        pin = contextual._pin(source_owner_pins[name], maximum)
        contextual._require(pin["path"] == source_owner_paths()[name], "cached-input owner must be the fixed current library file")
        options["pins"]["source:" + name] = pin
    options["pins"]["source_plan"] = contextual._pin(source_plan_pin, max_reference_bytes)
    options["pins"]["production"] = contextual._pin(production_pin, max_reference_bytes)
    # A bounded preliminary header read admits only declared historical byte witnesses.
    # Full single-link/current-source fences precede all validation helper calls.
    report = contextual._json(contextual._read(options["pins"]["production"], retain=True))
    _report_header(report, request["dimension"])
    historical, witnesses = {}, {}
    for index, (path, digest) in enumerate(report["producer_files"].items()):
        info = os.lstat(path)
        pin = contextual._pin(dict(path=path, bytes=info.st_size, sha256=digest), 512 * 1024)
        name = "producer:" + str(index)
        historical[name], witnesses[name] = pin, list(_historical_read(pin))
    if request["dimension"] == 384:
        pin = contextual._pin(report["source_artifact"], max_reference_bytes)
        historical["source_artifact"], witnesses["source_artifact"] = pin, list(_historical_read(pin))
    options.update(historical_pins=historical, historical_witnesses=witnesses)
    contextual._require(sum(pin["bytes"] for pin in options["pins"].values()) +
        sum(pin["bytes"] for pin in historical.values()) <= contextual.MAX_TOTAL_BYTES,
        "aggregate retained-cache custody bytes exceed bound")
    return options


def _source_packet(documents, options, dimension):
    _verify_origins(options)
    source = importlib.import_module(_module_name("fresh_scalar_source_inputs"))
    single = importlib.import_module(_module_name("fresh_scalar_source_inputs_single"))
    _verify_origins(options)
    plan, report = documents["source_plan"], documents["production"]
    _report_header(report, dimension)
    contextual._require(contextual._raw(source._plan(plan)) == contextual._raw(plan),
                        "typed canonical retained source plan differs")
    expected_pins = {pin["path"]: pin["sha256"] for name, pin in options["historical_pins"].items()
                     if name.startswith("producer:")}
    contextual._require(contextual._raw(report["producer_files"]) == contextual._raw(expected_pins),
                        "captured historical producer identities differ")
    if dimension == 384:
        contextual._require(contextual._raw(report["source_artifact"]) ==
            contextual._raw(options["historical_pins"]["source_artifact"]), "captured source artifact differs")
    contextual._require(contextual._raw(report["representation"]) == contextual._raw(_representation(dimension)),
                        "exact retained native encoder representation required")
    _verify_origins(options)
    if dimension == 768:
        _native768_record(plan, report)
        _verify_origins(options)
    expected = single.assemble(plan, report, dimension=dimension)
    # Keep each producer's native digest convention. This wire comparison closes
    # all cache fields and excludes bool/int substitutions and attached targets.
    contextual._require(contextual._raw(expected) == contextual._raw(documents["source_inputs"]) ==
        contextual._raw(documents["source_contexts"]), "retained source cache differs from exact native reassembly")
    _verify_origins(options)
    by_id = contextual._source_rows(expected["rows"], expected["source_contexts"], dimension, options["row_ids"])
    return contextual._selected_sources(by_id, options["row_ids"])


def _prepare(options):
    # Read all current owners and all archived witnesses before any helper runs.
    initial = {name: contextual._witness(pin["path"]) for name, pin in options["pins"].items()}
    for pin in options["pins"].values():
        contextual._read(pin)
    _historical_fence(options)
    _verify_origins(options)
    plan, prepared, witnesses = normative._prepare(options, _decoder_contract_id=DECODER_CONTRACT_ID,
                                                   _source_packet=_source_packet)
    receipts = plan["artifact_receipts"]
    receipts["source_cache"] = receipts.pop("source_inputs")
    receipts.pop("source_contexts")
    production = contextual._json(contextual._read(options["pins"]["production"], retain=True))
    source_plan = contextual._json(contextual._read(options["pins"]["source_plan"], retain=True))
    plan.update(schema=SCHEMA, historical_evidence_receipts=options["historical_pins"],
        historical_evidence_link_counts={name: identity[-1] for name, identity in options["historical_witnesses"].items()},
        historical_evidence_policy="canonical regular metadata witnesses; observed links 1..128; no archived code execution",
        source_cache_binding=dict(schema="retained-source-cache-binding/v1",
            cache_schema="fresh-scalar-source-inputs-single/v1", source_plan_sha256=source_plan["plan_sha256"],
            production_sha256=production["production_sha256"], source_rows_sha256=source_plan["source_rows_sha256"],
            comparison_seal_sha256=source_plan["sealed_comparison_sha256"], comparison_seal_verified=False,
            recorded_native_source_token_vector_consistency_checked=True, recorded_producer_byte_witnesses_checked=True,
            encoder_execution_attested=False, newly_executed_encoder_forward=False, fresh_holdout_qualified=False,
            representation=production["representation"], paragraphs=48, unique_vectors=216, clauses=180))
    plan["decoder_contract"].update(cached_source_scope="retained_fresh48_source_plan_and_native_production",
        arbitrary_new_source_inputs_supported=False)
    plan["input_contract"].update(paragraph_vector_binding="pinned_native_production_reassembly",
        recorded_native_vector_binding_checked=True, saved_paragraph_vector_producer_authenticated=False)
    _closing_fence(options, initial)
    return json.loads(contextual._raw(plan)), prepared, witnesses


def prepare_normative_cached_legal_ir_runtime(request, *, checkpoint_pin, preprocessing_pin,
        donor_checkpoint_pin, source_cache_pin, source_plan_pin, production_pin, source_owner_pins,
        row_ids, deadline_seconds=120, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Validate existing native source receipts and selected state without a model."""
    try:
        return _prepare(_capture(request, checkpoint_pin=checkpoint_pin, preprocessing_pin=preprocessing_pin,
            donor_checkpoint_pin=donor_checkpoint_pin, source_cache_pin=source_cache_pin, source_plan_pin=source_plan_pin,
            production_pin=production_pin, source_owner_pins=source_owner_pins, row_ids=row_ids,
            deadline_seconds=deadline_seconds, max_reference_bytes=max_reference_bytes))[0]
    except (OSError, RuntimeError, OverflowError, TypeError, UnicodeError, KeyError, ValueError) as error:
        raise NormativeCachedLegalRuntimeError("cannot prepare bounded retained-cache replay: " + str(error)) from error


def _bind_matched_numeric_report(report, owner, plan, packet):
    """Check the raw decoder result against the selected arm before keeping it."""
    expected = dict(schema=owner.SCHEMA, dimension=plan["request"]["dimension"],
        codec_sha256=plan["codec_sha256"], output_cap=plan["budgets"]["decoder_output_tokens"],
        row_count=len(plan["row_ids"]), model_tensor_sha256=plan["model_tensor_sha256"],
        model_tensor_sha256_before=plan["model_tensor_sha256"], model_tensor_sha256_after=plan["model_tensor_sha256"],
        weights_unchanged=True, ambient_rng_preserved=True, source_inputs_unchanged=True,
        source_inputs_sha256=contextual._digest(packet), source_contexts_sha256=contextual._digest(packet["contexts"]),
        **owner._FALSE)
    contextual._require(type(report) is dict and set(report) == set(expected) | {"predictions", "completed"}
        and all(type(report[key]) is type(value) and report[key] == value for key, value in expected.items()),
        "matched numeric checkpoint, source packet or profile differs")
    predictions = report["predictions"]
    contextual._require(type(predictions) is list and len(predictions) == len(plan["row_ids"]),
        "matched numeric result must retain every selected row")
    output_cap = expected["output_cap"]
    vocabulary_size = len(plan["codec"]["target_vocabulary"])
    for row, identity in zip(predictions, plan["row_ids"], strict=True):
        contextual._require(type(row) is dict and set(row) == {"id", "token_ids", "eos_reached", "generation_status"}
            and type(row["id"]) is str and row["id"] == identity,
            "matched numeric result changed the selected row order or identity")
        tokens, status = row["token_ids"], row["generation_status"]
        contextual._require(type(tokens) is list and len(tokens) < output_cap
            and all(type(token) is int and 3 <= token < vocabulary_size for token in tokens)
            and type(status) is str and row["eos_reached"] is (status == "eos")
            and ((status == "output_limit" and len(tokens) == output_cap - 1)
                or (status in ("eos", "invalid_special_token") and len(tokens) <= output_cap - 2)
                or (status == "deadline" and not tokens)), "matched numeric tokens, termination or budget differs")
    contextual._require(report["completed"] is all(row["generation_status"] != "deadline" for row in predictions),
        "matched numeric completion contradicts its row outcomes")
    return json.loads(contextual._raw(report))


class _NormativeCachedLegalAutoencoder(normative._NormativeLegalAutoencoder):
    def _recheck(self):
        plan = super()._recheck()
        options = json.loads(self._options_bytes)
        _historical_fence(options)
        _joint_identity_fence(options, self._witnesses)
        return plan

    def describe(self):
        result = super().describe()
        plan = json.loads(self._plan_bytes)
        result.update(schema="normative-retained-source-cache-description/v1", decoder_contract_id=DECODER_CONTRACT_ID,
            source_cache_binding=plan["source_cache_binding"], historical_evidence_receipts=plan["historical_evidence_receipts"],
            historical_evidence_policy=plan["historical_evidence_policy"],
            historical_evidence_link_counts=plan["historical_evidence_link_counts"])
        return result

    def infer_cached(self):
        result = super().infer_cached()
        result["schema"] = "normative-retained-source-cache-inference/v1"
        return result


    def infer_matched_paragraph_shuffle(self, request, *, control_owner_pin):
        """Compare two source-only inputs on the selected loaded checkpoint.

        The ordinary retained-cache request never enters this mode. The caller
        explicitly selects the two arms, the same checkpoint bytes and the
        ordered cache roster. Both calls share the original inference deadline.
        The returned rows are raw generation outcomes for later scoring.
        """
        entered = monotonic()
        result = None
        started = returned = 0
        try:
            plan = self._recheck()
            budget = plan["budgets"]
            deadline = entered + budget["deadline_seconds"]
            checkpoint = plan["artifact_receipts"]["checkpoint"]
            ids = plan["row_ids"]
            match_request = dict(schema=MATCHED_PARAGRAPH_SHUFFLE_REQUEST_SCHEMA,
                arms=["conditioned", "paragraph_only_shuffle"], row_ids=ids, checkpoint_sha256=checkpoint["sha256"])
            contextual._require(type(request) is dict and request == match_request
                and all(type(request[key]) is type(value) for key, value in match_request.items())
                and all(type(value) is str for value in request["arms"] + request["row_ids"]),
                "matched paragraph shuffle request must select the exact two arms, checkpoint and ordered cache rows")
            source_pin = contextual._pin(control_owner_pin, 512 * 1024)
            name = _module_name("clause_source_controls")
            contextual._require(source_pin["path"] == str(Path(__file__).with_name("clause_source_controls.py")),
                "matched paragraph shuffle requires the fixed current control owner")
            pins = {"control": source_pin}
            witnesses = {"control": contextual._witness(source_pin["path"])}
            contextual._fence(pins, witnesses)
            control_owner = importlib.import_module(name)
            options = json.loads(self._options_bytes)

            def fence():
                self._recheck()
                contextual._fence(pins, witnesses)
                _joint_identity_fence(options, self._witnesses)
                contextual._require(sys.modules.get(name) is control_owner and control_owner.__file__ == source_pin["path"],
                    "matched paragraph shuffle control owner origin changed")

            fence()
            baseline = plan["source_inputs"]
            fixed_contexts = contextual._raw(baseline["contexts"])
            original_hash = contextual._digest(baseline)
            # The control owner accepts an opaque fourth field. It is removed
            # from every numerical call packet below.
            envelope = [dict(row, target_ids=[]) for row in baseline["rows"]]
            changed_rows, contexts, execution = control_owner.prepare_control(
                envelope, baseline["contexts"], "paragraph_only_shuffle")
            shuffled = {"rows": [{key: row[key] for key in ("id", "source_text", "input")} for row in changed_rows],
                        "contexts": contexts}
            control = execution["control"]
            assignment = control["source_assignment"]
            original_by_id = {row["id"]: row for row in baseline["rows"]}
            contextual._require(contextual._digest(baseline) == original_hash
                and contextual._raw(contexts) == fixed_contexts
                and control["kind"] == "paragraph_only_shuffle"
                and set(assignment) == set(assignment.values()) == set(ids)
                and [row["id"] for row in shuffled["rows"]] == ids
                and all(row["source_text"] == original_by_id[row["id"]]["source_text"]
                    and assignment[row["id"]] != row["id"]
                    and row["input"] == original_by_id[assignment[row["id"]]]["input"] != original_by_id[row["id"]]["input"]
                    for row in shuffled["rows"]), "matched paragraph control changed context, population or donor mapping")
            controls = [dict(kind="conditioned", source_assignment={identity: identity for identity in ids}), control]
            arms = [dict(control=item, status="not_dispatched", raw_candidate_report=None,
                        row_outcomes=[dict(id=identity, status="not_dispatched") for identity in ids]) for item in controls]
            result = dict(schema="normative-retained-cache-matched-paragraph-shuffle-inference/v1",
                request=match_request, checkpoint_pin=checkpoint, model_tensor_sha256=plan["model_tensor_sha256"],
                source_cache_pin=plan["artifact_receipts"]["source_cache"], control_owner_pin=source_pin, row_ids=ids,
                row_receipts=plan["row_receipts"], source_contexts_sha256=contextual._digest(baseline["contexts"]),
                budgets=budget, arms=arms, execution_complete=False, all_rows_reached_eos=False,
                original_targets_accessed=False, semantic_fidelity_assessed=False, authority=dict(contextual._AUTHORITY))
            for arm, packet in zip(arms, (baseline, shuffled), strict=True):
                fence()
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                before = contextual._raw(packet)
                started += 1
                self._inference_started = True
                arm.update(status="refused", row_outcomes=[dict(id=identity, status="refused") for identity in ids])
                observed = self._owner.infer_contextual_legal_model(self._model, packet,
                    output_cap=budget["decoder_output_tokens"], deadline_seconds=remaining, batch_size=budget["batch_size"])
                returned += 1
                self._inferred = True
                contextual._require(contextual._raw(packet) == before, "matched numerical owner mutated source packet")
                report = _bind_matched_numeric_report(observed, self._owner, plan, packet)
                arm["raw_candidate_report"] = report
                fence()
                contextual._require(contextual._raw(packet) == before, "matched source packet changed before closing fence")
                arm["row_outcomes"] = [dict(id=row["id"], status=row["generation_status"]) for row in report["predictions"]]
                if monotonic() >= deadline:
                    arm["status"] = "returned_after_deadline"
                    break
                arm["status"] = "returned" if report["completed"] else "incomplete"
            result["execution_complete"] = all(arm["status"] == "returned" for arm in arms)
            result["all_rows_reached_eos"] = result["execution_complete"] and all(
                row["status"] == "eos" for arm in arms for row in arm["row_outcomes"])
            result.update(numerical_dispatches_started=started, numerical_reports_returned=returned)
            return result
        except Exception as error:
            refused = error if isinstance(error, NormativeCachedLegalRuntimeError) else NormativeCachedLegalRuntimeError(str(error))
            refused.model_load_started = refused.model_load_performed = True
            refused.model_inference_started, refused.model_inference_executed = bool(started), bool(returned)
            if result is not None:
                result.update(numerical_dispatches_started=started, numerical_reports_returned=returned)
            refused.matched_comparison_report = result
            if refused is error:
                raise
            raise refused from error


def open_normative_cached_legal_ir_autoencoder(request, *, checkpoint_pin, preprocessing_pin,
        donor_checkpoint_pin, source_cache_pin, source_plan_pin, production_pin, source_owner_pins,
        row_ids, deadline_seconds=120, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Restore the retained selected decoder; never encode or fit new inputs."""
    started = returned = False
    try:
        options = _capture(request, checkpoint_pin=checkpoint_pin, preprocessing_pin=preprocessing_pin,
            donor_checkpoint_pin=donor_checkpoint_pin, source_cache_pin=source_cache_pin, source_plan_pin=source_plan_pin,
            production_pin=production_pin, source_owner_pins=source_owner_pins, row_ids=row_ids,
            deadline_seconds=deadline_seconds, max_reference_bytes=max_reference_bytes)
        plan, prepared, witnesses = _prepare(options)
        owner = contextual._numeric_owner(plan)
        _closing_fence(options, witnesses)
        started = True
        model = owner.restore_contextual_legal_model(json.loads(contextual._raw(prepared)))
        returned = True
        handle = _NormativeCachedLegalAutoencoder(owner, model, options, plan, witnesses, _prepare_plan=_prepare)
        handle._recheck()
        return handle
    except Exception as error:
        refused = error if isinstance(error, NormativeCachedLegalRuntimeError) else NormativeCachedLegalRuntimeError(str(error))
        refused.model_load_started, refused.model_load_performed = started, returned
        if refused is error:
            raise
        raise refused from error


__all__ = ["SCHEMA", "DECODER_CONTRACT_ID", "MATCHED_PARAGRAPH_SHUFFLE_REQUEST_SCHEMA",
    "SOURCE_OWNER_NAMES", "MAX_REFERENCE_BYTES",
    "NormativeCachedLegalRuntimeError", "source_owner_paths", "prepare_normative_cached_legal_ir_runtime",
    "open_normative_cached_legal_ir_autoencoder"]
