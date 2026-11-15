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


# Full-norm proposal fixtures remain fictional and unreviewed. Source bytes,
# public known context and the actual nine-field output are distinct inputs.
from copy import deepcopy

from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    COMPLETE_NORM_SOURCE_PROFILE, COMPLETE_NORM_TARGET_CODEC,
    ReviewedDecoderTokenizerAdapter, TorchCompleteNormGenerationAdapter,
    propose_source_conditioned_complete_norm,
)


def _full_norm_fixture():
    from ipfs_datasets_py.logic.autoformal import corpus_source, legal_relational_norm_v1
    from ipfs_datasets_py.logic.syntax_core import ast, signatures

    sort = signatures.LogicSort("Object")
    counter = 0
    def nid():
        nonlocal counter
        counter += 1
        return "fixture:proposal-node:" + str(counter)
    def atom(symbol, *variables):
        return ast.mk_predicate(nid(), symbol,
            [ast.mk_variable(nid(), value, sort) for value in variables])
    action = atom("Assigns", "officer", "clerk")
    obligation = ast.mk_extension(nid(), family="tdfol", profile="tdfol_default",
        features=("legacy.obligation", "legacy.classic_letter"),
        payload_schema="legacy.deontic/v1",
        payload={"kind": "obligation", "letter": "O", "resolution": "deontic",
                 "schema_version": "legacy.deontic/v1"}, children=(action,))
    body = ast.mk_implies(nid(), atom("CoveredOfficer", "officer"), obligation)
    body = ast.mk_exists(nid(), [ast.Binder("clerk", sort)], body)
    body = ast.mk_forall(nid(), [ast.Binder("officer", sort)], body)
    signature = signatures.LogicSignature("fixture:proposal-signature", family="tdfol",
        profile="tdfol_default", sorts=(sort,), symbols=(
            signatures.declare_predicate("CoveredOfficer", (sort,)),
            signatures.declare_predicate("Assigns", (sort, sort))))
    expression = ast.TypedExpression("fixture:proposal-expression", body, signature).to_dict()
    request = {"schema": "legal-relational-norm-request/v1",
        "interpretation_status": "authored_unreviewed_declaration", "expression": expression,
        "argument_roles": [{"symbol": "CoveredOfficer", "roles": ["officer"]},
                           {"symbol": "Assigns", "roles": ["officer", "clerk"]}], "source_binding": None}
    raw = json.dumps(request, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    prepared = legal_relational_norm_v1.prepare_relational_norm_v1(raw,
        expected_request_sha256=hashlib.sha256(raw).hexdigest())
    text = "For this fictional proposal, every covered officer must assign a clerk. Café."
    source_raw = text.encode("utf-8")
    source_sha = hashlib.sha256(source_raw).hexdigest()
    version = corpus_source.build_source_version(source_id="fixture:proposal-source",
        release_id="fixture:proposal-act", edition="fictional-edition", provision_id="fixture:proposal-section",
        raw_bytes=source_raw, expected_raw_sha256=source_sha, extracted_text=text,
        expected_extracted_sha256=source_sha, extraction_profile="identity/v1",
        normalization_profile="identity/v1", media_type="text/plain")
    occurrence = corpus_source.build_source_occurrence(version, expected_raw_sha256=source_sha,
        extracted_text=text, expected_extracted_sha256=source_sha, start_char=0, end_char=len(text),
        start_utf8=0, end_utf8=len(source_raw))
    binding = {"source_version_cid": version["record_cid"], "occurrence_cid": occurrence["record_cid"],
               "document_revision": "fixture:proposal-revision-1"}
    context = {"jurisdiction": "fictional-jurisdiction", "instrument_id": "fixture:proposal-act",
        "governing_edition": "fictional-edition", "legal_as_of_utc": "2024-06-01T00:00:00Z",
        "valid_from_utc": "2024-01-01T00:00:00Z", "valid_until_utc": "2025-01-01T00:00:00Z"}
    return text, {"profile": prepared["profile"], "typed_expression": prepared["typed_expression"],
        "argument_roles": prepared["argument_roles"], "assumptions": [],
        "governing_context": context, "interpretation_id": "fixture:unreviewed-interpretation",
        "source_binding": binding, "definition_uses": [], "cross_references": []}


class _FullNormTokenizer(_InertSourceTokenizer):
    bos_token_id, eos_token_id, vocab_size = 1, 2, 512

    def __init__(self):
        super().__init__()
        self.metadata["vocab_size"] = self.vocab_size
        self.encoded = []

    def encode(self, text):
        self.encoded.append(text)
        return super().encode(text)


def _full_norm_case(offered=None):
    source, target = _full_norm_fixture()
    tokenizer = _FullNormTokenizer()
    output = target if offered is None else offered(target)
    wire = json.dumps(output, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    model = _InertSourceTokenModel([1, *tokenizer.encode(wire), 2])
    tokenizer.encoded.clear()
    args = {"request_id": "fixture:request-id-must-not-enter-model",
        "source_text": source, "known_source_binding": deepcopy(target["source_binding"]),
        "known_governing_context": deepcopy(target["governing_context"]),
        # This is an independently supplied fixture selection, never filled
        # from the output or a reviewed/admission target. It selects an ID
        # only; no meaning-selection policy is supplied by this fixture.
        "known_selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": "fixture:unreviewed-interpretation", "selection_mode": "identifier_only"},
        "expected_source_sha256": "sha256:" + hashlib.sha256(source.encode()).hexdigest(),
        "expected_model_binding_sha256": _source_only_digest(model.metadata),
        "expected_tokenizer_binding_sha256": _source_only_digest(tokenizer.metadata),
        "max_input_tokens": 65536, "max_new_tokens": 32768}
    return model, tokenizer, args, target


def test_full_norm_exact_nine_fields_source_wire_and_all_authority_remain_unreviewed():
    model, tokenizer, args, target = _full_norm_case()
    before = deepcopy(args)
    result = propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert result["status"] == "complete" and result["complete_norm_candidate"] == target
    assert result["typed_ir"] == target["typed_expression"]
    assert set(result["complete_norm_candidate"]) == {"profile", "typed_expression", "argument_roles",
        "assumptions", "governing_context", "interpretation_id", "source_binding", "definition_uses", "cross_references"}
    actual = model.calls[0]
    assert actual["prefix"] == (tokenizer.bos_token_id,)
    assert actual["input_ids"][0] == tokenizer.bos_token_id
    assert actual["input_ids"][-1] == tokenizer.eos_token_id
    source_wire = tokenizer.decode(actual["input_ids"][1:-1])
    assert source_wire == json.dumps({"profile": COMPLETE_NORM_SOURCE_PROFILE,
        "source_text": args["source_text"], "governing_context": args["known_governing_context"],
        "source_binding": args["known_source_binding"],
        "selection_context": args["known_selection_context"]}, ensure_ascii=True, sort_keys=True,
        separators=(",", ":"), allow_nan=False)
    assert set(json.loads(source_wire)) == {"profile", "source_text", "governing_context", "source_binding",
                                         "selection_context"}
    assert args["request_id"] not in source_wire
    assert json.loads(source_wire)["selection_context"] == args["known_selection_context"]
    assert "typed_expression" not in source_wire and "argument_roles" not in source_wire
    assert "Caf\\u00e9" in source_wire
    assert result["source_text"] == args["source_text"] and args == before
    assert result["target_codec"] == COMPLETE_NORM_TARGET_CODEC
    assert COMPLETE_NORM_SOURCE_PROFILE == "reviewed-source-selection-context/v2"
    assert COMPLETE_NORM_TARGET_CODEC == "complete-reviewed-norm-json/v2"
    assert result["known_selection_context"] == args["known_selection_context"]
    assert result["semantic_selection_supported"] is False
    assert result["candidate_syntax"]["semantic_selection_supported"] is False
    assert result["candidate_syntax"]["known_interpretation_identifier_matches"] is True
    assert result["candidate_syntax"]["training_mask"] == result["candidate_syntax"]["evaluation_gold_mask"] == 0
    assert result["authority"] == UNVERIFIED_AUTHORITY
    assert not any(result["candidate_syntax"]["authority"].values())
    assert result["counts"] == {"complete": 1, "incomplete": 0, "abstained": 0,
                                "unsupported": 0, "invalid": 0, "error": 0}
    for key in ("legal_review_verified", "proof_authority", "training_gold_authority", "Lean_admitted",
                "physical_model_assets_verified", "source_authority_authenticated", "model_execution_authenticated"):
        assert result[key] is False


@pytest.mark.parametrize("missing", ["profile", "typed_expression", "argument_roles", "assumptions",
    "governing_context", "interpretation_id", "source_binding", "definition_uses", "cross_references"])
def test_full_norm_missing_fields_are_invalid_without_gold_completion(missing):
    model, tokenizer, args, _ = _full_norm_case(lambda target: {key: value for key, value in target.items() if key != missing})
    result = propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert result["status"] == "invalid" and result["complete_norm_candidate"] is None
    assert missing not in json.loads(result["raw_output_text"])


@pytest.mark.parametrize("field", ["source_version_cid", "occurrence_cid", "document_revision"])
def test_full_norm_changed_known_source_is_rejected_not_filled(field):
    def mutate(target):
        other = deepcopy(target)
        if field == "document_revision":
            other["source_binding"][field] = "fixture:other-revision"
        else:
            other["source_binding"][field] = target["source_binding"][
                "occurrence_cid" if field == "source_version_cid" else "source_version_cid"]
        return other
    model, tokenizer, args, _ = _full_norm_case(mutate)
    result = propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert result["status"] == "invalid" and result["complete_norm_candidate"] is None


@pytest.mark.parametrize("field,value", [
    ("jurisdiction", "other-fictional-jurisdiction"), ("instrument_id", "fixture:other-act"),
    ("governing_edition", "other-fictional-edition"), ("legal_as_of_utc", "2024-06-02T00:00:00Z"),
    ("valid_from_utc", "2024-02-01T00:00:00Z"), ("valid_until_utc", "2026-01-01T00:00:00Z")])
def test_full_norm_changed_governing_context_is_rejected_not_filled(field, value):
    def mutate(target):
        other = deepcopy(target)
        other["governing_context"][field] = value
        return other
    model, tokenizer, args, _ = _full_norm_case(mutate)
    result = propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert result["status"] == "invalid" and result["complete_norm_candidate"] is None


@pytest.mark.parametrize("construct", ["profile", "assumptions"])
def test_full_norm_unsupported_construct_remains_visible_and_unaccepted(construct):
    def mutate(target):
        other = deepcopy(target)
        other[construct] = "future-unprovided-profile/v1" if construct == "profile" else ["unprovided-premise"]
        return other
    model, tokenizer, args, _ = _full_norm_case(mutate)
    result = propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert result["status"] == "unsupported" and result["complete_norm_candidate"] is None
    assert json.loads(result["raw_output_text"])[construct]


@pytest.mark.parametrize("case", ["extra_field", "authority", "wrong_arity", "unknown_AST_field"])
def test_full_norm_invalid_or_discarded_output_structure_never_counts_complete(case):
    def mutate(target):
        other = deepcopy(target)
        if case == "extra_field": other["hidden_original_target"] = "forbidden"
        elif case == "authority": other["proof_authority"] = True
        elif case == "wrong_arity": other["argument_roles"][0]["roles"].append("clerk")
        else: other["typed_expression"]["unprovided_semantic_clause"] = "must remain visible"
        return other
    model, tokenizer, args, _ = _full_norm_case(mutate)
    result = propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert result["status"] == "invalid" and result["complete_norm_candidate"] is None


@pytest.mark.parametrize("case,status", [("abstain", "abstained"), ("missing_EOS", "incomplete"),
    ("missing_BOS", "invalid"), ("duplicate_EOS", "invalid"), ("budget_truncated", "incomplete")])
def test_full_norm_actual_incomplete_abstained_and_invalid_histories_are_separate(case, status):
    model, tokenizer, args, _ = _full_norm_case()
    if case == "abstain": model.history = None
    elif case == "missing_EOS": model.history = model.history[:-1]
    elif case == "missing_BOS": model.history = model.history[1:]
    elif case == "duplicate_EOS": model.history.append(2)
    else:
        model.history = model.history[:4]
        args["max_new_tokens"] = 3
    result = propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert result["status"] == status and result["complete_norm_candidate"] is None
    assert result["counts"][status] == 1 and sum(result["counts"].values()) == 1


@pytest.mark.parametrize("case", ["source_budget", "source_not_lossless", "implicit_special", "vocabulary"])
def test_full_norm_input_failures_happen_before_model_generation(case):
    model, tokenizer, args, _ = _full_norm_case()
    if case == "source_budget": args["max_input_tokens"] = 3
    elif case == "source_not_lossless": tokenizer.decode = lambda ids: "changed"
    elif case == "implicit_special": tokenizer.encode = lambda text: [1, *[ord(c) + 100 for c in text]]
    else: tokenizer.encode = lambda text: [tokenizer.vocab_size]
    result = propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert result["status"] in {"unsupported", "invalid"}
    assert result["model_call_count"] == 0 and model.calls == []


def test_full_norm_forbids_review_or_reference_transport_before_tokenizer_or_model():
    model, tokenizer, args, _ = _full_norm_case()
    args["known_governing_context"]["reviewed_reference_target"] = {"is_valid": True}
    with pytest.raises(ValueError):
        propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert model.calls == [] and tokenizer.encoded == []


def test_full_norm_tokenizer_binding_requires_actual_reviewed_contract_vocabulary():
    model, tokenizer, args, _ = _full_norm_case()
    del tokenizer.metadata["vocab_size"]
    args["expected_tokenizer_binding_sha256"] = _source_only_digest(tokenizer.metadata)
    with pytest.raises(ProposalAdvisorValidationError, match="binding"):
        propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert model.calls == []


def _torch_full_norm_case(architecture, target, *, omit_eos=False):
    # Actual Torch/model protocol fixture; it is neither a pretrained asset nor
    # a learned scientific result. No numerical fitting or model download.
    torch = pytest.importorskip("torch")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
        ReviewedPretrainedTokenizer, TorchReviewedDecoderBackend,
    )
    from ipfs_datasets_py.logic.autoformal.training_cycle_inputs import _reviewed_decoder_tokenizer_contract
    wire = json.dumps(target, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    history = torch.tensor([1, *[value + 3 for value in wire.encode("utf-8")], 2], dtype=torch.long)
    if omit_eos:
        history = history[:-1]
    class Config:
        is_encoder_decoder = architecture == "encoder_decoder"
        def to_dict(self):
            return {"is_encoder_decoder": self.is_encoder_decoder, "max_position_embeddings": 131072,
                    "fixture_only": True}
    class GenerationConfig:
        def __init__(self):
            self.forced_eos_token_id = 2
            self.forced_bos_token_id = 17
            self.forced_decoder_ids = [[1, 18]]
        def to_dict(self):
            return {"forced_eos_token_id": self.forced_eos_token_id,
                    "forced_bos_token_id": self.forced_bos_token_id,
                    "forced_decoder_ids": deepcopy(self.forced_decoder_ids),
                    "min_length": 5, "min_new_tokens": 4, "num_return_sequences": 3}
    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = torch.nn.Embedding(512, 2)
            self.register_buffer("fixture_history", history)
            self.config = Config()
            self.generation_config = GenerationConfig()
            self.calls = []
            self.corrupt_prefix = False
            self.change_weights = False
            self.fail_generate = False
            self.last_tensor = None
        def get_input_embeddings(self): return self.embedding
        def get_output_embeddings(self): return self.embedding
        def generate(self, **kwargs):
            self.calls.append({key: value.detach().clone() if torch.is_tensor(value) else value
                               for key, value in kwargs.items()})
            assert kwargs["forced_eos_token_id"] is None and kwargs["forced_bos_token_id"] is None
            assert kwargs["forced_decoder_ids"] is None
            assert kwargs["decoder_start_token_id"] == kwargs["bos_token_id"] == 1
            assert kwargs["min_new_tokens"] == kwargs["min_length"] == 0
            if self.fail_generate: raise RuntimeError("fictional generation failure")
            if self.change_weights:
                with torch.no_grad(): self.embedding.weight.add_(1)
            if self.config.is_encoder_decoder:
                self.last_tensor = self.fixture_history.unsqueeze(0).clone()
                return self.last_tensor
            prefix = kwargs["input_ids"].clone()
            if self.corrupt_prefix: prefix[0, 0] += 1
            self.last_tensor = torch.cat((prefix, self.fixture_history[1:].unsqueeze(0)), dim=1)
            return self.last_tensor
    class LoadedTokenizer:
        # This explicit byte fixture implements the actual maintained wrapper
        # delegate protocol. It is not a production/pretrained tokenizer.
        bos_token_id, eos_token_id, vocab_size = 1, 2, 512
        def __init__(self):
            self.byte_to_id = list(range(3, 259))
            self.frontend_config = {"normalizer": "identity", "cleanup": False}
            self.text_encoding = "utf-8"
            self.observation_state = {}
        def encode(self, text, *, add_special_tokens, truncation):
            assert add_special_tokens is False and truncation is False
            if self.frontend_config["normalizer"] == "lowercase":
                text = text.lower()
            return [self.byte_to_id[value] for value in text.encode(self.text_encoding, errors="strict")]
        def decode(self, ids, *, skip_special_tokens, clean_up_tokenization_spaces):
            assert skip_special_tokens is False and clean_up_tokenization_spaces is False
            inverse = {token: value for value, token in enumerate(self.byte_to_id)}
            return bytes(inverse[value] for value in ids).decode(self.text_encoding, errors="strict")
        def pipeline_serialization(self):
            from ipfs_datasets_py.logic.autoformal.training_cycle_inputs import _reviewed_decoder_fixed_byte_pipeline
            return _reviewed_decoder_fixed_byte_pipeline(self)
    model = Model()
    tokenizer = ReviewedPretrainedTokenizer(LoadedTokenizer(), bos_token_id=1,
        eos_token_id=2, vocab_size=512, allow_fictional_fixture=True)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    backend = TorchReviewedDecoderBackend(model, optimizer, tokenizer, architecture=architecture,
        max_sequence_tokens=131072, pretrained=False)
    identity = backend.identity()
    pair = backend.snapshot_checkpoint()
    reference = lambda name, body: {"path": "/fictional/unreviewed/" + name,
        "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    contract = _reviewed_decoder_tokenizer_contract(tokenizer)
    parent = {"schema": "reviewed-legal-ir-decoder-checkpoint/v1",
        "checkpoint_lineage_id": "fixture:unreviewed-lineage", "base_version_id": "fixture:unreviewed-base",
        "backend_identity": identity,
        "assets": [reference("asset-" + name, ("fictional-" + name).encode())
                   for name in ("model", "tokenizer", "unit-test-license")], "training_binding": None,
        "model_state": reference("model", pair["model_state"]),
        "optimizer_state": reference("optimizer", pair["optimizer_state"]),
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "batch_size": 1, "seed": 0, "parent_checkpoint_sha256": None,
        "producer_pins": {"worker": identity["implementation_sha256"], "inputs": "1" * 64,
                          "consumer": "2" * 64, "admission": "3" * 64, "splits": "4" * 64},
        "token_budgets": {"max_source_tokens": 65536, "max_target_tokens": 32769,
                          "tokenizer_contract": contract},
        "qualified": False, "promotion_performed": False}
    parent_raw = json.dumps(parent, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    guards = []
    kwargs = {"model_id": "fixture:actual-Torch-generation", "parent_checkpoint_bytes": parent_raw,
        "model_state_bytes": pair["model_state"], "optimizer_state_bytes": pair["optimizer_state"],
        "expected_parent_checkpoint_sha256": "sha256:" + hashlib.sha256(parent_raw).hexdigest(),
        "expected_backend_identity_sha256": _source_only_digest(identity),
        "expected_generation_configuration_sha256": _source_only_digest(model.generation_config.to_dict()),
        "execution_guard": lambda: guards.append("execution"),
        "asset_policy_guard": lambda record: guards.append(deepcopy(record))}
    return torch, model, tokenizer, backend, kwargs, guards


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_actual_torch_full_norm_generation_restores_pair_and_uses_source_only_BOS_to_EOS(architecture):
    _, _, args, target = _full_norm_case()
    torch, model, tokenizer, backend, kwargs, guards = _torch_full_norm_case(architecture, target)
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    bridge = ReviewedDecoderTokenizerAdapter(tokenizer, binding=tokenizer.binding_metadata())
    args["expected_model_binding_sha256"] = _source_only_digest(adapter.binding_metadata())
    args["expected_tokenizer_binding_sha256"] = _source_only_digest(bridge.binding_metadata())
    before_training = model.training
    result = propose_source_conditioned_complete_norm(adapter, bridge, **args)
    assert result["status"] == "complete" and result["complete_norm_candidate"] == target
    assert model.training is before_training
    call = model.calls[0]
    assert set(call) == {"input_ids", "attention_mask", "max_new_tokens", "eos_token_id", "pad_token_id",
        "do_sample", "num_beams", "num_return_sequences", "return_dict_in_generate",
        "forced_eos_token_id", "forced_bos_token_id", "forced_decoder_ids", "bos_token_id",
        "decoder_start_token_id", "min_length", "min_new_tokens"} | (
        {"decoder_input_ids"} if architecture == "encoder_decoder" else set())
    assert call["do_sample"] is False and call["num_beams"] == 1
    assert call["num_return_sequences"] == 1
    assert call["forced_eos_token_id"] is call["forced_bos_token_id"] is call["forced_decoder_ids"] is None
    actual = tuple(call["input_ids"][0].tolist())
    if architecture == "causal_lm":
        assert actual[-1] == 1
        actual = actual[:-1]
    assert actual[0] == 1 and actual[-1] == 2
    source = json.loads(tokenizer.decode(actual[1:-1]))
    assert set(source) == {"profile", "source_text", "source_binding", "governing_context", "selection_context"}
    assert source["source_text"] == args["source_text"]
    assert source["selection_context"] == args["known_selection_context"]
    assert result["semantic_selection_supported"] is False
    observed = adapter.generation_observation()
    assert observed["model_generate_calls"] == observed["checkpoint_restores_completed"] == 1
    assert observed["checkpoint_restore_attempts"] == 1
    assert observed["physical_model_assets_verified"] is observed["model_execution_authenticated"] is False
    assert guards and all("target_json" not in value for value in guards if isinstance(value, dict))
    assert backend.restored_checkpoint_matches(kwargs["model_state_bytes"], kwargs["optimizer_state_bytes"]) is True


@pytest.mark.parametrize("case", ["parent_digest", "model_digest", "target_codec", "nonzero_unbound",
                                  "backend_identity", "checkpoint_progress"])
def test_full_norm_actual_checkpoint_identity_or_progress_changes_refuse_before_generation(case):
    _, _, args, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    if case == "parent_digest": kwargs["expected_parent_checkpoint_sha256"] = "sha256:" + "9" * 64
    elif case == "model_digest": kwargs["model_state_bytes"] += b"changed"
    elif case == "backend_identity": kwargs["expected_backend_identity_sha256"] = "sha256:" + "8" * 64
    else:
        parent = json.loads(kwargs["parent_checkpoint_bytes"])
        if case == "target_codec": parent["backend_identity"]["target_codec"] = "lossy-placeholder/v1"
        elif case == "nonzero_unbound": parent["progress"]["optimizer_steps"] = 1
        else:
            parent["progress"]["optimizer_steps"] = 1
            parent["training_binding"] = {"source_profile": COMPLETE_NORM_SOURCE_PROFILE,
                "target_codec": COMPLETE_NORM_TARGET_CODEC,
                "tokenizer_contract": parent["token_budgets"]["tokenizer_contract"]}
        raw = json.dumps(parent, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        kwargs["parent_checkpoint_bytes"] = raw
        kwargs["expected_parent_checkpoint_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
        if case == "target_codec": kwargs["expected_backend_identity_sha256"] = _source_only_digest(parent["backend_identity"])
    with pytest.raises(ValueError):
        adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
        ids = (1, *tokenizer.encode("{}"), 2)
        adapter.generate_token_ids(ids, decoder_prefix_ids=(1,), max_new_tokens=32768)
    assert model.calls == []


@pytest.mark.parametrize("case", ["resource_guard", "asset_guard", "source_budget", "target_budget", "causal_prefix",
                                  "model_failure", "changed_weights"])
def test_actual_torch_full_norm_guard_budget_history_and_failure_controls(case):
    _, _, args, target = _full_norm_case()
    architecture = "causal_lm" if case == "causal_prefix" else "encoder_decoder"
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case(architecture, target)
    def refused(*_): raise ValueError("fixture policy refused")
    if case == "resource_guard": kwargs["execution_guard"] = refused
    elif case == "asset_guard": kwargs["asset_policy_guard"] = refused
    model.corrupt_prefix = case == "causal_prefix"
    model.fail_generate = case == "model_failure"
    model.change_weights = case == "changed_weights"
    ids = (1, *tokenizer.encode("{}"), 2)
    # Keep the source-budget case on its own refusal path after the shared
    # target-capacity preflight; the target case deliberately mismatches it.
    max_new = 3 if case == "target_budget" else 32768
    if case in {"source_budget", "target_budget"}:
        parent = json.loads(kwargs["parent_checkpoint_bytes"])
        parent["token_budgets"]["max_source_tokens" if case == "source_budget" else "max_target_tokens"] = 3
        raw = json.dumps(parent, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        kwargs["parent_checkpoint_bytes"] = raw
        kwargs["expected_parent_checkpoint_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    before_training = model.training
    with pytest.raises((ValueError, RuntimeError)):
        adapter.generate_token_ids(ids, decoder_prefix_ids=(1,), max_new_tokens=max_new)
    assert model.training is before_training
    if case in {"resource_guard", "asset_guard", "source_budget", "target_budget"}:
        assert model.calls == [] and adapter.generation_observation()["checkpoint_restore_attempts"] == 0
    else:
        assert len(model.calls) == 1 and adapter.generation_observation()["caller_backend_may_have_changed"] is True


@pytest.mark.parametrize("profile", ["typed", "complete_norm"])
def test_actual_returned_history_is_frozen_before_binding_callback_can_add_EOS(profile):
    if profile == "typed":
        baseline_model, tokenizer, args = _source_only_fixture()
        call = propose_source_conditioned_typed_ir
    else:
        baseline_model, tokenizer, args, _ = _full_norm_case()
        call = propose_source_conditioned_complete_norm
    class MutatingHistoryModel(_InertSourceTokenModel):
        returned = None
        def generate_token_ids(self, *values, **kwargs):
            self.returned = super().generate_token_ids(*values, **kwargs)
            return self.returned
        def binding_metadata(self):
            if self.returned is not None and self.returned[-1] != 2:
                self.returned.append(2)
            return super().binding_metadata()
    model = MutatingHistoryModel(baseline_model.history[:-1])
    result = call(model, tokenizer, **args)
    assert model.returned[-1] == 2  # The callback really changed its own list.
    assert result["status"] == "incomplete" and result["generated_ids"][-1] != 2
    assert result["counts"]["incomplete"] == 1 and result["counts"]["complete"] == 0


@pytest.mark.parametrize("field", ["bos_token_id", "eos_token_id", "vocab_size"])
def test_complete_norm_tokenizer_adapter_requires_plain_actual_integer_contract(field):
    _, _, _, target = _full_norm_case()
    _, _, tokenizer, _, _, _ = _torch_full_norm_case("encoder_decoder", target)
    declared = tokenizer.binding_metadata()
    setattr(tokenizer, field, True)
    with pytest.raises(ProposalAdvisorValidationError):
        ReviewedDecoderTokenizerAdapter(tokenizer, binding=declared).binding_metadata()


def test_actual_torch_returned_tensor_is_frozen_before_after_generate_callback_adds_EOS():
    _, _, args, target = _full_norm_case()
    torch, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target, omit_eos=True)
    def add_eos(record):
        if record["operation"] == "after_generate":
            value = model.last_tensor
            old_length = value.shape[1]
            value.resize_(1, old_length + 1)
            value[0, -1] = 2
    kwargs["asset_policy_guard"] = add_eos
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    bridge = ReviewedDecoderTokenizerAdapter(tokenizer, binding=tokenizer.binding_metadata())
    args["expected_model_binding_sha256"] = _source_only_digest(adapter.binding_metadata())
    args["expected_tokenizer_binding_sha256"] = _source_only_digest(bridge.binding_metadata())
    result = propose_source_conditioned_complete_norm(adapter, bridge, **args)
    assert int(model.last_tensor[0, -1]) == 2
    assert result["status"] == "incomplete" and result["generated_ids"][-1] != 2
    assert result["complete_norm_candidate"] is None


@pytest.mark.parametrize("phase", ["restore_checkpoint_pair", "generate", "after_generate"])
def test_actual_torch_public_backend_object_swap_is_detected_at_point_of_use(phase):
    _, _, _, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    def replace_model(record):
        if record["operation"] == phase:
            backend.model = deepcopy(model)
    kwargs["asset_policy_guard"] = replace_model
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    with pytest.raises(ProposalAdvisorValidationError, match="object identity"):
        adapter.generate_token_ids((1, *tokenizer.encode("{}"), 2), decoder_prefix_ids=(1,), max_new_tokens=32768)
    assert len(model.calls) == (1 if phase == "after_generate" else 0)


def test_actual_torch_direct_source_token_list_is_detached_before_guard_callbacks():
    _, _, _, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    source = [1, *tokenizer.encode("{}"), 2]
    original = tuple(source)
    def mutate_input(record):
        if record["operation"] == "validate_generation":
            source[1] = 999999
    kwargs["asset_policy_guard"] = mutate_input
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    adapter.generate_token_ids(source, decoder_prefix_ids=[1], max_new_tokens=32768)
    assert source[1] == 999999
    assert tuple(model.calls[0]["input_ids"][0].tolist()) == original


def test_actual_torch_mixed_submodule_modes_are_restored_exactly():
    _, _, _, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    model.train(True)
    model.embedding.train(False)
    before = [(module, module.training) for module in model.modules()]
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    adapter.generate_token_ids((1, *tokenizer.encode("{}"), 2), decoder_prefix_ids=(1,), max_new_tokens=32768)
    assert [(module, module.training) for module in model.modules()] == before
    assert model.training is True and model.embedding.training is False


@pytest.mark.parametrize("case", ["declared_hash", "guard_mutation"])
def test_actual_torch_generation_configuration_is_independently_bound(case):
    _, _, _, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    if case == "declared_hash":
        kwargs["expected_generation_configuration_sha256"] = "sha256:" + "9" * 64
    else:
        def change_generation_config(record):
            if record["operation"] == "generate":
                model.generation_config.forced_bos_token_id = 23
        kwargs["asset_policy_guard"] = change_generation_config
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    with pytest.raises(ProposalAdvisorValidationError, match="generation configuration"):
        adapter.generate_token_ids((1, *tokenizer.encode("{}"), 2), decoder_prefix_ids=(1,), max_new_tokens=32768)
    assert model.calls == []


def test_actual_torch_requires_same_tokenizer_object_used_by_loaded_checkpoint_backend():
    _, _, args, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    _, _, other, _, _, _ = _torch_full_norm_case("encoder_decoder", target)
    bridge = ReviewedDecoderTokenizerAdapter(other, binding=other.binding_metadata())
    args["expected_model_binding_sha256"] = _source_only_digest(adapter.binding_metadata())
    args["expected_tokenizer_binding_sha256"] = _source_only_digest(bridge.binding_metadata())
    result = propose_source_conditioned_complete_norm(adapter, bridge, **args)
    assert result["status"] == "error" and result["reason"] == "checkpoint_tokenizer_adapter_validation_failed"
    assert model.calls == [] and adapter.generation_observation()["checkpoint_restore_attempts"] == 0


def test_syntactically_complete_wrong_modality_still_has_no_legal_or_training_authority():
    def change_modal(target):
        other = deepcopy(target)
        def visit(value):
            if isinstance(value, dict):
                if value.get("payload_schema") == "legacy.deontic/v1":
                    value["features"] = ["legacy.permission", "legacy.classic_letter"]
                    value["payload"] = {"kind": "permission", "letter": "P", "resolution": "deontic",
                                        "schema_version": "legacy.deontic/v1"}
                for child in value.values(): visit(child)
            elif isinstance(value, list):
                for child in value: visit(child)
        visit(other["typed_expression"])
        # A changed AST needs its newly derived digest, not the old commitment.
        other["typed_expression"]["content_digest"] = ""
        from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression
        other["typed_expression"] = TypedExpression.from_dict(other["typed_expression"]).to_dict()
        return other
    model, tokenizer, args, _ = _full_norm_case(change_modal)
    result = propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert result["status"] == "complete"
    assert not any(result["candidate_syntax"]["authority"].values())
    assert result["candidate_syntax"]["semantic_use_eligible"] is False
    assert result["training_gold_authority"] is result["legal_review_verified"] is False
    assert result["semantic_selection_supported"] is False
    # Identifier equality alone cannot distinguish these competing meanings.
    # Syntax completion is therefore deliberately separate from source fidelity.
    plain_model, plain_tokenizer, plain_args, _ = _full_norm_case()
    plain = propose_source_conditioned_complete_norm(plain_model, plain_tokenizer, **plain_args)
    assert plain["status"] == "complete" and plain["input_identity"] == result["input_identity"]
    assert plain["typed_ir"] != result["typed_ir"]
    assert plain["semantic_selection_supported"] is False


@pytest.mark.parametrize("side", ["output", "caller"])
def test_full_norm_selection_identifier_mismatch_is_rejected_without_overwriting(side):
    def change_output(target):
        other = deepcopy(target)
        other["interpretation_id"] = "fixture:other-independent-interpretation"
        return other
    model, tokenizer, args, target = _full_norm_case(change_output if side == "output" else None)
    if side == "caller":
        args["known_selection_context"]["interpretation_id"] = "fixture:other-caller-selection"
    selected_before = deepcopy(args["known_selection_context"])
    result = propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert result["status"] == "invalid" and result["complete_norm_candidate"] is None
    assert result["candidate_syntax"] is None and result["typed_ir"] is None
    assert result["known_selection_context"] == selected_before == args["known_selection_context"]
    assert json.loads(result["raw_output_text"])["interpretation_id"] == (
        "fixture:other-independent-interpretation" if side == "output" else target["interpretation_id"])
    assert result["semantic_selection_supported"] is False


@pytest.mark.parametrize("case", ["missing_keyword", "missing_ID", "extra_policy", "meaning_mode", "target_payload"])
def test_full_norm_unprovided_or_unsupported_selection_refuses_before_any_callbacks(case):
    model, tokenizer, args, _ = _full_norm_case()
    if case == "missing_keyword":
        del args["known_selection_context"]
    elif case == "missing_ID":
        del args["known_selection_context"]["interpretation_id"]
    elif case == "extra_policy":
        args["known_selection_context"]["meaning_description"] = "unprovided substantive policy"
    elif case == "meaning_mode":
        args["known_selection_context"]["selection_mode"] = "meaning_policy"
    else:
        args["known_selection_context"]["reviewed_target"] = {"typed_expression": "forbidden"}
    with pytest.raises((ValueError, TypeError)):
        propose_source_conditioned_complete_norm(model, tokenizer, **args)
    assert model.calls == [] and tokenizer.encoded == []


@pytest.mark.parametrize("case", ["old_three_integer_contract", "old_backend_ID", "old_source_profile"])
def test_actual_torch_full_norm_v1_checkpoint_identities_are_explicitly_incompatible(case):
    _, _, _, target = _full_norm_case()
    _, model, _, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    parent = json.loads(kwargs["parent_checkpoint_bytes"])
    if case == "old_three_integer_contract":
        contract = parent["token_budgets"]["tokenizer_contract"]
        parent["token_budgets"]["tokenizer_contract"] = {
            key: contract[key] for key in ("bos_token_id", "eos_token_id", "vocab_size")}
    elif case == "old_backend_ID":
        parent["backend_identity"]["backend_id"] = parent["backend_identity"]["backend_id"].replace("/v2:", "/v1:")
        kwargs["expected_backend_identity_sha256"] = _source_only_digest(parent["backend_identity"])
    else:
        parent["training_binding"] = {"source_profile": "reviewed-source-known-context/v1",
            "target_codec": COMPLETE_NORM_TARGET_CODEC,
            "tokenizer_contract": parent["token_budgets"]["tokenizer_contract"]}
    raw = json.dumps(parent, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    kwargs["parent_checkpoint_bytes"] = raw
    kwargs["expected_parent_checkpoint_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    with pytest.raises(ProposalAdvisorValidationError):
        TorchCompleteNormGenerationAdapter(backend, **kwargs)
    assert model.calls == []


@pytest.mark.parametrize("change", ["vocabulary", "normalizer", "caller_digest"])
def test_reviewed_tokenizer_full_pipeline_binding_detects_changes_with_same_three_integer_IDs(change):
    _, _, _, target = _full_norm_case()
    _, model, tokenizer, _, _, _ = _torch_full_norm_case("encoder_decoder", target)
    before = tokenizer.binding_metadata()
    ids = tuple(getattr(tokenizer, key) for key in ("bos_token_id", "eos_token_id", "vocab_size"))
    declared = deepcopy(before)
    if change == "vocabulary":
        mapping = tokenizer.tokenizer.byte_to_id
        mapping[65], mapping[66] = mapping[66], mapping[65]
    elif change == "normalizer":
        tokenizer.tokenizer.frontend_config["normalizer"] = "lowercase"
    else:
        declared["configuration_sha256"] = "sha256:" + "9" * 64
    assert tuple(getattr(tokenizer, key) for key in ("bos_token_id", "eos_token_id", "vocab_size")) == ids
    actual = tokenizer.binding_metadata()
    if change != "caller_digest":
        assert actual["configuration_sha256"] != before["configuration_sha256"]
        assert (actual["vocabulary_sha256"] != before["vocabulary_sha256"]) is (change == "vocabulary")
    with pytest.raises(ProposalAdvisorValidationError, match="pipeline binding"):
        ReviewedDecoderTokenizerAdapter(tokenizer, binding=declared).binding_metadata()
    assert model.calls == []


@pytest.mark.parametrize("phase", ["validate_generation", "generate", "after_generate"])
def test_actual_torch_complete_checkpoint_tokenizer_pipeline_drift_refuses(phase):
    _, _, _, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    source = (1, *tokenizer.encode("{}"), 2)
    def mutate_mapping(record):
        if record["operation"] == phase:
            values = tokenizer.tokenizer.byte_to_id
            values[65], values[66] = values[66], values[65]
    kwargs["asset_policy_guard"] = mutate_mapping
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    with pytest.raises(ValueError):
        adapter.generate_token_ids(source, decoder_prefix_ids=(1,), max_new_tokens=32768)
    assert len(model.calls) == (1 if phase == "after_generate" else 0)


def test_actual_torch_complete_checkpoint_pipeline_is_derived_not_a_three_integer_or_caller_label():
    _, _, _, target = _full_norm_case()
    _, _, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    from ipfs_datasets_py.logic.autoformal.training_cycle_inputs import _reviewed_decoder_tokenizer_contract
    contract = _reviewed_decoder_tokenizer_contract(tokenizer)
    parent = json.loads(kwargs["parent_checkpoint_bytes"])
    assert set(contract) == {"schema", "bos_token_id", "eos_token_id", "vocab_size",
                             "pipeline_kind", "pipeline_sha256", "pipeline_bytes"}
    assert contract == parent["token_budgets"]["tokenizer_contract"]
    assert contract["schema"] == "reviewed-decoder-tokenizer-contract/v2"
    assert contract["pipeline_kind"] == "fictional_fixed_byte"
    binding = tokenizer.binding_metadata()
    assert set(binding) == {"tokenizer_id", "vocabulary_sha256", "configuration_sha256",
                            "bos_token_id", "eos_token_id", "vocab_size"}
    assert binding["configuration_sha256"] == "sha256:" + contract["pipeline_sha256"]
    assert backend.identity()["backend_id"].startswith("torch-complete-reviewed-decoder/v2:")
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    bridge = ReviewedDecoderTokenizerAdapter(tokenizer, binding=binding)
    adapter.validate_tokenizer_adapter(bridge)
    assert adapter.generation_observation()["physical_model_assets_verified"] is False
    assert adapter.generation_observation()["model_generate_calls"] == 0


@pytest.mark.parametrize("mutation", ["class_forcing_inventory", "class_overrides", "guard_record", "observation_record"])
def test_actual_torch_generation_policy_snapshot_survives_shared_and_returned_record_mutation(monkeypatch, mutation):
    # The fixture's model.generate asserts the actual forced-ID/minimum/BOS
    # kwargs. This is a policy-custody control, not learned-model evidence.
    _, _, _, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    declared = deepcopy(TorchCompleteNormGenerationAdapter._GENERATION_POLICY)
    # Isolate mutation of this legacy mutable class declaration from other
    # tests. The adapter must take an owned snapshot when constructed below.
    monkeypatch.setattr(TorchCompleteNormGenerationAdapter, "_GENERATION_POLICY", deepcopy(declared))
    guard_policies = []
    def mutate_after_binding(record):
        guard_policies.append(deepcopy(record["generation_policy"]))
        if record["operation"] != "generate":
            return
        if mutation == "class_forcing_inventory":
            TorchCompleteNormGenerationAdapter._GENERATION_POLICY["extra_forcing_fields"].clear()
        elif mutation == "class_overrides":
            TorchCompleteNormGenerationAdapter._GENERATION_POLICY.update(
                do_sample=True, num_beams=4, forced_eos_token_id=2, min_new_tokens=7)
        elif mutation == "guard_record":
            record["generation_policy"]["extra_forcing_fields"].clear()
            record["generation_policy"]["do_sample"] = True
        else:
            returned = adapter.generation_observation()
            returned["generation_policy"]["extra_forcing_fields"].clear()
            returned["generation_policy"]["do_sample"] = True
    kwargs["asset_policy_guard"] = mutate_after_binding
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    binding_before = adapter.binding_metadata()
    observed_before = adapter.generation_observation()["generation_policy"]
    history = adapter.generate_token_ids((1, *tokenizer.encode("{}"), 2),
        decoder_prefix_ids=(1,), max_new_tokens=32768)
    assert history[0] == 1 and history[-1] == 2 and len(model.calls) == 1
    actual = model.calls[0]
    assert actual["forced_decoder_ids"] is actual["forced_bos_token_id"] is actual["forced_eos_token_id"] is None
    assert actual["do_sample"] is False and actual["num_beams"] == actual["num_return_sequences"] == 1
    assert actual["min_new_tokens"] == actual["min_length"] == 0
    assert adapter.binding_metadata() == binding_before
    assert adapter.generation_observation()["generation_policy"] == observed_before == declared
    assert guard_policies and all(value == declared for value in guard_policies)
    assert type(adapter._generation_policy_wire) is bytes
    if mutation == "class_forcing_inventory":
        assert TorchCompleteNormGenerationAdapter._GENERATION_POLICY["extra_forcing_fields"] == []
    elif mutation == "class_overrides":
        assert TorchCompleteNormGenerationAdapter._GENERATION_POLICY["do_sample"] is True


def test_actual_torch_mutated_shared_policy_cannot_configure_a_later_adapter(monkeypatch):
    _, _, _, target = _full_norm_case()
    _, model, _, backend, kwargs, guards = _torch_full_norm_case("encoder_decoder", target)
    changed = deepcopy(TorchCompleteNormGenerationAdapter._GENERATION_POLICY)
    changed["extra_forcing_fields"].clear()
    changed["num_beams"] = 4
    monkeypatch.setattr(TorchCompleteNormGenerationAdapter, "_GENERATION_POLICY", changed)
    with pytest.raises(ProposalAdvisorValidationError, match="policy changed before construction"):
        TorchCompleteNormGenerationAdapter(backend, **kwargs)
    assert model.calls == [] and guards == []


def _full_norm_selected_parent_target_budget(kwargs, capacity):
    parent = json.loads(kwargs["parent_checkpoint_bytes"])
    parent["token_budgets"]["max_target_tokens"] = capacity
    raw = json.dumps(parent, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    kwargs["parent_checkpoint_bytes"] = raw
    kwargs["expected_parent_checkpoint_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_actual_torch_shared_target_capacity_accepts_default8192_with8191_new_tokens(architecture):
    _, _, _, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case(architecture, target)
    _full_norm_selected_parent_target_budget(kwargs, 8192)
    assert model.fixture_history.numel() <= 8192  # Complete nine-field fixture, never shortened.
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    history = adapter.generate_token_ids((1, *tokenizer.encode("{}"), 2),
        decoder_prefix_ids=(1,), max_new_tokens=8191)
    assert history[0] == 1 and history[-1] == 2 and len(history) <= 8192
    assert len(model.calls) == 1 and model.calls[0]["max_new_tokens"] == 8191
    assert adapter.generation_observation()["checkpoint_restores_completed"] == 1
    assert adapter.generation_observation()["physical_model_assets_verified"] is False


@pytest.mark.parametrize("capacity,max_new", [(65536, 32768), (32769, 32767), (8192, 8190), (8192, 8192)])
def test_actual_torch_unmatched_complete_target_capacity_refuses_before_callbacks_or_Torch_import(
        monkeypatch, capacity, max_new):
    import builtins
    from ipfs_datasets_py.logic.formalization.proposal_advisors import SourceConditionedGenerationUnsupported
    _, _, _, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, guards = _torch_full_norm_case("encoder_decoder", target)
    _full_norm_selected_parent_target_budget(kwargs, capacity)
    source = (1, *tokenizer.encode("{}"), 2)
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    callback_calls, torch_imports = [], []
    def forbidden_backend_callback(*args, **kw):
        callback_calls.append(True)
        raise AssertionError("backend must not be touched for an unmatched capacity")
    backend.identity = backend.inspect_checkpoint = backend.restore_checkpoint = forbidden_backend_callback
    real_import = builtins.__import__
    def bounded_import(name, *args, **kw):
        if name == "torch":
            torch_imports.append(name)
            raise AssertionError("adapter Torch import must follow the complete-budget preflight")
        return real_import(name, *args, **kw)
    with monkeypatch.context() as scoped:
        scoped.setattr(builtins, "__import__", bounded_import)
        with pytest.raises(SourceConditionedGenerationUnsupported, match="complete target budget"):
            adapter.generate_token_ids(source, decoder_prefix_ids=(1,), max_new_tokens=max_new)
    assert callback_calls == torch_imports == guards == model.calls == []
    assert adapter.generation_observation()["checkpoint_restore_attempts"] == 0
    assert adapter.generation_observation()["model_generate_calls"] == 0


@pytest.mark.parametrize("capacity,max_new", [(65536, 32768), (8192, 8190)])
def test_full_norm_public_unmatched_capacity_retains_source_as_counted_unsupported(capacity, max_new):
    _, _, args, target = _full_norm_case()
    _, model, tokenizer, backend, kwargs, _ = _torch_full_norm_case("encoder_decoder", target)
    _full_norm_selected_parent_target_budget(kwargs, capacity)
    adapter = TorchCompleteNormGenerationAdapter(backend, **kwargs)
    bridge = ReviewedDecoderTokenizerAdapter(tokenizer, binding=tokenizer.binding_metadata())
    args["expected_model_binding_sha256"] = _source_only_digest(adapter.binding_metadata())
    args["expected_tokenizer_binding_sha256"] = _source_only_digest(bridge.binding_metadata())
    args["max_new_tokens"] = max_new
    result = propose_source_conditioned_complete_norm(adapter, bridge, **args)
    assert result["status"] == "unsupported" and result["counts"]["unsupported"] == 1
    assert sum(result["counts"].values()) == 1
    assert result["source_text"] == args["source_text"]
    assert result["known_selection_context"] == args["known_selection_context"]
    assert result["complete_norm_candidate"] is result["typed_ir"] is result["candidate_syntax"] is None
    assert result["model_call_count"] == 1  # One protocol attempt, no actual model.generate.
    assert result["generated_ids"] == [] and result["semantic_selection_supported"] is False
    assert model.calls == []
    assert adapter.generation_observation()["checkpoint_restore_attempts"] == 0
    assert adapter.generation_observation()["model_generate_calls"] == 0
