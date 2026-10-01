"""Reproject exact merged-checkpoint predictions with optional bound context.

This separate artifact does not rewrite a completed numerical round, its v1
DuckDB aggregation evidence, or the shipped model defaults. Requalifying needs
fresh native execution; serialized receipts are historical observations only.
"""
from pathlib import Path
import hashlib
import time

from . import contracts as c, runner
from . import projections_v2 as projections
from .. import structured_source_384 as decoder

CONTEXTS_SCHEMA = "distributed-384-projection-contexts/v1"
SCHEMA = "distributed-384-checkpoint-projections/v1"


def _contexts(path, plan, checkpoint_ref, rows):
    if path is None:
        return {}, None, None
    value, reference = c.read_json_bound(path)
    c.require(type(value) is dict and set(value) == {"schema", "plan_id", "checkpoint_sha256", "rows", *c.FALSE}
              and value["schema"] == CONTEXTS_SCHEMA, "closed checkpoint projection contexts required")
    c.require(all(value[k] is False for k in c.FALSE), "contexts cannot grant authority")
    c.require(value["plan_id"] == plan["plan_id"] and value["checkpoint_sha256"] == checkpoint_ref["sha256"],
              "contexts belong to another checkpoint or round")
    c.require(type(value["rows"]) is list and len(value["rows"]) <= len(rows), "bounded projection context rows required")
    ids = {r["id"] for r in rows}
    result = {}
    for row in value["rows"]:
        c.require(type(row) is dict and set(row) == {"id", "context"} and type(row["id"]) is str
            and row["id"] in ids and row["id"] not in result, "unique selected context row identity required")
        c.require(type(row["context"]) is dict, "supplied context must be a bound envelope object")
        result[row["id"]] = row["context"]
    return result, reference, value


