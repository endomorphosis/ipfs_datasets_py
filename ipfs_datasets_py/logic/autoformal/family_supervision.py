"""Project one sentence into the logic families it actually needs.

The available families are first-order logic, deontic logic, temporal
first-order logic, temporal deontic first-order logic, cognitive event
calculus, and frame logic. A span does not receive every family. An
abstention still yields a fragment. A missing actor or action is a stitch
fixture that ``lake build Legal`` can compile and a later stage can join.
Neither a fragment nor a fixture is an admit.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

FAMILY_NAMES = ("fol", "deontic", "tfol", "tdfol", "cec", "frame_logic")
# Bridges the autoencoder trains against. A span still selects only some families.
TRAINING_BRIDGE_NAMES = ("modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec")
# Autoencoder views that correspond to a selected family. FOL and TFOL are
# recorded for later chaining; the autoencoder does not have those views.
_VIEW_FOR_FAMILY = {
    "deontic": "deontic",
    "tdfol": "tdfol",
    "cec": "cec",
    "frame_logic": "frame_logic",
}
_TEMPORAL_CUES = ("before", "after", "until", "when", "not later than")
_DEONTIC_MODALITY = {"O", "P", "F", "obligation", "permission", "prohibition"}
_LAKE_ENVIRONMENT = {"lake_not_on_path", "empty", "no_renderable_norms"}


def _norm(rule: Mapping[str, Any], text: str, span_id: str) -> dict[str, Any]:
    modality = str(rule.get("modality") or "")
    return {
        "action": str(rule.get("action") or ""),
        "actor": str(rule.get("actor") or ""),
        "modality": modality,
        "norm_type": {"O": "obligation", "P": "permission", "F": "prohibition"}.get(modality, modality),
        "object": str(rule.get("object") or ""),
        "source_id": span_id,
        "source_text": text,
        "text": text,
    }


def stitch_symbol(span_id: str, slot: str) -> str:
    """Join key for a later stage. The symbol names the span and the open slot."""

    return f"stitch:{span_id}:{slot}"


def open_slots(actor: str, action: str) -> list[str]:
    slots: list[str] = []
    if not str(actor or "").strip():
        slots.append("actor")
    if not str(action or "").strip():
        slots.append("action")
    return slots


def _temporal(text: str) -> bool:
    import re

    return re.search(r"\b(?:before|after|until|when|not later than)\b", text.lower()) is not None


def _text_deontic(text: str) -> bool:
    import re

    return re.search(r"\b(?:shall|must|may)\b", text.lower()) is not None


def select_families(text: str, rule: Mapping[str, Any]) -> list[str]:
    """Pick the families this sentence needs. Do not instantiate the others."""

    modality = str(rule.get("modality") or "")
    actor = str(rule.get("actor") or "").strip()
    action = str(rule.get("action") or "").strip()
    temporal = _temporal(text)
    deontic = modality in _DEONTIC_MODALITY or _text_deontic(text)
    if deontic and temporal:
        return ["tdfol"]
    if deontic:
        return ["deontic"]
    if temporal and (actor or action):
        return ["tfol"]
    if temporal:
        return ["tfol"]
    if action:
        return ["cec"]
    if actor:
        return ["fol"]
    return ["frame_logic"]


def _filled(rule: Mapping[str, Any], span_id: str) -> tuple[str, str, list[str]]:
    actor = str(rule.get("actor") or "").strip()
    action = str(rule.get("action") or "").strip()
    slots = open_slots(actor, action)
    if "actor" in slots:
        actor = stitch_symbol(span_id, "actor")
    if "action" in slots:
        action = stitch_symbol(span_id, "action")
    return actor, action, slots


def _frame_triples(span_id: str, actor: str, action: str, slots: Sequence[str]) -> list[dict[str, str]]:
    triples = [
        {"object": actor, "predicate": "actor", "subject": span_id},
        {"object": action, "predicate": "event", "subject": span_id},
    ]
    for slot in slots:
        triples.append({
            "object": stitch_symbol(span_id, slot),
            "predicate": "stitch",
            "subject": span_id,
        })
    return triples


def project_span_families(text: str, span_id: str = "span") -> dict[str, Any]:
    """Compile one span and record only the families that fit.

    An abstention still gets a fragment. A missing actor or action becomes a
    stitch fixture. Nothing here is a Lake admit.
    """

    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    from ipfs_datasets_py.logic.bridge.cec_dcec import _dcec_records
    from ipfs_datasets_py.logic.bridge.fol_tdfol import _tdfol_formula_records

    session = AutoformalSession()
    outcome = compile_span(session, text, span_id or "span")
    rules = [
        dict(row.rule)
        for row in session.rows
        if getattr(row, "status", "") in {"compiled", "roundtrip_ok"}
        and isinstance(getattr(row, "rule", None), dict)
        and "-partial" not in str(getattr(row, "document_id", ""))
    ]
    rule = dict(rules[0]) if rules else {"action": "", "actor": "", "modality": "", "object": ""}
    selected = select_families(text, rule)
    actor, action, slots = _filled(rule, span_id)
    obj = str(rule.get("object") or "").strip()
    modality = str(rule.get("modality") or "")
    families: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    norm = _norm({**rule, "action": action, "actor": actor, "object": obj}, text, span_id)
    if "deontic" in selected:
        formula = f"{modality}({actor}, {action}, {obj})".strip()
        families["deontic"] = {"formula": formula, "present": bool(formula), "triples": []}
    if "tdfol" in selected:
        try:
            records = _tdfol_formula_records([norm])
            formula = str((records[0] if records else {}).get("formula") or "")
        except Exception as exc:
            formula = ""
            errors.append(f"tdfol:{type(exc).__name__}")
        families["tdfol"] = {"formula": formula, "present": bool(formula), "triples": []}
    if "tfol" in selected:
        formula = f"Always({action}({actor}))"
        families["tfol"] = {"formula": formula, "present": True, "triples": []}
    if "fol" in selected:
        formula = f"{action or actor}({actor})"
        families["fol"] = {"formula": formula, "present": bool(formula), "triples": []}
    if "cec" in selected:
        try:
            records = _dcec_records([norm], document_id=span_id, source_text=text)
            formula = str((records[0] if records else {}).get("formula") or "")
        except Exception as exc:
            formula = ""
            errors.append(f"cec:{type(exc).__name__}")
        if not formula:
            formula = f"HoldsAt({action}({actor}), t0)"
        families["cec"] = {"formula": formula, "present": bool(formula), "triples": []}
    if "frame_logic" in selected or slots:
        if "frame_logic" not in selected:
            selected = [*selected, "frame_logic"]
        families["frame_logic"] = {
            "formula": f"frame({actor}, {action})",
            "present": True,
            "triples": _frame_triples(span_id, actor, action, slots),
        }
    stitch_rules: list[dict[str, str]] = []
    if slots:
        stitch_rules.append({
            "action": action,
            "actor": actor,
            "modality": "Frame",
            "object": obj,
        })
    missing = [name for name in selected if not families.get(name, {}).get("present")]
    return {
        "admitted": False,
        "available_families": list(FAMILY_NAMES),
        "compiler_status": str(outcome.get("compiler_status") or ""),
        "decompiled": str(outcome.get("decompiled") or ""),
        "errors": errors,
        "families": families,
        "formalized": False,
        "missing_families": missing,
        "rules": rules,
        "selected_families": selected,
        "span_id": span_id,
        "stitch": {
            "joins": [stitch_symbol(span_id, slot) for slot in slots],
            "open_slots": slots,
            "span_id": span_id,
        },
        "stitch_rules": stitch_rules,
    }


def lake_build_projection(
    projection: Mapping[str, Any],
    *,
    check: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """``lake build Legal`` for the projected norms. A build is not an admit."""

    from ipfs_datasets_py.logic.autoformal.lake_probe import lake_check, render_logic_batch

    rules = list(projection.get("rules") or []) + list(projection.get("stitch_rules") or [])
    source, count = render_logic_batch(rules)
    receipt = {
        "admitted": False,
        "error": "no_renderable_norms",
        "formalized": False,
        "lake_ok": False,
        "log": "",
        "target": "Legal",
        "theorem_count": count,
    }
    if count < 1 or not source.strip():
        return receipt
    checked = dict((check or lake_check)(source))
    receipt.update(checked)
    receipt["admitted"] = False
    receipt["formalized"] = False
    receipt["target"] = "Legal"
    receipt["theorem_count"] = count
    return receipt


def disagreement_reason(
    projection: Mapping[str, Any],
    autoencoder: Mapping[str, Any] | None,
    lake: Mapping[str, Any] | None,
) -> str:
    """Name why the autoencoder and the compiler/decompiler are not yet agreed.

    An empty string means this span does not open a supervisor goal.
    """

    if str(projection.get("compiler_status") or "") not in {"compiled", "roundtrip_ok"}:
        return "compiler_abstain"
    if projection.get("missing_families"):
        return "capture_not_in_decompilation"
    report = dict(autoencoder or {})
    if report.get("ok") is False and int(report.get("legal_ir_target_count") or 0) <= 0:
        return "inference_still_failing"
    views = report.get("view_distribution") if isinstance(report.get("view_distribution"), Mapping) else {}
    selected = [str(name) for name in projection.get("selected_families") or [] if str(name) in _VIEW_FOR_FAMILY]
    missing = [
        family for family in selected
        if views and float(views.get(_VIEW_FOR_FAMILY[family]) or 0) <= 0
    ]
    if missing or report.get("grammar_rejections"):
        return "capture_not_in_decompilation"
    if isinstance(lake, Mapping) and lake.get("lake_ok") is False:
        error = str(lake.get("error") or "")
        if error and error not in _LAKE_ENVIRONMENT:
            return "strict_roundtrip_failed"
    return ""


def family_goal_rows(
    samples: Sequence[Mapping[str, Any]],
    *,
    autoencoder: Mapping[str, Any] | None = None,
    lake_check: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """One agreement row per span. Disagreement is a goal input, not an admit."""

    rows = []
    projections = []
    for sample in samples:
        text = str(sample.get("text") or "")
        span_id = str(sample.get("source_span_id") or sample.get("id") or "span")
        if not text:
            continue
        projection = project_span_families(text, span_id)
        lake = lake_build_projection(projection, check=lake_check) if lake_check is not None else None
        reason = disagreement_reason(projection, autoencoder, lake)
        projections.append({"families": projection["families"], "lake": lake, "span_id": span_id})
        rows.append({
            "agrees": not reason,
            "canonical_citation": str(sample.get("canonical_citation") or ""),
            "decompiled": projection["decompiled"],
            "dropped": list(projection["missing_families"]),
            "entry_cid": str(sample.get("entry_cid") or ""),
            "id": span_id,
            "legal_id": str(sample.get("legal_id") or ""),
            "reason": reason,
            "skipped": False,
            "source_span_id": span_id,
            "text": text,
        })
    agreed = sum(1 for row in rows if row["agrees"])
    return {
        "admitted": False,
        "agreed": agreed,
        "agrees": bool(rows) and agreed == len(rows),
        "formalized": False,
        "operative": len(rows),
        "projections": projections,
        "reason": "" if rows and agreed == len(rows) else "compiler_disagreement",
        "router_called": False,
        "rows": rows,
        "wrote_compiler": False,
    }


def demote_failed_lake(spans: Sequence[Mapping[str, Any]], lake: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Open a supervisor gap when ``lake build Legal`` rejects a projected norm.

    A missing Lake install is not a compiler disagreement. A failed build is
    not an admit.
    """

    if not isinstance(lake, Mapping) or lake.get("lake_ok") is not False:
        return []
    if str(lake.get("error") or "") in _LAKE_ENVIRONMENT:
        return []
    fresh: list[dict[str, Any]] = []
    for span in spans:
        if not isinstance(span, dict) or span.get("strict_status") != "roundtrip_ok" or not span.get("rules"):
            continue
        span["admitted"] = False
        span["formalized"] = False
        span["strict_reason"] = "strict_roundtrip_failed"
        span["strict_status"] = "gap"
        fresh.append(span)
    return fresh


