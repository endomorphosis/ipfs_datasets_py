"""Join corpus identity to the existing live native-projection training gates.

Source decoding and structural reconstruction have distinct readiness reports.
The source inventory reuses the existing transfer-corpus contract. A prepared
structural corpus contains live observations and exact replayable typed inputs;
its saved manifest is evidence to inspect, never authority to resume training.
No source applicability reviews, embeddings, targets or split labels are made
up here, and no model checkpoint format or qualification policy is changed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import unicodedata
import weakref

from . import family_training_v2 as source_owner
from . import family_training_v7 as targets
from . import gte_transfer_corpus as transfer
from . import projection_validation_contract_v5 as policy

SCHEMA = "native-projection-corpus-readiness/v1"
SOURCE_SCHEMA = "source-decoder-corpus-readiness/v1"
ROW_FIELDS = frozenset({"id", "document_id", "group_id", "split", "source_inputs", "observation"})
MAX_ROWS = policy.MAX_BATCH_ROWS * 2
MAX_SOURCE_BYTES = 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_REPORT_BYTES = policy.MAX_BATCH_BYTES
_ISSUED = weakref.WeakKeyDictionary()
_FALSE = {"admitted": False, "qualified": False, "formalized": False, "roundtrip_ok": False,
    "source_semantics_verified": False, "source_authority_authenticated": False,
    "source_decoder_training_allowed": False, "checkpoint_promoted": False,
    "constitution_formalized": False, "global_holdout_verified": False}


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    return _sha(_raw(value))


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _pins():
    return {name: _sha(Path(module.__file__).read_bytes()) for name, module in (
        ("native_targets", targets), ("native_source_owner", source_owner),
        ("projection_policy", policy), ("transfer_corpus", transfer))} | {
            "readiness_owner": _sha(Path(__file__).read_bytes())}


_IMPORTED_PINS = _pins()


def _guard():
    _require(_pins() == _IMPORTED_PINS, "corpus readiness producers changed after import")


def _source_validator_pins(domains):
    """Pin the direct shape owners and named native routes used by this audit."""
    if not domains:
        return {}
    prefix = "ipfs_datasets_py."
    names = {__package__ + ".source_training_v2"}
    if "legal_ir" in domains:
        names.add(prefix + "optimizers.logic_theorem_optimizer.legal_formula_codec")
    if set(domains) - {"legal_ir"}:
        names.add(prefix + "optimizers.logic_theorem_optimizer.domain_384_autoencoder")
    routes = {
        "intent_ir": ("logic.intent_ir.decoder", "logic.intent_ir.schema", "logic.intent_ir.formalize.rich_grammar"),
        "security_ir": ("logic.security_ir.model", "logic.software_verification.program"),
        "ui_ux_ir": ("logic.formalization.autoencoder.ui_source_contract_384", "logic.ui_ux_ir.decoder",
            "logic.ui_ux_ir.schema", "logic.ui_ux_ir.model.components"),
    }
    names.update(prefix + name for domain in domains for name in routes.get(domain, ()))
    return {name: _sha(Path(importlib.import_module(name).__file__).read_bytes()) for name in sorted(names)}


def audit_source_corpus(rows, *, vector_space_id, dimension=384, max_rows=4096):
    """Inventory source-decoder prerequisites without authorizing fitting.

    Rows are exactly the existing ``gte_transfer_corpus.ROW_FIELDS`` contract.
    Native 384D target shape is checked when supported. A supplied vector or a
    declaration of independent labels cannot stand in for verified embedding
    production, reviewed context, or the exact live projection/target join.
    Test/canary roles and leakage components remain as the existing owner found
    them. This API does not open held-out payloads in an optimizer.
    """
    _guard()
    _require(type(max_rows) is int and 1 <= max_rows <= 4096, "bounded source corpus row budget required")
    _require(type(rows) in (list, tuple), "materialized source rows required for target joins")
    audit = transfer.audit_transfer_rows(rows, dimension=dimension,
        vector_space_id=vector_space_id, max_rows=max_rows)
    from . import source_training_v2 as source_decoder
    indexed = {transfer._json_digest(row): row for row in rows if type(row) is dict}
    domains = {binding["domain_id"] for binding in audit["rows"]
        if dimension == 384 and binding["domain_id"] in source_decoder.DOMAINS
        and binding["row_sha256"] is not None
        and indexed[binding["row_sha256"]].get("reference_target") is not None}
    validator_pins = _source_validator_pins(domains)
    records = []
    for binding in audit["rows"]:
        row = indexed.get(binding["row_sha256"], {}) if binding["row_sha256"] is not None else {}
        blockers = list(binding["quarantine_reasons"]) + list(binding["ineligible_reasons"])
        if binding["deduplicated"]:
            blockers.append("duplicate_reference_row")
        target_shape = False
        diagnostic = None
        if dimension == 384 and binding["domain_id"] in source_decoder.DOMAINS and row.get("reference_target") is not None:
            try:
                source_decoder.validate_target(binding["domain_id"], row["reference_target"])
                if binding["domain_id"] == "ui_ux_ir":
                    from .ui_source_contract_384 import validate_training_target
                    validate_training_target(row["reference_target"])
                target_shape = True
            except (ValueError, TypeError, KeyError) as error:
                diagnostic = str(error)[:1024]
        if not target_shape:
            blockers.append("native_source_decoder_target_not_validated")
        blockers += ["verified_embedding_producer_join_missing", "source_context_review_missing",
                     "exact_decoder_target_to_native_projection_join_missing", "live_native_projection_gate_missing"]
        records.append({"id": binding["id"], "domain_id": binding["domain_id"],
            "row_sha256": binding["row_sha256"], "target_origin": binding["target_origin"],
            "native_target_shape_validated": target_shape, "native_target_diagnostic": diagnostic,
            "reference_inventory_eligibility": binding["eligibility"],
            "blockers": sorted(set(blockers)), **_FALSE})
    result = {"schema": SOURCE_SCHEMA, "producer": dict(_IMPORTED_PINS), "transfer_audit": audit,
        "source_target_validator_pins": validator_pins,
        "source_target_validator_pin_scope": "direct_shape_owners_and_named_domain_validator_routes",
        "rows": records, "source_decoder_ready_row_count": 0,
        "scope": "inventory_and_native_target_shape_not_verified_source_supervision",
        "embedding_production_executed": False, "training_executed": False, **_FALSE}
    _guard()
    _require(_source_validator_pins(domains) == validator_pins,
        "source target validators changed during corpus audit")
    result["manifest_sha256"] = _digest(result)
    return result


def _text(value):
    return type(value) is str and 0 < len(value.encode("utf-8")) <= 512 and bool(value.strip())


def _inspect_projection_rows(domain_id, rows):
    _guard()
    _require(domain_id in transfer.DOMAINS, "explicit supported corpus domain required")
    _require(type(rows) in (list, tuple) and 2 <= len(rows) <= MAX_ROWS,
        "bounded projection corpus with train and validation rows required")
    identities, inventories = set(), {"train": [], "validation": []}
    observations, reports = {key: [] for key in inventories}, {key: [] for key in inventories}
    source_total = report_total = 0
    for row in rows:
        _require(type(row) is dict and set(row) == ROW_FIELDS, "closed projection corpus row required")
        _require(all(_text(row[name]) for name in ("id", "document_id", "group_id")),
            "bounded row, document and group identities required")
        _require(row["id"] not in identities, "unique ordered corpus row IDs required")
        identities.add(row["id"])
        split = row["split"]
        _require(type(split) is str and split in inventories,
            "only train and validation rows can enter fitting; test and canary are sealed out")
        inputs, observation = row["source_inputs"], row["observation"]
        _require(type(inputs) is dict and inputs, "exact typed source inputs required")
        _require(domain_id != "ui_ux_ir" or "source_text" not in inputs,
            "UI source identity must use the canonical native row; arbitrary source_text overrides are forbidden")
        _require(type(observation) is policy.ProjectionValidationObservation,
            "live projection observation required; saved JSON is insufficient")
        report = observation.native_report()
        _require(report["domain_id"] == domain_id, "corpus native target domain differs")
        targets.validate_family_training_report_v7(report, **inputs)
        raw, basis, _ = source_owner._source_bytes(domain_id, inputs)
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_SOURCE_BYTES, "bounded canonical source bytes required")
        text = raw.decode("utf-8")
        source_total += len(raw)
        report_total += len(_raw(report))
        _require(source_total <= MAX_TOTAL_SOURCE_BYTES and report_total <= MAX_TOTAL_REPORT_BYTES,
            "projection corpus source/report closure exceeds aggregate byte bound")
        reference = source_owner.supplemental_source_ref(domain_id, **inputs).to_dict()
        binding = {"id": row["id"], "document_id": row["document_id"], "group_id": row["group_id"],
            "split": split, "source_sha256": _sha(raw), "source_bytes": len(raw), "source_basis": basis,
            "normalized_source_sha256": _sha(" ".join(unicodedata.normalize("NFKC", text).casefold().split()).encode()),
            "source_ref": reference, "source_ref_sha256": _digest(reference),
            "source_ref_id": reference["ref_id"], "native_source_digest": report["source_digest"],
            "native_report_sha256": _digest(report),
            "projections": [{"projection_id": target["projection_id"], "target_sha256": target["target_sha256"]}
                for target in report["projections"]]}
        inventories[split].append(binding)
        observations[split].append(observation)
        reports[split].append(report)
    _require(all(inventories.values()) and all(len(value) <= policy.MAX_BATCH_ROWS for value in inventories.values()),
        "nonempty bounded training and validation splits required")
    exclusion_keys = ("id", "document_id", "group_id", "source_sha256", "normalized_source_sha256",
                      "source_ref_sha256", "source_ref_id", "native_source_digest")
    for key in exclusion_keys:
        _require(not {row[key] for row in inventories["train"]} & {row[key] for row in inventories["validation"]},
            "training/validation " + key + " leakage")
    gates = {split: policy.evaluate_projection_training_batch(observations[split], domain_id=domain_id,
        target_reports=reports[split]) for split in inventories}
    ready = all(gate["strict_training_allowed"] for gate in gates.values())
    manifest = {"schema": SCHEMA, "domain_id": domain_id, "producer": dict(_IMPORTED_PINS),
        "objective": "native_structural_projection_reconstruction", "ordered_bindings": inventories,
        "source_bytes": source_total, "native_report_bytes": report_total,
        "split_exclusion_keys": list(exclusion_keys), "native_validation": gates,
        "strict_structural_training_allowed": ready,
        "source_group_scope": "caller_declared_document_and_group_plus_exact_and_normalized_source_exclusion",
        "semantic_group_independence_verified": False,
        "embedding_required_for_structural_objective": False,
        "live_observations_required_at_fit": True, "serialized_manifest_can_authorize_training": False,
        "source_decoding_and_feature_reconstruction_are_distinct": True,
        "training_executed": False, **_FALSE}
    _guard()
    manifest["manifest_sha256"] = _digest(manifest)
    return manifest, observations


@dataclass(frozen=True, eq=False)
class PreparedProjectionCorpus:
    """Issued process-local corpus binding; persistence keeps audit evidence only."""
    _bytes: bytes

    def to_dict(self):
        return json.loads(self._bytes)


def prepare_validated_projection_corpus(domain_id, rows):
    """Bind exact inputs, live native reports and declared train/tuning groups.

    Row fields are exactly ``ROW_FIELDS``. Each native observation must have
    been issued by the existing v5 owner; saved receipts cannot be used. Inputs
    are replayed by v7, and both splits retain complete original gate reports.
    Missing family reviews/floors remain blockers. No declaration is invented.
    """
    manifest, _ = _inspect_projection_rows(domain_id, rows)
    # Native owners use frozen provenance mappings that deliberately cannot be
    # deep-copied. Keep the live inputs, copy row metadata, and replay the whole
    # exact target before every use; mutation invalidates the issued handle.
    frozen = tuple(dict(row) for row in rows)
    copied, _ = _inspect_projection_rows(domain_id, frozen)
    _require(copied == manifest, "copied corpus source identity differs")
    handle = PreparedProjectionCorpus(_raw(manifest))
    _ISSUED[handle] = (domain_id, frozen)
    return handle


def validate_prepared_projection_corpus(prepared):
    _require(type(prepared) is PreparedProjectionCorpus and prepared in _ISSUED,
        "issued live prepared corpus required; saved manifests are insufficient")
    domain, rows = _ISSUED[prepared]
    current, _ = _inspect_projection_rows(domain, rows)
    _require(_raw(current) == prepared._bytes, "prepared corpus or live native evidence changed")
    return current


class CorpusReadinessError(ValueError):
    def __init__(self, report):
        self._bytes = _raw(report)
        super().__init__("strict structural corpus gate failed; see retained native blockers")

    def to_dict(self):
        return json.loads(self._bytes)


def train_prepared_projection_corpus(prepared, *, output_dir, **options):
    """Use the unchanged optimized v5 trainer only after exact live corpus replay."""
    manifest = validate_prepared_projection_corpus(prepared)
    if not manifest["strict_structural_training_allowed"]:
        raise CorpusReadinessError(manifest)
    domain, rows = _ISSUED[prepared]
    from ....optimizers.logic_theorem_optimizer.autoencoder_family_training_validated_v5 import train_validated_family_projection_autoencoder
    observations = {split: [row["observation"] for row in rows if row["split"] == split]
                    for split in ("train", "validation")}
    fitted = train_validated_family_projection_autoencoder(observations["train"], observations["validation"],
        domain_id=domain, output_dir=output_dir, **options)
    final = validate_prepared_projection_corpus(prepared)
    _require(final == manifest, "corpus changed during training; candidate cannot be accepted")
    return {**fitted, "corpus_manifest": final, "corpus_manifest_sha256": final["manifest_sha256"]}


__all__ = ["audit_source_corpus", "PreparedProjectionCorpus", "prepare_validated_projection_corpus",
    "validate_prepared_projection_corpus", "train_prepared_projection_corpus", "CorpusReadinessError"]