def qualify_round(round_dir, checkpoint_path, output_dir, *, contexts_path=None, row_ids=None,
                  required_families=None, lake_executable=None, java_executable=None,
                  tla2tools_jar=None, timeout_seconds=60):
    started = time.perf_counter()
    data = runner._round(round_dir, validation=True)
    plan, base = data["plan"], data["base"]
    checkpoint, checkpoint_ref = c.read_json_bound(checkpoint_path)
    runtime = decoder.Runtime(checkpoint)
    c.require(checkpoint["domain_id"] == plan["domain_id"] and
        checkpoint["training"].get("plan_id") == plan["plan_id"] and
        checkpoint["training"].get("base_checkpoint_sha256") == plan["base_checkpoint_sha256"] and
        checkpoint["training"].get("recipe_sha256") == plan["recipe_sha256"], "checkpoint training round differs")
    c.require(checkpoint["projection_state"] == base["projection_state"] and
        checkpoint["target_schema"] == base["target_schema"] and
        checkpoint["training_manifest"] == plan["training_manifest"] and
        checkpoint["validation_manifest"] == plan["validation_manifest"], "checkpoint corpus or frozen encoder differs")
    rows = [{k: row[k] for k in ("id", "source_text", "embedding")} for row in data["validation"]]
    if row_ids is not None:
        known = {r["id"] for r in rows}
        c.require(type(row_ids) in (list, tuple) and row_ids and all(type(i) is str and i in known for i in row_ids)
                  and len(set(row_ids)) == len(row_ids), "unique known nonempty validation row selection required")
        selected = set(row_ids)
        rows = [r for r in rows if r["id"] in selected]
    contexts, context_ref, context_value = _contexts(contexts_path, plan, checkpoint_ref, rows)
    predictions = runtime.infer(rows)["rows"]
    c.require(len(predictions) == len(rows), "checkpoint prediction count differs")
    prepared = []
    # Prepare all declarations before executing any tools. Context can only
    # supplement the current prediction, never substitute a target/teacher.
    for row, prediction in zip(rows, predictions):
        c.require(prediction["id"] == row["id"] and prediction["source_sha256"] ==
            hashlib.sha256(row["source_text"].encode()).hexdigest() and
            prediction["head_sha256"] == checkpoint["head_sha256"] and
            prediction["projection_sha256"] == checkpoint["projection_sha256"] and
            prediction["target_access"] is False and prediction["teacher_forcing"] is False,
            "prediction provenance or inference input scope differs")
        prepared.append(projections.prepare_candidate_projection(plan["domain_id"], prediction["candidate_ir"],
            row["source_text"], context=contexts.get(row["id"]), required_families=required_families))
    root = Path(output_dir).absolute()
    c.require(not root.exists() and not root.is_symlink(), "fresh projection evidence directory required")
    c.write_json(root / "job.json", dict(schema=SCHEMA, **c.binding(plan), checkpoint=checkpoint_ref,
        input_rows_sha256=c.digest(rows), contexts=context_ref, row_ids=[r["id"] for r in rows],
        requested_families=prepared[0].report["requested_families"],
        native_check_requested=lake_executable is not None, **c.FALSE))
    c.write_json(root / "inference-inputs.json", rows)
    c.write_json(root / "inference.json", predictions)
    if contexts_path is not None:
        c.write_json(root / "contexts.json", context_value)
    records = []
    for i, (row, prediction, handle) in enumerate(zip(rows, predictions, prepared)):
        report = handle.report
        if lake_executable is not None:
            if handle.native_report is not None:
                report = projections.check_candidate_projection(handle, lake_executable=lake_executable,
                    output_directory=root / ("native-" + str(i)), java_executable=java_executable,
                    tla2tools_jar=tla2tools_jar, timeout_seconds=timeout_seconds)
            elif plan["domain_id"] == "security_ir" and prediction["candidate_ir"] is not None:
                # Existing source-expression path can execute without inventing
                # the CodeUnit vulnerability metadata required by broader views.
                from .. import source_program_lake_384 as source_lake
                source_rows = [dict(id=row["id"], source_text=row["source_text"], candidate_ir=prediction["candidate_ir"])]
                execution = source_lake.build_source_program_lake(source_rows,
                    lake_executable=lake_executable, output_directory=root / ("native-" + str(i)),
                    timeout_seconds=timeout_seconds)
                receipt = source_lake.verify_source_program_lake(execution, source_rows)
                report.pop("report_sha256")
                report.update(lake_build_executed=receipt["backend_executed"],
                    source_program_execution={k: v for k, v in receipt.items() if k != "lean_source"},
                    live_issued_handle_verified=True, saved_receipt_is_live_authority=False)
                for family in report["families"]:
                    family["native_checks_passed"] = (family["family_id"] == "program" and receipt["all_candidates_compiled"])
                report["all_requested_native_checks_passed"] = bool(report["families"]) and all(
                    family["native_checks_passed"] for family in report["families"])
                report["report_sha256"] = c.digest(report)
        path = c.write_json(root / "reports" / (report["report_sha256"] + ".json"), report)
        records.append(dict(id=row["id"], candidate_sha256=c.digest(prediction["candidate_ir"]),
            report_path=str(path), report_sha256=report["report_sha256"],
            context_supplied=row["id"] in contexts, report=report))
    counts = {f: dict(supported=0, missing_context=0, failed=0, native_checks_passed=0)
              for f in prepared[0].report["requested_families"]}
    for record in records:
        for family in record["report"]["families"]:
            counts[family["family_id"]][family["status"]] += 1
            counts[family["family_id"]]["native_checks_passed"] += family.get("native_checks_passed", False)
    summary = dict(schema=SCHEMA, **c.binding(plan), checkpoint=checkpoint_ref, contexts=context_ref,
        rows=len(rows), full_validation_rows=len(data["validation"]), selected_subset=len(rows) != len(data["validation"]),
        family_counts=counts, records=[{k: v for k, v in r.items() if k != "report"} for r in records],
        all_required_families_supported=all(r["report"]["all_required_families_supported"] for r in records),
        all_auxiliary_families_supported=all(r["report"]["all_auxiliary_families_supported"] for r in records),
        all_requested_dependencies_supported=all(r["report"]["all_requested_dependencies_supported"] for r in records),
        all_requested_native_checks_passed=all(r["report"]["all_requested_native_checks_passed"] for r in records),
        native_check_scope="syntax_and_types_only",
        evaluation_scope="training_round_tuning_predictions_with_explicit_optional_declarations",
        target_access=False, context_inferred_by_model=False, source_model_fidelity_verified=False,
        elapsed_seconds=time.perf_counter()-started, **c.FALSE)
    c.write_json(root / "summary.json", summary)
    return summary
