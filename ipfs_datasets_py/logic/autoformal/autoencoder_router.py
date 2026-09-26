"""Infer with the autoencoder before any training or router call.

If inference fails, one training step may be accepted and only then may the
LLM router propose a compiler and decompiler. Agreement with the deterministic
compiler runs only after inference succeeds. A proposal is not imported, and
agreement is not an admit.
"""

from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Callable, Sequence


_FORBIDDEN = ("subprocess", "os.system", "eval(", "exec(", "__import__", "open(")


def _proposal_text(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        payload = value
    else:
        try:
            payload = json.loads(str(value or ""))
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, dict):
        return {}
    compiler = str(payload.get("compiler") or "")
    decompiler = str(payload.get("decompiler") or "")
    if not compiler or not decompiler:
        return {}
    return {"compiler": compiler, "decompiler": decompiler}


def _source_rejected(source: str, required_name: str) -> str:
    if any(token in source for token in _FORBIDDEN):
        return "forbidden_call"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "syntax"
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if required_name not in names:
        return f"missing_{required_name}"
    return ""


def llm_router_generate(prompt: str, **kwargs: Any) -> str:
    """Project a prompt through the configured llm_router at temperature 0.

    The ``provider`` value ``llm_router`` is the loop label, not a backend name,
    so it is not forwarded. This does not import a proposed compiler.
    """

    from ipfs_datasets_py.logic.modal.leanstral_audit import resolve_leanstral_llm_router

    module, _metadata = resolve_leanstral_llm_router()
    # Leave model_name and provider unset. generate_text then uses
    # select_efficient_route on the model-manager price/intelligence table.
    return str(module.generate_text(
        prompt,
        temperature=kwargs.get("temperature", 0),
        task_kind="legal",
    ))


def _inference_ok(result: Any) -> bool:
    return bool(isinstance(result, dict) and result.get("ok"))


def _base(*, stage: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "stage": stage,
        "inference_ok": False,
        "trained": False,
        "router_called": False,
        "wrote_compiler": False,
        "agrees": False,
        "admitted": False,
        "formalized": False,
        "reason": "",
    }
    payload.update(extra)
    return payload


