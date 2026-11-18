"""Original-bound selected-population accounting for two fixed token profiles.

This additive successor preserves the pinned v1 owner and its caches. The
private decoded records are created here, never accepted from a caller.
No numerical inference, context permission, legal review or proof is implied.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat

CORE_SCHEMA = "legal-relational-batch-core/v1"
CONTENT_SCHEMA = "legal-relational-content-token-batch-evaluation/v2"
CATALOG_SCHEMA = "legal-relational-catalog-token-batch-evaluation/v1"
CATALOG_PROFILE = "full-selected-catalog-token-output-diagnostics/v1"
CATALOG_PREDICTIONS_SCHEMA = "legal-relational-catalog-token-batch-predictions/v1"
PROFILES = ("content_tokens_v1", "catalog_tokens_v1")
CONTENT_PROFILE = "full-selected-context-bound-content-token-output-diagnostics/v1"
CONTENT_PREDICTIONS_SCHEMA = "legal-relational-content-token-batch-predictions/v1"
MAX_POPULATION_BYTES = 128 * 1024
MAX_REFERENCES_BYTES = 16 * 1024 * 1024
MAX_PREDICTIONS_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_REQUEST_BYTES = 524288
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_PAIR_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_POPULATION_ROWS = 64
MAX_OBSERVATIONS = 256
MAX_JSON_NODES = 500000
MAX_JSON_DEPTH = 96
_REFERENCE_FIELDS = {"id", "status", "request_utf8", "request_sha256", "report", "report_sha256", "reason"}
_GENERATION_FIELDS = {"kind", "population_sha256", "latent_dimension", "checkpoint_sha256",
                      "encoder_sha256", "settings_sha256", "teacher_forcing", "target_access"}
TERMINAL_STATUSES = ("missing", "duplicate", "malformed", "unverifiable_generation", "abstained",
                     "unsupported", "invalid_typed_output", "valid_without_reference", "compared")
_COMPACT_DECLARED_ONLY = ("abstained", "unsupported", "error", "timeout", "cancellation", "not_started")
_COMPACT_PREDICTION_FIELDS = {"id", "source_sha256", "context_sha256", "status", "teacher_forcing",
                            "target_access", "generated_ids", "generated_ids_sha256", "reason"}
_CONTENT_CONTEXT_FIELDS = {"content_context_utf8", "content_context_sha256", "content_context_origin"}
_CONTENT_CONTEXT_ORIGINS = ("authored_fixture", "target_derived_label", "caller_supplied_unverified")
CONTENT_TERMINAL_STATUSES = (*TERMINAL_STATUSES, "incomplete", "invalid_frame", "invalid_content_output",
                           "budget_exhausted", "error", "timeout", "cancellation", "not_started")
_CONTENT_REJECTION_STATUSES = {"invalid_token_ids": "invalid_frame", "missing_bos": "invalid_frame",
    "interior_special_tokens": "invalid_frame", "invalid_compact_prefix": "invalid_content_output",
    "invalid_compact_content": "invalid_content_output", "output_limit_without_eos": "budget_exhausted",
    "no_admissible_next_token_within_total_limit": "budget_exhausted"}
COMPARISON_FIELDS = ("exact_typed_expression_equal", "family_profile_equal", "signature_declarations_equal",
                     "argument_roles_equal", "declared_structure_equal", "lexical_alpha_structure_equal")
FALSE_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified", "applicability_verified",
    "governing_use_verified", "independently_reviewed", "accepted", "admitted",
    "semantic_equivalence_verified", "legal_equivalence_verified", "semantic_graph_admitted",
    "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "decoder_accuracy_established", "model_executed", "training_executed", "backend_executed",
    "Lean_admitted", "proof_authority", "model_execution_verified",
    "generation_declarations_are_independent_proof", "partition_membership_verified",
    "source_commitments_verified", "reviewed_targets_verified",
    "numerical_execution_authenticated", "latent_only_verified",
), False)
_OUTPUT_FIELDS = {"schema", "profile", "status", "inputs", "population", "reference_availability",
    "coverage", "observation_ledger", "occurrences", "terminal_counts", "valid_typed_output",
    "full_selected_structure_diagnostics", "comparable_pair_structure_diagnostics", "generation",
    "generation_issues", "producer_pins", "authority", "training_mask", "evaluation_gold_mask",
    "generation_claims_are_declarations_only", "metric_reference_access", "limitations"}

_SOURCE_SPECS = (
    ('ipfs_datasets_py.logic.autoformal.legal_relational_batch_evaluation_v1', 'logic/autoformal/legal_relational_batch_evaluation_v1.py', '663af1184aeb73d10213e9953fee501303119de076886fa526dabff2b16d2138'),
    ('ipfs_datasets_py.logic.autoformal.legal_relational_norm_v1', 'logic/autoformal/legal_relational_norm_v1.py', '6af97bbe5bb729fc6218b77bc32551aaca5d2ed2ba89d61312937a3109032614'),
    ('ipfs_datasets_py.logic.autoformal.legal_relational_reconstruction_v1', 'logic/autoformal/legal_relational_reconstruction_v1.py', '13d4279872d9cc3184d5796596b984193e49b51c7a56c4066857bce74b3e3723'),
    ('ipfs_datasets_py.logic.autoformal.legal_family_routes', 'logic/autoformal/legal_family_routes.py', '5e997e84596c1875d0140573b33a08ff9c12902b003ed3669e1f7bf51aee7c2d'),
    ('ipfs_datasets_py.logic.syntax_core', 'logic/syntax_core/__init__.py', '20dd418d90360cdb42c64ba8b87bedcdb640228b460ef6c6ae60312365130e81'),
    ('ipfs_datasets_py.logic.parsers', 'logic/parsers/__init__.py', 'e75f0c2ffea0f0706a3d1768a794849e6c013b6647dc59ba331f44797c233386'),
    ('ipfs_datasets_py.logic.syntax_core.ast', 'logic/syntax_core/ast.py', '4709513f18ab270858fe9595d88a847ddc52092606c52c7802947abed1ab9ac4'),
    ('ipfs_datasets_py.logic.syntax_core.algebra', 'logic/syntax_core/algebra.py', 'd3587e2270943167ebef226e03cbd70cfc8888d936647670a21cfa514240e6b7'),
    ('ipfs_datasets_py.logic.syntax_core.contracts', 'logic/syntax_core/contracts.py', 'ce6d49e05ca2b09a84a3125ed6ad4c4aae4adf2c5943d3a4fd4eeeb057b444a8'),
    ('ipfs_datasets_py.logic.syntax_core.signatures', 'logic/syntax_core/signatures.py', '49dd4fb0096661a05a15f056eb57248349e2b4e0b02e83239f36db36788c75bf'),
    ('ipfs_datasets_py.logic.syntax_core.diagnostics', 'logic/syntax_core/diagnostics.py', 'a291db3c2cea04ae8dd9221a5e5ddbebd419679c02a5a008034e3755e7650d8f'),
    ('ipfs_datasets_py.logic.syntax_core.lexer', 'logic/syntax_core/lexer.py', 'f666e9759323508f4e90964c0d71164645af9ce1de60bed778e5f64f7f4a3aea'),
    ('ipfs_datasets_py.logic.syntax_core.registry', 'logic/syntax_core/registry.py', 'eff5ca12d748eff1e9463b737a8243c97d89cac51e1b604fe2c765aed885cb44'),
    ('ipfs_datasets_py.logic.families.namespaces', 'logic/families/namespaces.py', 'ba097e653158a812d66ead978d6405d61adaa293521305333579b19bd69a432d'),
    ('ipfs_datasets_py.logic.parsers.legacy_modal', 'logic/parsers/legacy_modal.py', '7b18812ea6fcba8b65ed7dc5c3407e0ad06ac9760c5c66441e9677463f9eb66e'),
    ('ipfs_datasets_py.logic.parsers.modal', 'logic/parsers/modal.py', '3131ff1dd516ebdf52071215c2c7983f9cf317d86bb138ff9437faae9b227942'),
    ('ipfs_datasets_py.logic.parsers.event_calculus', 'logic/parsers/event_calculus.py', '8bd7217febef6daf86f76bae7e03ab0cbf7eb22a1b64f3040fd26a3d2ebfc390'),
    ('ipfs_datasets_py.logic.TDFOL.tdfol_core', 'logic/TDFOL/tdfol_core.py', '67be350d1fb0422a64ab040349b2d51c4008fbeeb8b59a99b8901d681d7d71c7'),
    ('ipfs_datasets_py.logic.intent_ir.formalize.modal_projections', 'logic/intent_ir/formalize/modal_projections.py', '7337b9266ed4f171ec7ee763828f8b637bf57930d8b89fa0d47139650996a14d'),
    ('ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_tokens_v1', 'logic/formalization/autoencoder/legal_compact_content_tokens_v1.py', '145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e'),
    ('ipfs_datasets_py.logic.autoformal.legal_compact_content_v1', 'logic/autoformal/legal_compact_content_v1.py', 'de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e'),
    ('ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_catalog_tokens_v1', 'logic/formalization/autoencoder/legal_compact_catalog_tokens_v1.py', 'bc9e425707c98db3425b5dafb1ab75e5c70002cbf6c229ef1f815eb9bb4612af'),
)
_LEGACY_SHA = "663af1184aeb73d10213e9953fee501303119de076886fa526dabff2b16d2138"
_SELF_PATH = Path(__file__).absolute()
_ROOT = _SELF_PATH.parents[2]
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LEGACY_MODULE = None
_SOURCE_BASELINES = {}
_CATALOG_CONTEXT_FIELDS = {"catalog_context_utf8", "catalog_context_sha256", "catalog_context_origin"}
_DECODED_FIELDS = {"schema", "index", "id", "raw_observation", "raw_observation_sha256",
    "associated_population_index", "declared_status", "shape_valid", "shape_reasons",
    "provenance_valid", "provenance_reasons", "decode_profile", "decode_attempted",
    "decoder_report", "decoder_report_sha256", "decoder_disposition", "decoder_reason",
    "candidate_request_utf8", "candidate_request_sha256", "request_overflow", "outcome"}


class RelationalBatchCoreError(ValueError):
    """Original input, fixed source, public replay or complete bound refused."""


def _need(condition, message):
    if not condition:
        raise RelationalBatchCoreError(message)


def _is_sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _text(value, maximum):
    return type(value) is str and 0 < len(value) <= maximum and bool(value.strip())


def _snapshot(path):
    _need(type(path) is Path or isinstance(path, Path), "trusted fixed source path required")
    _need(path.is_absolute(), "absolute trusted fixed source required")
    for parent in (path.parent, *path.parent.parents):
        _need(stat.S_ISDIR(parent.lstat().st_mode), "unaliased trusted source parents required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_SOURCE_BYTES,
              "bounded regular trusted source required")
        raw = stream.read(MAX_SOURCE_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat()),
          "trusted source changed during snapshot")
    return hashlib.sha256(raw).hexdigest(), identity(before)

_SELF_SNAPSHOT = _snapshot(_SELF_PATH)
_SELF_PIN = _SELF_SNAPSHOT[0]

def _fixed_sources(profile):
    _need(type(profile) is str and profile in PROFILES, "one closed batch-core profile required")
    snapshots = {str(_SELF_PATH): _snapshot(_SELF_PATH)}
    _need(snapshots[str(_SELF_PATH)] == _SELF_SNAPSHOT, "batch core changed since import")
    for _, relative, expected in _SOURCE_SPECS[:-1] if profile == "content_tokens_v1" else _SOURCE_SPECS:
        path = _ROOT / relative
        snapshots[str(path)] = _snapshot(path)
        _need(snapshots[str(path)][0] == expected, "fixed batch dependency generation differs")
    return snapshots


def _helper():
    global _LEGACY_MODULE
    if _LEGACY_MODULE is not None:
        return _LEGACY_MODULE
    name, relative, expected = _SOURCE_SPECS[0]
    path = _ROOT / relative
    before = _snapshot(path)
    _need(before[0] == expected == _LEGACY_SHA, "pinned original batch helper differs")
    if _LEGACY_MODULE is None:
        module = importlib.import_module(name)
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == path,
              "canonical original helper module required")
        _need(module._SELF_PIN == expected and module._SELF_SNAPSHOT == before,
              "original helper import anchor differs")
        _need(_snapshot(path) == before, "original helper changed during lazy import")
        _LEGACY_MODULE = module
    _need(_LEGACY_MODULE._SELF_PIN == expected and _LEGACY_MODULE._SELF_SNAPSHOT == before,
          "original helper import anchor changed")
    return _LEGACY_MODULE


def _copy(value, maximum, budget=None):
    return _helper()._copy(value, maximum, budget)


def _wire(value, maximum):
    return _helper()._wire(value, maximum)


def _digest(value, maximum):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _transport(raw, expected, maximum, budget):
    return _helper()._transport(raw, expected, maximum, budget)


def _reference(row, identity):
    return _helper()._reference(row, identity)


def _generation(predictions, population_sha):
    return _helper()._generation(predictions, population_sha)


def _load_owners(profile):
    before = _fixed_sources(profile)
    modules = {}
    for name, relative, _ in _SOURCE_SPECS[:-1] if profile == "content_tokens_v1" else _SOURCE_SPECS:
        module = importlib.import_module(name)
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == _ROOT / relative,
              "canonical batch dependency module origin required")
        modules[relative] = module
    _need(_fixed_sources(profile) == before, "batch dependencies changed during lazy imports")
    return modules


def _source_snapshots(profile, modules):
    """Only the pinned route owner can nominate extra producer paths."""
    snapshots = _fixed_sources(profile)
    route = modules["logic/autoformal/legal_family_routes.py"]
    closure = route.producer_pins()
    _need(type(closure) is dict and len(closure) <= 128, "bounded trusted route closure required")
    for name, expected in closure.items():
        _need(type(name) is str and Path(name).is_absolute() and _is_sha(expected),
              "trusted route source identity required")
        path = Path(name)
        _need(path.is_relative_to(_ROOT) and ".." not in path.parts,
              "trusted route dependency must be inside canonical package")
        observed = _snapshot(path)
        _need(observed[0] == expected and (name not in snapshots or snapshots[name] == observed),
              "trusted route source generation differs")
        snapshots[name] = observed
    pins = {name: value[0] for name, value in snapshots.items()}
    for relative, module in modules.items():
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == _ROOT / relative,
              "loaded batch owner canonical origin changed")
    legacy = modules["logic/autoformal/legal_relational_batch_evaluation_v1.py"]
    _need(legacy._SELF_PIN == _LEGACY_SHA and
          legacy._SELF_SNAPSHOT == snapshots[str(_ROOT / "logic/autoformal/legal_relational_batch_evaluation_v1.py")],
          "original helper loaded source anchor changed")
    for relative, cache in (("logic/autoformal/legal_relational_norm_v1.py", "_OWNER_PINS"),
                            ("logic/autoformal/legal_relational_reconstruction_v1.py", "_OPERATION_PINS")):
        module = modules[relative]
        _need(module._SELF_PIN == pins[str(_ROOT / relative)], "relational import anchor differs")
        prior = getattr(module, cache)
        _need(prior is None or (type(prior) is dict and prior.items() <= pins.items()),
              "relational cached source identity differs")
    for relative in ("logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
                     "logic/autoformal/legal_compact_content_v1.py"):
        _need(modules[relative]._SELF_SHA == pins[str(_ROOT / relative)], "content import anchor differs")
    if profile == "catalog_tokens_v1":
        relative = "logic/formalization/autoencoder/legal_compact_catalog_tokens_v1.py"
        _need(modules[relative]._SELF_SNAPSHOT == snapshots[str(_ROOT / relative)],
              "catalog import anchor differs")
    if profile not in _SOURCE_BASELINES:
        _SOURCE_BASELINES[profile] = dict(snapshots)
    _need(snapshots == _SOURCE_BASELINES[profile], "batch profile source physical identity changed")
    return snapshots


@contextmanager
def _guard(fence):
    """Preserve the first escaping exception if final custody also refuses."""
    try:
        yield
    except BaseException as primary:
        try:
            fence()
        except BaseException:
            primary.add_note("Closing batch custody check also refused; primary exception preserved.")
        raise
    else:
        fence()


def _catalog_observation(value, index, population_index, population_rows, generation_issues, *, content_generation_kind=None):
    """Catalog-specific sibling of the pinned ordinary content row intake."""
    identity = value.get("id") if type(value) is dict else None
    identity = identity if _text(identity, 256) else None
    associated = population_index.get(identity) if identity is not None else None
    declared = value.get("status") if type(value) is dict else None
    declared = declared if type(declared) is str and len(declared) <= 128 else None
    row = {"index": index, "id": identity, "sha256": _digest(value, MAX_PREDICTIONS_BYTES),
        "associated_population_index": associated, "declared_status": declared,
        "shape_valid": False, "shape_reasons": [], "provenance_valid": False,
        "provenance_reasons": [], "outcome": None,
        "raw_observation": _copy(value, MAX_PREDICTIONS_BYTES)}
    row.update(catalog_decoding=None, catalog_decoding_sha256=None)
    shape, provenance, decodable_ids = row["shape_reasons"], row["provenance_reasons"], None
    if type(value) is not dict:
        shape.append("observation_not_object")
    else:
        if set(value) != _COMPACT_PREDICTION_FIELDS | _CATALOG_CONTEXT_FIELDS:
            shape.append("prediction_fields_mismatch")
        if identity is None:
            shape.append("prediction_id_invalid")
        for name in ("source_sha256", "context_sha256"):
            if not _is_sha(value.get(name)):
                shape.append("prediction_" + name + "_invalid")
            elif associated is not None and value[name] != population_rows[associated][name]:
                provenance.append("prediction_" + name + "_mismatch")
        for name in ("teacher_forcing", "target_access"):
            if value.get(name) is not False:
                provenance.append("prediction_" + name + "_not_false")
        if declared == "generated":
            if value.get("reason") is not None:
                shape.append("generated_reason_nonnull")
            ids = value.get("generated_ids")
            if type(ids) is list:
                _need(len(ids) <= 512, "complete catalog sequence exceeds 512 IDs; truncation refused")
            valid_ids = type(ids) is list and all(type(token) is int and
                -(1 << 63) < token < (1 << 63) for token in ids)
            if not valid_ids:
                shape.append("generated_ids_plain_int63_list_required")
            elif not _is_sha(value.get("generated_ids_sha256")):
                shape.append("generated_ids_sha256_invalid")
            elif _digest(ids, MAX_PREDICTIONS_BYTES) != value["generated_ids_sha256"]:
                shape.append("generated_ids_sha256_mismatch")
            else:
                # Identity/provenance/duplicate failures do not erase the byte
                # observations. Mechanical decoding supplies no credit for them.
                decodable_ids = list(ids)
            text, expected = value.get("catalog_context_utf8"), value.get("catalog_context_sha256")
            raw = text.encode("utf-8") if type(text) is str else None
            if raw is not None:
                _need(0 < len(raw) <= MAX_REQUEST_BYTES, "complete catalog context byte bound exceeded")
            if type(text) is not str or not _is_sha(expected):
                shape.append("catalog_context_bytes_and_sha256_required")
                decodable_ids = None
            else:
                _need(hashlib.sha256(raw).hexdigest() == expected, "independent catalog context pin differs")
            if value.get("catalog_context_origin") not in _CONTENT_CONTEXT_ORIGINS:
                shape.append("catalog_context_origin_invalid")
                decodable_ids = None
            elif (value["catalog_context_origin"] == "target_derived_label" and
                  content_generation_kind == "decoder_declared"):
                provenance.append("decoder_declared_target_derived_context")
        elif declared in _COMPACT_DECLARED_ONLY:
            if value.get("generated_ids") is not None or value.get("generated_ids_sha256") is not None:
                shape.append("declared_nonoutput_contains_generated_ids")
            if not _text(value.get("reason"), 512):
                shape.append("declared_nonoutput_reason_required")
            if any(value.get(key) is not None for key in _CATALOG_CONTEXT_FIELDS):
                shape.append("declared_nonoutput_contains_catalog_context")
        else:
            shape.append("prediction_status_invalid")
    if generation_issues:
        provenance.append("generation_declaration_invalid")
    row["shape_valid"], row["provenance_valid"] = not shape, not provenance
    return row, decodable_ids, False

def _preflight_assets(population_raw, references_raw, predictions_raw, population_sha, references_sha, predictions_sha,
               *, profile):
    budget = [MAX_JSON_NODES]
    population = _transport(population_raw, population_sha, MAX_POPULATION_BYTES, budget)
    references = _transport(references_raw, references_sha, MAX_REFERENCES_BYTES, budget)
    predictions = _transport(predictions_raw, predictions_sha, MAX_PREDICTIONS_BYTES, budget)
    _need(type(population) is dict and set(population) == {"schema", "partition", "selection_sha256", "rows"}
          and population["schema"] == "legal-relational-batch-population/v1"
          and _text(population["partition"], 128) and _is_sha(population["selection_sha256"])
          and type(population["rows"]) is list and 1 <= len(population["rows"]) <= MAX_POPULATION_ROWS,
          "closed nonempty bounded population required")
    by_id = {}
    for index, row in enumerate(population["rows"]):
        _need(type(row) is dict and set(row) == {"id", "source_sha256", "context_sha256"}
              and _text(row["id"], 256) and _is_sha(row["source_sha256"]) and _is_sha(row["context_sha256"])
              and row["id"] not in by_id, "unique closed population occurrence required")
        by_id[row["id"]] = index
    _need(type(references) is dict and set(references) == {"schema", "population_sha256", "rows"}
          and references["schema"] == "legal-relational-batch-references/v1"
          and references["population_sha256"] == population_sha and type(references["rows"]) is list
          and len(references["rows"]) == len(by_id), "complete population-bound references required")
    for reference, identity in zip(references["rows"], by_id):
        _reference(reference, identity)
    extra = {"codec", "codec_sha256"}
    schema = CONTENT_PREDICTIONS_SCHEMA if profile == "content_tokens_v1" else CATALOG_PREDICTIONS_SCHEMA
    _need(type(predictions) is dict and set(predictions) in (
              {"schema", "generation", "rows"} | extra, {"schema", "rows"} | extra)
          and predictions["schema"] == schema and type(predictions["rows"]) is list
          and len(predictions["rows"]) <= MAX_OBSERVATIONS, "closed bounded predictions envelope required")
    _need(type(predictions["codec"]) is dict and _is_sha(predictions["codec_sha256"])
          and _digest(predictions["codec"], 32768) == predictions["codec_sha256"],
          "independently bound complete compact codec required")
    generation, issues = _generation(predictions, population_sha)
    observations = []
    for i, value in enumerate(predictions["rows"]):
        if profile == "content_tokens_v1":
            row = _helper()._compact_observation(value, i, by_id, population["rows"], issues,
                content=True, content_generation_kind=generation["kind"])
        else:
            row = _catalog_observation(value, i, by_id, population["rows"], issues,
                content_generation_kind=generation["kind"])
        observations.append(row)
    return population, references, predictions, generation, issues, observations


_CATALOG_REPORT_FIELDS = {
    "schema", "profile", "format", "selection_policy", "codec_sha256", "context_sha256",
    "context_raw_sha256", "catalog_context", "catalog_sha256", "owner_pins", "authority",
    "training_mask", "evaluation_gold_mask", "status", "reason", "generated_ids",
    "generated_content_raw_utf8", "generated_content_hex", "generated_content_sha256",
    "framing", "selection", "counts"}
_SELECTION_FIELDS = {"catalog_content", "catalog_content_sha256", "selected_catalog_indices",
    "unused_catalog_indices", "catalog_to_effective", "selected_role_row_indices",
    "effective_context", "effective_context_sha256", "effective_content", "effective_content_sha256",
    "prediction", "prediction_sha256", "catalog_prediction_id"}


def _catalog_report_pins(report, pins, states):
    _need(type(report) is dict and set(report) == _CATALOG_REPORT_FIELDS
          and report["schema"] == "legal-compact-catalog-token-candidate/v1"
          and report["profile"] == "object-relational-compact-catalog-tokens/v1"
          and report["format"] == "fixed-json-lexical-compact-catalog/v1"
          and report["selection_policy"] == "referenced_predicates_in_catalog_order/v1",
          "complete fixed catalog candidate report required")
    expected = {str(_ROOT / relative) for relative in (
        "logic/formalization/autoencoder/legal_compact_catalog_tokens_v1.py",
        "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
        "logic/autoformal/legal_compact_content_v1.py", "logic/autoformal/legal_relational_norm_v1.py",
        "logic/syntax_core/ast.py", "logic/syntax_core/signatures.py", "logic/TDFOL/tdfol_core.py")}
    records = report["owner_pins"]
    _need(type(records) is list and len(records) == len(expected), "complete catalog producer population required")
    seen = set()
    for row in records:
        _need(type(row) is dict and set(row) == {"path", "bytes", "sha256"}, "closed catalog source record required")
        name = row["path"]
        _need(type(name) is str and name in expected and name not in seen and name in pins
              and row["sha256"] == pins[name] and type(row["bytes"]) is int
              and row["bytes"] == states[name][1][3], "catalog producer differs from fixed source closure")
        seen.add(name)
    _need(seen == expected and type(report["authority"]) is dict and bool(report["authority"])
          and all(value is False for value in report["authority"].values())
          and type(report["training_mask"]) is int and report["training_mask"] == 0
          and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0,
          "catalog output authority or masks differ")


def _catalog_projection(selection, context, content, codec_sha):
    """Recount declared indices on the existing owner's validated tree, not parse syntax."""
    _need(type(selection) is dict and set(selection) == _SELECTION_FIELDS,
          "complete closed catalog selection required")
    used = set()

    def project(tree, mapping=None):
        kind = tree[0]
        if kind == "variable":
            return list(tree)
        if kind == "predicate":
            used.add(tree[1])
            return [kind, tree[1] if mapping is None else mapping[tree[1]],
                    [project(child, mapping) for child in tree[2]]]
        if kind in ("forall", "exists", "extension"):
            return [kind, tree[1], project(tree[2], mapping)]
        return [kind, *(project(child, mapping) for child in tree[1:])]

    project(content["tree"])
    catalog = context["catalog"]
    total = len(catalog["signature"]["symbols"])
    selected = sorted(used)
    _need(bool(selected) and all(type(i) is int and 0 <= i < total for i in selected),
          "nonempty in-range catalog subset required")
    mapping = {old: new for new, old in enumerate(selected)}
    roles = {row["symbol"]: i for i, row in enumerate(catalog["argument_roles"])}
    role_indices = [roles[catalog["signature"]["symbols"][i]["name"]] for i in selected]
    effective_context = _copy(catalog, MAX_REQUEST_BYTES)
    effective_context["signature"]["symbols"] = [catalog["signature"]["symbols"][i] for i in selected]
    effective_context["argument_roles"] = [catalog["argument_roles"][i] for i in role_indices]
    effective_content = {"schema": "legal-relational-compact-content/v1", "tree": project(content["tree"], mapping)}
    expected = {
        "catalog_content": content, "catalog_content_sha256": _digest(content, 262144),
        "selected_catalog_indices": selected, "unused_catalog_indices": [i for i in range(total) if i not in used],
        "catalog_to_effective": [mapping.get(i) for i in range(total)], "selected_role_row_indices": role_indices,
        "effective_context": effective_context, "effective_context_sha256": _digest(effective_context, MAX_REQUEST_BYTES),
        "effective_content": effective_content, "effective_content_sha256": _digest(effective_content, 262144)}
    identity = {"schema": "legal-compact-catalog-prediction-identity/v1",
        "selection_policy": "referenced_predicates_in_catalog_order/v1", "codec_sha256": codec_sha,
        "context_sha256": _digest(context, MAX_REQUEST_BYTES), "content_sha256": expected["catalog_content_sha256"]}
    expected["catalog_prediction_id"] = "compact-catalog-prediction-v1:" + _digest(identity, 4096)
    _need(_wire({key: selection[key] for key in expected}, 2 * 1024 * 1024)
          == _wire(expected, 2 * 1024 * 1024), "catalog selection differs from original-index projection")
    return effective_content, effective_context


