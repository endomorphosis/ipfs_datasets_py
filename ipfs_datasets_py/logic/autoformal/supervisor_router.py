"""Ask llm_router for one edit after a strict gap is already a supervisor todo.

The proposal is not imported and is not applied to TypedDeonticCanonicalCompiler
or decompile_rule. Temperature stays 0. Agreement is not an admit.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping


def _named(values: Any) -> list[str]:
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        return []
    names: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def router_prompt(row: Mapping[str, Any]) -> str:
    """Name the approved files for this failure. Do not guess a compiler rewrite."""

    paths = _named(row.get("allowed_edit_paths"))
    if paths:
        target = (
            "Edit only the existing files in allowed_edit_paths. "
            "Do not replace them.\n"
        )
    else:
        target = (
            "No approved edit path is recorded for this failure. "
            "Do not guess a compiler or decompiler rewrite. Do not replace them.\n"
        )
    return (
        target
        + "Return strict JSON with keys compiler, decompiler, and parser. "
        "Include only keys whose files are listed. "
        "compiler must define compile. decompiler must define decompile. "
        "parser must define at least one function.\n"
        "A match is not an admit. Do not import Mathlib. Do not use sorry, admit, or axiom. "
        "Do not import modules. Do not call the network. Do not mark the Constitution formalized.\n"
        + json.dumps(
            {
                "allowed_edit_paths": paths,
                "decompiled": str(row.get("decompiled") or ""),
                "failure_mode": str(row.get("reason") or row.get("failure_mode") or ""),
                "preserve": _named(row.get("preserve")),
                "replace": _named(row.get("replace")),
                "source_span_id": str(row.get("source_span_id") or row.get("id") or ""),
                "source_text": str(row.get("text") or ""),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )


def row_for_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the sealed repair scope onto the clause row. The row alone has no file list."""

    row = dict(packet["row"]) if isinstance(packet.get("row"), Mapping) else {}
    row["preserve"] = list(packet.get("preserve") or [])
    row["replace"] = list(packet.get("replace") or [])
    row["allowed_edit_paths"] = list(packet.get("allowed_edit_paths") or [])
    return row


def resolve_gap_with_router(
    row: Mapping[str, Any],
    generate: Callable[..., str],
) -> dict[str, Any]:
    """One router call for one gap. The returned source is evidence, not a patch."""

    if row.get("agrees") is True or row.get("skipped") is True:
        return {
            "admitted": False,
            "formalized": False,
            "imported": False,
            "proposal_keys": [],
            "proposal_sha256": "",
            "reason": "not_a_gap",
            "router_called": False,
            "wrote_compiler": False,
        }
    kinds = _edit_kinds(row.get("allowed_edit_paths"))
    if not kinds:
        return _router_receipt(raw="", reason="no_approved_edit_path", router_called=False)
    raw = str(generate(router_prompt(row), temperature=0, task_kind="legal") or "")
    proposal, reason = _scoped_proposal(raw, kinds)
    if reason:
        return _router_receipt(raw="", reason=reason)
    digest = hashlib.sha256(json.dumps(proposal, sort_keys=True).encode("utf-8")).hexdigest()
    return _router_receipt(raw=digest, reason="", proposal_keys=sorted(proposal))


def provide_claimed_gap(
    attempt: Any,
    *,
    task_source: Any,
    generate: Callable[..., str],
) -> dict[str, Any]:
    """Router evidence for one claimed gap. This does not finish or admit the task."""

    from ipfs_datasets_py.logic.autoformal.supervisor_queue import read_packet

    task = task_source.get(str(getattr(attempt, "task_cid", "") or ""))
    body = getattr(task, "body", None) if task is not None else None
    if not isinstance(body, Mapping):
        receipt = _router_receipt(raw="", reason="task_missing")
        receipt["status"] = "router_proposal"
        receipt["accepted"] = False
        return receipt
    recorded = body.get("router_proposal")
    if (
        isinstance(recorded, Mapping)
        and str(recorded.get("proposal_sha256") or "")
        and recorded.get("applied") is False
        and recorded.get("imported") is False
        and recorded.get("wrote_compiler") is False
    ):
        receipt = _router_receipt(
            raw=str(recorded.get("proposal_sha256") or ""),
            reason="proposal_already_recorded",
            router_called=False,
            proposal_keys=_named(recorded.get("proposal_keys")),
        )
        receipt["status"] = "router_proposal"
        receipt["accepted"] = False
        return receipt
    packet = read_packet(Path(str(body.get("packet_path") or "")), str(body.get("packet_sha256") or ""))
    receipt = resolve_gap_with_router(row_for_packet(packet), generate)
    receipt["status"] = "router_proposal"
    # A proposal is not accepted repair evidence. Production mode must not
    # treat it as a completed edit.
    receipt["accepted"] = False
    return receipt