def census_autoencoder_span(
    text: str,
    span_id: str,
    autoencoder_output: str,
    scores: Mapping[str, Any],
    *,
    round_index: int = 0,
) -> dict[str, Any]:
    """Recompile the autoencoder text and compare it with the source fragment.

    A short holdout score is recorded against this round's threshold. Agreement
    does not admit the sentence.
    """

    from ipfs_datasets_py.logic.autoformal.span_agreement import metric_misses, threshold_at_round

    source = project_span_families(text, span_id)
    replica_text = str(autoencoder_output or "").strip()
    replica = project_span_families(replica_text, span_id + ":replica") if replica_text else None
    replicated = (
        replica is not None
        and replica["selected_families"] == source["selected_families"]
        and replica["stitch"]["open_slots"] == source["stitch"]["open_slots"]
    )
    threshold = threshold_at_round(round_index)
    misses = metric_misses(scores, threshold)
    if not replica_text or (misses and replicated):
        reason = "inference_still_failing"
    elif not replicated:
        # Both the compiler and the decompiler are in this scope, so a router
        # reply that edits either file can be drained.
        reason = "strict_roundtrip_failed"
    else:
        reason = ""
    capture = {
        "autoencoder_output": replica_text[:240],
        "below_threshold": misses,
        "holdout_scores": {
            key: scores.get(key)
            for key in ("cosine_similarity", "cross_entropy_loss", "reconstruction_loss")
        },
        "replicated": replicated,
        "selected_families": list(source["selected_families"]),
        "stitch": dict(source["stitch"]),
        "threshold": threshold,
        "training_bridges": list(TRAINING_BRIDGE_NAMES),
        "training_families": list(FAMILY_NAMES),
    }
    return {
        "agrees": not reason,
        "canonical_citation": "",
        "capture": capture,
        "decompiled": source["decompiled"],
        "dropped": list(source["stitch"]["open_slots"]),
        "entry_cid": "",
        "id": span_id,
        "legal_id": "",
        "reason": reason,
        "skipped": False,
        "source_span_id": span_id,
        "text": text,
    }


