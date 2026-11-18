"""Bridge tests: FormalFormula / ConstraintStatement dual-read and typed write.

Acceptance (LFP-016):

* typed expressions validate family / profile / schema
* constraint contracts dual-read legacy payloads but write TypedExpression and
  TranslationContract@2 when those are supplied
* arbitrary JSON/text and a boolean loss flag cannot masquerade as elaborated
  syntax or a preservation receipt
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.translations import (
    CONTRACT_INTERFACE,
    NodeDisposition,
    NodeMapEntry,
    PreservationRelation,
    SymbolMapEntry,
    TranslationContract,
    TranslationEndpoint,
    TranslationIdentities,
)
from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    CONSTRAINT_CONTRACT_INTERFACE,
    TRANSLATION_CONTRACT_INTERFACE,
    ConstraintRole,
    ConstraintStatement,
    ConstraintValidationError,
    TranslationReceipt,
    coerce_constraint_expression,
    coerce_translation_payload,
    serialize_constraint_expression,
    serialize_translation_payload,
)
from ipfs_datasets_py.logic.formalization.views import (
    FORMALIZATION_ARTIFACT_V2_INTERFACE,
    FormalFormula,
    FormalizationValidationError,
    coerce_formula_expression,
    is_typed_expression,
    serialize_formula_expression,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    TYPED_EXPRESSION_INTERFACE,
    TYPED_EXPRESSION_SCHEMA_VERSION,
    TypedExpression,
    mk_predicate,
)
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


def _typed_expression(
    *,
    expression_id: str = "expr:bridge-1",
    predicate: str = "P",
) -> TypedExpression:
    signature = propositional_signature(
        "sig:bridge",
        (predicate, "Q"),
        family="propositional",
        profile="classical",
    )
    return TypedExpression(
        expression_id=expression_id,
        root=mk_predicate(f"n:{predicate}", predicate),
        signature=signature,
        family="propositional",
        profile="classical",
    )


def _translation_contract() -> TranslationContract:
    return TranslationContract(
        contract_id="bridge_deontic_to_fol",
        source=TranslationEndpoint(
            family_id="deontic",
            profile_id="deontic_default",
            fragment_id="deontic_core",
            schema_id="deontic_schema",
            notation_id="deontic_notation",
            content_identity="sha256:deontic",
        ),
        target=TranslationEndpoint(
            family_id="first_order",
            profile_id="first_order_default",
            fragment_id="first_order_core",
            schema_id="first_order_schema",
            notation_id="first_order_notation",
            content_identity="sha256:first_order",
        ),
        preservation=PreservationRelation.HEURISTIC,
        identities=TranslationIdentities(
            compiler_identity="sha256:" + "a" * 64,
            profile_identity="sha256:" + "b" * 64,
            config_identity="sha256:" + "c" * 64,
            source_identity=(
                "bafkreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            target_identity=(
                "bafkreibbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
            environment_identity="sha256:" + "d" * 64,
        ),
        proof_safe=False,
        counterexample_safe=False,
        authority_ceiling=EvidenceAuthority.NONE,
        node_map=(
            NodeMapEntry(
                source_node_id="n_grant",
                target_node_ids=("t_fact",),
                disposition=NodeDisposition.APPROXIMATED,
                reason="heuristic lowering",
            ),
        ),
        symbol_map=(
            SymbolMapEntry(
                source_symbol_id="publish",
                target_symbol_ids=("publish_fol",),
                disposition=NodeDisposition.MAPPED,
            ),
        ),
        required_source_node_ids=("n_grant",),
        required_source_symbol_ids=("publish",),
        description="Reviewed heuristic deontic-to-FOL bridge edge.",
    )


# ---------------------------------------------------------------------------
# FormalFormula dual-read / typed write
# ---------------------------------------------------------------------------


def test_formal_formula_dual_reads_legacy_json_and_writes_legacy() -> None:
    formula = FormalFormula(
        formula_id="formula:legacy",
        view_id="view:facts",
        expression={"predicate": "holds", "arguments": ["x"]},
        source_ref_ids=("source:1",),
        span_ids=("span:1",),
    )
    assert formula.is_typed is False
    assert is_typed_expression(formula.expression) is False
    payload = formula.to_dict()
    assert payload["expression"] == {"arguments": ["x"], "predicate": "holds"}
    restored = FormalFormula.from_dict(payload)
    assert restored.expression == formula.expression
    assert FORMALIZATION_ARTIFACT_V2_INTERFACE == "FormalizationArtifact@2"


def test_formal_formula_accepts_typed_expression_and_writes_typed_envelope() -> None:
    typed = _typed_expression()
    formula = FormalFormula(
        formula_id="formula:typed",
        view_id="view:prop",
        expression=typed,
        source_ref_ids=("source:1",),
        span_ids=("span:1",),
    )
    assert formula.is_typed is True
    assert isinstance(formula.expression, TypedExpression)
    assert formula.expression.family.value == "propositional"
    assert formula.expression.profile.value == "classical"
    assert formula.expression.schema_version == TYPED_EXPRESSION_SCHEMA_VERSION

    payload = formula.to_dict()
    expression = payload["expression"]
    assert expression["interface"] == TYPED_EXPRESSION_INTERFACE
    assert expression["schema_version"] == TYPED_EXPRESSION_SCHEMA_VERSION
    assert expression["family"]["value"] == "propositional"
    assert expression["profile"]["value"] == "classical"

    restored = FormalFormula.from_dict(payload)
    assert restored.is_typed is True
    assert restored.expression.content_digest == typed.content_digest


def test_typed_expression_validates_family_profile_schema() -> None:
    with pytest.raises(FormalizationValidationError, match="TypedExpression"):
        coerce_formula_expression(
            {
                "interface": TYPED_EXPRESSION_INTERFACE,
                "schema_version": TYPED_EXPRESSION_SCHEMA_VERSION,
                "expression_id": "expr:bad",
                # Missing root/signature — cannot masquerade as elaborated syntax.
                "family": "propositional",
                "profile": "classical",
            }
        )

    with pytest.raises(FormalizationValidationError, match="TypedExpression"):
        FormalFormula(
            formula_id="formula:masquerade",
            view_id="view:prop",
            expression={
                "interface": TYPED_EXPRESSION_INTERFACE,
                "expression_id": "expr:masquerade",
                "root": {"not": "a logic node"},
                "signature": {"not": "a signature"},
            },
            source_ref_ids=("source:1",),
        )


def test_arbitrary_json_text_cannot_masquerade_as_typed_expression() -> None:
    # Unclaimed legacy JSON is dual-read as non-typed.
    legacy = coerce_formula_expression({"operator": "and", "args": []})
    assert is_typed_expression(legacy) is False
    assert serialize_formula_expression(legacy) == {"args": [], "operator": "and"}

    # Claiming TypedExpression without valid structure fails closed.
    with pytest.raises(FormalizationValidationError):
        coerce_formula_expression(
            {
                "interface": "TypedExpression@1",
                "expression_id": "x",
                "root": {},
                "signature": {},
            }
        )


# ---------------------------------------------------------------------------
# ConstraintStatement dual-read / typed write
# ---------------------------------------------------------------------------


def test_constraint_statement_dual_reads_legacy_and_writes_typed() -> None:
    legacy = ConstraintStatement(
        statement_id="stmt:legacy",
        role=ConstraintRole.CLAIM,
        logic_family="first_order",
        expression={"predicate": "p", "arguments": ["x"]},
        source_ref_ids=("source:1",),
        span_ids=("span:1",),
    )
    assert legacy.is_typed is False
    assert legacy.to_dict()["expression"]["predicate"] == "p"

    typed = _typed_expression(predicate="P")
    # propositional family matches TypedExpression
    statement = ConstraintStatement(
        statement_id="stmt:typed",
        role=ConstraintRole.CLAIM,
        logic_family="propositional",
        expression=typed,
        source_ref_ids=("source:1",),
        span_ids=("span:1",),
    )
    assert statement.is_typed is True
    wire = statement.to_dict()["expression"]
    assert wire["interface"] == TYPED_EXPRESSION_INTERFACE
    restored = ConstraintStatement.from_dict(statement.to_dict())
    assert restored.is_typed is True
    assert CONSTRAINT_CONTRACT_INTERFACE == "ConstraintContract@2"


def test_constraint_expression_rejects_text_masquerade() -> None:
    with pytest.raises(ConstraintValidationError, match="elaborated syntax"):
        coerce_constraint_expression("just some text")
    with pytest.raises(ConstraintValidationError, match="elaborated syntax"):
        coerce_constraint_expression(True)
    with pytest.raises(ConstraintValidationError, match="TypedExpression"):
        coerce_constraint_expression(
            {
                "interface": TYPED_EXPRESSION_INTERFACE,
                "schema_version": TYPED_EXPRESSION_SCHEMA_VERSION,
                "expression_id": "bad",
            }
        )


def test_constraint_statement_rejects_family_disagreement_with_typed() -> None:
    typed = _typed_expression()
    with pytest.raises(ConstraintValidationError, match="disagrees with TypedExpression"):
        ConstraintStatement(
            statement_id="stmt:mismatch",
            role=ConstraintRole.CLAIM,
            logic_family="deontic",
            expression=typed,
            source_ref_ids=("source:1",),
        )


# ---------------------------------------------------------------------------
# Translation dual-read: TranslationContract@2 vs legacy receipt / loss flag
# ---------------------------------------------------------------------------


def test_translation_dual_reads_legacy_receipt_and_contract() -> None:
    legacy = TranslationReceipt(
        translation_id="translation:legacy",
        source_logic_family="deontic",
        target_logic_family="first_order",
        source_view_id="view:deontic",
        target_view_id="view:fol",
        lossy=True,
    )
    assert coerce_translation_payload(legacy.to_dict()) == legacy
    wire = serialize_translation_payload(legacy)
    assert wire["lossy"] is True
    assert "preservation" not in wire

    contract = _translation_contract()
    parsed = coerce_translation_payload(contract.to_dict())
    assert isinstance(parsed, TranslationContract)
    assert parsed.interface == CONTRACT_INTERFACE == TRANSLATION_CONTRACT_INTERFACE
    written = serialize_translation_payload(parsed)
    assert written["interface"] == "TranslationContract@2"
    assert written["preservation"] == "heuristic"
    assert "lossy" not in written or written.get("lossy") is not True


def test_boolean_loss_flag_cannot_masquerade_as_preservation_receipt() -> None:
    with pytest.raises(ConstraintValidationError, match="boolean loss flag"):
        coerce_translation_payload(True)
    with pytest.raises(ConstraintValidationError, match="boolean loss flag"):
        coerce_translation_payload(False)
    with pytest.raises(ConstraintValidationError, match="boolean loss flag"):
        coerce_translation_payload({"lossy": True})
    with pytest.raises(ConstraintValidationError, match="boolean loss flag"):
        coerce_translation_payload({"lossy": False})


def test_claimed_translation_contract_must_validate_fully() -> None:
    with pytest.raises(ConstraintValidationError, match="TranslationContract@2"):
        coerce_translation_payload(
            {
                "interface": "TranslationContract@2",
                "contract_id": "incomplete",
                "preservation": "exact_equivalence",
                # Missing source/target/identities — not a preservation receipt.
            }
        )


def test_serialize_helpers_round_trip_typed_surfaces() -> None:
    typed = _typed_expression()
    assert serialize_constraint_expression(typed)["interface"] == TYPED_EXPRESSION_INTERFACE
    assert coerce_constraint_expression(
        serialize_constraint_expression(typed)
    ).content_digest == typed.content_digest

    contract = _translation_contract()
    assert (
        serialize_translation_payload(contract)["interface"]
        == TRANSLATION_CONTRACT_INTERFACE
    )


from typing import Any

# Source-only typed-IR adapter fixtures are explicitly fictional and inert.
# No weights, tokenizer assets, legal review, native prover, or quality result.
import hashlib
import json

from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    ProposalAdvisorValidationError,
    UNVERIFIED_AUTHORITY,
    propose_source_conditioned_typed_ir,
)


def _source_only_digest(record: Any) -> str:
    raw = json.dumps(record, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _fictional_relational_expression() -> dict[str, Any]:
    from ipfs_datasets_py.logic.syntax_core.ast import (
        Binder, TypedExpression, mk_constant, mk_forall, mk_predicate, mk_variable,
    )
    from ipfs_datasets_py.logic.syntax_core.signatures import (
        atomic_sort, many_sorted_fol_signature,
    )
    actor, document, institution = (atomic_sort(name) for name in
                                    ("FictionalActor", "FictionalNotice", "FictionalInstitution"))
    signature = many_sorted_fol_signature(
        "sig:fictional-send", sorts=(actor, document, institution),
        constants=(("FictionalBoard", institution),),
        predicates=(("Sends", (actor, document, institution)),),
        family="first_order", profile="many_sorted",
    )
    root = mk_forall(
        "node:fictional-all", (Binder("actor", actor), Binder("notice", document)),
        mk_predicate("node:fictional-send", "Sends", (
            mk_variable("node:actor", "actor", actor),
            mk_variable("node:notice", "notice", document),
            mk_constant("node:board", "FictionalBoard", institution),
        )),
    )
    return TypedExpression("expr:fictional-send", root, signature).to_dict()


class _InertSourceTokenizer:
    def __init__(self) -> None:
        self.metadata = {
            "tokenizer_id": "fixture:character-tokenizer",
            "vocabulary_sha256": "sha256:" + "3" * 64,
            "configuration_sha256": "sha256:" + "4" * 64,
            "bos_token_id": 1, "eos_token_id": 2,
        }

    def binding_metadata(self) -> dict[str, Any]:
        return dict(self.metadata)

    def encode(self, text: str) -> list[int]:
        return [ord(character) + 100 for character in text]

    def decode(self, token_ids: tuple[int, ...]) -> str:
        return "".join(chr(token - 100) for token in token_ids)


class _InertSourceTokenModel:
    def __init__(self, history: list[int] | None) -> None:
        self.history = history
        self.calls: list[dict[str, Any]] = []
        self.metadata = {
            "model_id": "fixture:token-model", "checkpoint_sha256": "sha256:" + "1" * 64,
            "configuration_sha256": "sha256:" + "2" * 64,
        }
        self.change_binding = False
        self.raise_error = False

    def binding_metadata(self) -> dict[str, Any]:
        return dict(self.metadata)

    def generate_token_ids(self, input_ids: tuple[int, ...], *,
                           decoder_prefix_ids: tuple[int, ...],
                           max_new_tokens: int) -> list[int] | None:
        self.calls.append({"input_ids": input_ids, "prefix": decoder_prefix_ids,
                           "max_new_tokens": max_new_tokens})
        if self.change_binding:
            self.metadata["checkpoint_sha256"] = "sha256:" + "5" * 64
        if self.raise_error:
            raise RuntimeError("private provider detail must not enter evidence")
        return None if self.history is None else list(self.history)


def _source_only_fixture(output: str | None = None, *, abstain: bool = False):
    tokenizer = _InertSourceTokenizer()
    if output is None:
        payload = _fictional_relational_expression()
        # Derived canonical identity is computed by the AST owner, not predicted.
        payload["content_digest"] = ""
        output = json.dumps(payload, sort_keys=True)
    history = None if abstain else [1, *tokenizer.encode(output), 2]
    model = _InertSourceTokenModel(history)
    source = "  Every fictional clerk sends every fictional notice to FictionalBoard. § 1\r\n"
    kwargs = {
        "request_id": "request:fictional-source-only", "source_text": source,
        "source_ref_ids": ("source:fictional-statute",), "source_revision": "fictional-edition-1",
        "expected_source_sha256": "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "expected_model_binding_sha256": _source_only_digest(model.metadata),
        "expected_tokenizer_binding_sha256": _source_only_digest(tokenizer.metadata),
        "expected_family": "first_order", "expected_profile": "many_sorted",
        "max_input_tokens": 65_536, "max_new_tokens": 32_768,
    }
    return model, tokenizer, kwargs


def test_source_only_complete_typed_IR_preserves_source_roles_and_scopes() -> None:
    model, tokenizer, kwargs = _source_only_fixture()
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == "complete"
    assert result["typed_ir"] == _fictional_relational_expression()
    assert result["source_text"] == kwargs["source_text"]
    assert result["source_utf8_sha256"] == kwargs["expected_source_sha256"]
    assert result["source_revision"] == "fictional-edition-1"
    assert model.calls[0]["prefix"] == (1,)
    assert result["generated_ids"] == model.history
    assert result["new_token_count"] == len(model.history) - 1
    prompt = json.loads(tokenizer.decode(model.calls[0]["input_ids"]))
    assert prompt["source"]["text"] == kwargs["source_text"]
    assert set(prompt) == {"profile", "authority", "instruction", "request_id", "source",
                           "output_family", "output_profile"}
    assert result["counts"] == {"complete": 1, "incomplete": 0, "abstained": 0,
                                "unsupported": 0, "invalid": 0, "error": 0}
    assert result["authority"] == UNVERIFIED_AUTHORITY
    for key in ("legal_review_verified", "proof_authority", "training_gold_authority",
                "Lean_admitted", "physical_model_assets_verified", "source_authority_authenticated",
                "model_execution_authenticated"):
        assert result[key] is False
    identity = result.pop("result_identity")
    assert identity == _source_only_digest(result)


@pytest.mark.parametrize("alteration,expected", [
    ("no_eos", "incomplete"), ("after_eos", "invalid"),
    ("duplicate_eos", "invalid"), ("extra_bos", "invalid"),
    ("missing_bos", "invalid"), ("empty", "invalid"), ("only_bos", "incomplete"),
])
def test_source_only_actual_token_completion_is_required(alteration: str, expected: str) -> None:
    model, tokenizer, kwargs = _source_only_fixture()
    assert model.history is not None
    if alteration == "no_eos":
        model.history.pop()
    elif alteration == "after_eos":
        model.history.append(200)
    elif alteration == "duplicate_eos":
        model.history.append(2)
    elif alteration == "extra_bos":
        model.history.insert(1, 1)
    elif alteration == "missing_bos":
        model.history.pop(0)
    elif alteration == "empty":
        model.history = []
    else:
        model.history = [1]
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == expected
    assert result["typed_ir"] is None
    assert result["counts"][expected] == 1


@pytest.mark.parametrize("kind", ["unknown_clause", "nested_unknown", "duplicate_json", "nonfinite",
                                  "wrong_arity", "authority", "wrong_profile", "bare_term"])
def test_source_only_invalid_or_dropped_typed_AST_is_rejected(kind: str) -> None:
    payload = _fictional_relational_expression()
    payload["content_digest"] = ""
    if kind == "unknown_clause":
        payload["unimplemented_exception"] = {"unless": "fictional emergency"}
    elif kind == "nested_unknown":
        payload["root"]["binders"][0]["unimplemented_scope"] = "different actor"
    elif kind == "wrong_arity":
        payload["root"]["arguments"][0]["arguments"].pop()
    elif kind == "authority":
        payload["proof_authority"] = True
    elif kind == "wrong_profile":
        payload["profile"] = "unsupported_profile"
    elif kind == "bare_term":
        payload["root"] = payload["root"]["arguments"][0]["arguments"][2]
    output = json.dumps(payload)
    if kind == "duplicate_json":
        output = output[:-1] + ', "root": {}}'
    elif kind == "nonfinite":
        output = output[:-1] + ', "unsupported": NaN}'
    model, tokenizer, kwargs = _source_only_fixture(output)
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == "invalid"
    assert result["typed_ir"] is None


def test_source_only_budget_refusal_never_truncates_source_or_AST() -> None:
    model, tokenizer, kwargs = _source_only_fixture()
    kwargs["max_input_tokens"] = 1
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == "unsupported" and model.calls == []
    assert result["source_text"] == kwargs["source_text"]
    kwargs["max_input_tokens"] = 65_536
    kwargs["max_new_tokens"] = 1
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == "invalid" and result["typed_ir"] is None
    assert result["generated_ids"] == model.history
    kwargs["max_new_tokens"] = 32_768
    kwargs["max_output_bytes"] = 1
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == "unsupported" and result["typed_ir"] is None


@pytest.mark.parametrize("binding", ["source", "model", "tokenizer", "during_model_call"])
def test_source_only_independent_identity_pins_must_match(binding: str) -> None:
    model, tokenizer, kwargs = _source_only_fixture()
    if binding == "source":
        kwargs["source_text"] += " Changed actor."
    elif binding == "model":
        model.metadata["checkpoint_sha256"] = "sha256:" + "5" * 64
    elif binding == "tokenizer":
        tokenizer.metadata["vocabulary_sha256"] = "sha256:" + "5" * 64
    else:
        model.change_binding = True
    with pytest.raises(ProposalAdvisorValidationError, match="binding"):
        propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert len(model.calls) == int(binding == "during_model_call")


def test_source_only_abstention_and_operational_error_are_distinct_without_provider_text() -> None:
    model, tokenizer, kwargs = _source_only_fixture(abstain=True)
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == "abstained" and result["reason"] == "explicit_model_abstention"
    model.raise_error = True
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == "error" and result["reason"] == "model_generation_callback_failed"
    assert result["counts"]["error"] == 1 and result["counts"]["abstained"] == 0
    assert "private provider" not in json.dumps(result)


@pytest.mark.parametrize("extra", [
    {"context_profile": "rich/v1"}, {"rich_context": {"eligible": True}},
])
def test_source_only_rich_context_requires_future_versioned_validation(extra: dict[str, Any]) -> None:
    model, tokenizer, kwargs = _source_only_fixture()
    with pytest.raises(ProposalAdvisorValidationError, match="unsupported context"):
        propose_source_conditioned_typed_ir(model, tokenizer, **kwargs, **extra)
    assert model.calls == []


def test_source_only_closed_API_does_not_accept_reference_target_or_decoder_prefix() -> None:
    model, tokenizer, kwargs = _source_only_fixture()
    for hidden in ("reference_target", "target_ast", "decoder_prefix_ids", "gold_labels"):
        with pytest.raises(TypeError):
            propose_source_conditioned_typed_ir(model, tokenizer, **kwargs, **{hidden: "hidden"})
    assert model.calls == []


def test_source_only_undeclared_tokenizer_normalization_is_unsupported() -> None:
    model, tokenizer, kwargs = _source_only_fixture()
    original = tokenizer.decode
    tokenizer.decode = lambda ids: original(ids).replace("fictional", "normalized")
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == "unsupported"
    assert result["reason"] == "tokenizer_does_not_preserve_complete_prompt"
    assert model.calls == []


def test_source_only_inference_identity_binds_budget_and_model_pins() -> None:
    model, tokenizer, kwargs = _source_only_fixture()
    first = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    kwargs["max_new_tokens"] -= 1
    second = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert first["input_identity"] == second["input_identity"]
    assert first["inference_context_identity"] != second["inference_context_identity"]
    assert first["result_identity"] != second["result_identity"]


@pytest.mark.parametrize(("owner", "method"), [
    ("model", "binding_metadata"), ("tokenizer", "binding_metadata"),
    ("tokenizer", "encode"), ("tokenizer", "decode"),
])
def test_source_only_callback_failures_are_explicit_operational_errors(owner: str, method: str) -> None:
    model, tokenizer, kwargs = _source_only_fixture()
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("private callback detail")
    setattr(model if owner == "model" else tokenizer, method, fail)
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == "error" and result["counts"]["error"] == 1
    assert result["counts"]["abstained"] == 0 and result["typed_ir"] is None
    assert result["model_call_count"] == 0
    assert "private callback detail" not in json.dumps(result)


def test_source_only_output_decode_failure_is_error_after_one_model_call() -> None:
    model, tokenizer, kwargs = _source_only_fixture()
    original = tokenizer.decode
    calls = 0
    def decode(ids: tuple[int, ...]) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("private output callback detail")
        return original(ids)
    tokenizer.decode = decode
    result = propose_source_conditioned_typed_ir(model, tokenizer, **kwargs)
    assert result["status"] == "error" and result["counts"]["abstained"] == 0
    assert result["model_call_count"] == 1 and result["typed_ir"] is None
    assert "private output callback" not in json.dumps(result)