def _hold_clause(body: Mapping[str, Any]) -> dict[str, Any]:
    """Read the sealed clause. A missing packet does not drop the hold."""

    empty = {
        "allowed_edit_paths": [],
        "failure_reason": "",
        "replace": [],
        "source_readable": False,
        "source_span_id": "",
        "source_text": "",
    }
    path = str(body.get("packet_path") or "")
    digest = str(body.get("packet_sha256") or "")
    if not path or not digest:
        return empty
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import RepairQueueError, read_packet

    try:
        packet = read_packet(Path(path), digest)
    except (OSError, RepairQueueError, ValueError):
        return empty
    row = packet.get("row") if isinstance(packet, Mapping) else None
    if not isinstance(row, Mapping):
        return empty
    return {
        "allowed_edit_paths": _named(packet.get("allowed_edit_paths"))[:8],
        "failure_reason": str(row.get("reason") or ""),
        "replace": _named(packet.get("replace"))[:8],
        "source_readable": True,
        "source_span_id": str(row.get("source_span_id") or ""),
        "source_text": str(row.get("text") or "")[:240],
    }


def review_holds(task_source: Any) -> dict[str, Any]:
    """List parked router proposals. This does not claim, reopen, or admit them."""

    holds: list[dict[str, Any]] = []
    cursor = ""
    for _ in range(20):
        page = task_source.list_tasks(status="blocked", cursor=cursor, limit=100)
        for task in page.tasks:
            body = getattr(task, "body", None)
            if not isinstance(body, Mapping):
                continue
            receipt = body.get("completion_receipt")
            recorded = body.get("router_proposal")
            if not isinstance(receipt, Mapping) or receipt.get("operation") != "router_proposal_review":
                continue
            if not isinstance(recorded, Mapping) or recorded.get("applied") is not False:
                continue
            if recorded.get("imported") is not False or recorded.get("wrote_compiler") is not False:
                continue
            goal_cid = str(getattr(task, "goal_cid", "") or "")
            goal = None
            getter = getattr(getattr(task_source, "_intent", None), "get_goal", None)
            if goal_cid and callable(getter):
                goal = getter(goal_cid)
            goal_body = goal.get("body") if isinstance(goal, Mapping) and isinstance(goal.get("body"), Mapping) else {}
            holds.append({
                "admitted": False,
                "applied": False,
                "attempt_id": str(receipt.get("attempt_id") or ""),
                "formalized": False,
                "goal_cid": goal_cid,
                "goal_kind": str(goal_body.get("kind") or ""),
                "goal_status": str(goal.get("status") or "") if isinstance(goal, Mapping) else "",
                "goal_title": str(goal.get("title") or "") if isinstance(goal, Mapping) else "",
                "imported": False,
                "proposal_keys": _named(recorded.get("proposal_keys")),
                "proposal_sha256": str(recorded.get("proposal_sha256") or ""),
                "task_alias": str(getattr(task, "task_alias", "") or ""),
                "task_cid": str(getattr(task, "task_cid", "") or ""),
                "wrote_compiler": False,
                **_hold_clause(body),
            })
        cursor = str(getattr(page, "next_cursor", "") or "")
        if not cursor:
            break
    holds.sort(key=lambda item: item["task_cid"])
    by_key = {"compiler": 0, "decompiler": 0, "parser": 0}
    for hold in holds:
        for key in hold.get("proposal_keys") or []:
            if key in by_key:
                by_key[key] += 1
    return {
        "admitted": False,
        "formalized": False,
        "holds": holds,
        "review_hold_keys": by_key,
        "router_called": False,
        "wrote_compiler": False,
    }


def _edit_kinds(paths: Any) -> set[str]:
    kinds: set[str] = set()
    for path in _named(paths):
        name = path.replace("\\", "/")
        if name.endswith("decompiler.py"):
            kinds.add("decompiler")
        elif name.endswith("compiler.py"):
            kinds.add("compiler")
        elif name.endswith("deontic_parser.py") or name.endswith("formula_builder.py"):
            kinds.add("parser")
    return kinds


def _parser_rejected(source: str) -> str:
    if any(token in source for token in ("subprocess", "os.system", "eval(", "exec(", "__import__", "open(")):
        return "forbidden_call"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "syntax"
    if not any(isinstance(node, ast.FunctionDef) for node in tree.body):
        return "missing_parser_function"
    return ""


