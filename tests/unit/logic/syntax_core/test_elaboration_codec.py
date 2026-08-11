"""Unit tests for parser registry, elaborator, normalizer, and codec (LFP-015).

Acceptance coverage:

* registry collision / implicit fallback is rejected
* codecs round-trip
* normalization is idempotent
* unresolved overloads / unknown signatures do not reach backends
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.syntax_core.ast import (
    Binder,
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_and,
    mk_application,
    mk_constant,
    mk_equality,
    mk_exists,
    mk_false,
    mk_forall,
    mk_iff,
    mk_implies,
    mk_not,
    mk_or,
    mk_predicate,
    mk_true,
    mk_variable,
)
from ipfs_datasets_py.logic.syntax_core.codec import (
    CODEC_MODULE_VERSION,
    DEFAULT_CODEC,
    TYPED_LOGIC_CODEC_INTERFACE,
    CodecEnvelope,
    CodecError,
    CodecKind,
    TypedLogicCodec,
    decode,
    encode,
    round_trip,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseArtifact,
    ParseRequest,
    ParseStatus,
    SourceDocument,
)
from ipfs_datasets_py.logic.syntax_core.elaboration import (
    CODE_UNKNOWN_SIGNATURE,
    CODE_UNKNOWN_SYMBOL,
    CODE_UNRESOLVED_OVERLOAD,
    DEFAULT_ELABORATOR,
    DEFAULT_NORMALIZER,
    ELABORATION_MODULE_VERSION,
    LOGIC_ELABORATOR_INTERFACE,
    ElaborationError,
    ElaborationResult,
    ElaborationStatus,
    LogicElaborator,
    LogicTypechecker,
    OverloadCandidate,
    OverloadSet,
    UnresolvedOverloadError,
    elaborate_expression,
    normalize,
    resolve_overload,
)
from ipfs_datasets_py.logic.syntax_core.registry import (
    LOGIC_PARSER_REGISTRY_INTERFACE,
    REGISTRY_MODULE_VERSION,
    DuplicateParserError,
    ImplicitFallbackError,
    LogicParserDescriptor,
    LogicParserRegistry,
    ParserKey,
    UnknownParserError,
    empty_parser_registry,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    INDIVIDUAL_SORT,
    LogicSignature,
    SymbolKind,
    atomic_sort,
    declare_function,
    many_sorted_fol_signature,
    propositional_signature,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _person():
    return atomic_sort("Person")


def _fol_signature() -> LogicSignature:
    person = _person()
    return many_sorted_fol_signature(
        "sig:fol:elab",
        sorts=(person,),
        constants=(("alice", person), ("bob", person)),
        functions=(("father", (person,), person),),
        predicates=(
            ("Human", (person,)),
            ("Knows", (person, person)),
            ("Rains", ()),
        ),
        family="first_order",
        profile="many_sorted",
    )


def _prop_signature() -> LogicSignature:
    return propositional_signature("sig:prop:elab", ("P", "Q", "R"))


def _human_alice() -> LogicNode:
    person = _person()
    return mk_predicate(
        "n:human-alice",
        "Human",
        (mk_constant("n:alice", "alice", person),),
    )


def _stub_parser(request: ParseRequest) -> ParseArtifact:
    # FAILED is valid without a CST; OK requires complete source coverage.
    return ParseArtifact(
        artifact_id="art:stub",
        request_id=request.request_id,
        document_id=request.document.document_id,
        status=ParseStatus.FAILED,
    )


def _descriptor(
    *,
    descriptor_id: str = "desc:fol:1",
    notation: str = "fol",
    version: str = "1.0.0",
    profile: str = "many_sorted",
) -> LogicParserDescriptor:
    return LogicParserDescriptor(
        descriptor_id=descriptor_id,
        key=ParserKey.from_parts(notation, version, profile),
        family_id="first_order",
        features=("first_order",),
        implementation="tests.stub_parser",
    )


# ---------------------------------------------------------------------------
# Module / interface identity
# ---------------------------------------------------------------------------


def test_module_versions_and_interfaces() -> None:
    assert REGISTRY_MODULE_VERSION == "1.0.0"
    assert ELABORATION_MODULE_VERSION == "1.0.0"
    assert CODEC_MODULE_VERSION == "1.0.0"
    assert LOGIC_PARSER_REGISTRY_INTERFACE == "LogicParserRegistry@1"
    assert LOGIC_ELABORATOR_INTERFACE == "LogicElaborator@1"
    assert TYPED_LOGIC_CODEC_INTERFACE == "TypedLogicCodec@1"


# ---------------------------------------------------------------------------
# Parser registry — collisions and no implicit fallback
# ---------------------------------------------------------------------------


def test_registry_register_and_exact_resolve() -> None:
    registry = empty_parser_registry()
    desc = _descriptor()
    registry.register(desc, parser=_stub_parser)
    parser = registry.resolve(
        notation_id="fol",
        notation_version="1.0.0",
        semantic_profile_id="many_sorted",
    )
    assert callable(parser)
    resolved = registry.resolve_descriptor(key=desc.key)
    assert resolved.descriptor_id == desc.descriptor_id
    assert desc.key in registry
    assert len(registry) == 1


def test_registry_collision_rejected() -> None:
    registry = empty_parser_registry()
    registry.register(_descriptor(), parser=_stub_parser)
    with pytest.raises(DuplicateParserError, match="collides"):
        registry.register(
            _descriptor(descriptor_id="desc:fol:2"),
            parser=_stub_parser,
        )


def test_registry_descriptor_id_collision_under_different_key() -> None:
    registry = empty_parser_registry()
    registry.register(_descriptor(), parser=_stub_parser)
    with pytest.raises(DuplicateParserError, match="descriptor_id"):
        registry.register(
            _descriptor(
                descriptor_id="desc:fol:1",
                notation="tptp",
                version="1.0.0",
                profile="fof",
            ),
            parser=_stub_parser,
        )


def test_registry_replace_requires_explicit_flag() -> None:
    registry = empty_parser_registry()
    registry.register(_descriptor(), parser=_stub_parser)

    def other(request: ParseRequest) -> ParseArtifact:
        return _stub_parser(request)

    with pytest.raises(DuplicateParserError):
        registry.register(_descriptor(descriptor_id="desc:fol:3"), parser=other)
    registry.register(
        _descriptor(descriptor_id="desc:fol:3"),
        parser=other,
        replace=True,
    )
    assert registry.resolve_descriptor(key=_descriptor().key).descriptor_id == (
        "desc:fol:3"
    )


def test_registry_unknown_key_rejected() -> None:
    registry = empty_parser_registry()
    registry.register(_descriptor(), parser=_stub_parser)
    with pytest.raises(UnknownParserError, match="implicit fallback"):
        registry.resolve(
            notation_id="fol",
            notation_version="9.9.9",
            semantic_profile_id="many_sorted",
        )


def test_registry_missing_version_is_implicit_fallback() -> None:
    registry = empty_parser_registry()
    registry.register(_descriptor(), parser=_stub_parser)
    with pytest.raises(ImplicitFallbackError, match="notation_version"):
        registry.resolve(
            notation_id="fol",
            notation_version=None,
            semantic_profile_id="many_sorted",
        )


def test_registry_partial_key_api_rejected() -> None:
    registry = empty_parser_registry()
    with pytest.raises(ImplicitFallbackError, match="partial-key"):
        registry.resolve_by_partial(notation_id="fol")


def test_registry_latest_version_sentinel_rejected() -> None:
    with pytest.raises(ImplicitFallbackError, match="fallback sentinel"):
        ParserKey.from_parts("fol", "latest", "many_sorted")
    with pytest.raises(ImplicitFallbackError):
        ParserKey.from_parts("fol", "*", "many_sorted")


def test_registry_parse_requires_explicit_version() -> None:
    registry = empty_parser_registry()
    registry.register(_descriptor(), parser=_stub_parser)
    document = SourceDocument.from_text("doc:1", "Human(alice)")
    request = ParseRequest(
        request_id="req:1",
        document=document,
        notation_id="fol",
        profile_id="many_sorted",
    )
    artifact = registry.parse(request, notation_version="1.0.0")
    assert artifact.status is ParseStatus.FAILED
    assert artifact.request_id == request.request_id
    with pytest.raises(ImplicitFallbackError):
        registry.parse(request, notation_version="")


def test_registry_freeze_is_immutable() -> None:
    registry = empty_parser_registry()
    registry.register(_descriptor(), parser=_stub_parser)
    frozen = registry.freeze()
    with pytest.raises(Exception, match="immutable"):
        frozen.register(
            _descriptor(
                descriptor_id="desc:other",
                notation="tptp",
                version="1.0.0",
                profile="fof",
            ),
            parser=_stub_parser,
        )


def test_registry_descriptor_round_trip_dict() -> None:
    desc = _descriptor()
    restored = LogicParserDescriptor.from_dict(desc.to_dict())
    assert restored.to_dict() == desc.to_dict()


# ---------------------------------------------------------------------------
# Overload resolution — unresolved never backend-ready
# ---------------------------------------------------------------------------


def test_overload_unique_resolution() -> None:
    person = _person()
    animal = atomic_sort("Animal")
    overload = OverloadSet(
        name="id",
        candidates=(
            OverloadCandidate(
                declaration=declare_function("id", (person,), person),
                candidate_id="cand:id:person",
            ),
            OverloadCandidate(
                declaration=declare_function("id", (animal,), animal),
                candidate_id="cand:id:animal",
            ),
        ),
    )
    chosen = resolve_overload(overload, (person,), expected_kind=SymbolKind.FUNCTION)
    assert chosen.candidate_id == "cand:id:person"
    assert chosen.declaration.range == person


def test_overload_zero_matches_unresolved() -> None:
    person = _person()
    overload = OverloadSet(
        name="id",
        candidates=(
            OverloadCandidate(
                declaration=declare_function("id", (person,), person),
                candidate_id="cand:id:person",
            ),
        ),
    )
    with pytest.raises(UnresolvedOverloadError, match="no candidate"):
        resolve_overload(overload, (INDIVIDUAL_SORT,))


def test_overload_ambiguous_unresolved() -> None:
    person = _person()
    # Two candidates with identical domain — ambiguous.
    overload = OverloadSet(
        name="f",
        candidates=(
            OverloadCandidate(
                declaration=declare_function("f", (person,), person),
                candidate_id="cand:f:1",
            ),
            OverloadCandidate(
                declaration=declare_function("f", (person,), person),
                candidate_id="cand:f:2",
            ),
        ),
    )
    with pytest.raises(UnresolvedOverloadError, match="ambiguous"):
        resolve_overload(overload, (person,))


def test_unresolved_overload_not_backend_ready() -> None:
    person = _person()
    # Signature has no `id`; only the overload table does, and it will not match.
    signature = many_sorted_fol_signature(
        "sig:ov",
        sorts=(person,),
        constants=(("alice", person),),
        predicates=(("Human", (person,)),),
    )
    overload = OverloadSet(
        name="id",
        candidates=(
            OverloadCandidate(
                declaration=declare_function("id", (person,), person),
                candidate_id="cand:id:person",
            ),
        ),
    )
    # Application of id to wrong sort via a constant of wrong sort is hard;
    # use zero-arg mismatch: apply id with animal-typed free var without sort
    # match by using an overload that only accepts Animal while node uses Person.
    animal = atomic_sort("Animal")
    overload_animal_only = OverloadSet(
        name="id",
        candidates=(
            OverloadCandidate(
                declaration=declare_function("id", (animal,), animal),
                candidate_id="cand:id:animal",
            ),
        ),
    )
    node = mk_application(
        "n:app",
        "id",
        (mk_constant("n:alice", "alice", person),),
        sort=person,
    )
    elaborator = LogicElaborator(
        signature=signature,
        overloads=(overload_animal_only,),
    )
    result = elaborator.elaborate(node, expression_id="expr:ov")
    assert result.status is ElaborationStatus.UNRESOLVED
    assert "id" in result.unresolved_overloads
    assert result.backend_ready is False
    with pytest.raises(ElaborationError, match="not backend-ready"):
        result.require_backend_ready()
    assert any(
        d.code in {CODE_UNRESOLVED_OVERLOAD, CODE_UNKNOWN_SYMBOL}
        for d in result.diagnostics
    )
    # Silence unused.
    assert overload.name == "id"


def test_unknown_symbol_not_backend_ready() -> None:
    signature = _fol_signature()
    node = mk_predicate(
        "n:unknown",
        "NotInSignature",
        (mk_constant("n:alice", "alice", _person()),),
    )
    result = LogicElaborator(signature=signature).elaborate(
        node, expression_id="expr:unk"
    )
    assert result.backend_ready is False
    assert result.status in {
        ElaborationStatus.FAILED,
        ElaborationStatus.UNRESOLVED,
    }
    assert "NotInSignature" in result.unknown_symbols or any(
        d.code == CODE_UNKNOWN_SYMBOL for d in result.diagnostics
    )
    with pytest.raises(ElaborationError, match="not backend-ready"):
        result.require_backend_ready()


def test_unknown_signature_not_backend_ready() -> None:
    node = mk_true("n:t")
    result = LogicElaborator(signature=None).elaborate(node)
    assert result.backend_ready is False
    assert result.status is ElaborationStatus.REJECTED
    assert any(d.code == CODE_UNKNOWN_SIGNATURE for d in result.diagnostics)
    with pytest.raises(ElaborationError, match="not backend-ready"):
        DEFAULT_ELABORATOR.elaborate_to_backend(node)


def test_successful_elaboration_is_backend_ready() -> None:
    signature = _fol_signature()
    node = _human_alice()
    result = elaborate_expression(node, signature, expression_id="expr:ok")
    assert result.status is ElaborationStatus.OK
    assert result.backend_ready is True
    typed = result.require_backend_ready()
    assert isinstance(typed, TypedExpression)
    assert typed.root.kind is NodeKind.PREDICATE
    assert result.normalized_root is not None
    assert result.semantic_digest
    assert "alice" in result.symbol_table


# ---------------------------------------------------------------------------
# Normalization — idempotent
# ---------------------------------------------------------------------------


def test_normalization_idempotent_and() -> None:
    p = mk_predicate("n:p", "P")
    q = mk_predicate("n:q", "Q")
    r = mk_predicate("n:r", "R")
    # Nested and with permuted order.
    formula = mk_and("n:and1", mk_and("n:and2", r, p), q)
    first = normalize(formula)
    second = normalize(first)
    assert first.to_dict() == second.to_dict()
    assert DEFAULT_NORMALIZER.is_normalized(first)


def test_normalization_idempotent_or_and_iff() -> None:
    p = mk_predicate("n:p", "P")
    q = mk_predicate("n:q", "Q")
    formula = mk_or("n:or", mk_or("n:or2", q, p), p)
    first = normalize(formula)
    second = normalize(first)
    assert first.to_dict() == second.to_dict()

    iff = mk_iff("n:iff", q, p)
    n1 = normalize(iff)
    n2 = normalize(n1)
    assert n1.to_dict() == n2.to_dict()


def test_normalization_strips_ranges_and_is_deterministic() -> None:
    from ipfs_datasets_py.logic.syntax_core.contracts import SourceRange

    person = _person()
    left = mk_constant("n:a1", "alice", person, range=SourceRange(start=0, end=5))
    right = mk_constant("n:a2", "alice", person, range=SourceRange(start=6, end=11))
    # Same semantic content, different node ids/ranges → same normalized form.
    n1 = normalize(left)
    n2 = normalize(right)
    assert n1.to_dict() == n2.to_dict()
    assert n1.range is None


def test_normalization_quantifier_body() -> None:
    person = _person()
    body = mk_predicate(
        "n:h",
        "Human",
        (mk_variable("n:x", "x", person),),
    )
    formula = mk_forall("n:all", (Binder(name="x", sort=person),), body)
    first = normalize(formula)
    second = normalize(first)
    assert first.to_dict() == second.to_dict()
    assert first.kind is NodeKind.FORALL


def test_normalization_connectives_flatten_and_sort() -> None:
    p = mk_predicate("n:p", "P")
    q = mk_predicate("n:q", "Q")
    r = mk_predicate("n:r", "R")
    a = normalize(mk_and("n:1", p, q, r))
    b = normalize(mk_and("n:2", r, mk_and("n:3", q, p)))
    # After flatten+sort, both should match.
    assert a.to_dict() == b.to_dict()


# ---------------------------------------------------------------------------
# Typechecker / elaborator integration
# ---------------------------------------------------------------------------


def test_typecheck_report_ok_for_well_typed() -> None:
    signature = _prop_signature()
    node = mk_implies(
        "n:imp",
        mk_predicate("n:p", "P"),
        mk_predicate("n:q", "Q"),
    )
    report = LogicTypechecker(signature).typecheck(node)
    assert report.ok is True
    assert report.root is not None
    assert report.backend_ready is False  # typecheck alone never grants authority


def test_typecheck_sort_mismatch() -> None:
    person = _person()
    signature = many_sorted_fol_signature(
        "sig:mm",
        sorts=(person,),
        constants=(("alice", person),),
        predicates=(("Human", (person,)),),
    )
    # Predicate expects Person; feed a Boolean formula as term — shape fails earlier.
    # Use wrong constant sort via undeclared application.
    bad = mk_predicate(
        "n:bad",
        "Human",
        (mk_application("n:f", "missing", (mk_constant("n:a", "alice", person),)),),
    )
    report = LogicTypechecker(signature).typecheck(bad)
    assert report.ok is False


def test_elaborator_to_dict_round_trip() -> None:
    elaborator = LogicElaborator(signature=_prop_signature())
    restored = LogicElaborator.from_dict(elaborator.to_dict())
    assert restored.signature is not None
    assert restored.signature.signature_id == elaborator.signature.signature_id


def test_elaboration_result_dict_round_trip() -> None:
    signature = _fol_signature()
    result = elaborate_expression(
        _human_alice(), signature, expression_id="expr:rt"
    )
    restored = ElaborationResult.from_dict(result.to_dict())
    assert restored.backend_ready is True
    assert restored.content_digest == result.content_digest
    assert restored.semantic_digest == result.semantic_digest


def test_propositional_elaboration_and_exists() -> None:
    signature = _fol_signature()
    person = _person()
    body = mk_predicate(
        "n:h",
        "Human",
        (mk_variable("n:x", "x", person),),
    )
    formula = mk_exists("n:ex", (Binder(name="x", sort=person),), body)
    result = LogicElaborator(signature=signature).elaborate(
        formula, expression_id="expr:ex"
    )
    assert result.backend_ready is True
    assert result.root is not None
    assert result.root.kind is NodeKind.EXISTS


# ---------------------------------------------------------------------------
# Codec round-trips
# ---------------------------------------------------------------------------


def test_codec_typed_expression_round_trip() -> None:
    signature = _fol_signature()
    expr = TypedExpression(
        expression_id="expr:codec",
        root=_human_alice(),
        signature=signature,
    )
    codec = TypedLogicCodec()
    envelope = codec.encode_typed_expression(expr)
    assert envelope.kind is CodecKind.TYPED_EXPRESSION
    restored = codec.decode_typed_expression(envelope)
    assert restored.expression_id == expr.expression_id
    assert restored.content_digest == expr.content_digest
    assert restored.root.kind is expr.root.kind
    # Bytes path.
    again = codec.decode_typed_expression(codec.encode_bytes(expr))
    assert again.content_digest == expr.content_digest


def test_codec_logic_node_round_trip() -> None:
    node = mk_and(
        "n:and",
        mk_predicate("n:p", "P"),
        mk_not("n:not", mk_predicate("n:q", "Q")),
    )
    restored = DEFAULT_CODEC.decode_node(DEFAULT_CODEC.encode_node(node))
    assert restored.to_dict() == node.to_dict()


def test_codec_signature_round_trip() -> None:
    signature = _fol_signature()
    restored = DEFAULT_CODEC.decode_signature(DEFAULT_CODEC.encode_signature(signature))
    assert restored.to_dict() == signature.to_dict()


def test_codec_elaboration_result_round_trip() -> None:
    signature = _fol_signature()
    result = elaborate_expression(
        _human_alice(), signature, expression_id="expr:codec-elab"
    )
    codec = TypedLogicCodec()
    restored = codec.decode_elaboration_result(codec.encode_elaboration_result(result))
    assert restored.backend_ready is True
    assert restored.content_digest == result.content_digest
    assert restored.status is ElaborationStatus.OK
    assert restored.typed_expression is not None


def test_codec_module_helpers_round_trip() -> None:
    signature = _prop_signature()
    expr = TypedExpression(
        expression_id="expr:mod",
        root=mk_predicate("n:p", "P"),
        signature=signature,
    )
    assert isinstance(round_trip(expr), TypedExpression)
    assert isinstance(decode(encode(expr)), TypedExpression)


def test_codec_json_string_round_trip() -> None:
    signature = _prop_signature()
    expr = TypedExpression(
        expression_id="expr:json",
        root=mk_or("n:or", mk_predicate("n:p", "P"), mk_predicate("n:q", "Q")),
        signature=signature,
    )
    text = DEFAULT_CODEC.encode_json(expr)
    # Stable deterministic JSON (sorted keys).
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    restored = DEFAULT_CODEC.decode_typed_expression(text)
    assert restored.content_digest == expr.content_digest


def test_codec_rejects_unknown_schema_version() -> None:
    bad = {
        "kind": CodecKind.LOGIC_NODE.value,
        "schema_version": "syntax-logic-node/v999",
        "payload": mk_true().to_dict(),
        "codec_version": "syntax-typed-logic-envelope/v1",
        "metadata": {},
    }
    with pytest.raises(CodecError, match="unsupported"):
        DEFAULT_CODEC.decode(bad)


def test_codec_rejects_unknown_envelope_version() -> None:
    with pytest.raises(CodecError, match="unsupported envelope"):
        CodecEnvelope(
            kind=CodecKind.LOGIC_NODE,
            schema_version="syntax-logic-node/v1",
            payload=mk_true().to_dict(),
            codec_version="syntax-typed-logic-envelope/v999",
        )


def test_codec_rejects_digest_mismatch() -> None:
    signature = _prop_signature()
    expr = TypedExpression(
        expression_id="expr:dig",
        root=mk_predicate("n:p", "P"),
        signature=signature,
    )
    envelope = DEFAULT_CODEC.encode(expr).to_dict()
    envelope["content_digest"] = "0" * 64
    with pytest.raises(CodecError, match="content_digest"):
        CodecEnvelope.from_dict(envelope)


def test_codec_encode_dispatch() -> None:
    signature = _prop_signature()
    assert DEFAULT_CODEC.encode(signature).kind is CodecKind.SIGNATURE
    assert DEFAULT_CODEC.encode(mk_false()).kind is CodecKind.LOGIC_NODE


def test_full_pipeline_registry_elaborate_codec() -> None:
    """End-to-end: register parser key, elaborate formula, codec round-trip."""

    registry = empty_parser_registry()
    registry.register(_descriptor(), parser=_stub_parser)
    assert registry.resolve(
        notation_id="fol",
        notation_version="1.0.0",
        semantic_profile_id="many_sorted",
    )

    signature = _fol_signature()
    person = _person()
    formula = mk_and(
        "n:top",
        mk_predicate("n:h1", "Human", (mk_constant("n:a", "alice", person),)),
        mk_predicate("n:h2", "Human", (mk_constant("n:b", "bob", person),)),
    )
    result = LogicElaborator(signature=signature).elaborate(
        formula, expression_id="expr:pipe"
    )
    assert result.backend_ready is True
    # Normalization fixed point on the elaborated root.
    assert result.normalized_root is not None
    assert (
        normalize(result.normalized_root).to_dict()
        == result.normalized_root.to_dict()
    )
    # Codec round-trip preserves readiness.
    restored = DEFAULT_CODEC.decode_elaboration_result(
        DEFAULT_CODEC.encode_elaboration_result(result)
    )
    assert restored.backend_ready is True
    assert restored.require_backend_ready().content_digest == (
        result.typed_expression.content_digest  # type: ignore[union-attr]
    )


def test_equality_and_application_elaboration() -> None:
    signature = _fol_signature()
    person = _person()
    alice = mk_constant("n:a", "alice", person)
    father_alice = mk_application(
        "n:f",
        "father",
        (alice,),
        sort=person,
    )
    formula = mk_equality("n:eq", father_alice, mk_constant("n:b", "bob", person))
    result = elaborate_expression(formula, signature, expression_id="expr:eq")
    assert result.backend_ready is True
    assert result.root is not None
    assert result.root.kind is NodeKind.EQUALITY