def _decode_catalog_observations(observations, predictions, modules, pins, states, fence):
    catalog = modules["logic/formalization/autoencoder/legal_compact_catalog_tokens_v1.py"]
    content_owner = modules["logic/autoformal/legal_compact_content_v1.py"]
    output = []
    for row, ids, _ in observations:
        request_raw = None
        if ids is not None:
            offered = row["raw_observation"]
            context_raw = offered["catalog_context_utf8"].encode("utf-8")
            fence()
            checked = catalog.decode_compact_catalog_tokens_v1(ids, context_raw,
                expected_context_sha256=offered["catalog_context_sha256"], codec=predictions["codec"],
                expected_codec_sha256=predictions["codec_sha256"])
            fence()
            _wire(checked, 2 * 1024 * 1024)
            _catalog_report_pins(checked, pins, states)
            # Public intake has already checked duplicate-free context JSON and all declarations.
            context = json.loads(context_raw)
            canonical_context = _wire(context, MAX_REQUEST_BYTES)
            _need(_wire(checked["generated_ids"], 32768) == _wire(ids, 32768) and checked["context_raw_sha256"] == offered["catalog_context_sha256"]
                  and checked["context_sha256"] == hashlib.sha256(canonical_context).hexdigest()
                  and _wire(checked["catalog_context"], MAX_REQUEST_BYTES) == canonical_context
                  and checked["catalog_sha256"] == _digest(context["catalog"], MAX_REQUEST_BYTES)
                  and checked["codec_sha256"] == predictions["codec_sha256"],
                  "catalog decoder original input commitments differ")
            vocabulary = predictions["codec"]["vocabulary"]
            valid = all(0 <= i < len(vocabulary) for i in ids)
            bos, eos, terminal = bool(ids) and ids[0] == 1, 2 in ids, bool(ids) and ids[-1] == 2
            body = ids[1:-1] if bos and terminal else ids[1:] if bos else ids
            interior = any(0 <= i < 3 for i in body)
            text = "".join(vocabulary[i] for i in body) if valid and not interior else None
            framing = {"bos_present": bos, "eos_present": eos, "eos_terminal": terminal,
                "token_ids_valid": valid, "interior_special_tokens": interior,
                "terminated": bool(valid and bos and terminal and not interior)}
            _need(_wire(checked["framing"], 4096) == _wire(framing, 4096)
                  and checked["generated_content_raw_utf8"] == text,
                  "catalog framing or generated lexical bytes differ")
            if text is None:
                _need(checked["generated_content_hex"] is checked["generated_content_sha256"] is None,
                      "unrecoverable catalog content cannot claim byte commitments")
            else:
                raw_content = text.encode("utf-8")
                _need(checked["generated_content_hex"] == raw_content.hex()
                      and checked["generated_content_sha256"] == hashlib.sha256(raw_content).hexdigest(),
                      "catalog generated content byte commitments differ")
            status, reason = checked["status"], checked["reason"]
            _need(type(status) is str and (reason is None or type(reason) is str),
                  "plain catalog decoder disposition required")
            _need((status == "valid_candidate" and reason is None) or
                  (status == "incomplete" and reason in ("missing_bos_and_eos", "missing_eos")) or
                  (status == "rejected" and reason in _CONTENT_REJECTION_STATUSES),
                  "unsupported catalog-token intake disposition")
            if status == "valid_candidate":
                selection = checked["selection"]
                _need(text is not None and type(selection) is dict, "valid catalog selection and bytes required")
                original_content = json.loads(text)
                _need(_wire(original_content, 262144).decode("utf-8") == text,
                      "catalog candidate content must have canonical lexical form")
                effective_content, effective_context = _catalog_projection(selection, context, original_content,
                    predictions["codec_sha256"])
                prediction = selection["prediction"]
                _helper()._content_report_pins(prediction, pins, states)
                _need(selection["prediction_sha256"] == _digest(prediction, 2 * 1024 * 1024)
                      and prediction["identity_mode"] == "generated" and _wire(prediction["counts"], 4096) == _wire(checked["counts"], 4096)
                      and prediction["request"].get("source_binding") is None,
                      "catalog nested prediction identity or commitment differs")
                effective_raw, effective_context_raw = _wire(effective_content, 262144), _wire(effective_context, MAX_REQUEST_BYTES)
                fence()
                replayed = content_owner.decode_prediction_v1(effective_raw, effective_context_raw,
                    expected_content_sha256=selection["effective_content_sha256"],
                    expected_context_sha256=selection["effective_context_sha256"])
                fence()
                _helper()._content_report_pins(replayed, pins, states)
                _need(_wire(prediction, MAX_REPORT_BYTES) == _wire(replayed, MAX_REPORT_BYTES),
                      "catalog prediction differs from target-free effective-content replay")
                request_raw = _wire(prediction["request"], MAX_REQUEST_BYTES)
                _need(hashlib.sha256(request_raw).hexdigest() == prediction["request_sha256"],
                      "catalog reconstructed request commitment differs")
            else:
                _need(checked["selection"] is None and checked["counts"] is None,
                      "nonvalid catalog output cannot contain a reconstructed selection")
            row["catalog_decoding"] = _copy(checked, 2 * 1024 * 1024)
            row["catalog_decoding_sha256"] = _digest(checked, 2 * 1024 * 1024)
        output.append((row, request_raw, False))
    return output