def _json_object(raw: str) -> dict[str, Any] | None:
    """Read a JSON object from a router reply. Fences and leading prose are ignored."""

    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        fence = text.rfind("```")
        if fence >= 0:
            text = text[:fence]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _clean_source(source: str) -> str:
    text = str(source or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        fence = text.rfind("```")
        if fence >= 0:
            text = text[:fence]
    return text.strip()


def _scoped_proposal(raw: str, kinds: set[str]) -> tuple[dict[str, str], str]:
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import _source_rejected

    payload = _json_object(raw)
    if payload is None:
        return {}, "router_output_unreadable"
    proposal: dict[str, str] = {}
    dropped = ""
    for key in ("compiler", "decompiler", "parser"):
        text = _clean_source(str(payload.get(key) or ""))
        if not text:
            continue
        if key not in kinds:
            dropped = dropped or f"{key}_not_in_scope"
            continue
        proposal[key] = text
    if not proposal:
        return {}, dropped or "missing_scoped_edit"
    checks = {
        "compiler": lambda source: _source_rejected(source, "compile"),
        "decompiler": lambda source: _source_rejected(source, "decompile"),
        "parser": _parser_rejected,
    }
    for key, source in proposal.items():
        reason = checks[key](source)
        if reason:
            return {}, reason
    return proposal, ""


def repair_and_recensus(
    row: Mapping[str, Any],
    *,
    generate: Callable[..., str],
    scratch: Path,
    autoencoder_output: str,
) -> dict[str, Any]:
    """Ask llm_router for a scoped repair, run it, and census the result.

    The proposal is written only under ``scratch``. The installed compiler and
    decompiler are not replaced. A later agreement is not an admit.
    """

    receipt = {
        "admitted": False,
        "agrees_with_autoencoder": False,
        "applied": False,
        "census_rerun": False,
        "formalized": False,
        "imported": False,
        "proposal_keys": [],
        "proposal_sha256": "",
        "reason": "",
        "router_called": False,
        "wrote_compiler": False,
    }
    kinds = _edit_kinds(row.get("allowed_edit_paths"))
    if not kinds:
        receipt["reason"] = "no_approved_edit_path"
        return receipt
    try:
        raw = str(generate(router_prompt(row), temperature=0, task_kind="legal") or "")
    except Exception as exc:
        receipt["router_called"] = True
        receipt["reason"] = f"router_failed:{type(exc).__name__}"
        return receipt
    proposal, reason = _scoped_proposal(raw, kinds)
    receipt["router_called"] = True
    if reason:
        receipt["reason"] = reason
        return receipt
    digest = hashlib.sha256(json.dumps(proposal, sort_keys=True).encode("utf-8")).hexdigest()
    receipt["proposal_keys"] = sorted(proposal)
    receipt["proposal_sha256"] = digest
    scratch.mkdir(parents=True, exist_ok=True)
    paths = {
        "compiler": scratch / "compiler_repair.py",
        "decompiler": scratch / "decompiler_repair.py",
        "parser": scratch / "parser_repair.py",
    }
    for key, source in proposal.items():
        paths[key].write_text(source, encoding="utf-8")
    receipt["applied"] = True
    produced = _repair_output(paths, str(row.get("text") or ""))
    receipt["census_rerun"] = True
    if produced is None:
        receipt["reason"] = "repair_raised"
        return receipt
    from ipfs_datasets_py.logic.autoformal.family_supervision import project_span_families

    repaired = project_span_families(produced, str(row.get("source_span_id") or "span") + ":repaired")
    autoencoded = project_span_families(str(autoencoder_output or ""), str(row.get("source_span_id") or "span") + ":autoencoder")
    agrees = (
        repaired["selected_families"] == autoencoded["selected_families"]
        and repaired["stitch"]["open_slots"] == autoencoded["stitch"]["open_slots"]
    )
    receipt["agrees_with_autoencoder"] = agrees
    receipt["reason"] = "" if agrees else "census_still_disagrees"
    return receipt


def _repair_output(paths: Mapping[str, Path], source_text: str) -> str | None:
    """Run the scoped repair. A crash is a failed census, not an installed compiler."""

    import importlib.util

    order = (
        ("decompiler_repair", paths.get("decompiler"), "decompile"),
        ("compiler_repair", paths.get("compiler"), "compile"),
    )
    for module_name, path, function_name in order:
        if path is None or not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            function = getattr(module, function_name)
            produced = function(source_text)
        except Exception:
            return None
        return str(produced or "")
    return None


def _router_receipt(
    *,
    raw: str,
    reason: str,
    router_called: bool = True,
    proposal_keys: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "admitted": False,
        "formalized": False,
        "imported": False,
        "proposal_keys": list(proposal_keys or []),
        "proposal_sha256": raw,
        "reason": reason,
        "router_called": router_called,
        "wrote_compiler": False,
    }
