def triples_from_sample(sample: Any) -> list[dict[str, str]]:
    """Frame-logic triples already extracted into the sample. No second parse."""

    modal_ir = getattr(sample, "modal_ir", None)
    frame = getattr(modal_ir, "frame_logic", None)
    raw = []
    if frame is not None and hasattr(frame, "to_triples"):
        try:
            raw = list(frame.to_triples() or [])
        except (TypeError, ValueError, AttributeError):
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
    try:
        from ipfs_datasets_py.logic.modal.codec import modal_ir_to_flogic_triples

        raw = list(modal_ir_to_flogic_triples(modal_ir) or [])
    except (ImportError, OSError, TypeError, ValueError, AttributeError):
        return []
    for item in raw:
        triple = _triple(item)
        if triple is None or triple["predicate"] not in _ONTOLOGY_PREDICATES:
            continue
        triples.append(triple)
        if len(triples) >= 32:
            break
    return triples

def capture_samples(samples: Sequence[Any]) -> list[dict[str, Any]]:
    from ipfs_datasets_py.logic.autoformal.recipient_reference import recipient_surface_from_sentence

    records = []
    for sample in samples:
        text = str(getattr(sample, "text", "") or "")
        record = ontology_record(
            sample_id=str(getattr(sample, "sample_id", "") or ""),
            text=text,
            triples=triples_from_sample(sample),
        )
        if text and not record["recipient"]["surface"]:
            try:
                surface = recipient_surface_from_sentence(text)
            except (ImportError, OSError, TypeError, ValueError):
                surface = ""
            if surface:
                record["recipient"] = recipient_reference(surface)
        if text and not record["procedure"]["procedure_id"]:
            try:
                from ipfs_datasets_py.logic.autoformal.procedure_slot import procedure_from_sentence

                record["procedure"] = procedure_from_sentence(text)
            except (ImportError, OSError, TypeError, ValueError):
                pass
        records.append(record)
    return records