def _decoded_record(row, request_raw, overflow, profile):
    field = "content_decoding" if profile == "content_tokens_v1" else "catalog_decoding"
    checked = row[field]
    record = {"schema": "legal-relational-batch-decoded-observation/v1", "index": row["index"],
        "id": row["id"], "raw_observation": row["raw_observation"], "raw_observation_sha256": row["sha256"],
        "associated_population_index": row["associated_population_index"], "declared_status": row["declared_status"],
        "shape_valid": row["shape_valid"], "shape_reasons": row["shape_reasons"],
        "provenance_valid": row["provenance_valid"], "provenance_reasons": row["provenance_reasons"],
        "decode_profile": profile, "decode_attempted": checked is not None,
        "decoder_report": checked, "decoder_report_sha256": row[field + "_sha256"],
        "decoder_disposition": None if checked is None else checked["status"],
        "decoder_reason": None if checked is None else checked["reason"],
        "candidate_request_utf8": None if request_raw is None else request_raw.decode("utf-8"),
        "candidate_request_sha256": None if request_raw is None else hashlib.sha256(request_raw).hexdigest(),
        "request_overflow": overflow, "outcome": None}
    record = _copy(record, MAX_PREDICTIONS_BYTES)
    _check_record(record, profile)
    return record


def _check_record(record, profile):
    _need(type(record) is dict and set(record) == _DECODED_FIELDS
          and record["schema"] == "legal-relational-batch-decoded-observation/v1"
          and record["decode_profile"] == profile and type(record["index"]) is int
          and 0 <= record["index"] < MAX_OBSERVATIONS
          and type(record["shape_valid"]) is bool and type(record["provenance_valid"]) is bool
          and type(record["decode_attempted"]) is bool and record["request_overflow"] is False,
          "closed private decoded observation required")
    _need(_digest(record["raw_observation"], MAX_PREDICTIONS_BYTES) == record["raw_observation_sha256"],
          "private decoded record raw observation differs")
    checked = record["decoder_report"]
    if not record["decode_attempted"]:
        _need(all(record[key] is None for key in ("decoder_report", "decoder_report_sha256", "decoder_disposition",
            "decoder_reason", "candidate_request_utf8", "candidate_request_sha256")),
            "unattempted decode cannot contain candidate evidence")
        return
    _need(type(checked) is dict and _digest(checked, MAX_REPORT_BYTES) == record["decoder_report_sha256"]
          and checked["status"] == record["decoder_disposition"] and checked["reason"] == record["decoder_reason"],
          "private decoded report commitment differs")
    if checked["status"] != "valid_candidate":
        _need(record["candidate_request_utf8"] is record["candidate_request_sha256"] is None,
              "nonvalid private record cannot contain candidate request")
    else:
        prediction = checked["prediction"] if profile == "content_tokens_v1" else checked["selection"]["prediction"]
        raw = _wire(prediction["request"], MAX_REQUEST_BYTES)
        _need(record["candidate_request_utf8"] == raw.decode("utf-8")
              and record["candidate_request_sha256"] == hashlib.sha256(raw).hexdigest() == prediction["request_sha256"],
              "private candidate request differs from original public prediction")


