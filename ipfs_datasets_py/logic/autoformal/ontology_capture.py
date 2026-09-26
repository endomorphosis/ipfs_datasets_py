"""Capture frame-logic ontology from autoencoder samples, and sanitize fixtures.

Capture does not admit a fragment. Admission runs only after sanitation
passes. A sanitation failure leaves the fragment proposed.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from ipfs_datasets_py.logic.autoformal.recipient_reference import recipient_reference
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_ontology_observation import (
    capture_scope, note_suppressed, record_scope, stage_scope,
)


_RECIPIENT_PREDICATES = frozenset({"recipient", "action_recipient", "beneficiary"})
_SORT_PREDICATES = frozenset({"type", "isa"})
_ONTOLOGY_PREDICATES = _RECIPIENT_PREDICATES | _SORT_PREDICATES | frozenset({
    "actor",
    "action",
    "object",
    "modality",
    "procedure",
    "role",
})


def _triple(value: Any) -> dict[str, str] | None:
    if isinstance(value, dict):
        subject = str(value.get("subject") or "").strip()
        predicate = str(value.get("predicate") or "").strip()
        obj = str(value.get("object") or "").strip()
    else:
        subject = str(getattr(value, "subject", "") or "").strip()
        predicate = str(getattr(value, "predicate", "") or "").strip()
        obj = str(getattr(value, "object", "") or "").strip()
    if not subject or not predicate or not obj:
        return None
    return {"subject": subject, "predicate": predicate, "object": obj}


def triples_from_sample(sample: Any) -> list[dict[str, str]]:
    """Frame-logic triples already extracted into the sample. No second parse."""

    modal_ir = getattr(sample, "modal_ir", None)
    frame = getattr(modal_ir, "frame_logic", None)
    raw = []
    if frame is not None and hasattr(frame, "to_triples"):
        with stage_scope("frame_triples"):
            try:
                raw = list(frame.to_triples() or [])
            except (TypeError, ValueError, AttributeError) as exc:
                note_suppressed("frame_triples", exc)
                raw = []
    triples: list[dict[str, str]] = []
    for item in raw:
        triple = _triple(item)
        if triple is None or triple["predicate"] not in _ONTOLOGY_PREDICATES:
            continue
        triples.append(triple)
        if len(triples) >= 32:
            break
    if triples or modal_ir is None:
        return triples
    with stage_scope("fallback_projection"):
        try:
            from ipfs_datasets_py.logic.modal.codec import modal_ir_to_flogic_triples

            raw = list(modal_ir_to_flogic_triples(modal_ir) or [])
        except (ImportError, OSError, TypeError, ValueError, AttributeError) as exc:
            note_suppressed("fallback_projection", exc)
            return []
    for item in raw:
        triple = _triple(item)
        if triple is None or triple["predicate"] not in _ONTOLOGY_PREDICATES:
            continue
        triples.append(triple)
        if len(triples) >= 32:
            break
    return triples


def ontology_record(
    *,
    sample_id: str,
    text: str,
    triples: Sequence[dict[str, str]],
    recipient_surface: str = "",
) -> dict[str, Any]:
    """One captured ontology. Admitted stays false."""

    surface = " ".join(str(recipient_surface or "").split())
    if not surface:
        for triple in triples:
            if triple.get("predicate") in _RECIPIENT_PREDICATES:
                surface = triple["object"]
                break
    sorts = []
    for triple in triples:
        if triple.get("predicate") in _SORT_PREDICATES and triple["object"] not in sorts:
            sorts.append(triple["object"])
    return {
        "sample_id": str(sample_id or ""),
        "text": str(text or ""),
        "triples": [dict(triple) for triple in list(triples)[:32]],
        "sorts": sorts,
        "recipient": recipient_reference(surface) if surface else recipient_reference(""),
        "procedure": {"events": [], "procedure_id": "", "surface": "", "admitted": False},
        "admitted": False,
    }


def capture_samples(samples: Sequence[Any]) -> list[dict[str, Any]]:
    with capture_scope("capture_samples") as batch:
        with stage_scope("recipient_import"):
            from ipfs_datasets_py.logic.autoformal.recipient_reference import recipient_surface_from_sentence

        records = []
        for ordinal, sample in enumerate(samples):
            with record_scope(ordinal) as observation:
                text = str(getattr(sample, "text", "") or "")
                record = ontology_record(
                    sample_id=observation.identify(str(getattr(sample, "sample_id", "") or "")),
                    text=text,
                    triples=triples_from_sample(sample),
                )
                if text and not record["recipient"]["surface"]:
                    with stage_scope("recipient"):
                        try:
                            surface = recipient_surface_from_sentence(text)
                        except (ImportError, OSError, TypeError, ValueError) as exc:
                            note_suppressed("recipient", exc)
                            surface = ""
                        if surface:
                            record["recipient"] = recipient_reference(surface)
                if text:
                    with stage_scope("actors"):
                        try:
                            from ipfs_datasets_py.logic.autoformal.embedded_actor import (
                                actor_triples,
                                clause_actors,
                            )

                            actors = clause_actors(text)
                        except (ImportError, OSError, TypeError, ValueError) as exc:
                            note_suppressed("actors", exc)
                            actors = []
                        record["actors"] = [
                            {"surface": actor["surface"], "role": actor["role"], "admitted": False}
                            for actor in actors
                        ]
                        for triple in actor_triples(record["sample_id"], actors):
                            if len(record["triples"]) >= 32:
                                break
                            if triple not in record["triples"]:
                                record["triples"].append(triple)
                if text and not record["procedure"]["procedure_id"]:
                    with stage_scope("procedure"):
                        try:
                            from ipfs_datasets_py.logic.autoformal.procedure_slot import procedure_from_sentence

                            record["procedure"] = procedure_from_sentence(text)
                        except (ImportError, OSError, TypeError, ValueError) as exc:
                            note_suppressed("procedure", exc)
                            pass
                records.append(record)
                observation.emitted()
        batch.returned(len(records))
        return records


_COORD_STOP = frozenset({
    "also", "been", "from", "have", "into", "only", "same", "shall", "such",
    "than", "that", "then", "them", "they", "this", "thereof", "under", "until",
    "when", "where", "which", "with",
})


def _coordination_head(part: str) -> str:
    words = [
        word.lower()
        for word in re.findall(r"[A-Za-z]{4,}", part)
        if word.lower() not in _COORD_STOP
    ]
    return words[-1] if words else ""


def coordinated_pieces(text: str) -> list[str]:
    """Heads of ``or`` pieces in the source. A word that is not in the source is not added."""

    parts = re.split(r"\s+or\s+", str(text or ""), flags=re.I)
    if len(parts) < 2:
        return []
    heads: list[str] = []
    for part in parts:
        for sub in re.split(r"\s+and\s+", part, flags=re.I):
            head = _coordination_head(sub)
            if head and head not in heads:
                heads.append(head)
    return heads


_SCHEMA_PLACEHOLDER = re.compile(r"\b(?:if condition|unless exception)\b", re.I)


def schema_placeholders(decompiled: str) -> list[str]:
    """Schema labels printed in place of a clause. A match is not an admit."""

    return [match.group(0).lower() for match in _SCHEMA_PLACEHOLDER.finditer(str(decompiled or ""))]


def missing_qualifier_surfaces(source: str, decompiled: str) -> list[str]:
    """Condition, exception, and temporal text that the decompilation dropped.

    A schema label is not a substitute for that text.
    """

    from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
        extract_condition_details,
        extract_exception_details,
        extract_temporal_constraint_details,
    )

    rendered = str(decompiled or "").casefold()
    missing: list[str] = []
    seen: set[str] = set()
    details = (
        list(extract_condition_details(source))
        + list(extract_exception_details(source))
        + list(extract_temporal_constraint_details(source))
    )
    for item in details:
        surface = " ".join(str(item.get("normalized_text") or item.get("value") or "").split())
        key = surface.casefold()
        if len(key) < 3 or key in seen or key in {"condition", "exception"}:
            continue
        seen.add(key)
        if key in rendered:
            continue
        parts = [part.strip() for part in re.split(r"[:;]", key) if len(part.strip()) >= 3]
        if len(parts) >= 2 and all(part in rendered for part in parts):
            continue
        needed = [
            token for token in re.findall(r"[a-z0-9']+", key)
            if token not in {"shall", "must", "may", "not"} and len(token) > 2
        ]
        have = re.findall(r"[a-z0-9']+", rendered)
        index = 0
        for token in have:
            if index < len(needed) and token == needed[index]:
                index += 1
        if needed and index == len(needed):
            continue
        missing.append(surface)
    return missing


def dropped_clauses(source: str, decompiled: str) -> list[str]:
    """Coordinated heads in the parser object that the decompilation dropped.

    Heads that the parser never stored are not required. A word that is not in
    the source is not added.
    """

    from ipfs_datasets_py.logic.deontic import DeonticConverter

    converted = DeonticConverter(
        jurisdiction="us",
        document_type="statute",
        use_ml=False,
        use_cache=False,
        enable_monitoring=False,
    ).convert(source)
    elements = [
        item
        for item in (getattr(getattr(converted, "output", None), "parser_elements", ()) or [])
        if isinstance(item, dict)
    ]
    objects = []
    if elements:
        obj = " ".join(str(elements[0].get("action_object") or "").split())
        if obj:
            objects.append(obj)
    rendered = str(decompiled or "").lower()
    missing: list[str] = []
    for obj in objects:
        for piece in coordinated_pieces(obj):
            if piece not in rendered and piece not in missing:
                missing.append(piece)
    return missing


def sanitize_fixture(
    text: str,
    *,
    must_contain: Sequence[str] = (),
    only_fields: Sequence[str] | None = None,
    compile_one: Any = None,
) -> dict[str, Any]:
    """A fixture passes only when the compiler result still states the required phrases.

    ``only_fields`` is the diagnostic set allowed for an abstaining fixture.
    An empty decompilation fails any required phrase.
    """

    if compile_one is None:
        from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

        session = AutoformalSession()

        def compile_one(sentence: str) -> dict[str, Any]:
            return compile_span(session, sentence, "sanitation-fixture")

    outcome = compile_one(text)
    fields = [str(item) for item in outcome.get("fields") or [] if str(item)]
    decompiled = str(outcome.get("decompiled") or "")
    reasons: list[str] = []
    if only_fields is not None and set(fields) != {str(item) for item in only_fields}:
        reasons.append("diagnostic_set")
    for phrase in must_contain:
        if phrase not in decompiled:
            reasons.append(f"missing:{phrase}")
    if str(outcome.get("compiler_status") or "") == "compiled" and not decompiled:
        reasons.append("empty_decompilation")
    if dropped_clauses(text, decompiled):
        reasons.append("dropped_clause")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "compiler_status": str(outcome.get("compiler_status") or ""),
        "fields": fields,
        "decompiled": decompiled,
        "admitted": False,
    }


def vocabulary_from_capture(capture: dict[str, Any]) -> dict[str, list[str]] | None:
    """Atoms named by a finished autoencoder capture. Not an installed ontology."""

    buckets = {"actors": [], "actions": [], "objects": [], "qualifiers": []}
    which = {
        "actor": "actors",
        "action": "actions",
        "object": "objects",
        "modality": "qualifiers",
        "type": "qualifiers",
    }
    for triple in capture.get("triples") or []:
        bucket = which.get(str(triple.get("predicate") or ""))
        obj = " ".join(str(triple.get("object") or "").split())
        if bucket and obj and obj not in buckets[bucket]:
            buckets[bucket].append(obj)
    surface = " ".join(str((capture.get("recipient") or {}).get("surface") or "").split())
    if surface and surface not in buckets["qualifiers"]:
        buckets["qualifiers"].append(surface)
    if not buckets["actors"] or not buckets["actions"]:
        return None
    return buckets


def project_finished_document(
    spans: Sequence[dict[str, Any]],
    captures: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Project one finished autoencoder pass into the deterministic compiler.

    The document is finished only when every span id has a capture. The
    compiler still abstains or drops clauses on its own rules. This function
    does not set ``formalized``.
    """

    by_id: dict[str, dict[str, Any]] = {}
    for capture in captures:
        sample_id = str(capture.get("sample_id") or "")
        if sample_id and sample_id not in by_id:
            by_id[sample_id] = capture
    missing = [str(span.get("id") or "") for span in spans if str(span.get("id") or "") not in by_id]
    if missing or not spans:
        return {
            "finished": False,
            "reason": "incomplete_autoencoder_pass",
            "missing": missing,
            "formalized": False,
            "admitted": False,
            "document_complete": False,
            "rows": [],
        }
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    session = AutoformalSession()
    rows = []
    for span in spans:
        span_id = str(span.get("id") or "")
        text = str(span.get("text") or "")
        capture = by_id[span_id]
        outcome = compile_span(
            session,
            text,
            span_id,
            vocabulary=vocabulary_from_capture(capture),
        )
        decompiled = str(outcome.get("decompiled") or "")
        missing_pieces = dropped_clauses(text, decompiled)
        fields = [str(item) for item in outcome.get("fields") or []]
        roundtrip = (
            outcome.get("compiler_status") == "compiled"
            and not missing_pieces
            and not fields
            and bool(decompiled)
        )
        rows.append({
            "id": span_id,
            "compiler_status": outcome.get("compiler_status"),
            "fields": fields,
            "decompiled": decompiled,
            "dropped": missing_pieces,
            "reason": "dropped_clause" if missing_pieces else str(outcome.get("reason") or ""),
            "roundtrip_ok": roundtrip,
            "admitted": False,
            "capture_admitted": bool(capture.get("admitted")),
        })
    return {
        "finished": True,
        "reason": "",
        "missing": [],
        "formalized": False,
        "admitted": False,
        "document_complete": all(row["roundtrip_ok"] for row in rows),
        "rows": rows,
    }


def admit_after_sanitation(registry: Any, fragment: dict[str, Any], sanitation: dict[str, Any]) -> dict[str, Any]:
    """Admit only a fragment whose fixture sanitation passed. Otherwise leave it proposed."""

    proposed = registry.propose(fragment)
    if proposed.get("status") == "rejected":
        return proposed
    if not sanitation.get("passed"):
        return {
            **proposed,
            "status": "proposed",
            "admitted": False,
            "reason": "sanitation_failed",
            "sanitation_reasons": list(sanitation.get("reasons") or []),
        }
    admitted = registry.admit(str(fragment.get("relation") or ""))
    admitted["sanitation_passed"] = True
    return admitted