def _write_proposal(
    samples: Sequence[Any],
    report: dict[str, Any],
    generate: Callable[..., str] | None,
    output_dir: Path | None,
    disagreement: dict[str, Any],
) -> dict[str, Any]:
    """Ask the router for an edit only after the compiler disagreed."""

    accepted = int(report.get("accepted_epochs") or 0)
    if generate is None:
        return _base(
            stage="autoencoder",
            trained=True,
            reason="router_not_configured",
            accepted_epochs=accepted,
        )
    captures = list(report.get("captures") or [])
    prompt = (
        "The autoencoder inference and the IR compiler/decompiler disagree. "
        "Emit an edit to TypedDeonticCanonicalCompiler and decompile_rule. "
        "Do not replace them.\n"
        "Return strict JSON with keys compiler and decompiler. compiler must define compile. "
        "decompiler must define decompile.\n"
        "The edit must make the decompiled sentence contain every capture token that is already "
        "in the source. A match is not an admit. Admit only when that match holds and "
        "lake build Legal succeeds. lake build with no target is not a compile. "
        "Do not import Mathlib. Do not use sorry, admit, or axiom. Render Lean only for a "
        "minimum_duration whose integer quantity survived. within_duration is not a Lean minimum.\n"
        "Do not import modules. Do not call the network. Do not mark the Constitution formalized.\n"
        + json.dumps(
            {
                "captures": captures,
                "disagreement": {
                    "agreed": disagreement.get("agreed"),
                    "operative": disagreement.get("operative"),
                    "reason": disagreement.get("reason"),
                    "todos": list(disagreement.get("todos") or []),
                },
                "samples": len(list(samples)),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    raw = generate(prompt, temperature=0, task_kind="legal")
    proposal = _proposal_text(raw)
    if not proposal:
        return _base(
            stage="llm_router",
            trained=True,
            router_called=True,
            reason="router_output_unreadable",
            accepted_epochs=accepted,
        )
    compiler_reason = _source_rejected(proposal["compiler"], "compile")
    decompiler_reason = _source_rejected(proposal["decompiler"], "decompile")
    if compiler_reason or decompiler_reason:
        return _base(
            stage="llm_router",
            trained=True,
            router_called=True,
            reason=compiler_reason or decompiler_reason,
            accepted_epochs=accepted,
        )
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "proposed_compiler.py").write_text(proposal["compiler"], encoding="utf-8")
        (output_dir / "proposed_decompiler.py").write_text(proposal["decompiler"], encoding="utf-8")
    return _base(
        stage="proposal",
        trained=True,
        router_called=True,
        wrote_compiler=output_dir is not None,
        reason="",
        accepted_epochs=accepted,
        proposal=proposal,
    )


def inference_from_bridge_receipt(receipt: dict[str, Any], span_count: int) -> dict[str, Any]:
    """A finished autoencoder pass has one legal-IR target for every span.

    The target is a view, not a compile and not an admit.
    """

    bridge = receipt.get("bridge") if isinstance(receipt.get("bridge"), dict) else {}
    try:
        targets = int(bridge.get("legal_ir_target_count") or 0)
    except (TypeError, ValueError):
        targets = 0
    return {
        "ok": targets == span_count and targets > 0,
        "target_count": targets,
        "span_count": span_count,
        "captures": [],
        "admitted": False,
    }


_SURFACE_DASHES = str.maketrans({char: "-" for char in "‐‑‒–—−"})
_SURFACE_WORD = re.compile(r"(?<!\w)[A-Za-z0-9]+(?:[.,/-][A-Za-z0-9]+)*(?!\w)")
_ACTOR_SCOPE_PREFIX = re.compile(
    r"^(?:for\s+(?:fiscal|calendar)\s+year\b|if\b|when\b|whenever\b|unless\b|"
    r"provided\s+that\b|subject\s+to\b)|"
    r",\s*(?:in\s+consultation\s+with\b|if\b|when\b|unless\b|subject\s+to\b)",
    re.I,
)


def source_surface_diagnostics(source: str, rendered: str, *, actors: Sequence[str] = ()) -> dict:
    """Conservative loss alarms independent of the candidate deontic parser.

    Keep digit-bearing identifiers and multiplicities (not merely substrings).
    Only typographic dashes/case are normalized; alternative numeric spellings
    need review. A separate leading section-heading line is metadata, not the
    operative body. Embedded headings are not stripped. These necessary checks
    do not establish role alignment, unit preservation, or legal equivalence.
    """
    heading = ""
    first, separator, rest = source.partition("\n")
    match = re.fullmatch(r"\s*§\s*\S+\s+(.+)", first)
    body = source
    # A citation prefix alone cannot turn an operative first line into metadata.
    ambiguous_heading = re.search(r"\b(?:shall|must|may|required|authorized|prohibited)\b", first, re.I)
    if separator and match and not ambiguous_heading:
        heading, body = match.group(1), rest

    def numeric_surfaces(text: str) -> Counter:
        normalized = text.translate(_SURFACE_DASHES).casefold()
        return Counter(word for word in _SURFACE_WORD.findall(normalized)
                       if any(char.isdigit() for char in word))

    missing = numeric_surfaces(body) - numeric_surfaces(rendered)
    heading_key = " ".join(heading.casefold().split())
    contaminated = []
    for actor in actors:
        key = " ".join(str(actor).casefold().split())
        if (_ACTOR_SCOPE_PREFIX.search(key)
                or (heading_key and (key == heading_key or key.startswith(heading_key + " ")))):
            contaminated.append(str(actor))
    return {"missing_numeric_surfaces": sorted(missing.elements()),
            "actor_scope_issues": contaminated}


def agreement_census(samples: Sequence[Any], inference: dict[str, Any]) -> dict[str, Any]:
    """Score every span. One abstain does not hide the rest of the document."""

    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    from ipfs_datasets_py.logic.autoformal.ontology_capture import (
        dropped_clauses,
        missing_qualifier_surfaces,
        schema_placeholders,
    )

    captures = {
        str(item.get("sample_id") or ""): item
        for item in inference.get("captures") or []
    }
    session = AutoformalSession()
    rows = []
    for sample in samples:
        if isinstance(sample, str):
            text, sample_id, kind = sample, "", "operative"
        else:
            text = str(sample.get("text") or "")
            sample_id = str(sample.get("id") or "")
            kind = str(sample.get("status") or "operative")
        if not text or kind in {"non_operative", "inactive"}:
            rows.append({
                "id": sample_id,
                "status": kind,
                "agrees": False,
                "skipped": True,
                "reason": kind,
            })
            continue
        # Hold references so identity comparisons cannot confuse replaced rows
        # with newly allocated rows. Only this span's fresh compiler rows count.
        previous_rows = tuple(session.rows)
        previous_row_ids = {id(row) for row in previous_rows}
        outcome = compile_span(session, text, sample_id or "agreement")
        fields = [str(item) for item in outcome.get("fields") or []]
        if outcome.get("compiler_status") not in {"compiled", "repeal"} and fields:
            outcome = compile_span(session, text, (sample_id or "agreement") + "-partial", allow_partial=True)
        decompiled = str(outcome.get("decompiled") or "")
        actors = [str(row.rule.get("actor") or "") for row in session.rows
                  if id(row) not in previous_row_ids and row.status == "compiled" and row.rule]
        integrity = source_surface_diagnostics(text, decompiled, actors=actors)
        missing = dropped_clauses(text, decompiled)
        placeholders = schema_placeholders(decompiled)
        omitted = missing_qualifier_surfaces(text, decompiled)
        for item in placeholders + omitted:
            if item not in missing:
                missing.append(item)
        reason = ""
        agrees = (
            outcome.get("compiler_status") == "compiled"
            and bool(decompiled)
            and not missing
            and not placeholders
            and not omitted
        )
        if outcome.get("compiler_status") == "repeal":
            slotted = _repeal_reading(text, sample_id)
            # The id string "amend-21 repeals amend-18" is not the sentence.
            # Agreement keeps the performative words and still does not admit.
            agrees = bool(slotted) and _repeal_surface_kept(text, decompiled)
            reason = "" if agrees else "repeal_surface_dropped"
            missing = [] if agrees else ["repealed"]
        elif outcome.get("compiler_status") != "compiled" or not decompiled:
            agrees = False
            reason = "compiler_abstain:" + ",".join(fields) if fields else "compiler_abstain"
        elif placeholders:
            agrees = False
            reason = "schema_placeholder"
        elif omitted:
            agrees = False
            reason = "qualifier_not_in_decompilation"
        elif missing:
            agrees = False
            reason = "dropped_clause"
        if agrees and integrity["actor_scope_issues"]:
            agrees = False
            reason = "compiler_abstain:actor_scope_contamination"
        if agrees and integrity["missing_numeric_surfaces"]:
            agrees = False
            reason = "dropped_clause"
        for surface in integrity["missing_numeric_surfaces"]:
            if surface not in missing:
                missing.append(surface)
        capture = _capture_for_first_clause(text, captures.get(sample_id) or {})
        if agrees:
            for triple in capture.get("triples") or []:
                obj = str(triple.get("object") or "").strip().lower()
                if obj and obj in text.lower() and obj not in decompiled.lower():
                    agrees = False
                    reason = "capture_not_in_decompilation"
                    break
        extra = sample if isinstance(sample, dict) else {}
        rows.append({
            "id": sample_id,
            "text": text,
            "status": "agree" if agrees else "gap",
            "agrees": agrees,
            "skipped": False,
            "reason": reason,
            "dropped": missing,
            "source_integrity": integrity,
            "decompiled": decompiled,
            "capture": capture,
            "canonical_citation": str(extra.get("canonical_citation") or ""),
            "entry_cid": str(extra.get("entry_cid") or ""),
            "legal_id": str(extra.get("legal_id") or ""),
            "source_span_id": str(extra.get("source_span_id") or sample_id),
        })
    operative = [row for row in rows if not row["skipped"]]
    agreed = sum(1 for row in operative if row["agrees"])
    todos = [
        ir_edit_todo(row).to_dict()
        for row in operative
        if not row["agrees"]
    ]
    return {
        "agrees": bool(operative) and agreed == len(operative),
        "reason": "" if operative and agreed == len(operative) else "compiler_disagreement",
        "operative": len(operative),
        "agreed": agreed,
        "admitted": False,
        "formalized": False,
        "todos": todos,
        "rows": rows,
    }


def _repeal_surface_kept(text: str, decompiled: str) -> bool:
    """The projected sentence still names the repealed article."""

    from ipfs_datasets_py.logic.autoformal.repeal_fixture import repeal_from_sentence

    surface = " ".join(str(repeal_from_sentence(text, instrument_id="surface").get("surface") or "").split())
    if not surface:
        return False
    rendered = " ".join(str(decompiled or "").casefold().split())
    needed = " ".join(surface.casefold().split()).rstrip(".")
    return bool(needed) and needed in rendered and "repealed" in rendered


def _repeal_reading(text: str, sample_id: str) -> str:
    """Fixture reading of a repeal. Empty when the sentence is not one."""

    from ipfs_datasets_py.logic.autoformal.repeal_fixture import RepealFixture, repeal_from_sentence

    instrument = sample_id.split(".sec-", 1)[0].split(".span-", 1)[0]
    parsed = repeal_from_sentence(text, instrument_id=instrument)
    if not parsed["target_id"] or not instrument:
        return ""
    fixture = RepealFixture()
    stored = fixture.put(instrument_id=instrument, text=text)
    if stored.get("result") != "yes":
        return ""
    return f"{instrument} repeals {parsed['target_id']}"


def _capture_for_first_clause(text: str, capture: dict[str, Any]) -> dict[str, Any]:
    """Keep only features that belong to the first parsed clause.

    A later clause's recipient must not be required of the first decompilation.
    """

    from ipfs_datasets_py.logic.deontic import DeonticConverter

    converted = DeonticConverter(
        jurisdiction="us",
        document_type="statute",
        use_ml=False,
        use_cache=False,
        enable_monitoring=False,
    ).convert(text)
    elements = [item for item in (getattr(getattr(converted, "output", None), "parser_elements", ()) or []) if isinstance(item, dict)]
    if not elements:
        return capture
    element = elements[0]
    scope = " ".join(
        str(part or "")
        for part in (
            element.get("action_object"),
            element.get("action_recipient"),
            " ".join(element.get("action") or []) if isinstance(element.get("action"), list) else element.get("action"),
        )
    ).lower()
    triples = []
    for triple in capture.get("triples") or []:
        obj = " ".join(str(triple.get("object") or "").split())
        if obj and obj.lower() in scope:
            triples.append(dict(triple))
    recipient = " ".join(str(element.get("action_recipient") or "").split())
    narrowed = dict(capture)
    narrowed["triples"] = triples
    narrowed["recipient"] = {"surface": recipient, "admitted": False}
    return narrowed


def _required_tokens(text: str, capture: dict[str, Any], missing: Sequence[str]) -> list[str]:
    required: list[str] = []
    for triple in capture.get("triples") or []:
        obj = " ".join(str(triple.get("object") or "").split())
        if obj and obj.lower() in text.lower() and obj not in required:
            required.append(obj)
    surface = " ".join(str((capture.get("recipient") or {}).get("surface") or "").split())
    if surface and surface.lower() in text.lower() and surface not in required:
        required.append(surface)
    for head in missing:
        if head and head not in required:
            required.append(head)
    return required


def ir_edit_todo(row: Mapping[str, Any]) -> Any:
    """A queue item that carries the failure, the capture, and the accept test."""

    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import ModalTodo

    capture = dict(row.get("capture") or {})
    text = str(row.get("text") or "")
    missing = [str(item) for item in row.get("dropped") or []]
    failure_mode = str(row.get("reason") or "compiler_disagreement")
    features = {
        "procedure": str((capture.get("procedure") or {}).get("procedure_id") or ""),
        "recipient": str((capture.get("recipient") or {}).get("surface") or ""),
        "triples": [dict(triple) for triple in list(capture.get("triples") or [])[:8]],
    }
    acceptance = {
        "failure_mode": failure_mode,
        "lake": "lake build Legal only for minimum_duration with a surviving integer quantity",
        "match_is_not_admit": True,
        "must_contain": _required_tokens(text, capture, missing),
    }
    return ModalTodo(
        todo_id=f"ir-edit:{row.get('id')}:{failure_mode}",
        action="edit_ir_compiler",
        objective="decompiled sentence must contain the autoencoder tokens that are in the source",
        sample_ids=[str(row.get("id") or "")],
        citations=[],
        loss_name=failure_mode,
        loss_value=1.0,
        priority=1.0,
        metadata={
            "acceptance": acceptance,
            "autoencoder_features": features,
            "decompiled": str(row.get("decompiled") or ""),
            "failure_mode": failure_mode,
            "source_text": text,
        },
    )


def patch_matches_autoencoder(todo: Any, decompiled: str) -> dict[str, Any]:
    """Whether a decompilation clears the todo. Agreement is not a Lake admit."""

    required = list((todo.metadata.get("acceptance") or {}).get("must_contain") or [])
    rendered = str(decompiled or "").lower()
    missing = [token for token in required if str(token).lower() not in rendered]
    return {"agrees": not missing and bool(rendered), "missing": missing, "admitted": False}


def integrate_when_agreed(todo: Any, decompiled: str) -> dict[str, Any]:
    """Mark the todo integrated only when the decompilation matches the capture."""

    result = patch_matches_autoencoder(todo, decompiled)
    if not result["agrees"]:
        todo.fail_validation("autoencoder_disagreement:" + ",".join(result["missing"]))
        result["integrated"] = False
        return result
    todo.metadata["admitted"] = False
    todo.metadata["integrated_decompiled"] = decompiled
    todo.complete()
    result["integrated"] = True
    return result


def agrees_with_compiler(samples: Sequence[Any], inference: dict[str, Any]) -> dict[str, Any]:
    """Whether each working capture still appears in the deterministic decompilation.

    The proposed router source is not executed. Disagreement is not an admit.
    """

    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    from ipfs_datasets_py.logic.autoformal.ontology_capture import (
        missing_qualifier_surfaces,
        schema_placeholders,
    )

    captures = {str(item.get("sample_id") or ""): item for item in inference.get("captures") or []}
    session = AutoformalSession()
    checked = 0
    for sample in samples:
        if isinstance(sample, str):
            text, sample_id = sample, ""
        else:
            text = str(getattr(sample, "text", "") or (sample.get("text") if isinstance(sample, dict) else "") or "")
            sample_id = str(getattr(sample, "sample_id", "") or (sample.get("id") if isinstance(sample, dict) else "") or "")
        if not text:
            continue
        checked += 1
        outcome = compile_span(session, text, sample_id or "agreement")
        decompiled = str(outcome.get("decompiled") or "").lower()
        if outcome.get("compiler_status") != "compiled" or not decompiled:
            return {"agrees": False, "reason": "compiler_abstain", "admitted": False}
        if schema_placeholders(decompiled):
            return {"agrees": False, "reason": "schema_placeholder", "admitted": False}
        if missing_qualifier_surfaces(text, decompiled):
            return {"agrees": False, "reason": "qualifier_not_in_decompilation", "admitted": False}
        capture = captures.get(sample_id) or {}
        for triple in capture.get("triples") or []:
            obj = str(triple.get("object") or "").strip().lower()
            if obj and obj in text.lower() and obj not in decompiled:
                return {"agrees": False, "reason": "capture_not_in_decompilation", "admitted": False}
        surface = str((capture.get("recipient") or {}).get("surface") or "").strip().lower()
        if surface and surface in text.lower() and surface not in decompiled:
            return {"agrees": False, "reason": "recipient_not_in_decompilation", "admitted": False}
    if checked == 0:
        return {"agrees": False, "reason": "no_text", "admitted": False}
    return {"agrees": True, "reason": "", "admitted": False}


def run_inference_then_router(
    samples: Sequence[Any],
    *,
    infer: Callable[[Sequence[Any]], dict[str, Any]],
    train: Callable[[Sequence[Any]], dict[str, Any]],
    generate: Callable[..., str] | None = None,
    agree: Callable[..., dict[str, Any]] | None = None,
    output_dir: Path | None = None,
    max_steps: int = 4,
) -> dict[str, Any]:
    """Infer, train until that passes, then compare with the compiler.

    The router emits an edit only when the compiler and the autoencoder
    disagree. Agreement is not an admit.
    """

    sample_list = list(samples)
    current = infer(sample_list)
    steps = 0
    accepted_total = 0
    last_report: dict[str, Any] = {}
    if not _inference_ok(current):
        for _ in range(max(1, int(max_steps))):
            last_report = train(sample_list)
            steps += 1
            accepted_total += int(last_report.get("accepted_epochs") or 0)
            current = infer(sample_list)
            if _inference_ok(current):
                break
        if not _inference_ok(current):
            return _base(
                stage="autoencoder",
                trained=steps > 0,
                reason="inference_still_failing",
                training_steps=steps,
                accepted_epochs=accepted_total,
            )
    agreement = (agree or agrees_with_compiler)(sample_list, current)
    if agreement.get("agrees"):
        return _base(
            stage="agreement",
            inference_ok=True,
            trained=steps > 0,
            agrees=True,
            reason="",
            training_steps=steps,
            accepted_epochs=accepted_total,
        )
    report = dict(last_report)
    report["accepted_epochs"] = max(accepted_total, 1)
    if current.get("captures"):
        report["captures"] = list(current.get("captures") or [])
    written = _write_proposal(sample_list, report, generate, output_dir, agreement)
    written["inference_ok"] = True
    written["trained"] = steps > 0
    written["training_steps"] = steps
    written["accepted_epochs"] = accepted_total
    written["agrees"] = False
    written["admitted"] = False
    written["formalized"] = False
    if not written["reason"]:
        written["reason"] = str(agreement.get("reason") or "compiler_disagreement")
    return written


def run_inference_then_supervisor(
    samples: Sequence[Any],
    *,
    infer: Callable[[Sequence[Any]], dict[str, Any]],
    train: Callable[[Sequence[Any]], dict[str, Any]],
    agree: Callable[..., dict[str, Any]] | None = None,
    submit: Callable[..., dict[str, Any]] | None = None,
    board_path: Path | None = None,
    upload: Callable[..., dict[str, Any]] | None = None,
    native: Callable[..., dict[str, Any]] | None = None,
    query: str = "",
    release_id: str = "",
    max_steps: int = 4,
) -> dict[str, Any]:
    """Infer, then send discrepancies to the supervisor todo loop.

    Failed jobs are not sent to the autoencoder, compiler, or decompiler.
    Agreement is not an admit.
    """

    from ipfs_datasets_py.logic.autoformal.supervisor_todo import submit_discrepancies

    def default_submit(agreement, **kwargs):
        # The native compiler queue requires source-bound repair evidence.
        # Inference-only failures remain supervisor todos, not invented edits.
        inference_only = agreement.get("reason") == "inference_still_failing"
        receipt = submit_discrepancies(agreement, native=None if inference_only else native, **kwargs)
        if inference_only and native is not None:
            receipt["native_enqueue_skipped"] = "inference_failure_has_no_compiler_source"
        return receipt

    sample_list = list(samples)
    current = infer(sample_list)
    steps = 0
    accepted_total = 0
    if not _inference_ok(current):
        for _ in range(max(1, int(max_steps))):
            last_report = train(sample_list)
            steps += 1
            accepted_total += int(last_report.get("accepted_epochs") or 0)
            current = infer(sample_list)
            if _inference_ok(current):
                break
        if not _inference_ok(current):
            failed = _base(
                stage="supervisor_todo",
                trained=steps > 0,
                reason="inference_still_failing",
                training_steps=steps,
                accepted_epochs=accepted_total,
            )
            packet = {
                "agrees": False,
                "reason": "inference_still_failing",
                "rows": [
                    {
                        "id": "inference",
                        "text": "",
                        "reason": "inference_still_failing",
                        "agrees": False,
                        "skipped": False,
                        "dropped": [],
                        "decompiled": "",
                    }
                ],
            }
            submitted = (submit or default_submit)(
                packet,
                board_path=board_path,
                query=query,
                release_id=release_id,
                upload=upload,
            )
            failed.update(
                {
                    "jsonl_written": False,
                    "router_called": False,
                    "wrote_compiler": False,
                    "task_count": int(submitted.get("task_count") or 0),
                    "supervisor": submitted,
                }
            )
            return failed
    agreement = (agree or agreement_census)(sample_list, current)
    if agreement.get("agrees"):
        return _base(
            stage="agreement",
            inference_ok=True,
            trained=steps > 0,
            agrees=True,
            reason="",
            training_steps=steps,
            accepted_epochs=accepted_total,
        )
    submitted = (submit or default_submit)(
        agreement,
        board_path=board_path,
        query=query,
        release_id=release_id,
        upload=upload,
    )
    return {
        "accepted_epochs": accepted_total,
        "admitted": False,
        "agrees": False,
        "formalized": False,
        "inference_ok": True,
        "jsonl_written": False,
        "reason": str(agreement.get("reason") or "compiler_disagreement"),
        "router_called": False,
        "stage": "supervisor_todo",
        "supervisor": submitted,
        "task_count": int(submitted.get("task_count") or 0),
        "trained": steps > 0,
        "training_steps": steps,
        "wrote_compiler": False,
    }
