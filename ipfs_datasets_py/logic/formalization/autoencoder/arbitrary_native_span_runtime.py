"""Opt-in raw GTE384 occurrence cache to retained warm-start span decoding.

Preparation checks recorded inputs and the fixed reviewed historical recipe;
it imports no tensor library and constructs no model. Opening explicitly uses
the retained continuation constructor, including its saved-optimizer validation.
Copied spans and checked syntax remain unaccepted, unqualified proposals.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

from . import arbitrary_native_source_cache as cache_owner
from . import contextual_legal_ir_runtime as custody
from ...legal_ir import canonical_decoder_preflight as preflight
from ...legal_ir import canonical_span_decoder as span_boundary

SCHEMA = "arbitrary-native-retained-span-runtime-plan/v1"
INFERENCE_SCHEMA = "arbitrary-native-retained-span-inference/v1"
DECODER_CONTRACT_ID = "arbitrary-raw-gte384-retained-span/v1"
CONTROLS = ("none", "zero", "disabled", "rotate")
EQUIVALENCE_SHA256 = "c2ab0d2a353289084cbcf9def1700fd5efe47c1f714a783b681494aaeeaa83b5"
EQUIVALENCE_BYTES = 10795
HISTORICAL_CONTEXT = dict(dimension=384,
    representation_id="actual_frozen_legal_ir/raw384/v1",
    producer_sha256="0e8a4bff65241bd9f7cfa4fd6200cbf1216d836d4687418d25d1c79d9b3ca12d",
    training_index_sha256="739964281f8eb516ca7849da422d44428d9ce09a3f2b64df2c34da2d26d6949f")
MODEL = dict(dimension=384, model_id="thenlper/gte-small",
    revision="17e1f347d17fe144873b1201da91788898c639cd")
ASSETS_SHA256 = "def8d7e04c05560b1d0dd1fa9317be7a59a1ba8399ca725be0ac807a9a264edc"
OLD_ENCODER_SHA256 = "27855f5ffd59ebc45444d5e37c18ff1569618084cd27b1503db112940051ffb0"
NEW_ENCODER_SHA256 = "ce80ed6294009e04580051e6eb06a817d74a8a56f04814ad0a698e3d27dd0d41"
EXECUTION = dict(backend="sentence-transformers", cpu_threads=1, device="cpu",
    dtype="float32", eval_mode=True, gradient_mode="inference_mode", kind="native",
    max_tokens=512, normalization="l2", pooling="mean", seed=0, truncation=False)
FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
    source_semantics_verified=False, semantic_accuracy_measured=False,
    training_executed=False, encoder_executed=False, targets_accessed=False,
    family_bridge_admitted=False, Lake_executed=False, default_promotion=False,
    bit_identical_new_encoder_outputs_proven=False, native_execution_attested=False,
    full_in_repo_import_graph_qualified=False)
_AUTOENCODER = ("arbitrary_native_span_runtime", "arbitrary_native_source_cache",
    "contextual_legal_ir_runtime", "legal_native_conditioning", "dimension_source_inputs",
    "source_embeddings_768", "source_embeddings_768_complete", "gte_multilingual_profile")
_OPTIMIZER = ("autoencoder_corpus_manifest", "autoencoder_embedding_production",
    "autoencoder_embedding_runtime", "autoencoder_training_worker", "legal_span_formula",
    "legal_span_continuation", "legal_formula_codec", "legal_ir_grammar_decoder",
    "legal_ir_family_evaluator", "autoencoder_native_pool", "modal_autoencoder_adaptive_optimizer")
_LEGAL_IR = ("canonical_decoder_preflight", "canonical_source_guards",
    "canonical_span_decoder", "canonical_contracts")
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RESIDENT = {module.__name__: module for module in (cache_owner, custody, preflight, span_boundary)}
_require = custody._require
SpanRuntimeError = custody.ContextualLegalRuntimeError


def _ascii(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_ascii(value)).hexdigest()


def _same(left, right):
    # JSON byte comparison preserves boolean versus numeric type distinctions.
    return _ascii(left) == _ascii(right)


def source_owner_paths():
    directory = Path(__file__).parent
    root = directory.parents[2]
    return {
        **{__package__ + "." + name: str(directory / (name + ".py")) for name in _AUTOENCODER},
        **{"ipfs_datasets_py.optimizers.logic_theorem_optimizer." + name:
           str(root / "optimizers/logic_theorem_optimizer" / (name + ".py")) for name in _OPTIMIZER},
        **{"ipfs_datasets_py.logic.legal_ir." + name:
           str(root / "logic/legal_ir" / (name + ".py")) for name in _LEGAL_IR},
        "ipfs_datasets_py.utils.cid_utils": str(root / "utils/cid_utils.py"),
    }


def _origins(options):
    for name, path in source_owner_paths().items():
        module = sys.modules.get(name)
        if module is not None:
            _require(getattr(module, "__file__", None) == path, "retained span source namespace origin differs")
            _require(_RESIDENT.setdefault(name, module) is module, "retained span source module replaced")
    own = options["pins"]["owner:" + __name__]
    _require(own["sha256"] == _SELF_SHA, "resident span adapter source changed")


def _capture(*, checkpoint_pin, source_cache_pin, source_requests_pin,
             native384_receipt_refs, source_artifact_pins, raw384_equivalence_pin,
             source_owner_pins, row_ids, control="none"):
    _require(type(control) is str and control in CONTROLS, "explicit retained span control required")
    _require(type(row_ids) in (list, tuple) and 1 <= len(row_ids) <= 64
        and all(type(key) is str and key.strip() and len(key) <= 256 for key in row_ids)
        and len(set(row_ids)) == len(row_ids), "one to64 unique occurrence IDs required")
    _require(control != "rotate" or len(row_ids) >= 2, "rotate requires two original occurrences")
    owners = source_owner_paths()
    _require(type(source_owner_pins) is dict and set(source_owner_pins) == set(owners),
        "exact retained span source owner closure required")
    pins = {}
    for name, value in source_owner_pins.items():
        pin = custody._pin(value, 512 * 1024)
        _require(pin["path"] == owners[name], "fixed current span source owner required")
        pins["owner:" + name] = pin
    for name, value in (("checkpoint", checkpoint_pin), ("cache", source_cache_pin),
                        ("requests", source_requests_pin), ("equivalence", raw384_equivalence_pin)):
        pins[name] = custody._pin(value, custody.MAX_REFERENCE_BYTES)
    _require(type(native384_receipt_refs) in (list, tuple) and 1 <= len(native384_receipt_refs) <= 16,
        "bounded exact native384 production refs required")
    refs = [custody._pin(value, custody.MAX_REFERENCE_BYTES) for value in native384_receipt_refs]
    _require(len({pin["path"] for pin in refs}) == len(refs), "duplicate native production reference")
    for index, pin in enumerate(refs):
        pins["native:" + str(index)] = pin
    _require(type(source_artifact_pins) is dict and 1 <= len(source_artifact_pins) <= 64,
        "bounded exact source artifact inventory required")
    artifacts = {}
    for key, value in source_artifact_pins.items():
        pin = custody._pin(value, custody.MAX_REFERENCE_BYTES)
        _require(key == pin["sha256"], "source artifact key must be its byte hash")
        artifacts[key] = pin
        pins["artifact:" + key] = pin
    result = dict(pins=pins, native_refs=refs, artifact_pins=artifacts,
        row_ids=list(row_ids), control=control)
    _require(sum(pin["bytes"] for pin in pins.values()) <= custody.MAX_TOTAL_BYTES,
        "retained span input closure exceeds64MiB")
    _origins(result)
    return result


def _equivalence(options):
    pin = options["pins"]["equivalence"]
    _require(pin["sha256"] == EQUIVALENCE_SHA256 and pin["bytes"] == EQUIVALENCE_BYTES,
        "fixed independently reviewed raw384 equivalence receipt required")
    value = custody._json(custody._read(pin, retain=True))
    _require(value["schema"] == "raw-gte384-retained-span-equivalence/v1"
        and _same(value["historical_context_contract"], HISTORICAL_CONTEXT) and _same(value["model"], MODEL)
        and value["model_assets_sha256"] == ASSETS_SHA256 and _same(value["execution_common"], EXECUTION)
        and value["historical_encoder_code_sha256"] == OLD_ENCODER_SHA256
        and value["current_encoder_code_sha256"] == NEW_ENCODER_SHA256
        and value["historical_batch_size"] == 16 and value["current_receipt_batch_size"] == 4
        and value["cryptographic_execution_attestation"] is False
        and value["numerical_execution_performed"] is False and value["source_semantics_verified"] is False,
        "raw384 concrete encoder recipe/authority differs")
    refs = value["historical_recipe_evidence"]
    _require(type(refs) is dict and len(refs) == 13, "exact historical recipe closure required")
    for path, ref in refs.items():
        validated = custody._pin(ref, custody.MAX_REFERENCE_BYTES)
        _require(path == validated["path"], "historical recipe reference path differs")
        options["pins"]["recipe:" + path] = validated
    _require(sum(ref["bytes"] for ref in options["pins"].values()) <= custody.MAX_TOTAL_BYTES,
        "raw384 complete recipe closure exceeds64MiB")
    _require(options["pins"]["checkpoint"] in (value["raw384_checkpoint_pin"], value["source_only_checkpoint_pin"]),
        "only reviewed raw384 or disabled source-only retained checkpoint supported")
    for ref in options["native_refs"]:
        report = custody._json(custody._read(ref, retain=True))
        _require(_same(report["model"], MODEL) and _digest(report["model_assets"]) == ASSETS_SHA256
            and _same(report["execution"], {**EXECUTION, "batch_size": 4})
            and report["producer"]["code_sha256"] == NEW_ENCODER_SHA256
            and report["producer"]["runtime_versions"] == value["runtime_versions"],
            "new native receipt profile/assets/version differs from reviewed raw384 recipe")
    return value


def _checkpoint_metadata(checkpoint, options, equivalence):
    flags = {"qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
        "semantic_correctness_verified", "promotion_performed", "publication_performed"}
    fields = {"schema", "lineage_id", "initialization", "implementation", "source_parent_checkpoint",
        "source_parent_checkpoint_sha256", "source_parent_optimizer_steps", "initial_model_state_sha256",
        "initial_base_checkpoint_sha256", "context_contract", "context_contract_sha256", "base_checkpoint",
        "parent_checkpoint_sha256", *flags}
    _require(type(checkpoint) is dict and set(checkpoint) == fields
        and checkpoint["schema"] == "warm-start-span-legal-formula-checkpoint/v1"
        and checkpoint["lineage_id"] == "warm_start_source_span_formula_v1"
        and all(checkpoint[key] is False for key in flags), "closed unqualified continuation checkpoint required")
    _require(_same(checkpoint["context_contract"], HISTORICAL_CONTEXT)
        and checkpoint["context_contract_sha256"] == _digest(HISTORICAL_CONTEXT),
        "raw GTE384 contract required; trained384 or width-only relabelling refused")
    _require(_digest(checkpoint) == options["pins"]["checkpoint"]["sha256"],
        "retained checkpoint canonical content identity differs")
    parent, base = checkpoint["source_parent_checkpoint"], checkpoint["base_checkpoint"]
    for record in (parent, base):
        base_fields = {"schema", "lineage_id", "config", "implementation", "training_manifest_sha256",
            "training_count", "tuning_manifest_sha256", "tuning_count", "model_state", "optimizer_state",
            "progress", "parent_checkpoint_sha256", *flags}
        _require(type(record) is dict and set(record) == base_fields
            and record["schema"] == "span-legal-formula-checkpoint/v1"
            and record["lineage_id"] == "source_span_formula_v1" and all(record[key] is False for key in flags),
            "retained base checkpoint schema/authority differs")
    _require(checkpoint["source_parent_checkpoint_sha256"] == _digest(parent)
        == equivalence["historical_parent_base_checkpoint_sha256"], "historical source parent differs")
    from ....optimizers.logic_theorem_optimizer import legal_span_continuation
    _origins(options)
    _require(_same(checkpoint["initialization"], legal_span_continuation._INITIALIZATION)
        and type(checkpoint["source_parent_optimizer_steps"]) is int
        and checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] > 0,
        "retained warm-start provenance differs")
    expected_config = equivalence["raw384_model_config"]
    is_raw = options["pins"]["checkpoint"] == equivalence["raw384_checkpoint_pin"]
    _require(_same(base["config"], {**expected_config, "latent_enabled": is_raw}),
        "retained raw/source-only base configuration differs")
    prefix = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
    expected_impl = {key: options["pins"]["owner:" + name]["sha256"] for key, name in (
        ("span", prefix + "legal_span_formula"), ("codec", prefix + "legal_formula_codec"),
        ("canonical", "ipfs_datasets_py.logic.legal_ir.canonical_contracts"),
        ("grammar", prefix + "legal_ir_grammar_decoder"))}
    _require(parent["implementation"] == base["implementation"] == expected_impl
        and checkpoint["implementation"] == dict(continuation_sha256=
            options["pins"]["owner:" + prefix + "legal_span_continuation"]["sha256"], base_span=expected_impl),
        "checkpoint retained owner source fingerprint differs")
    return dict(schema=checkpoint["schema"], lineage_id=checkpoint["lineage_id"],
        checkpoint_sha256=_digest(checkpoint), source_parent_checkpoint_sha256=_digest(parent),
        base_checkpoint_sha256=_digest(base), model_state_sha256=_digest(base["model_state"]),
        source_parent_optimizer_steps=checkpoint["source_parent_optimizer_steps"],
        initialization=deepcopy(checkpoint["initialization"]),
        context_contract=deepcopy(HISTORICAL_CONTEXT), context_contract_sha256=checkpoint["context_contract_sha256"],
        input_dimension=384, latent_enabled=is_raw, config=deepcopy(base["config"]))


def _prepare(options):
    _origins(options)
    equivalence = _equivalence(options)
    witnesses = {name: custody._witness(pin["path"]) for name, pin in options["pins"].items()}
    for pin in options["pins"].values():
        custody._read(pin)
    checkpoint = custody._json(custody._read(options["pins"]["checkpoint"], retain=True))
    metadata = _checkpoint_metadata(checkpoint, options, equivalence)
    requests = custody._json(custody._read(options["pins"]["requests"], retain=True))
    _require(type(requests) is list and {row["source"]["artifact"]["sha256"] for row in requests}
        == set(options["artifact_pins"]), "exact requested source artifact inventory required")

    def resolver(artifact):
        pin = options["artifact_pins"].get(artifact["sha256"])
        _require(pin is not None and pin["bytes"] == artifact["bytes"], "source resolver identity differs")
        custody._read(pin)
        return pin["path"]

    cache = cache_owner.validate_arbitrary_native_source_cache(
        custody._json(custody._read(options["pins"]["cache"], retain=True)), source_requests=requests,
        native384_receipt_refs=options["native_refs"], source_resolver=resolver)
    _origins(options)
    _require(cache["dimension"] == 384, "raw native384 cache required")
    by_id = {row["id"]: row for row in cache["rows"]}
    sources = {row["id"]: row for row in requests}
    _require(all(key in by_id for key in options["row_ids"]), "selected occurrence is unavailable in native cache")
    selected = [deepcopy(by_id[key]) for key in options["row_ids"]]
    vectors = [row["input"] for row in selected]
    donors = list(range(len(selected)))
    if options["control"] == "rotate":
        vectors, donors = vectors[1:] + vectors[:1], donors[1:] + donors[:1]
    elif options["control"] == "zero":
        vectors = [[0.] * 384 for row in selected]
    # Same pure tokenizer used by the retained preflight facade; no Torch import.
    native = span_boundary._native()
    _origins(options)
    rows, positions = [], []
    for index, row in enumerate(selected):
        source = sources[row["id"]]
        _require(row["source_text"] == source["source_text"], "physical occurrence source text differs")
        diagnostic = preflight.analyze_decoder_source(row["source_text"])
        outcome = "clarification_required" if diagnostic["outcome"] == "clarification_required" else "source_blocked"
        encoding = dict(outcome="not_assessed", token_count=None, reason=None)
        if diagnostic["outcome"] == "unassessed":
            try:
                tokens = native.tokenize_source(row["source_text"])
            except ValueError as error:
                outcome = "source_encoding_unavailable"
                encoding.update(outcome="unavailable", reason=str(error))
            else:
                encoding.update(outcome="admitted", token_count=len(tokens))
                outcome = "decoder_unavailable"
                positions.append(index)
        donor = selected[donors[index]]["id"]
        rows.append(dict(id=row["id"], position=index, source=deepcopy(source["source"]),
            source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(), preflight=diagnostic,
            encoding=encoding, outcome=outcome, original_latent_sha256=_digest(row["input"]),
            effective_latent_sha256=_digest(vectors[index]), latent_donor_id=donor,
            latent_donor_position=donors[index], latent_donor_source=deepcopy(sources[donor]["source"]),
            latent_input_enabled=options["control"] != "disabled" and metadata["latent_enabled"],
            decoder_row=None))
    plan = dict(schema=SCHEMA, decoder_contract_id=DECODER_CONTRACT_ID, checkpoint_metadata=metadata,
        control=options["control"], owner_control="disabled" if options["control"] == "disabled" else "none",
        rows=rows, input_count=len(rows), eligible_count=len(positions), submitted_positions=positions,
        outcome_counts={outcome: sum(row["outcome"] == outcome for row in rows)
            for outcome in sorted({row["outcome"] for row in rows})},
        artifact_receipts=deepcopy(options["pins"]), input_representation="raw_native_GTE_small384",
        source_owner_inventory_scope="selected retained adapter/cache/decoder owners; not a full repository import graph",
        custody_scope=custody._SCOPE,
        paragraph_vectors_only=True, cached_clause_vectors_used=False, document_context_applied=False,
        representation_compatibility_scope="reviewed recorded recipe compatibility; no bit equality or execution attestation",
        historical_encoder_code_sha256=OLD_ENCODER_SHA256, current_encoder_code_sha256=NEW_ENCODER_SHA256,
        historical_batch_size=16, current_recorded_batch_size=4,
        model_load_performed=False, checkpoint_numeric_geometry_validated=False,
        optimizer_steps_executed=0, authority=dict(FALSE))
    custody._fence(options["pins"], witnesses)
    _origins(options)
    return plan, checkpoint, selected, vectors, witnesses


def prepare_arbitrary_native_span_runtime(**options):
    """Prepare exact new source occurrences without constructing a decoder."""
    return _prepare(_capture(**options))[0]


class _SpanHandle:
    def __init__(self, options, decoder, metadata):
        self._options = deepcopy(options)
        self._decoder = decoder
        self._metadata = deepcopy(metadata)
        self._inference_started = self._inference_returned = False
        self._last_raw_report = None

    @property
    def model(self):
        return None if self._decoder is None else self._decoder.model

    def describe(self):
        plan = _prepare(deepcopy(self._options))[0]
        plan.update(model_load_performed=self._decoder is not None,
            checkpoint_numeric_geometry_validated=self._decoder is not None,
            retained_saved_optimizer_state_validation_performed=self._decoder is not None)
        return plan

    def infer_cached(self, control=None):
        self._inference_started = self._inference_returned = False
        self._last_raw_report = None
        try:
            return self._infer_cached(control)
        except Exception as error:
            refused = error if isinstance(error, SpanRuntimeError) else SpanRuntimeError(str(error))
            refused.model_load_started = refused.model_load_performed = self._decoder is not None
            refused.model_inference_started = self._inference_started
            refused.model_inference_executed = self._inference_returned
            refused.raw_candidate_report = deepcopy(self._last_raw_report)
            if refused is error:
                raise
            raise refused from error

    def _infer_cached(self, control=None):
        """Retain all occurrence dispositions; only eligible sources reach inference."""
        options = deepcopy(self._options)
        if control is not None:
            _require(type(control) is str and control in CONTROLS, "unsupported explicit latent control")
            _require(control != "rotate" or len(options["row_ids"]) >= 2, "rotate requires two occurrences")
            options["control"] = control
        plan, _, selected, vectors, witnesses = _prepare(options)
        raw = None
        positions = plan["submitted_positions"]
        if positions:
            _require(self._decoder is not None, "retained decoder unavailable")
            import torch
            _require(torch.get_num_threads() == 1, "dedicated one-thread CPU inference required")
            modules = list(self.model.modules())
            parameters = list(self.model.parameters())
            _require(all(module.training is False for module in modules)
                and all(parameter.grad is None for parameter in parameters),
                "retained model must stay in evaluation mode without gradients")
            flags = [parameter.requires_grad for parameter in parameters]
            before_rng = torch.get_rng_state().clone()
            before = _digest({name: value.detach().cpu().tolist() for name, value in self.model.state_dict().items()})
            _require(before == self._metadata["model_state_sha256"], "retained model changed before inference")
            _origins(options)
            self._inference_started = True
            raw = self._decoder.decode_formal_logic([selected[index]["source_text"] for index in positions],
                [vectors[index] for index in positions], latent_ablation=plan["owner_control"])
            self._inference_returned = True
            self._last_raw_report = deepcopy(raw)
            _origins(options)
            batch_fields = {"schema", "lineage_id", "checkpoint_sha256", "base_checkpoint_sha256",
                "source_parent_checkpoint_sha256", "source_parent_optimizer_steps", "context_contract_sha256",
                "initialization", "rows", "decoded_count", "status", "latent_ablation", "target_access",
                "teacher_forcing", "training_executed", *span_boundary._NATIVE_FALSE}
            _require(type(raw) is dict and set(raw) == batch_fields, "closed retained owner batch required")
            _require(raw["schema"] == "warm-start-span-legal-formula-inference/v1"
                and raw["lineage_id"] == "warm_start_source_span_formula_v1"
                and raw["checkpoint_sha256"] == self._metadata["checkpoint_sha256"]
                and raw["base_checkpoint_sha256"] == self._metadata["base_checkpoint_sha256"]
                and raw["source_parent_checkpoint_sha256"] == self._metadata["source_parent_checkpoint_sha256"]
                and raw["context_contract_sha256"] == self._metadata["context_contract_sha256"]
                and type(raw["source_parent_optimizer_steps"]) is int
                and raw["source_parent_optimizer_steps"] == self._metadata["source_parent_optimizer_steps"]
                and _same(raw["initialization"], self._metadata["initialization"])
                and raw["latent_ablation"] == plan["owner_control"]
                and all(raw[key] is False for key in span_boundary._NATIVE_FALSE)
                and raw["target_access"] is False and raw["teacher_forcing"] is False
                and raw["training_executed"] is False and type(raw["rows"]) is list
                and len(raw["rows"]) == len(positions),
                "retained owner batch schema/custody differs")
            for index, candidate in zip(positions, raw["rows"], strict=True):
                span_boundary._validate_decoder_row(candidate, plan["rows"][index], selected[index])
                plan["rows"][index]["decoder_row"] = deepcopy(candidate)
                plan["rows"][index]["outcome"] = "decoder_proposal" if candidate["status"] == "decoded" else "decoder_abstained"
            decoded = sum(candidate["status"] == "decoded" for candidate in raw["rows"])
            status = "decoded" if decoded == len(positions) else "partial" if decoded else "abstained"
            _require(type(raw["decoded_count"]) is int and raw["decoded_count"] == decoded
                and raw["status"] == status, "retained owner status/count differs")
            after = _digest({name: value.detach().cpu().tolist() for name, value in self.model.state_dict().items()})
            _require(before == after and torch.equal(before_rng, torch.get_rng_state()),
                "retained inference changed weights or ambient CPU RNG")
            _require(all(module.training is False for module in modules)
                and all(parameter.grad is None for parameter in parameters)
                and [parameter.requires_grad for parameter in parameters] == flags,
                "retained inference changed mode, gradients or parameter flags")
        custody._fence(options["pins"], witnesses)
        _origins(options)
        return dict(schema=INFERENCE_SCHEMA, decoder_contract_id=DECODER_CONTRACT_ID,
            checkpoint_metadata=deepcopy(self._metadata), control=options["control"], rows=plan["rows"],
            input_count=len(plan["rows"]), eligible_count=len(positions),
            submitted_positions=list(positions), custody_scope=custody._SCOPE,
            outcome_counts={name: sum(row["outcome"] == name for row in plan["rows"])
                for name in sorted({row["outcome"] for row in plan["rows"]})},
            raw_owner_report=deepcopy(raw), decoder_calls=int(bool(positions)), optimizer_steps_executed=0,
            numerical_custody_checked=bool(positions),
            weights_unchanged=True if positions else None,
            ambient_CPU_RNG_preserved=True if positions else None, authority=dict(FALSE))


def open_arbitrary_native_span_decoder(**options):
    """Explicitly restore only the unchanged retained continuation checkpoint."""
    started = returned = False
    try:
        captured = _capture(**options)
        plan, checkpoint, _, _, witnesses = _prepare(captured)
        decoder = None
        if plan["eligible_count"]:
            import torch
            _require(torch.get_num_threads() == 1, "dedicated one-thread CPU restoration required")
            from ....optimizers.logic_theorem_optimizer import legal_span_continuation
            _origins(captured)
            started = True
            with torch.random.fork_rng(devices=[]):
                decoder = legal_span_continuation.SpanContinuationDecoder(checkpoint)
            returned = True
            _origins(captured)
            custody._fence(captured["pins"], witnesses)
        return _SpanHandle(captured, decoder, plan["checkpoint_metadata"])
    except Exception as error:
        refused = error if isinstance(error, SpanRuntimeError) else SpanRuntimeError(str(error))
        refused.model_load_started, refused.model_load_performed = started, returned
        if refused is error:
            raise
        raise refused from error


__all__ = ["SCHEMA", "INFERENCE_SCHEMA", "DECODER_CONTRACT_ID", "CONTROLS",
    "source_owner_paths", "prepare_arbitrary_native_span_runtime", "open_arbitrary_native_span_decoder"]