def _decode_observations(observations, predictions, profile, modules, pins, states, fence):
    if profile == "content_tokens_v1":
        owners = (modules["logic/formalization/autoencoder/legal_compact_content_tokens_v1.py"],
                  modules["logic/autoformal/legal_compact_content_v1.py"])
        decoded = _helper()._decode_content_observations(observations, predictions, owners, pins, states, fence)
    else:
        decoded = _decode_catalog_observations(observations, predictions, modules, pins, states, fence)
    return [_decoded_record(row, raw, overflow, profile) for row, raw, overflow in decoded]


def _ledger(record):
    _check_record(record, record["decode_profile"])
    row = {key: record[key] for key in ("index", "id", "associated_population_index", "declared_status",
        "shape_valid", "shape_reasons", "provenance_valid", "provenance_reasons", "outcome", "raw_observation")}
    row["sha256"] = record["raw_observation_sha256"]
    field = "content_decoding" if record["decode_profile"] == "content_tokens_v1" else "catalog_decoding"
    row[field], row[field + "_sha256"] = record["decoder_report"], record["decoder_report_sha256"]
    return row


def _validate_references(references, relational, pins, fence):
    for reference in references["rows"]:
        if reference["status"] == "available":
            fence()
            try:
                checked = relational.validate_relational_norm_v1(reference["report"],
                    reference["request_utf8"].encode("utf-8"), expected_request_sha256=reference["request_sha256"],
                    expected_report_sha256=reference["report_sha256"])
            except ValueError:
                raise RelationalBatchCoreError("available original reference replay refused") from None
            fence()
            _need(checked == reference["report"], "reference replay changed original report")
            _helper()._owned_report(checked, pins)


