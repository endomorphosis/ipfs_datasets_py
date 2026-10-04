def _legal_ir_grammar_validation_from_target(
    target: Any,
    *,
    decoder: LegalIRGrammarDecoder,
    source_text: str,
) -> Optional[LegalIRGrammarValidation]:
    explicit = _existing_legal_ir_grammar_validation(target)
    if explicit is not None:
        return explicit
    source = _target_mapping(target)
    for key in (
        "scored_productions",
        "production_scores",
        "candidate_productions",
    ):
        if key not in source:
            continue
        return decoder.decode(
            source[key],
            family=_legal_ir_candidate_family(source),
            source_text=source_text,
            context=source,
        ).validation
    has_candidate, candidate, family = _legal_ir_candidate_from_target(target)
    if not has_candidate:
        return None
    return decoder.validate(candidate, family=family, source_text=source_text)
