"""Format-explicit replay of the original Intent/Security 384D checkpoints.

The twelve family/dimension storage lanes and their five-field legacy requests
remain unchanged. This opt-in wrapper additionally binds a versioned fragment
format to the authenticated checkpoint, its codec, and its complete original
fitting corpus. Preparation reads metadata only; opening uses the fixed Hub
loader. Targets and native evidence never enter the model call.

The structural checks below distinguish serialized fragment formats. They do
not execute native validators or establish grammar, referential correctness,
source fidelity, numerical quality, teacher, proof, store, or release authority.
Repeated file/plan checks are endpoint fences, not an atomic snapshot or lock.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import checkpoint_hub as hub
from . import ir_cell_routing as routing
from . import ir_cell_runtime as cached
from . import ir_original_corpus_runtime as original


SCHEMA = "ir-decoder-format-runtime-plan/v1"
CONTRACT_SCHEMA = "ir-decoder-format-contract/v1"
MAX_REFERENCE_BYTES = original.MAX_REFERENCE_BYTES
_FORMAT_FIELDS = {"target_format_id", "schema_version", "task_id"}
_TASK = "source_to_native_ir"
_FORMATS = {
    "intent_ir": {
        "target_format_id": "intent_ir/intent_rich_ast",
        "schema_version": "intent-rich-grammar/v1",
        "target_kind": "intent_rich_ast",
        "implementation_module": "ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar",
        "source_relative_path": "logic/intent_ir/formalize/rich_grammar.py",
        "source_bytes": 11527,
        "source_sha256": "6c40ac99d7e339651b6029764f94b12430ca515d4c5f7426770b013499efe92b",
    },
    "security_ir": {
        "target_format_id": "security_ir/program_expression",
        "schema_version": "program-ir/v1",
        "target_kind": "program_expression",
        "implementation_module": "ipfs_datasets_py.logic.software_verification.program",
        "source_relative_path": "logic/software_verification/program.py",
        "source_bytes": 58065,
        "source_sha256": "f051f42d64c5f993451972924953cc7eaa6d17df097235ddabfd5d791d406f91",
    },
}
_EXPRESSION_FIELDS = {"attributes", "evaluation_order", "expression_id", "kind",
    "operand_ids", "operator", "source_ref_ids", "span_ids", "symbol_ids", "type_ref"}
_EXPRESSION_KINDS = {"literal", "symbol", "unary", "binary", "conditional", "call",
    "field", "index", "quantified", "old", "result", "undefined"}
_MODALITIES = {"intended", "required", "prohibited", "permitted", "recommended"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
_SLOT = re.compile(r"[A-Za-z0-9_./:`-]+(?: [A-Za-z0-9_./:`-]+)*\Z")
_AUTHORITY = {**original._AUTHORITY, "output_semantics_verified": False,
    "learned_source_text_reconstruction_qualified": False}


class DecoderFormatRuntimeError(cached.IRCellRuntimeError):
    """Unsupported, mismatched, changed, or structurally foreign format binding.

    An inference-side refusal records that the fixed owner was already called;
    it does not turn that attempt into a pre-inference metadata refusal.
    """

    def __init__(self, message):
        super().__init__(message)
        self.model_load_started = False
        self.model_load_performed = False
        self.model_inference_started = False
        self.model_inference_executed = False
        self.raw_candidate_report = None


def _require(condition, message):
    if not condition:
        raise DecoderFormatRuntimeError(message)


def _format_request(value, request):
    _require(type(value) is dict and set(value) == _FORMAT_FIELDS
             and all(type(value[name]) is str for name in _FORMAT_FIELDS),
             "closed exact-string decoder format request required")
    family = request["ir_family_id"]
    _require(family in _FORMATS, "only original Intent/Security fragment formats are supported")
    expected = _FORMATS[family]
    _require(value["target_format_id"] == expected["target_format_id"]
             and value["schema_version"] == expected["schema_version"],
             "unsupported decoder target format or schema version for family")
    _require(value["task_id"] == request["task_id"] == _TASK,
             "decoder format task must equal original source_to_native_ir task")
    return {name: value[name] for name in _FORMAT_FIELDS}


def _options(directory_plan_pin, inventory_pins, request, format_request,
             package_manifest_pin, corpus_pin, corpus_split, row_ids, max_reference_bytes):
    options = original._options(directory_plan_pin, inventory_pins, request,
        package_manifest_pin, corpus_pin, corpus_split, row_ids, max_reference_bytes)
    options["format_request"] = _format_request(format_request, options["request"])
    # Serialize primitive captured data before any preparation or loader call.
    # No caller-owned mappings, custom deepcopy hooks, or mutable aliases survive.
    return json.loads(cached._raw(options))


def _string(value, name, *, maximum=4096, blank=False):
    _require(type(value) is str and len(value) <= maximum
             and (blank or bool(value.strip())), "bounded exact-string " + name + " required")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise DecoderFormatRuntimeError(name + " must be exact UTF8") from error


def _slot(value, name, *, words=16):
    _string(value, name, maximum=160)
    _require(len(value.split()) <= words and _SLOT.fullmatch(value) is not None
             and "  " not in value and value.count("`") % 2 == 0,
             "bounded rich Intent slot shape required")


def _intent_atom(value):
    _require(type(value) is dict and set(value) == {"kind", "actor", "action", "object", "modality"}
             and value["kind"] == "atom", "closed rich Intent atomic fragment required")
    _slot(value["actor"], "actor", words=4)
    _slot(value["object"], "object")
    _string(value["action"], "action", maximum=160)
    _require(_WORD.fullmatch(value["action"]) is not None
             and value["action"] == value["action"].lower()
             and type(value["modality"]) is str and value["modality"] in _MODALITIES,
             "rich Intent action or modality shape differs")


def _intent_document(value):
    _require(type(value) is dict and type(value.get("kind")) is str,
             "explicit rich Intent constructor required")
    kind = value["kind"]
    if kind == "atom":
        _intent_atom(value)
    elif kind in ("and", "or", "then"):
        _require(set(value) == {"kind", "left", "right"}, "closed two-branch rich Intent fragment required")
        _intent_atom(value["left"])
        _intent_atom(value["right"])
    elif kind == "if":
        _require(set(value) == {"kind", "guard", "body"}, "closed guarded rich Intent fragment required")
        guard = value["guard"]
        _require(type(guard) is dict and set(guard) == {"subject", "property", "negated"}
                 and type(guard["negated"]) is bool, "closed rich Intent condition shape required")
        _slot(guard["subject"], "guard subject", words=4)
        _string(guard["property"], "guard property", maximum=160)
        _require(_WORD.fullmatch(guard["property"]) is not None, "rich Intent property shape differs")
        _intent_atom(value["body"])
    else:
        raise DecoderFormatRuntimeError("unsupported rich Intent constructor")


def _ids(value, name, *, sorted_ids=False):
    _require(type(value) is list and len(value) <= 1024
             and all(type(item) is str and _IDENTIFIER.fullmatch(item) is not None for item in value)
             and len(value) == len(set(value)), "bounded unique ProgramExpression " + name + " required")
    if sorted_ids:
        _require(value == sorted(value), "serialized ProgramExpression ID order differs")


def _program_document(value):
    _require(type(value) is dict and set(value) == _EXPRESSION_FIELDS,
             "complete closed serialized ProgramExpression fragment required")
    kind = value["kind"]
    _require(type(kind) is str and kind in _EXPRESSION_KINDS, "declared ProgramExpression kind required")
    _require(type(value["expression_id"]) is str
             and _IDENTIFIER.fullmatch(value["expression_id"]) is not None,
             "stable ProgramExpression expression_id required")
    _string(value["type_ref"], "type_ref")
    _string(value["operator"], "operator", blank=True)
    _require(type(value["attributes"]) is dict, "serialized ProgramExpression attributes object required")
    for name in ("operand_ids", "evaluation_order", "symbol_ids", "source_ref_ids", "span_ids"):
        _ids(value[name], name, sorted_ids=name in ("symbol_ids", "source_ref_ids", "span_ids"))
    operands, order, symbols = value["operand_ids"], value["evaluation_order"], value["symbol_ids"]
    _require(len(order) == len(operands) and set(order) == set(operands),
             "ProgramExpression evaluation order differs from operands")
    _require(bool(value["source_ref_ids"] or value["span_ids"]), "source-mapped ProgramExpression fragment required")
    if kind in ("symbol", "result"):
        _require(len(symbols) == 1, "ProgramExpression symbol/result needs one symbol")
    if kind == "literal":
        _require(not operands and not symbols, "literal ProgramExpression cannot carry operands/symbols")
    arity = {"unary": 1, "field": 1, "old": 1, "binary": 2, "conditional": 3}.get(kind)
    if arity is not None:
        _require(len(operands) == arity, "ProgramExpression local arity differs")
    if kind in ("unary", "binary", "field", "index", "quantified"):
        _require(bool(value["operator"].strip()), "ProgramExpression operator required for kind")


def _target(value, family):
    _require(type(value) is dict and set(value) == {"kind", "document"}
             and type(value["kind"]) is str and value["kind"] == _FORMATS[family]["target_kind"],
             "decoder target must be the explicit requested fragment format")
    _require(len(cached._raw(value)) <= 128 * 1024, "decoder fragment exceeds source-pinned codec bound")
    if family == "intent_ir":
        _intent_document(value["document"])
    else:
        _program_document(value["document"])
    return value["document"]["kind"]


def _source(checkpoint, family):
    expected = _FORMATS[family]
    dependencies = checkpoint["implementation"]["dependencies"]
    _require(dependencies.get(expected["implementation_module"]) == expected["source_sha256"],
             "checkpoint lacks the known format-specific implementation binding")
    path = Path(__file__).resolve().parents[3] / expected["source_relative_path"]
    pin = {"path": str(path), "bytes": expected["source_bytes"], "sha256": expected["source_sha256"]}
    routing._read_pin(pin)
    return pin


def _prepare(options):
    forwarded = {key: value for key, value in options.items() if key != "format_request"}
    plan = original.prepare_ir_original_corpus_runtime(**forwarded)
    checkpoint_pin = plan["route"]["selected_checkpoint"]["receipt"]
    checkpoint = cached._json(checkpoint_pin, node_limit=4_000_000)
    corpus = cached._json(plan["corpus_receipt"], node_limit=4_000_000)
    family = options["request"]["ir_family_id"]
    source_pin = _source(checkpoint, family)
    constructors = {name: {} for name in ("train", "validation", "test")}
    for row in corpus["rows"]:
        kind = _target(row["target"], family)
        counts = constructors[row["split"]]
        counts[kind] = counts.get(kind, 0) + 1
    binding = {
        "schema": CONTRACT_SCHEMA,
        "format_request": dict(options["format_request"]),
        "ir_family_id": family, "dimension": 384, "dimension_role": "input_embedding",
        "target_kind": _FORMATS[family]["target_kind"],
        "output_scope": "serialized_native_fragment",
        "schema_version_binding": "source-declared format version; fragments have no self-version field",
        "checkpoint_receipt": checkpoint_pin, "checkpoint_schema": checkpoint["schema"],
        "architecture": checkpoint["architecture"],
        "codec_schema": checkpoint["codec"]["schema"],
        "canonical_codec_sha256": hashlib.sha256(cached._raw(checkpoint["codec"])).hexdigest(),
        "decoder_configuration_sha256": hashlib.sha256(cached._raw(checkpoint["config"])).hexdigest(),
        "implementation_declaration_sha256": hashlib.sha256(cached._raw(checkpoint["implementation"])).hexdigest(),
        "format_implementation_module": _FORMATS[family]["implementation_module"],
        "format_implementation_receipt": source_pin,
        "corpus_receipt": plan["corpus_receipt"],
        "training_manifest_sha256": hashlib.sha256(cached._raw(checkpoint["training_manifest"])).hexdigest(),
        "validation_manifest_sha256": hashlib.sha256(cached._raw(checkpoint["validation_manifest"])).hexdigest(),
        "all_original_targets_structurally_match": True,
        "all_original_targets_checked": len(corpus["rows"]),
        "fitted_constructor_coverage": constructors["train"],
        "original_constructor_coverage_by_split": constructors,
        "selected_output_contract_only": False,
        "candidate_output_check": "envelope, source/ID association, status and fragment structural format only",
        "native_grammar_verified": False,
    }
    contract_sha256 = hashlib.sha256(cached._raw(binding)).hexdigest()
    contract = {**binding, "contract_sha256": contract_sha256,
                "contract_id": CONTRACT_SCHEMA + ":" + contract_sha256}
    plan.update(schema=SCHEMA, format_request=dict(options["format_request"]), format_contract=contract,
        capability={**plan["capability"], "id": "experimental_original_domain384_format_replay/v1",
                    "format_explicit": True, "full_native_document_supported": False,
                    "source_text_decoder_supported": False, "logic_decoder_supported": False},
        authority=dict(_AUTHORITY))
    return deepcopy(plan)


def prepare_ir_decoder_format_runtime(directory_plan_pin, inventory_pins, request, *,
        format_request, package_manifest_pin, corpus_pin, corpus_split, row_ids,
        max_reference_bytes=MAX_REFERENCE_BYTES):
    """Authenticate a versioned original fragment contract without loading models."""
    try:
        options = _options(directory_plan_pin, inventory_pins, request, format_request,
            package_manifest_pin, corpus_pin, corpus_split, row_ids, max_reference_bytes)
        return _prepare(options)
    except DecoderFormatRuntimeError:
        raise
    except (routing.RoutingError, cached.IRCellRuntimeError) as error:
        raise DecoderFormatRuntimeError(str(error)) from error
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise DecoderFormatRuntimeError("invalid decoder format runtime binding") from error


def _candidate_checks(report, plan):
    family = plan["route"]["request"]["ir_family_id"]
    _require(type(report) is dict and report.get("schema") == "domain-384-typed-autoencoder/v1"
             and report.get("domain_id") == family and type(report.get("dimension")) is int
             and report["dimension"] == 384, "fixed Domain candidate report identity differs")
    rows = report.get("rows")
    inputs = {row["id"]: row for row in plan["inputs"]}
    _require(type(rows) is list and len(rows) == len(inputs), "one candidate row per captured input required")
    seen, checks, decoded = set(), [], 0
    for row in rows:
        _require(type(row) is dict and type(row.get("id")) is str
                 and row["id"] in inputs and row["id"] not in seen,
                 "unique exact captured candidate ID required")
        identifier = row["id"]
        seen.add(identifier)
        expected_sha = hashlib.sha256(inputs[identifier]["source_text"].encode("utf-8")).hexdigest()
        _require(row.get("source_sha256") == expected_sha, "candidate source digest differs from captured input")
        _require("candidate_ir" in row and type(row.get("status")) is str,
                 "explicit candidate status and candidate_ir required")
        status, candidate = row["status"], row["candidate_ir"]
        if status == "unqualified_candidate":
            constructor = _target(candidate, family)
            decoded += 1
            checks.append({"id": identifier, "status": status, "structural_format_match": True,
                           "constructor": constructor, "native_grammar_verified": False})
        else:
            _require(status == "fail_open_invalid_output" and candidate is None,
                     "invalid candidate status/format or contradictory abstention")
            checks.append({"id": identifier, "status": status, "structural_format_match": None,
                           "constructor": None, "native_grammar_verified": False})
    return {"attempted_rows": len(inputs), "decoded_rows": decoded,
            "abstained_rows": len(inputs) - decoded, "row_checks": checks,
            "native_grammar_verified": False, "semantic_correctness_verified": False}


class _DecoderFormatAutoencoder:
    def __init__(self, owner, options_bytes, plan):
        self._owner = owner
        self._options_bytes = options_bytes
        self._plan_bytes = cached._raw(plan)
        self._inference_started = False
        self._inferred = False

    def _recheck(self):
        plan = prepare_ir_decoder_format_runtime(**json.loads(self._options_bytes))
        _require(cached._raw(plan) == self._plan_bytes, "decoder format binding changed since opening")
        return plan

    def describe(self):
        plan = json.loads(self._plan_bytes)
        return deepcopy({"schema": "ir-decoder-format-runtime-description/v1",
            "runtime_selection": {"request": plan["route"]["request"],
                "runtime_id": plan["package_manifest"]["runtime"],
                "checkpoint": plan["route"]["selected_checkpoint"]["receipt"],
                "package_manifest": plan["package_manifest_receipt"]},
            "format_request": plan["format_request"], "format_contract": plan["format_contract"],
            "row_selection": {"corpus_receipt": plan["corpus_receipt"],
                "split": plan["corpus_split"], "row_ids": plan["row_ids"]},
            "original_corpus_membership": plan["original_corpus_membership"],
            "capability": plan["capability"], "model_load_performed": True,
            "model_load_started": True,
            "model_inference_started": self._inference_started,
            "cached_inference_executed": self._inferred,
            "authority": dict(_AUTHORITY), "budget_status": plan["budget_status"],
            "consistency_scope": cached._SCOPE})

    def infer_cached(self):
        """Infer fixed target-free original rows and refuse foreign output formats."""
        result = None
        inference_started, inference_returned = False, False
        try:
            plan = self._recheck()
            rows = deepcopy(plan["inputs"])
            before = cached._raw(rows)
            self._inference_started = True
            inference_started = True
            result = self._owner.infer(rows)
            self._inferred = True
            inference_returned = True
            _require(cached._raw(rows) == before, "runtime mutated target-free original call inputs")
            self._recheck()
            # Canonical serialization rejects nonserializable objects and
            # nonfinite numbers, then detaches the JSON owner report for checks.
            detached = json.loads(cached._raw(result))
            checks = _candidate_checks(detached, plan)
            return deepcopy({"schema": "ir-decoder-format-inference/v1",
                "runtime_selection": self.describe()["runtime_selection"],
                "format_request": plan["format_request"], "format_contract": plan["format_contract"],
                "row_receipts": plan["row_receipts"], "raw_candidate_report": detached,
                "candidate_format_checks": checks, "model_inference_executed": True,
                "authority": dict(_AUTHORITY), "budget_status": plan["budget_status"],
                "consistency_scope": cached._SCOPE})
        except Exception as error:
            # Ordinary owner failures still record the actual call boundary.
            # Process-control BaseExceptions retain their original behavior.
            refused = error if isinstance(error, DecoderFormatRuntimeError) else DecoderFormatRuntimeError(str(error))
            refused.model_load_started = True
            refused.model_load_performed = True
            refused.model_inference_started = inference_started
            refused.model_inference_executed = inference_returned
            if inference_returned:
                try:
                    refused.raw_candidate_report = json.loads(cached._raw(result))
                except Exception:
                    # Optional preservation must not replace the original
                    # ordinary failure or its actual owner-call flags.
                    pass
            if refused is error:
                raise
            raise refused from error


def _open_ir_decoder_format_autoencoder(directory_plan_pin, inventory_pins, request, *,
        format_request, package_manifest_pin, corpus_pin, corpus_split, row_ids,
        max_reference_bytes=MAX_REFERENCE_BYTES):
    load_started, load_returned = False, False
    try:
        options = _options(directory_plan_pin, inventory_pins, request, format_request,
            package_manifest_pin, corpus_pin, corpus_split, row_ids, max_reference_bytes)
        options_bytes = cached._raw(options)
        plan = prepare_ir_decoder_format_runtime(**json.loads(options_bytes))
        paths = {name: Path(pin["path"]) for name, pin in plan["package_file_receipts"].items()}
        load_started = True
        owner = hub._instantiate(deepcopy(plan["package_manifest"]), paths)
        load_returned = True
        wrapped = _DecoderFormatAutoencoder(owner, options_bytes, plan)
        wrapped._recheck()
        return wrapped
    except Exception as error:
        refused = error if isinstance(error, DecoderFormatRuntimeError) else DecoderFormatRuntimeError(str(error))
        refused.model_load_started = load_started
        refused.model_load_performed = load_returned
        if refused is error:
            raise
        raise refused from error


__all__ = ["SCHEMA", "CONTRACT_SCHEMA", "DecoderFormatRuntimeError",
           "prepare_ir_decoder_format_runtime"]