def _index_observations(records, population):
    by_id, unidentified = {}, []
    for row in records:
        if row["id"] is None:
            unidentified.append(row["index"])
            row["outcome"] = "unidentifiable"
        else:
            by_id.setdefault(row["id"], []).append(row["index"])
    expected_ids = [row["id"] for row in population["rows"]]
    missing = [identity for identity in expected_ids if identity not in by_id]
    duplicate = {identity: by_id[identity] for identity in expected_ids if len(by_id.get(identity, [])) > 1}
    unexpected = {identity: indices for identity, indices in by_id.items() if identity not in expected_ids}
    for indices in unexpected.values():
        for index in indices:
            records[index]["outcome"] = "unexpected"
    return by_id, unidentified, expected_ids, missing, duplicate, unexpected


def _classify_occurrence(indices, records):
    """Pure precedence; references cannot influence these gates."""
    if not indices:
        return "missing", ["missing_prediction"], None
    if len(indices) > 1:
        return "duplicate", ["duplicate_prediction_id"], None
    row = records[indices[0]]
    _check_record(row, row["decode_profile"])
    declared = row["declared_status"]
    if not row["shape_valid"]:
        return "malformed", list(row["shape_reasons"]), declared
    if not row["provenance_valid"]:
        return "unverifiable_generation", list(row["provenance_reasons"]), declared
    if declared in _COMPACT_DECLARED_ONLY:
        return declared, ["declared_" + declared], declared
    _need(row["decode_attempted"], "generated eligible observation must have public decode evidence")
    status, reason = row["decoder_disposition"], row["decoder_reason"]
    if status != "valid_candidate":
        _need(type(reason) is str, "plain decoded reason required")
        if status == "incomplete":
            _need(reason in ("missing_bos_and_eos", "missing_eos"), "known incomplete reason required")
            return "incomplete", [reason], declared
        _need(status == "rejected" and reason in _CONTENT_REJECTION_STATUSES, "known rejected disposition required")
        return _CONTENT_REJECTION_STATUSES[reason], [reason], declared
    return None, [], declared