def supervisor_repair_goals(
    rows: Sequence[Mapping[str, Any]],
    *,
    release_id: str = "uscode-formal-logic",
    code_identity: str = "uscode-formal-compiler",
    model_identity: str = "router-not-yet-called",
) -> dict[str, Any]:
    """Seal compiler disagreements as repair packets and score misses as training jobs.

    The repair packet schema is the one the accelerate supervisor already claims.
    A training job is not a compiler edit and is not a model promotion.
    """

    from ipfs_datasets_py.logic.autoformal.supervisor_dispatch import TRAINING_SCHEMA
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import SCHEMA, repair_packets
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import discrepancy_tasks

    operative = [dict(row) for row in rows if not row.get("skipped")]
    repairs = [row for row in operative if row.get("reason") != "inference_still_failing" and row.get("agrees") is not True]
    training = [row for row in operative if row.get("reason") == "inference_still_failing" or (row.get("capture") or {}).get("below_threshold")]
    packets = repair_packets(
        {"admitted": False, "agrees": False, "formalized": False, "rows": repairs},
        release_id=release_id,
        code_identity=code_identity,
        model_identity=model_identity,
        query="US Code formal-logic autoformal campaign",
    ) if repairs else []
    training_goals = []
    for row in training:
        task = discrepancy_tasks(
            {"rows": [{**row, "reason": "inference_still_failing", "agrees": False}]},
            query="US Code formal-logic autoformal campaign",
            release_id=release_id,
        )
        if not task:
            continue
        training_goals.append({
            **task[0],
            "admitted": False,
            "capture": dict(row.get("capture") or {}),
            "formalized": False,
            "schema": TRAINING_SCHEMA,
            "work_kind": "autoencoder_training",
            "wrote_compiler": False,
        })
    return {
        "admitted": False,
        "formalized": False,
        "repair_packets": packets,
        "repair_schema": SCHEMA,
        "router_called": False,
        "training_goals": training_goals,
        "training_schema": TRAINING_SCHEMA,
        "wrote_compiler": False,
    }


