"""Separate learned 384D NumPy unary-selection fragment, never a scalar widening.

The unchanged shared structured decoder predicts a canonical CALL expression.
Source qualification compares that unchanged prediction to an independently
replayed whole-file ProgramIR. Names, imports and spans remain provenance; no
deterministic prediction repair, numerical execution or proof takes place.
The initial grammar deliberately covers only a direct argmax/argmin return.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from . import source_function_units as units
from . import structured_source_384 as shared
from ...software_contracts import source_unit_numerical_links as links
from ...software_verification import numerical_logic as logic
from ...software_verification.program import ProgramExpression

PROFILE = "numpy-unary-selection-384@1"
SCHEMA = "numerical-selection-384-checkpoint@1"
CORPUS_SCHEMA = "numerical-selection-384-corpus@1"
MAX_ROWS = 128
MAX_BYTES = shared.MAX_BYTES
FALSE = dict(proof_authority=False, completion_authority=False, execution_authority=False,
    source_semantics_verified=False, whole_program_semantics_verified=False,
    source_obligations_discharged=0, scalar_profile_changed=False,
    source_executed=False, training_on_benchmark=False)


class NumericalSelectionError(ValueError):
    """A profile, corpus, model or source/candidate binding is outside scope."""


def _require(condition, message):
    if not condition:
        raise NumericalSelectionError(message)


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise NumericalSelectionError("bounded inert numerical profile JSON required") from exc
    _require(len(raw) <= MAX_BYTES, "numerical profile JSON exceeds bound")
    return raw


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(_wire(value))


def _pins():
    return dict(profile=_sha(Path(__file__).read_bytes()), extraction=units.pins(),
        shared=shared._implementation(), links=links._pins())


def _target(callee, parameter):
    _require(callee in ("numpy.argmax", "numpy.argmin") and type(parameter) is int
             and 0 <= parameter < 4, "closed selection production required")
    operands = ("expr:callee", f"expr:parameter:{parameter}")
    return dict(kind="program_expression", document=ProgramExpression(
        "expr:selection", "call", "python.object", operand_ids=operands,
        evaluation_order=operands, operator=callee, source_ref_ids=("source:selection",),
        attributes=dict(opaque=True, call_kind="python.call", positional_count=1,
            keyword_names=[], qualified_callee=callee, imported_callee=callee,
            callee_resolution="declared_import", runtime_identity_verified=False)).to_dict())


def prepare_selection_unit(*, source_bytes, path, unit_id=None):
    """Prepare one authored/inference source unit with exact module context.

    The target is a deterministic training label/checking reference, not learned
    output. Full original text is the embedding input so imports are not lost.
    ``unit_id=None`` is allowed only because this profile requires a singleton.
    This pure API never loads weights, embeds text, or executes target code.
    """
    _require(type(source_bytes) is bytes and 0 < len(source_bytes) <= 65536,
             "bounded exact UTF-8 source bytes required")
    try:
        text = source_bytes.decode("utf-8")
        tree = ast.parse(text)
    except (UnicodeError, SyntaxError, ValueError, RecursionError) as exc:
        raise NumericalSelectionError("complete Python source required") from exc
    _require(len(text) <= 16384, "shared source provenance character bound exceeded")
    inventory = units.extract_function_units(source_bytes=source_bytes,
        source_sha256=_sha(source_bytes), source_path=path)
    _require(inventory["status"] == "inventoried" and len(inventory["units"]) == 1,
             "one exactly mapped function unit required")
    unit = inventory["units"][0]
    _require(unit["status"] == "eligible" and (unit_id is None or unit_id == unit["unit_id"]),
             "exact eligible source unit identity required")
    functions = [node for node in tree.body if type(node) is ast.FunctionDef]
    _require(len(functions) == 1 and all(type(node) in (ast.Import, ast.ImportFrom, ast.FunctionDef)
             for node in tree.body) and not tree.type_ignores,
             "only module imports and one plain function are supported")
    function = functions[0]
    args = function.args
    _require(not (function.decorator_list or function.returns or function.type_comment
        or getattr(function, "type_params", ()) or args.posonlyargs or args.kwonlyargs
        or args.vararg or args.kwarg or args.defaults or args.kw_defaults)
        and 1 <= len(args.args) <= 4 and all(arg.annotation is None and not arg.type_comment for arg in args.args),
        "plain one-to-four-parameter selection signature required")
    parameters = [arg.arg for arg in args.args]
    _require(len(set(parameters)) == len(parameters) and all(name.isascii() for name in parameters),
             "distinct ASCII parameter names required")
    _require(len(function.body) == 1 and type(function.body[0]) is ast.Return
             and type(function.body[0].value) is ast.Call,
             "one direct unary selection call return required")
    call_ast = function.body[0].value
    _require(len(call_ast.args) == 1 and type(call_ast.args[0]) is ast.Name
             and call_ast.args[0].id in parameters and not call_ast.keywords,
             "one positional parameter operand without keywords or nesting required")
    native = logic.formalize_numerical_source(text, path=path)
    bound = links.bind_function_unit_logic(source_bytes=source_bytes,
        unit_inventory=inventory, numerical_report=native)
    link = bound["links"][0]
    _require(link["status"] == "matched" and link["structural_status"] == "structurally_complete",
             "complete source-bound numerical function required")
    program = native["structural"]["program"]
    native_function, = program["functions"]
    commands = {row["command_id"]: row for row in program["commands"]}
    expressions = {row["expression_id"]: row for row in program["expressions"]}
    blocks = native_function["cfg"]["blocks"]
    _require(len(blocks) == 1 and len(blocks[0]["command_ids"]) == 1,
             "single native return command required")
    command = commands[blocks[0]["command_ids"][0]]
    _require(command["kind"] == "return" and len(command["expression_ids"]) == 1,
             "exact native return expression required")
    call = expressions[command["expression_ids"][0]]
    attrs = call["attributes"]
    callee = attrs.get("imported_callee")
    _require(call["kind"] == "call" and attrs.get("callee_resolution") == "declared_import"
             and callee in ("numpy.argmax", "numpy.argmin") and attrs.get("positional_count") == 1
             and attrs.get("keyword_names") == [] and len(call["operand_ids"]) == 2,
             "unshadowed declared NumPy argmax/argmin call required")
    position = parameters.index(call_ast.args[0].id)
    argument = expressions[call["operand_ids"][1]]
    # ProgramFunction parameter IDs are ordered by source argument position.
    _require(argument["kind"] == "symbol"
             and argument["symbol_ids"] == [native_function["parameter_symbol_ids"][position]],
             "native parameter role differs from source")
    target = _target(callee, position)
    clone = dict(parameter_count=len(parameters), callee=callee, parameter_position=position)
    return dict(schema="numerical-selection-source-unit@1", profile=PROFILE,
        path=path, source_sha256=_sha(source_bytes), unit_id=unit["unit_id"],
        normalized_body_sha256=unit["normalized_body_sha256"],
        model_input_text=text, embedding_input_scope="exact_original_single_function_module",
        function_id=link["function_id"], source_ref_ids=call["source_ref_ids"], span_ids=call["span_ids"],
        start_byte=unit["start_byte"], end_byte=unit["end_byte"],
        canonical_roles=dict(parameter_position=position, parameter_count=len(parameters),
            callee_expression_id=call["operand_ids"][0], argument_expression_id=call["operand_ids"][1],
            parameter_symbol_id=argument["symbol_ids"][0], source_expression_id=call["expression_id"]),
        target=target, target_sha256=_digest(target), clone_sha256=_digest(clone),
        clone_scope="callee_and_parameter_position_and_signature_arity; all_identifier_and_import_alias_renames_collapsed",
        numerical_report_sha256=bound["numerical_report_sha256"], link_report_sha256=bound["report_sha256"],
        import_context=bound["import_context"], pending_obligation_ids=link["pending_obligation_ids"],
        family_artifact_ids=link["family_artifact_ids"], artifacts=bound["artifacts"],
        label_origin="independent_deterministic_source_replay", model_inference_executed=False, **FALSE)


def prepare_selection_corpus(rows):
    """Prepare explicit authored splits; reject rename/group/source leakage.

    Callers supply reviewed, independently authored inputs. This API does not
    discover repository files or accept a benchmark-derived training role.
    """
    _require(type(rows) is list and 3 <= len(rows) <= MAX_ROWS, "three to128 authored rows required")
    prepared, roles, seen = [], {}, set()
    fields = {"source_text", "path", "unit_id", "role", "group_id", "provenance"}
    for row in rows:
        _require(type(row) is dict and set(row) == fields, "closed authored corpus row required")
        _require(row["provenance"] == "independently_authored" and row["role"] in ("train", "validation", "holdout"),
                 "independently authored source and explicit split role required")
        _require(type(row["group_id"]) is str and 0 < len(row["group_id"]) <= 256
                 and type(row["source_text"]) is str, "bounded authored group/source required")
        unit = prepare_selection_unit(source_bytes=row["source_text"].encode(),
            path=row["path"], unit_id=row["unit_id"])
        _require(unit["unit_id"] not in seen, "duplicate source unit")
        seen.add(unit["unit_id"])
        for name, value in (("group", row["group_id"]), ("source", unit["source_sha256"]),
                            ("clone", unit["clone_sha256"])):
            prior = roles.setdefault((name, value), row["role"])
            _require(prior == row["role"], "source, alpha-clone or group crosses split roles")
        prepared.append(dict(unit=unit, role=row["role"], group_id=row["group_id"]))
    _require({row["role"] for row in prepared} == {"train", "validation", "holdout"},
             "all three authored split roles required")
    result = dict(schema=CORPUS_SCHEMA, profile=PROFILE, producer=_pins(),
        inputs=deepcopy(rows), rows=prepared, holdout_used_for_selection=False,
        provenance_status="caller_declared_authorship; external_provenance_review_required", **FALSE)
    result["corpus_sha256"] = _digest(result)
    return result


def _corpus(corpus):
    _require(type(corpus) is dict and type(corpus.get("inputs")) is list, "native authored corpus required")
    expected = prepare_selection_corpus(corpus["inputs"])
    _require(_wire(corpus) == _wire(expected), "authored corpus differs from exact replay")
    return expected


def _rows(corpus, embeddings, selected_roles):
    selected = [row for row in corpus["rows"] if row["role"] in selected_roles]
    _require(type(embeddings) is dict and set(embeddings) == {row["unit"]["unit_id"] for row in selected},
             "embeddings must exactly match requested split population")
    return [dict(id=row["unit"]["unit_id"], source_text=row["unit"]["model_input_text"],
        embedding=embeddings[row["unit"]["unit_id"]], target=row["unit"]["target"]) for row in selected]


def _manifest(corpus):
    return [dict(unit_id=row["unit"]["unit_id"], source_sha256=row["unit"]["source_sha256"],
        clone_sha256=row["unit"]["clone_sha256"], target_sha256=row["unit"]["target_sha256"],
        role=row["role"], group_id=row["group_id"]) for row in corpus["rows"]]


def train_selection_384(corpus, embeddings, *, parent_projection, config=None):
    """Fit a separate learned head; holdout vectors never enter this call.

    Parent weights must be an exact hash-bound, trained Legal384 checkpoint.
    The shared ridge implementation freezes its inherited projection and does
    not overwrite that parent. Returned checkpoint is a new profile envelope.
    """
    corpus = _corpus(corpus)
    _require(type(parent_projection) is dict and set(parent_projection) == {"path", "sha256"},
             "exact hash-bound trained Legal384 parent path required")
    parent_path = Path(parent_projection["path"])
    _require(parent_path.is_file() and not parent_path.is_symlink()
             and parent_path.stat().st_nlink == 1
             and 0 < parent_path.stat().st_size <= MAX_BYTES,
             "bounded regular independent Legal parent required")
    parent_raw = parent_path.read_bytes()
    _require(0 < len(parent_raw) <= MAX_BYTES and _sha(parent_raw) == parent_projection["sha256"],
             "Legal parent bytes differ")
    fit_rows = _rows(corpus, embeddings, {"train", "validation"})
    train_ids = {row["unit"]["unit_id"] for row in corpus["rows"] if row["role"] == "train"}
    result = shared.train("security_ir", [row for row in fit_rows if row["id"] in train_ids],
        [row for row in fit_rows if row["id"] not in train_ids], parent_projection=parent_projection, config=config)
    _require(parent_path.read_bytes() == parent_raw, "Legal parent changed during separate training")
    checkpoint = dict(schema=SCHEMA, profile=PROFILE, producer=_pins(), checkpoint=result["checkpoint"],
        checkpoint_sha256=_digest(result["checkpoint"]), corpus_sha256=corpus["corpus_sha256"],
        corpus_manifest=_manifest(corpus), parent_sha256=parent_projection["sha256"],
        holdout_used_for_selection=False, **FALSE)
    NumericalSelectionRuntime384(checkpoint)
    return dict(checkpoint=checkpoint, metrics=result["metrics"], **FALSE)


class NumericalSelectionRuntime384:
    """Use learned predictions unchanged; source matching is a separate gate."""

    def __init__(self, checkpoint):
        fields = {"schema", "profile", "producer", "checkpoint", "checkpoint_sha256", "corpus_sha256",
                  "corpus_manifest", "parent_sha256", "holdout_used_for_selection", *FALSE}
        _require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint["schema"] == SCHEMA
                 and checkpoint["profile"] == PROFILE, "separate numerical selection checkpoint required")
        _require(checkpoint["producer"] == _pins() and all(type(checkpoint[k]) is type(v)
                 and checkpoint[k] == v for k, v in FALSE.items())
                 and checkpoint["holdout_used_for_selection"] is False, "profile pins or authority differs")
        _require(checkpoint["checkpoint_sha256"] == _digest(checkpoint["checkpoint"])
                 and checkpoint["parent_sha256"] == checkpoint["checkpoint"]["parent_sha256"],
                 "profile checkpoint or parent digest differs")
        runtime = shared.Runtime(checkpoint["checkpoint"])
        _require(runtime.describe()["domain_id"] == "security_ir", "Security ProgramExpression shared decoder required")
        schema = checkpoint["checkpoint"]["target_schema"]
        allowed = [_target(callee, position) for callee in ("numpy.argmax", "numpy.argmin") for position in range(4)]
        _require(schema["shape"] == shared._shape(allowed[0]), "checkpoint target is outside selection CALL grammar")
        leaves = [shared._scalar_leaves(target) for target in allowed]
        slots = {tuple(row["path"]): row["classes"] for row in schema["slots"]}
        for path, value in shared._scalar_leaves(schema["template"]).items():
            candidates = slots.get(path, [value])
            _require(all(_wire(candidate) in {_wire(row[path]) for row in leaves} for candidate in candidates),
                     "checkpoint scalar vocabulary is outside selection grammar")
        manifest = checkpoint["corpus_manifest"]
        _require(type(manifest) is list and 3 <= len(manifest) <= MAX_ROWS
                 and all(type(row) is dict and set(row) == {"unit_id", "source_sha256", "clone_sha256",
                     "target_sha256", "role", "group_id"} for row in manifest), "closed corpus manifest required")
        _require({row["role"] for row in manifest} == {"train", "validation", "holdout"}
                 and len({row["unit_id"] for row in manifest}) == len(manifest), "manifest split population differs")
        for role, native_name in (("train", "training_manifest"), ("validation", "validation_manifest")):
            expected = sorted((r["unit_id"], r["source_sha256"], r["target_sha256"]) for r in manifest if r["role"] == role)
            actual = sorted((r["id"], r["source_sha256"], r["target_sha256"]) for r in checkpoint["checkpoint"][native_name])
            _require(expected == actual, "shared training population differs from profile manifest")
        for key in ("source_sha256", "clone_sha256", "group_id"):
            seen = {}
            for row in manifest:
                prior = seen.setdefault(row[key], row["role"])
                _require(prior == row["role"], "checkpoint source/clone/group split overlap")
        self.checkpoint, self.runtime = deepcopy(checkpoint), runtime

    def infer(self, rows, *, weight_ablation=None):
        """Target-free original-source inputs; numerical vectors are caller supplied.

        The shared decoder receives only id/source_text/embedding. Full-file
        source replay is used afterward to accept or reject the prediction,
        never to replace its operator or operand classes. Embedding provenance
        requires the owning embedding producer, not a caller's vector claim.
        """
        _require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS, "bounded source inference rows required")
        prepared, inputs, seen = [], [], set()
        for row in rows:
            _require(type(row) is dict and set(row) == {"source_text", "path", "unit_id", "embedding"},
                     "closed target-free numerical source row required")
            _require(type(row["source_text"]) is str, "exact original source text required")
            unit = prepare_selection_unit(source_bytes=row["source_text"].encode(),
                path=row["path"], unit_id=row["unit_id"])
            _require(unit["unit_id"] not in seen, "duplicate numerical inference unit")
            seen.add(unit["unit_id"])
            prepared.append(unit)
            inputs.append(dict(id=unit["unit_id"], source_text=unit["model_input_text"], embedding=row["embedding"]))
        neural = self.runtime.infer(inputs, weight_ablation=weight_ablation)
        _require([r["id"] for r in neural["rows"]] == [r["unit_id"] for r in prepared],
                 "learned inference unit order differs")
        output = []
        for prediction, unit in zip(neural["rows"], prepared):
            prediction = deepcopy(prediction)
            matched = prediction["candidate_ir"] is not None and _wire(prediction["candidate_ir"]) == _wire(unit["target"])
            output.append(dict(prediction=prediction, unit_id=unit["unit_id"], path=unit["path"],
                source_sha256=unit["source_sha256"],
                status="source_aligned_fragment" if matched else "fail_open_source_mismatch",
                source_candidate_match=matched, candidate_replaced=False, continue_planning=True,
                source_binding={key: unit[key] for key in ("function_id", "source_ref_ids", "span_ids",
                    "start_byte", "end_byte", "canonical_roles", "import_context")},
                matched_projection_refs={key: unit[key] for key in ("numerical_report_sha256", "link_report_sha256",
                    "pending_obligation_ids", "family_artifact_ids", "artifacts")} if matched else None,
                binding_scope="one_learned_canonical_CALL_checked_against_source; deterministic_whole_file_artifacts",
                model_inference_executed=True, **FALSE))
        return dict(schema="numerical-selection-384-inference@1", profile=PROFILE, rows=output,
            checkpoint_sha256=_digest(self.checkpoint), head_sha256=self.runtime.checkpoint["head_sha256"],
            projection_sha256=self.runtime.checkpoint["projection_sha256"], weight_ablation=weight_ablation,
            model_inference_executed=True, source_only_inputs=True, embedding_provenance_verified=False, **FALSE)


def evaluate_selection_384(checkpoint, corpus, embeddings, *, weight_ablation=None):
    """Evaluate only the held-out population, retaining unsupported target counts."""
    corpus = _corpus(corpus)
    runtime = NumericalSelectionRuntime384(checkpoint)
    _require(corpus["corpus_sha256"] == checkpoint["corpus_sha256"], "held-out corpus identity differs")
    _require(_wire(checkpoint["corpus_manifest"]) == _wire(_manifest(corpus)),
             "checkpoint manifest differs from exact authored corpus replay")
    rows = _rows(corpus, embeddings, {"holdout"})
    score = shared.evaluate(checkpoint["checkpoint"], rows, weight_ablation=weight_ablation)
    by_id = {r["unit"]["unit_id"]: r["unit"] for r in corpus["rows"] if r["role"] == "holdout"}
    inference = runtime.infer([dict(source_text=r["source_text"], path=by_id[r["id"]]["path"],
        unit_id=r["id"], embedding=r["embedding"]) for r in rows], weight_ablation=weight_ablation)
    return dict(schema="numerical-selection-384-evaluation@1", profile=PROFILE,
        metrics={k: score[k] for k in ("count", "exact_targets", "valid_candidates", "within_training_coverage",
            "outside_training_coverage", "semantic_leaf_accuracy", "classifier_slot_accuracy")},
        source_aligned_fragments=sum(row["source_candidate_match"] for row in inference["rows"]),
        inference=inference, holdout_used_for_selection=False, **FALSE)


def load_selection_checkpoint(path, *, expected_sha256):
    path = Path(path)
    _require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1
             and 0 < path.stat().st_size <= MAX_BYTES, "bounded regular numerical checkpoint required")
    raw = path.read_bytes()
    _require(_sha(raw) == expected_sha256, "numerical checkpoint bytes differ")
    return NumericalSelectionRuntime384(shared.native._parse(raw))


__all__ = ["PROFILE", "SCHEMA", "NumericalSelectionError", "prepare_selection_unit",
    "prepare_selection_corpus", "train_selection_384", "NumericalSelectionRuntime384",
    "evaluate_selection_384", "load_selection_checkpoint"]