def _compare_candidate(record, reference, relational, paired, pins, fence):
    request_raw = record["candidate_request_utf8"].encode("utf-8")
    request_sha = record["candidate_request_sha256"]
    fence()
    try:
        candidate = relational.prepare_relational_norm_v1(request_raw, expected_request_sha256=request_sha)
    except ValueError:
        raise RelationalBatchCoreError("public replay refused an already validated compact candidate") from None
    fence()
    candidate_sha = relational.relational_norm_report_sha256(candidate)
    validated = relational.validate_relational_norm_v1(candidate, request_raw,
        expected_request_sha256=request_sha, expected_report_sha256=candidate_sha)
    fence()
    _need(candidate == validated, "candidate public validation changed prepared output")
    _helper()._owned_report(validated, pins)
    if reference["status"] == "unavailable":
        return "valid_without_reference", ["reference_unavailable"], None
    pair = paired.prepare_relational_reconstruction_comparison_v1(reference["report"], candidate,
        reference_request_raw=reference["request_utf8"].encode("utf-8"), candidate_request_raw=request_raw,
        expected_reference_request_sha256=reference["request_sha256"], expected_candidate_request_sha256=request_sha,
        expected_reference_report_sha256=reference["report_sha256"], expected_candidate_report_sha256=candidate_sha)
    fence()
    _helper()._owned_report(pair, pins)
    diagnostic = _helper()._pair_diagnostic(pair, paired)
    return "compared", [], diagnostic