def goals_for_family_disagreement(
    samples: Sequence[Mapping[str, Any]],
    *,
    autoencoder: Mapping[str, Any] | None = None,
    lake_check: Callable[[str], Mapping[str, Any]] | None = None,
    release_id: str = "uscode-formal-logic",
    campaign_title: str = "US Code formal-logic autoformal campaign",
) -> dict[str, Any]:
    """Build supervisor goals for spans the autoencoder and compiler do not share.

    Agreement creates no goal. The router is not called and no compiler is written.
    """

    from ipfs_datasets_py.logic.autoformal.supervisor_loop import spawn_goal_tree
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import discrepancy_tasks

    agreement = family_goal_rows(samples, autoencoder=autoencoder, lake_check=lake_check)
    tasks = discrepancy_tasks(agreement, query=campaign_title, release_id=release_id) if not agreement["agrees"] else []
    tree = spawn_goal_tree(tasks, release_id=release_id, campaign_title=campaign_title) if tasks else {"goals": [], "tasks": []}
    return {
        "admitted": False,
        "agreement": agreement,
        "formalized": False,
        "goal_count": len(tree.get("goals") or []),
        "goals": list(tree.get("goals") or []),
        "router_called": False,
        "subgoal_count": sum(1 for goal in tree.get("goals") or [] if goal.get("kind") == "subgoal"),
        "task_count": len(tasks),
        "wrote_compiler": False,
    }