def _assemble_report(population_raw, references_raw, predictions_raw, population_sha, references_sha,
                     predictions_sha, population, references, predictions, generation, issues,
                     records, occurrences, terminal, matched, indexed, pins, profile):
    by_id, unidentified, expected_ids, missing, duplicate, unexpected = indexed
    count = len(expected_ids)
    ledger = [_ledger(record) for record in records]
    _need(sum(terminal.values()) == count and all(row["outcome"] is not None for row in ledger),
          "complete occurrence/observation accounting required")
    _need(sum(len(indices) for indices in by_id.values()) + len(unidentified) == len(ledger),
          "every observation must be retained exactly once")
    available = sum(row["status"] == "available" for row in references["rows"])
    valid = terminal["compared"] + terminal["valid_without_reference"]
    expected_population_sha256, expected_references_sha256, expected_predictions_sha256 = population_sha, references_sha, predictions_sha
    result = {"schema": CONTENT_SCHEMA if profile == "content_tokens_v1" else CATALOG_SCHEMA,
        "profile": CONTENT_PROFILE if profile == "content_tokens_v1" else CATALOG_PROFILE,
        "status": "full_selected_unreviewed_relational_batch_evaluated",
        "inputs": {name: {"sha256": expected, "bytes": len(raw)} for name, raw, expected in (
            ("population", population_raw, expected_population_sha256), ("references", references_raw, expected_references_sha256),
            ("predictions", predictions_raw, expected_predictions_sha256))},
        "population": {"population_sha256": expected_population_sha256, "partition": population["partition"],
            "selection_sha256": population["selection_sha256"], "ordered_ids": expected_ids},
        "reference_availability": {"available": available, "unavailable": count - available,
            "total": count, "fraction": available / count if count else None},
        "coverage": {"valid": not (missing or duplicate or unexpected or unidentified), "expected_count": count,
            "prediction_row_count": len(ledger), "missing_ids": missing, "duplicate_ids": duplicate,
            "unexpected_ids": unexpected, "unidentifiable_indices": unidentified},
        "observation_ledger": ledger, "occurrences": occurrences, "terminal_counts": terminal,
        "valid_typed_output": {"count": valid, "total": count, "fraction": valid / count if count else None},
        "full_selected_structure_diagnostics": {name: _helper()._fraction(matched[name], count) for name in COMPARISON_FIELDS},
        "comparable_pair_structure_diagnostics": {name: _helper()._fraction(matched[name], terminal["compared"]) for name in COMPARISON_FIELDS},
        "generation": generation, "generation_issues": issues, "producer_pins": dict(pins),
        "authority": dict(FALSE_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "generation_claims_are_declarations_only": True, "metric_reference_access": True,
        "limitations": [
            "The independently pinned selected population is the denominator; selection, partition and source/context hashes remain unauthenticated caller declarations.",
            "Current comparison scope is exact tdfol/tdfol_default@1.0.0 with source_binding=null and the existing bounded Object-predicate relational fragment; wider logic families are not qualified.",
            "Available references are replayed authored unreviewed declarations, not reviewed statutory gold; unavailable references remain in the denominator.",
            "All observations retain arrival indices and full canonical row hashes; duplicates never select a favorable candidate and unexpected observations never alter the population denominator.",
            "Generation dimension/checkpoint/encoder/settings fields and no-target flags are declarations only; no model, numerical execution, target-withholding or latent-only inference is authenticated.",
            "No decoder inference receipt adapter is supplied. Existing single-rule deontic observation evidence does not establish these typed requests as learned relational decoder outputs.",
            "File snapshots and known owner import anchors do not generally prove executed bytecode for preloaded unanchored modules; a qualified fresh checked-buffer native run supplies that separate execution context.",
            "Candidate lowering and existing public replay are deterministic syntax postprocessing, not model generation or legal-source equivalence.",
            "request_utf8 covers bounded UTF8 text, including malformed candidate JSON; arbitrary nonUTF8 model byte streams are outside this schema and invalid outer UTF8 refuses intake.",
            "Unsupported is an explicit caller abstention category; rejected typed outputs do not establish a syntax-versus-family-capability taxonomy.",
            "Full selected and comparable-pair rates are separate descriptive structural diagnostics; neither is reviewed accuracy or training qualification.",
            "No models, training, native Lake/backend execution, legal review, admission or publication occurs; existing owners may regenerate syntax-only Lean text.",
        ]}
    result["content_codec"] = {"schema": predictions["codec"]["schema"], "sha256": predictions["codec_sha256"]}
    result["declared_operational_statuses_are_unverified"] = True
    result["content_context_claims_are_declarations_only"] = True
    result["authority"].update(dict.fromkeys(("permitted_inference_context_verified",
        "content_context_origin_verified", "content_context_independence_verified",
        "checkpoint_compatibility_verified"), False))
    result["limitations"] = [line for line in result["limitations"] if not line.startswith((
        "No decoder inference receipt adapter", "request_utf8 covers", "Unsupported is an explicit"))]
    result["limitations"].extend([
        "Raw content tokens are interpreted only with each observation's separately committed signature/ordered-role context; source context_sha256 is a different binding.",
        "Context origin labels are unverified declarations. Authored fixtures and target-derived label contexts do not establish permitted source-only or held-out inference; caller-supplied context is also unverified.",
        "A decoder_declared generation with target_derived_label context contradicts its no-target-access declaration and receives no comparison credit; authored-control transport diagnostics remain conditional.",
        "Every observation and complete available content-decoder/prediction report is retained, including duplicate, unexpected and unidentifiable observations; no favorable observation is selected.",
        "Prediction decoding receives no reference, target identity sidecar or repair map. Content/context generate fresh IDs and binder names; exact identity, declared structure and lexical alpha structure remain distinct diagnostics.",
        "All comparisons are conditional on the supplied unverified vocabulary and ordered roles; the unchanged profile requires every declared predicate to occur and does not qualify broad-catalog selection.",
        "The fixed 537-entry content vocabulary admits at most 512 total IDs including BOS/EOS. This does not qualify a numerical head, checkpoint, target withholding, trained model or provider token savings.",
        "Incomplete, invalid frames, invalid content and exhausted local token budgets remain distinct; invalid UTF8 is not representable by this fixed lexical vocabulary and is not inferred from missing output.",
        "Explicit error, timeout, cancellation and not_started are caller declarations. Actual context, owner, source or full-bound refusal and interruption abort without a partial report.",
        "The complete report retains the unchanged 8MiB bound; no context, prediction, identity or selected occurrence is dropped to fit it. Archival exact restoration and unary definition profiles remain separate owners.",
    ])
    result["accounting_core"] = {"schema": CORE_SCHEMA, "profile": profile, "source_sha256": _SELF_PIN,
        "legacy_accounting_source_sha256": _LEGACY_SHA}
    if profile == "catalog_tokens_v1":
        result["catalog_codec"] = result.pop("content_codec")
        result["catalog_context_claims_are_declarations_only"] = result.pop("content_context_claims_are_declarations_only")
        for key in ("content_context_origin_verified", "content_context_independence_verified"):
            result["authority"][key.replace("content_context", "catalog_context")] = result["authority"].pop(key)
        result["authority"]["numerical_head_compatible"] = False
        old_scope = "All comparisons are conditional on the supplied unverified vocabulary and ordered roles; the unchanged profile requires every declared predicate to occur and does not qualify broad-catalog selection."
        _need(old_scope in result["limitations"], "extracted content scope statement differs")
        result["limitations"] = [
            "All comparisons are conditional on the supplied unverified full catalog. The explicit catalog profile permits a generated nonempty predicate subset; this is not context permission or legal applicability."
            if line == old_scope else line for line in result["limitations"]]
        result["limitations"].extend([
            "The complete original catalog, raw/canonical context commitments, original-index content, subset/unused/map/role indices, effective prediction and outer catalog identity remain in each available decoder report.",
            "Catalog selection follows generated references in original catalog order; only the independently replayed effective prediction supplies candidate request bytes. No reference repairs, selects or authorizes that context.",
            "The additive catalog facade and core have separate source pins. The pinned historical v1 batch owner and its consumers are unchanged.",
        ])
    return result


def prepare_relational_batch_core_v1(population_raw, references_raw, predictions_raw, *, profile,
        expected_population_sha256, expected_references_sha256, expected_predictions_sha256):
    """Replay original inputs under exactly one fixed, unreviewed token profile."""
    initial_fixed = _fixed_sources(profile)
    originals, original_hashes, modules, initial = None, None, None, None

    def fence():
        _need(_fixed_sources(profile) == initial_fixed, "fixed operation source custody changed")
        if originals is not None:
            _need(tuple(_digest(value, bound) for value, bound in originals) == original_hashes,
                  "detached original batch inputs changed")
        if modules is not None:
            current = _source_snapshots(profile, modules)
            _need(initial is None or current == initial, "trusted operation sources changed during evaluation")

    with _guard(fence):
        population, references, predictions, generation, issues, observations = _preflight_assets(
            population_raw, references_raw, predictions_raw, expected_population_sha256,
            expected_references_sha256, expected_predictions_sha256, profile=profile)
        originals = ((population, MAX_POPULATION_BYTES), (references, MAX_REFERENCES_BYTES),
                     (predictions, MAX_PREDICTIONS_BYTES))
        original_hashes = tuple(_digest(value, bound) for value, bound in originals)
        modules = _load_owners(profile)
        initial = _source_snapshots(profile, modules)
        pins = {name: observed[0] for name, observed in initial.items()}
        relational = modules["logic/autoformal/legal_relational_norm_v1.py"]
        paired = modules["logic/autoformal/legal_relational_reconstruction_v1.py"]
        if profile == "content_tokens_v1":
            codec_owner = modules["logic/formalization/autoencoder/legal_compact_content_tokens_v1.py"]
            actual_codec_sha = codec_owner.compact_content_token_codec_sha256(predictions["codec"])
        else:
            codec_owner = modules["logic/formalization/autoencoder/legal_compact_catalog_tokens_v1.py"]
            actual_codec_sha = codec_owner.compact_catalog_token_codec_sha256(predictions["codec"])
        _need(actual_codec_sha == predictions["codec_sha256"], "fixed profile codec differs")
        fence()
        _validate_references(references, relational, pins, fence)
        records = _decode_observations(observations, predictions, profile, modules, pins, initial, fence)
        indexed = _index_observations(records, population)
        by_id = indexed[0]
        terminal, matched = dict.fromkeys(CONTENT_TERMINAL_STATUSES, 0), dict.fromkeys(COMPARISON_FIELDS, 0)
        occurrences, retained_output_bytes = [], 0
        for index, source in enumerate(population["rows"]):
            reference = references["rows"][index]
            indices = list(by_id.get(source["id"], []))
            occurrence = {"index": index, **source, "reference": {key: reference[key] for key in
                ("status", "request_sha256", "report_sha256", "reason")}, "observation_indices": indices,
                "declared_status": None, "status": None, "reasons": [], "pair_diagnostic": None}
            status, reasons, declared = _classify_occurrence(indices, records)
            occurrence["declared_status"] = declared
            if status is None:
                status, reasons, diagnostic = _compare_candidate(records[indices[0]], reference, relational, paired, pins, fence)
                occurrence["pair_diagnostic"] = diagnostic
                if diagnostic is not None:
                    for name in COMPARISON_FIELDS:
                        matched[name] += int(diagnostic["comparisons"][name])
            occurrence["status"], occurrence["reasons"] = status, reasons
            terminal[status] += 1
            for observation_index in indices:
                records[observation_index]["outcome"] = status
            retained_output_bytes += len(_wire(occurrence, MAX_OUTPUT_BYTES))
            _need(retained_output_bytes <= MAX_OUTPUT_BYTES, "complete occurrence output bound exceeded")
            occurrences.append(occurrence)
        result = _assemble_report(population_raw, references_raw, predictions_raw, expected_population_sha256,
            expected_references_sha256, expected_predictions_sha256, population, references, predictions,
            generation, issues, records, occurrences, terminal, matched, indexed, pins, profile)
        raw = _wire(result, MAX_OUTPUT_BYTES)
        fence()
        return json.loads(raw)


def relational_batch_core_sha256(report):
    """Hash one complete successor report; this self-address grants no authority."""
    _need(type(report) is dict and type(report.get("accounting_core")) is dict,
          "complete batch-core report required")
    profile = report["accounting_core"].get("profile")
    initial = _fixed_sources(profile)
    with _guard(lambda: _need(_fixed_sources(profile) == initial, "core hash source custody changed")):
        detached = _copy(report, MAX_OUTPUT_BYTES)
        context = "content" if profile == "content_tokens_v1" else "catalog"
        _need(set(detached) == _OUTPUT_FIELDS | {"accounting_core", context + "_codec",
            "declared_operational_statuses_are_unverified", context + "_context_claims_are_declarations_only"}
            and detached["schema"] == (CONTENT_SCHEMA if profile == "content_tokens_v1" else CATALOG_SCHEMA)
            and detached["profile"] == (CONTENT_PROFILE if profile == "content_tokens_v1" else CATALOG_PROFILE)
            and detached["accounting_core"] == {"schema": CORE_SCHEMA, "profile": profile,
                "source_sha256": _SELF_PIN, "legacy_accounting_source_sha256": _LEGACY_SHA},
            "closed versioned batch-core identity required")
        return _digest(detached, MAX_OUTPUT_BYTES)


def validate_relational_batch_core_v1(report, population_raw, references_raw, predictions_raw, *, profile,
        expected_evaluation_sha256, expected_population_sha256, expected_references_sha256, expected_predictions_sha256):
    """Full original-bound regeneration; no supplied decoded record is accepted."""
    _need(_is_sha(expected_evaluation_sha256), "independent complete evaluation SHA256 required")
    offered = _copy(report, MAX_OUTPUT_BYTES)
    _need(relational_batch_core_sha256(offered) == expected_evaluation_sha256,
          "independent complete core evaluation pin differs")
    original = _wire(offered, MAX_OUTPUT_BYTES)
    regenerated = prepare_relational_batch_core_v1(population_raw, references_raw, predictions_raw, profile=profile,
        expected_population_sha256=expected_population_sha256, expected_references_sha256=expected_references_sha256,
        expected_predictions_sha256=expected_predictions_sha256)
    _need(original == _wire(regenerated, MAX_OUTPUT_BYTES), "evaluation differs from full original-bound regeneration")
    return regenerated


__all__ = ["RelationalBatchCoreError", "prepare_relational_batch_core_v1", "relational_batch_core_sha256",
           "validate_relational_batch_core_v1"]
