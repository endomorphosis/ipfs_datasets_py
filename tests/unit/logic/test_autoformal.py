"""Rule rows from the measured compiler. No model and no Lake."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _autoformal():
    path = Path(__file__).resolve().parents[3] / "ipfs_datasets_py" / "logic" / "autoformal" / "__init__.py"
    spec = importlib.util.spec_from_file_location("autoformal_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.reset_session()
    return module


LEASE = "The tenant shall pay one hundred dollars. When payment is after the fifth day, the tenant shall pay an additional ten dollars."
AGE = "No person shall be eligible who shall not have attained the age of thirty five years and been fourteen years a resident."
PREAMBLE = "We the People, in Order to form a more perfect Union, do ordain and establish this charter."


def test_lease_and_age_use_one_compiler_and_the_preamble_abstains() -> None:
    autoformal = _autoformal()
    session = autoformal.SESSION
    lease = session.open_document(LEASE, document_type="contract", document_id="lease")
    age = session.open_document(AGE, document_type="statute", document_id="age")
    preamble = session.open_document(PREAMBLE, document_id="preamble")
    for opened in (lease, age, preamble):
        session.compile_clause(opened["document_id"], opened["clauses"][0]["id"], frame_id="shared")
    assert lease["clauses"][0]["id"] in session.compiled_ids
    assert age["clauses"][0]["id"] in session.compiled_ids
    preamble_row = next(row for row in session.rows if row.clause_id == preamble["clauses"][0]["id"])
    assert preamble_row.status == "abstain"
    assert preamble_row.rule is None
    assert all(row.public()["admitted"] is False for row in session.rows)


def test_autoencoder_gate_does_not_call_a_model() -> None:
    import pytest
    from ipfs_datasets_py.logic.modal.autoencoder_loop import (
        LegalModalAutoencoderLoop,
        ModalAutoencoderLoopConfig,
    )

    def _fail_if_called(*_args, **_kwargs):
        pytest.fail("llm")

    loop = LegalModalAutoencoderLoop(
        ModalAutoencoderLoopConfig(
            allow_llm_repair=False,
            import_frame_logic_graph=False,
            evaluate_provers=False,
            check_external_prover_router=False,
        ),
        llm_generate=_fail_if_called,
    )
    for text, document_id in ((LEASE, "lease"), (AGE, "age")):
        result = loop.run(text, document_id=document_id, allow_llm_repair=False)
        assert result.codec_result is not None
        assert result.codec_result.modal_ir is not None
        assert result.codex_decision is not None
        assert result.llm_called is False
        assert result.llm_response == ""


def test_an_admitted_fragment_does_not_change_the_compiler() -> None:
    import importlib.util
    import sys
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "ipfs_datasets_py" / "logic" / "autoformal" / "ontology_fragments.py"
    spec = importlib.util.spec_from_file_location("ontology_fragments_compile_guard", path)
    assert spec is not None and spec.loader is not None
    fragments = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fragments
    spec.loader.exec_module(fragments)
    registry = fragments.FragmentRegistry()
    registry.propose({
        "relation": "qualifies",
        "domain": "Person",
        "range": "Office",
        "attachment": "conditions",
        "inverse": "qualified_by",
        "decompiler_phrase": "{person} qualifies for {office}",
        "fixture_id": "not-the-constitution",
    })
    assert registry.by_attachment() == {}
    registry.admit("qualifies")
    assert registry.by_attachment()["conditions"][0]["relation"] == "qualifies"
    autoformal = _autoformal()
    text = "Company A shall submit backup report within 10 days unless emergency."
    opened = autoformal.SESSION.open_document(text, document_id="backup-guard")
    clause_id = opened["clauses"][0]["id"]
    before = autoformal.SESSION.compile_clause("backup-guard", clause_id)["rows"][0]["decompiled"]
    after = autoformal.SESSION.compile_clause("backup-guard", clause_id)["rows"][0]["decompiled"]
    assert before == after
    assert "qualifies" not in before.lower()


def test_parser_atoms_roundtrip_without_a_hand_written_vocabulary() -> None:
    autoformal = _autoformal()
    text = "Company A shall submit backup report within 10 days unless emergency."
    opened = autoformal.SESSION.open_document(text, document_id="backup")
    clause_id = opened["clauses"][0]["id"]
    compiled = autoformal.SESSION.compile_clause("backup", clause_id)
    assert compiled["rows"][0]["status"] == "compiled"
    assert "submit" in compiled["rows"][0]["decompiled"].lower()
    report = autoformal.SESSION.roundtrip_clause("backup", clause_id)
    assert report["rows"][0]["status"] == "roundtrip_ok"
    assert report["rows"][0]["admitted"] is False
    preamble = autoformal.SESSION.open_document(PREAMBLE, document_id="preamble")
    preamble_id = preamble["clauses"][0]["id"]
    abstained = autoformal.SESSION.compile_clause("preamble", preamble_id)
    assert abstained["rows"][0]["status"] == "abstain"
    assert autoformal.vocabulary_from_clause(PREAMBLE) is None


def test_a_supplied_vocabulary_can_roundtrip_without_storage() -> None:
    autoformal = _autoformal()
    text = "Company A shall submit backup report within 10 days unless emergency."
    vocabulary = {
        "actors": ["company_a", "company_b", "agency"],
        "actions": ["submit", "file", "withdraw"],
        "objects": ["backup_report", "incident_report", "annual_report"],
        "qualifiers": ["within_10_days", "emergency", "within_30_days", "natural_disaster"],
    }
    opened = autoformal.SESSION.open_document(text, document_id="backup")
    clause_id = opened["clauses"][0]["id"]
    compiled = autoformal.SESSION.compile_clause("backup", clause_id, vocabulary=vocabulary)
    assert compiled["rows"][0]["status"] == "compiled"
    assert compiled["rows"][0]["decompiled"]
    report = autoformal.SESSION.roundtrip_clause("backup", clause_id)
    assert report["evaluated"] is True
    assert report["rows"][0]["status"] == "roundtrip_ok"
    assert report["rows"][0]["admitted"] is False


def test_roundtrip_does_not_promote_an_abstain() -> None:
    autoformal = _autoformal()
    opened = autoformal.SESSION.open_document(PREAMBLE, document_id="preamble")
    clause_id = opened["clauses"][0]["id"]
    autoformal.SESSION.compile_clause("preamble", clause_id)
    report = autoformal.SESSION.roundtrip_clause("preamble", clause_id)
    assert report["evaluated"] is False
    assert report["rows"][0]["status"] == "abstain"
    assert not hasattr(autoformal, "put_envelope")


def test_a_walk_receipt_without_a_cid_is_not_a_proof() -> None:
    autoformal = _autoformal()
    text = (
        "We the People, in Order to form a more perfect Union, do ordain and establish this charter.\n\n"
        "Company A shall submit backup report within 10 days unless emergency."
    )
    vocabulary = {
        "actors": ["company_a", "company_b", "agency"],
        "actions": ["submit", "file", "withdraw"],
        "objects": ["backup_report", "incident_report", "annual_report"],
        "qualifiers": ["within_10_days", "emergency", "within_30_days", "natural_disaster"],
    }
    opened = autoformal.SESSION.open_document(text, document_id="two")
    report = autoformal.SESSION.walk_document("two", vocabulary=vocabulary, renderable=lambda _rule: False)
    assert report["stopped"] is False
    assert len(report["receipts"]) == len(opened["clauses"])
    assert all(item["proved"] is False and item["content_cid"] == "" for item in report["receipts"])
    assert all(item["completion_authoritative"] is False for item in report["receipts"])
    forced = autoformal.as_supervisor_receipt({
        "clause_id": "x",
        "status": "roundtrip_ok",
        "content_cid": "",
        "proved": True,
        "completion_authoritative": True,
    })
    assert forced["completion_authoritative"] is False
    assert forced["proved"] is False


def test_citation_neighbors_are_one_sparse_hop() -> None:
    autoformal = _autoformal()
    triples = [
        {"subject": "anchor", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "neighbor", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "unrelated", "predicate": "citation", "object": "12 U.S.C. 1"},
    ]
    found = autoformal.citation_neighbors(triples, "anchor")
    assert found == ["neighbor"]
    assert "unrelated" not in found


def test_the_constraint_query_labels_a_pair_and_does_not_admit_it() -> None:
    autoformal = _autoformal()
    scope = {
        "jurisdiction": "US-OR",
        "as_of": "2024-06-15",
        "territory": "Multnomah",
        "subject_matter": "public-records",
        "actor": "agency",
        "subject": "requester",
        "resource": "records",
        "purpose": "disclosure",
        "authority_id": "auth:or-legislature",
        "enacted_date": "2019-01-01",
        "effective_from": "2020-01-01",
        "source_ref": "source:or-192",
        "provenance_id": "prov:or-192",
    }
    obligation = {"modality": "O", "decompiled": "Agency shall disclose records."}
    same = {"modality": "O", "decompiled": "Agency shall disclose records."}
    opposed = {"modality": "F", "decompiled": "Agency shall not disclose records."}
    positive = autoformal.query_pair(obligation, same, scope)
    conflict = autoformal.query_pair(obligation, opposed, scope)
    assert positive == {"label": "positive", "margin": 0, "admitted": False, "disposition": "applicable"}
    assert conflict["label"] == "contradiction"
    assert conflict["disposition"] == "conflict"
    assert conflict["admitted"] is False
    assert autoformal.query_pair(obligation, opposed, {})["reason"] == "incomplete_scope"


def test_a_neighbor_is_labeled_against_the_anchor_without_a_proof() -> None:
    autoformal = _autoformal()
    triples = [
        {"subject": "anchor", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "neighbor-a", "predicate": "citation", "object": "5 U.S.C. 552"},
    ]
    scope = {
        "jurisdiction": "US-OR",
        "as_of": "2024-06-15",
        "territory": "Multnomah",
        "subject_matter": "public-records",
        "actor": "agency",
        "subject": "requester",
        "resource": "records",
        "purpose": "disclosure",
        "authority_id": "auth:or-legislature",
        "enacted_date": "2019-01-01",
        "effective_from": "2020-01-01",
        "source_ref": "source:or-192",
        "provenance_id": "prov:or-192",
    }
    report = autoformal.neighbor_receipts(
        triples,
        "anchor",
        anchor_rule={"modality": "O"},
        scope=scope,
        formalize=lambda subject: {"clause_id": subject, "status": "roundtrip_ok", "modality": "F", "content_cid": ""},
    )
    assert report["stopped"] is False
    assert report["receipts"][0]["label"] == "contradiction"
    assert report["receipts"][0]["proved"] is False
    assert report["receipts"][0]["content_cid"] == ""


BACKUP = "Company A shall submit backup report within 10 days unless emergency."
BACKUP_VOCAB = {
    "actors": ["company_a", "company_b", "agency"],
    "actions": ["submit", "file", "withdraw"],
    "objects": ["backup_report", "incident_report", "annual_report"],
    "qualifiers": ["within_10_days", "emergency", "within_30_days", "natural_disaster"],
}
PAIR_SCOPE = {
    "jurisdiction": "US-OR",
    "as_of": "2024-06-15",
    "territory": "Multnomah",
    "subject_matter": "public-records",
    "actor": "agency",
    "subject": "requester",
    "resource": "records",
    "purpose": "disclosure",
    "authority_id": "auth:or-legislature",
    "enacted_date": "2019-01-01",
    "effective_from": "2020-01-01",
    "source_ref": "source:or-192",
    "provenance_id": "prov:or-192",
}


def test_a_cited_prohibition_conflicts_with_the_anchor_and_is_not_stored() -> None:
    autoformal = _autoformal()
    cited = [
        {"subject": "anchor", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "neighbor", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "unrelated", "predicate": "citation", "object": "12 U.S.C. 1"},
    ]
    result = autoformal.SESSION.formalize_against(
        BACKUP,
        "Company A shall not submit backup report within 10 days unless emergency.",
        triples=cited,
        anchor_id="anchor",
        neighbor_id="neighbor",
        scope=PAIR_SCOPE,
    )
    assert result["anchor_status"] == "roundtrip_ok"
    assert result["receipt"]["label"] == "contradiction"
    assert result["receipt"]["margin"] == 100
    assert result["receipt"]["proved"] is False
    assert result["receipt"]["content_cid"] == ""
    assert result["receipt"]["completion_authoritative"] is False
    assert result["admitted"] is False
    assert "repository" not in result
    assert "must not submit" in result["neighbor_decompiled"].lower()


def test_a_cited_statute_is_formalized_against_the_anchor_and_not_proved() -> None:
    autoformal = _autoformal()
    cited = [
        {"subject": "anchor", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "neighbor", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "unrelated", "predicate": "citation", "object": "12 U.S.C. 1"},
    ]
    missed = autoformal.SESSION.formalize_against(
        BACKUP, BACKUP, triples=cited, anchor_id="anchor", neighbor_id="unrelated",
        vocabulary=BACKUP_VOCAB, scope=PAIR_SCOPE,
    )
    assert missed["receipt"]["status"] == "not_retrieved"
    assert missed["receipt"]["proved"] is False
    assert autoformal.SESSION.compiled_ids == []
    calls = []
    opposed = autoformal.SESSION.formalize_against(
        BACKUP, PREAMBLE, triples=cited, anchor_id="anchor", neighbor_id="neighbor",
        vocabulary=BACKUP_VOCAB, scope=PAIR_SCOPE, allow_repair=True, generate=lambda _prompt: calls.append(1),
    )
    assert opposed["anchor_status"] == "roundtrip_ok"
    assert opposed["receipt"]["status"] == "abstain"
    assert opposed["receipt"]["label"] == "abstain"
    assert opposed["receipt"]["proved"] is False
    assert opposed["receipt"]["completion_authoritative"] is False
    assert calls == [1]
    second = autoformal.SESSION.formalize_against(
        BACKUP, PREAMBLE, triples=cited, anchor_id="anchor", neighbor_id="neighbor",
        vocabulary=BACKUP_VOCAB, scope=PAIR_SCOPE, allow_repair=True, generate=lambda _prompt: calls.append(1),
    )
    assert calls == [1]
    assert second["receipt"]["proved"] is False


def test_an_abstain_is_recompiled_once_and_then_stopped() -> None:
    autoformal = _autoformal()
    session = autoformal.SESSION
    opened = session.open_document(PREAMBLE, document_id="preamble")
    clause_id = opened["clauses"][0]["id"]
    session.compile_clause("preamble", clause_id)
    calls = {"generate": 0, "compile": 0}
    real = session.compile_clause

    def counting(document_id, clause_id, **kwargs):
        calls["compile"] += 1
        return real(document_id, clause_id, **kwargs)

    def generate(prompt: str) -> str:
        calls["generate"] += 1
        assert "shall not" in prompt
        assert "Do not rewrite the law" in prompt
        assert "modal_ir" in prompt
        return '{"frame_logic_triples":[{"subject":"NOT_IN_TEXT","predicate":"invented","object":"NOT_IN_TEXT"}]}'

    session.compile_clause = counting
    first = session.repair_clause(
        "preamble", clause_id, allow=True, generate=generate, positive="shall", negative="shall not",
    )
    assert first["accepted_triples"] == []
    assert first["rejected_triples"]
    second = session.repair_clause(
        "preamble", clause_id, allow=True, generate=generate, positive="shall", negative="shall not",
    )
    assert first["called"] is True
    assert first["recompiled"] is True
    assert first["status"] == "abstain"
    assert first["admitted"] is False
    assert calls == {"generate": 1, "compile": 1}
    assert second["called"] is False
    assert second["reason"] == "already_retried"


def test_the_repair_gate_opens_only_for_an_abstain() -> None:
    autoformal = _autoformal()
    calls = []

    def generate(prompt: str) -> str:
        calls.append(prompt)
        return "{}"

    kept = autoformal.repair_abstain({"status": "roundtrip_ok"}, allow=True, generate=generate, positive="shall", negative="shall not")
    closed = autoformal.repair_abstain({"status": "abstain"}, allow=False, generate=generate)
    opened = autoformal.repair_abstain({"status": "abstain"}, allow=True, generate=generate, positive="shall", negative="shall not")
    assert kept["called"] is False
    assert closed["called"] is False
    assert opened["called"] is True
    assert opened["admitted"] is False
    assert len(calls) == 1
    assert "shall not" in calls[0]
    assert "Do not rewrite the law" in calls[0]


def test_neighbors_are_receipts_one_at_a_time_and_unproved() -> None:
    autoformal = _autoformal()
    triples = [
        {"subject": "anchor", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "neighbor-a", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "neighbor-b", "predicate": "citation", "object": "5 U.S.C. 552"},
        {"subject": "unrelated", "predicate": "citation", "object": "12 U.S.C. 1"},
    ]

    def formalize(subject: str) -> dict:
        if subject == "neighbor-b":
            raise OSError("compiler environment")
        return {"clause_id": subject, "status": "roundtrip_ok", "content_cid": ""}

    report = autoformal.neighbor_receipts(triples, "anchor", formalize=formalize)
    assert report["stopped"] is True
    assert report["error"] == "OSError"
    assert [item["clause_id"] for item in report["receipts"]] == ["neighbor-a"]
    assert report["receipts"][0]["proved"] is False
    assert report["receipts"][0]["completion_authoritative"] is False
    assert "unrelated" not in [item["clause_id"] for item in report["receipts"]]


def test_a_shared_actor_and_action_is_a_contrastive_label_not_an_admit() -> None:
    autoformal = _autoformal()
    anchor = {"actor": "agency", "action": "disclose", "modality": "O"}
    same = {"actor": "agency", "action": "disclose", "modality": "O"}
    opposed = {"actor": "agency", "action": "disclose", "modality": "F"}
    other = {"actor": "company_a", "action": "submit", "modality": "O"}
    assert autoformal.label_pair(anchor, same) == {"label": "positive", "margin": 0, "admitted": False}
    assert autoformal.label_pair(anchor, opposed)["label"] == "contradiction"
    assert autoformal.label_pair(anchor, other)["label"] == "negative"
    assert autoformal.label_pair(anchor, opposed)["admitted"] is False


def test_an_environment_error_leaves_later_clauses_unrun() -> None:
    autoformal = _autoformal()
    text = "One.\n\nTwo.\n\nThree."
    autoformal.SESSION.open_document(text, document_id="three")

    real = autoformal.SESSION.compile_clause

    def fail_second(document_id, clause_id, **kwargs):
        if clause_id.endswith("c1"):
            raise OSError("compiler environment")
        return real(document_id, clause_id, **kwargs)

    autoformal.SESSION.compile_clause = fail_second
    report = autoformal.SESSION.walk_document("three")
    assert report["stopped"] is True
    assert report["error"] == "OSError"
    assert len(report["receipts"]) == 1
    assert report["receipts"][0]["proved"] is False


def test_repeal_skips_the_compiler() -> None:
    autoformal = _autoformal()
    text = "A person shall wait at least ten days.\n\nThe later rule shall wait at least twenty days."
    opened = autoformal.SESSION.open_document(
        text, document_id="repeal", edges=[{"kind": "repeal", "source": "1", "target": "0"}],
    )
    coverage = autoformal.SESSION.fill("repeal")
    assert opened["clauses"][0]["id"] not in autoformal.SESSION.compiled_ids
    assert coverage["counts"]["inactive"] == 1


def _compiled_row(autoformal, text: str, document_id: str) -> dict:
    opened = autoformal.SESSION.open_document(text, document_id=document_id)
    clause_id = opened["clauses"][0]["id"]
    return autoformal.SESSION.compile_clause(document_id, clause_id)["rows"][0]


def test_logic_tree_pin_resolves_inside_this_checkout() -> None:
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree, workspace_root

    root = workspace_root()
    assert root == Path(__file__).resolve().parents[3]
    resolved = require_workspace_logic_tree()
    for path in resolved.values():
        assert root in Path(path).parents


def test_eligible_to_an_office_is_not_a_recipient() -> None:
    autoformal = _autoformal()
    text = (
        "No Person except a natural born Citizen, or a Citizen of the United States, "
        "at the time of the Adoption of this Constitution, shall be eligible to the Office of President"
    )
    out = autoformal.compile_span(autoformal.SESSION, text, "natural-born", allow_partial=False)
    assert "recipient" not in out["fields"]
    rendered = out["decompiled"].lower()
    assert "natural born" in rendered
    assert "adoption" in rendered
    assert "eligible" in rendered
    assert "except a natural born" not in rendered
    row = next(item for item in autoformal.SESSION.rows if item.clause_id.startswith("natural-born"))
    assert row.status == "roundtrip_ok"
    assert (row.rule or {}).get("actor", "").lower() == "person"
    assert (row.rule or {}).get("modality") == "F"


def test_a_power_to_enforce_is_not_a_recipient() -> None:
    autoformal = _autoformal()
    text = "The Congress shall have power to enforce this article by appropriate legislation."
    out = autoformal.compile_span(autoformal.SESSION, text, "enforce", allow_partial=False)
    assert "recipient" not in out["fields"]
    assert "enforce" in out["decompiled"].lower()


def test_an_unsupported_recipient_is_named_and_still_abstains() -> None:
    autoformal = _autoformal()
    out = autoformal.compile_span(
        autoformal.SESSION,
        "The agency shall send the notice to the requester within 10 days.",
        "recipient-fixture",
    )
    assert out["compiler_status"] == "abstain"
    assert "recipient" in out["fields"]
    assert out["decompiled"] == ""


def test_three_sentence_compiler_gate_and_empty_vocabulary_abstains() -> None:
    autoformal = _autoformal()
    backup = _compiled_row(
        autoformal,
        "Company A shall submit backup report within 10 days unless emergency.",
        "gate-backup",
    )
    assert backup["status"] == "compiled"
    assert "10 days" in backup["decompiled"]
    assert "emergency" in backup["decompiled"]
    kinds = [item.get("temporal_kind") for item in backup["rule"].get("temporal_records") or []]
    assert kinds == ["within_duration"]

    prohibition = _compiled_row(autoformal, "The agency shall not disclose records.", "gate-prohibit")
    assert prohibition["status"] == "compiled"
    assert prohibition["rule"]["modality"] == "F"
    assert "must not" in prohibition["decompiled"] or "shall not" in prohibition["decompiled"]

    minimum = _compiled_row(
        autoformal,
        "The officer shall retain the file for at least 20 days.",
        "gate-minimum",
    )
    assert minimum["status"] == "compiled"
    records = minimum["rule"].get("temporal_records") or []
    assert records[0]["temporal_kind"] == "minimum_duration"
    assert records[0]["quantity"] == 20
    assert records[0]["value"] == "20 days"
    assert "at least 20 days" in minimum["decompiled"]
    assert "at least days" not in minimum["decompiled"]

    empty = autoformal._compile_text(
        "Company A shall submit backup report within 10 days unless emergency.",
        request_id="gate-empty",
        vocabulary={},
    )
    assert empty[0]["status"] == "abstain"
    assert empty[0]["rule"] is None


def test_constitution_agreement_census_is_not_an_admit() -> None:
    """Every operative span decompiles. That agreement is not a Lake admit."""

    from pathlib import Path

    from ipfs_datasets_py.logic.autoformal.autoencoder_router import agreement_census
    from ipfs_datasets_py.logic.autoformal.constitution_inventory import inventory_constitution

    path = Path("/home/barberb/lift_coding/JevOps/.improve-watch/us-constitution/constitution.txt")
    if not path.is_file():
        return
    samples = [
        {"id": span["id"], "text": span["text"], "status": span["status"]}
        for span in inventory_constitution(path.read_text()).get("spans") or []
    ]
    census = agreement_census(samples, {"captures": []})
    assert census["formalized"] is False
    assert census["admitted"] is False
    assert census["operative"] == census["agreed"]
    assert census["todos"] == []
    assert census["agrees"] is True
    for row in census["rows"]:
        rendered = str(row.get("decompiled") or "").lower()
        assert "if condition" not in rendered
        assert "unless exception" not in rendered


def test_a_condition_keeps_its_clause_instead_of_the_word_condition() -> None:
    autoformal = _autoformal()
    text = (
        "When vacancies happen in the Representation from any State, "
        "the Executive Authority thereof shall issue Writs of Election to fill such Vacancies."
    )
    vocabulary = autoformal.vocabulary_from_clause(text)
    assert vocabulary is not None
    assert "condition" not in {item.casefold() for item in vocabulary["qualifiers"]}
    out = autoformal.compile_span(autoformal.SESSION, text, "vacancy", allow_partial=True)
    rendered = out["decompiled"].lower()
    assert "if condition" not in rendered
    assert "vacancies happen" in rendered
    assert out["compiler_status"] == "compiled"


def test_a_spelled_within_duration_is_not_dropped() -> None:
    autoformal = _autoformal()
    text = (
        "The actual Enumeration shall be made within three Years after the first Meeting "
        "of the Congress of the United States, and within every subsequent Term of ten Years, "
        "in such Manner as they shall by Law direct."
    )
    out = autoformal.compile_span(autoformal.SESSION, text, "enumeration", allow_partial=True)
    rendered = out["decompiled"].lower()
    assert "within three years" in rendered
    assert "within every subsequent term of ten years" in rendered
    assert "if condition" not in rendered


def test_an_ordinal_is_not_reduced_to_its_suffix() -> None:
    from ipfs_datasets_py.logic.deontic.utils.deontic_parser import _action_object

    rendered = _action_object("meet on the 12th day")
    assert "12th" in rendered.split()
    assert "th" not in rendered.split()


def test_every_rule_in_one_sentence_is_decompiled() -> None:
    autoformal = _autoformal()
    text = (
        "If, at the time fixed for the beginning of the term of the President, "
        "the President elect shall have died, the Vice President elect shall become President."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "succession", allow_partial=True
    )["decompiled"].lower()
    assert "died" in rendered
    assert "become president" in rendered


def test_a_comma_before_shall_does_not_drop_the_vesting() -> None:
    autoformal = _autoformal()
    text = (
        "The judicial Power of the United States, shall be vested in one supreme Court, "
        "and in such inferior Courts as the Congress may from time to time ordain and establish."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "vest", allow_partial=True
    )["decompiled"].lower()
    assert "vested" in rendered
    assert "supreme" in rendered


def test_arising_under_the_constitution_is_kept() -> None:
    autoformal = _autoformal()
    text = (
        "The judicial Power shall extend to all Cases, in Law and Equity, "
        "arising under this Constitution, the Laws of the United States, and Treaties made."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "extend", allow_partial=True
    )["decompiled"].lower()
    assert "constitution" in rendered
    assert "treaties" in rendered


def test_article_five_proposes_amendments_when_two_thirds_deem_it_necessary() -> None:
    autoformal = _autoformal()
    text = (
        "The Congress, whenever two thirds of both Houses shall deem it necessary, "
        "shall propose Amendments to this Constitution."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "article-five", allow_partial=True
    )["decompiled"].lower()
    assert "propose amendments" in rendered
    assert "deem it necessary" in rendered
    assert "must deem it necessary shall" not in rendered


def test_the_thirteenth_amendment_forbids_slavery() -> None:
    autoformal = _autoformal()
    text = (
        "Neither slavery nor involuntary servitude, except as a punishment for crime "
        "whereof the party shall have been duly convicted, shall exist within the United States, "
        "or any place subject to their jurisdiction."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "amend-13", allow_partial=True
    )["decompiled"].lower()
    assert "slavery" in rendered
    assert "must not exist" in rendered
    assert "convicted" in rendered
    assert "must have been duly convicted shall exist" not in rendered


def test_a_qualification_keeps_age_citizenship_and_inhabitancy() -> None:
    autoformal = _autoformal()
    text = (
        "No Person shall be a Representative who shall not have attained to the Age of "
        "twenty five Years, and been seven Years a Citizen of the United States, and who "
        "shall not, when elected, be an Inhabitant of that State in which he shall be chosen."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "qualification", allow_partial=True
    )["decompiled"].lower()
    assert "twenty five" in rendered
    assert "seven" in rendered
    assert "inhabitant" in rendered
    assert "when elected" in rendered
    assert ". be an inhabitant" not in rendered
    assert "shall" not in rendered
    assert "if elected" not in rendered
    session = autoformal.SESSION
    row = next(item for item in session.rows if item.clause_id.startswith("qualification"))
    assert row.status == "roundtrip_ok"


def test_neither_shall_any_person_keeps_the_age_qualification() -> None:
    autoformal = _autoformal()
    text = (
        "neither shall any Person be eligible to that Office who shall not have attained "
        "to the Age of thirty five Years, and been fourteen Years a Resident within the United States."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "neither-eligible", allow_partial=False
    )["decompiled"].lower()
    assert "thirty five" in rendered
    assert "fourteen" in rendered
    assert "eligible" in rendered
    assert "neither must not" not in rendered
    assert "shall" not in rendered
    row = next(item for item in autoformal.SESSION.rows if item.clause_id.startswith("neither-eligible"))
    assert row.status == "roundtrip_ok"
    assert (row.rule or {}).get("actor", "").lower() != "neither"
    assert (row.rule or {}).get("modality") == "F"


def test_an_after_shall_is_not_its_own_duty() -> None:
    autoformal = _autoformal()
    text = (
        "Immediately after they shall be assembled in Consequence of the first Election, "
        "they shall be divided as equally as may be into three Classes."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "classes", allow_partial=True
    )["decompiled"].lower()
    assert "three classes" in rendered
    assert "assembled" in rendered
    assert not rendered.startswith("immediately after they must")


def test_an_interrupted_shall_keeps_adjourn() -> None:
    autoformal = _autoformal()
    text = (
        "Neither House, during the Session of Congress, shall, without the Consent of the other, "
        "adjourn for more than three days, nor to any other Place than that in which the two Houses "
        "shall be sitting."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "adjourn", allow_partial=True
    )["decompiled"].lower()
    assert "adjourn" in rendered
    assert "three days" in rendered
    assert "consent" in rendered


def test_an_elliptical_and_shall_keeps_the_same_actor() -> None:
    autoformal = _autoformal()
    text = (
        "The House of Representatives shall chuse their Speaker and other Officers; "
        "and shall have the sole Power of Impeachment."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "impeach", allow_partial=True
    )["decompiled"].lower()
    assert "speaker" in rendered
    assert "impeachment" in rendered


def test_a_shorter_exception_is_not_repeated() -> None:
    autoformal = _autoformal()
    text = (
        "They shall in all Cases, except Treason, Felony and Breach of the Peace, "
        "be privileged from Arrest during their Attendance."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "privilege-list", allow_partial=True
    )["decompiled"].lower()
    assert "felony" in rendered
    assert rendered.count("treason") == 1


def test_distinct_subject_must_and_may_clauses_do_not_merge() -> None:
    for source, expected in [
        ("The agency must retain reports; the clerk may publish notices.",
         "Agency must retain reports. Clerk may publish notices."),
        ("The agency may inspect reports; the clerk must retain notices.",
         "Agency may inspect reports. Clerk must retain notices."),
    ]:
        autoformal = _autoformal()
        outcome = autoformal.compile_span(autoformal.SESSION, source, "independent-clauses")
        assert outcome["compiler_status"] == "compiled"
        assert outcome["decompiled"] == expected
        kept = [
            row for row in autoformal.SESSION.rows
            if row.status in {"compiled", "roundtrip_ok"}
        ]
        assert len(kept) == 2


def test_a_parenthetical_when_does_not_govern_the_earlier_duty() -> None:
    autoformal = _autoformal()
    text = (
        "The United States shall guarantee to every State in this Union a Republican Form of Government, "
        "and shall protect each of them against Invasion; and on Application of the Legislature, "
        "or of the Executive (when the Legislature cannot be convened) against domestic Violence."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "guarantee", allow_partial=True
    )["decompiled"].lower()
    assert rendered.count("cannot be convened") == 1
    assert "republican" in rendered
    assert "protect" in rendered
    assert "invasion" in rendered
    assert "domestic violence" in rendered


def test_slot_deduplication_requires_the_same_source_clause() -> None:
    from copy import deepcopy
    from ipfs_datasets_py.logic.deontic.utils.deontic_parser import _dedupe_slot_surfaces

    short = {"type": "exception", "clause_type": "except", "normalized_text": "treason",
             "span": [32, 39], "clause_span": [25, 40]}
    long = {**short, "normalized_text": "treason, felony", "span": [32, 46], "clause_span": [25, 48]}
    element = {"exception_details": [short, long], "exceptions": ["old legacy surface"]}
    _dedupe_slot_surfaces(element)
    assert element["exception_details"] == element["exceptions"] == [long]

    # Negation, distinct occurrences, unknown/malformed provenance, different
    # introducers, and partial-word matches must never erase a condition.
    variants = [
        {**long, "normalized_text": "not treason"},
        {**long, "span": [90, 104], "clause_span": [83, 106]},
        {key: value for key, value in long.items() if key != "span"},
        {**long, "span": ["32", "46"]},
        {**long, "clause_span": [24, 48]},
        {**long, "clause_type": "unless"},
        {**long, "type": "condition"},
        {**long, "normalized_text": "treasonous conduct"},
    ]
    for alternative in variants:
        element = {"exception_details": [short, alternative], "exceptions": [short, alternative],
                   "condition_details": [], "temporal_constraint_details": []}
        before = deepcopy(element)
        _dedupe_slot_surfaces(element)
        assert element == before


def test_ir_does_not_reintroduce_parser_scoped_parenthetical_conditions() -> None:
    from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
    from ipfs_datasets_py.logic.deontic.utils.deontic_parser import analyze_normative_sentence

    source = ("The agency shall retain records, and shall send notice to the clerk "
              "(when the clerk is available).")
    elements = analyze_normative_sentence(source, "statute")
    assert len(elements) == 2
    for element in elements:
        assert element["slot_details_scoped"] is True
        assert element["condition_details"] == []
        assert not LegalNormIR.from_parser_element(element).conditions


def test_a_nested_shall_is_not_decompiled_twice() -> None:
    autoformal = _autoformal()
    text = (
        "The right of the people to be secure in their persons, houses, papers, and effects, "
        "against unreasonable searches and seizures, shall not be violated, and no Warrants shall issue, "
        "but upon probable cause, supported by Oath or affirmation."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "warrants", allow_partial=True
    )["decompiled"].lower()
    assert rendered.count("warrants") == 1
    assert "probable cause" in rendered
    assert "shall not be violated" not in rendered or "must not be violated" in rendered


def test_a_manner_clause_does_not_repeat_the_deadline() -> None:
    autoformal = _autoformal()
    text = (
        "The actual Enumeration shall be made within three Years after the first Meeting "
        "of the Congress of the United States, and within every subsequent Term of ten Years, "
        "in such Manner as they shall by Law direct."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "enumeration-manner", allow_partial=True
    )["decompiled"].lower()
    assert "three years" in rendered
    assert "ten years" in rendered
    assert rendered.count("three years") == 1
    assert rendered.count("ten years") == 1
    assert rendered.count("by law direct") == 1


def test_an_unless_shall_is_not_a_second_duty() -> None:
    autoformal = _autoformal()
    text = (
        "The Congress shall assemble at least once in every Year, and such Meeting shall be "
        "on the first Monday in December, unless they shall by Law appoint a different Day."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "assemble", allow_partial=True
    )["decompiled"].lower()
    assert "december" in rendered
    assert "appoint a different day" in rendered
    assert rendered.count("appoint a different day") == 1


def test_an_if_condition_is_not_repeated_as_its_own_duty() -> None:
    autoformal = _autoformal()
    text = (
        "If a President shall not have been chosen before the time fixed for the beginning of his term, "
        "or if the President elect shall have failed to qualify, then the Vice President elect shall act "
        "as President until a President shall have qualified."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "qualify", allow_partial=True
    )["decompiled"].lower()
    assert "act as president" in rendered
    assert "failed to qualify" in rendered
    assert "until a president shall have qualified" in rendered
    assert rendered.count("act as president") == 1


def test_an_if_comma_preamble_stays_on_the_succession() -> None:
    autoformal = _autoformal()
    text = (
        "If, at the time fixed for the beginning of the term of the President, "
        "the President elect shall have died, the Vice President elect shall become President."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "succession-if", allow_partial=True
    )["decompiled"].lower()
    assert "time fixed" in rendered
    assert "shall have died" in rendered
    assert "must have died" not in rendered
    assert "become president" in rendered


def test_if_he_approve_keeps_sign_and_return() -> None:
    autoformal = _autoformal()
    text = (
        "Every Bill which shall have passed the House of Representatives and the Senate, "
        "shall, before it become a Law, be presented to the President of the United States; "
        "If he approve he shall sign it, but if not he shall return it."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "presentment", allow_partial=True
    )["decompiled"].lower()
    assert "presented" in rendered
    assert "sign" in rendered
    assert "return" in rendered


def test_nor_shall_keeps_due_process_as_a_prohibition() -> None:
    autoformal = _autoformal()
    text = (
        "No State shall make or enforce any law which shall abridge the privileges or immunities "
        "of citizens of the United States; nor shall any State deprive any person of life, liberty, "
        "or property, without due process of law; nor deny to any person within its jurisdiction "
        "the equal protection of the laws."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "equal-protection", allow_partial=True
    )["decompiled"].lower()
    assert "due process" in rendered
    assert "equal protection" in rendered
    assert "must not deprive" in rendered or "must not" in rendered


def test_an_em_dash_list_keeps_the_later_cases() -> None:
    autoformal = _autoformal()
    text = (
        "The judicial Power shall extend to all Cases, in Law and Equity, arising under this "
        "Constitution, the Laws of the United States, and Treaties made, or which shall be made, "
        "under their Authority;—to all Cases affecting Ambassadors, other public Ministers and Consuls."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "extend-list", allow_partial=True
    )["decompiled"].lower()
    assert "ambassadors" in rendered
    assert "constitution" in rendered


def test_an_unknown_participle_is_not_stemmed() -> None:
    autoformal = _autoformal()
    text = (
        "Whenever the President transmits his written declaration that he is unable to discharge "
        "the powers and duties of his office, such powers and duties shall be discharged by the "
        "Vice President as Acting President."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "acting", allow_partial=True
    )["decompiled"].lower()
    assert "discharged" in rendered
    assert "discharg " not in rendered


def test_a_colon_clause_keeps_the_consent_exception() -> None:
    autoformal = _autoformal()
    text = (
        "No Title of Nobility shall be granted by the United States: And no Person holding "
        "any Office of Profit or Trust under them, shall, without the Consent of the Congress, "
        "accept of any present, Emolument, Office, or Title, of any kind whatever, from any King, "
        "Prince, or foreign State."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "nobility", allow_partial=True
    )["decompiled"].lower()
    assert "nobility" in rendered
    assert "consent" in rendered
    assert "present" in rendered


def test_a_parenthetical_except_keeps_the_verb_and_the_list() -> None:
    autoformal = _autoformal()
    text = (
        "They shall in all Cases, except Treason, Felony and Breach of the Peace, "
        "be privileged from Arrest during their Attendance at the Session."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "privilege", allow_partial=True
    )["decompiled"].lower()
    assert "privileged" in rendered
    assert "felony" in rendered
    assert "peace" in rendered


def test_a_historical_ordinal_keeps_its_suffix() -> None:
    from ipfs_datasets_py.logic.deontic.utils.deontic_parser import _action_object

    assert "3d" in _action_object("end on the 3d day").split()


def test_a_semicolon_list_keeps_the_later_verbs() -> None:
    autoformal = _autoformal()
    text = (
        "No State shall enter into any Treaty, Alliance, or Confederation; "
        "grant Letters of Marque and Reprisal; coin Money; "
        "or grant any Title of Nobility."
    )
    rendered = autoformal.compile_span(
        autoformal.SESSION, text, "state-list", allow_partial=True
    )["decompiled"].lower()
    assert "treaty" in rendered
    assert "marque" in rendered
    assert "coin" in rendered
    assert "nobility" in rendered


def test_within_a_place_is_not_cut_off_as_a_duration() -> None:
    autoformal = _autoformal()
    text = "The Secretary shall make publications available within this section."
    out = autoformal.compile_span(autoformal.SESSION, text, "within-place", allow_partial=True)
    assert "section" in out["decompiled"].lower()
    assert "if condition" not in out["decompiled"].lower()


def test_declarative_classification_is_not_coerced_into_an_obligation() -> None:
    from ipfs_datasets_py.logic.deontic.utils.deontic_parser import analyze_normative_sentence

    # Synthetic grammar probes, not judgments about a statute's legal effect.
    # A future classification family is allowed; fabricating O/P/F is not.
    for text in ("An amber triangle constitutes a marker.",
                 "Two red dots constitute a category label."):
        for element in analyze_normative_sentence(text, "statute"):
            assert element.get("norm_type") not in {"obligation", "permission", "prohibition"}
            assert element.get("deontic_operator") not in {"O", "P", "F"}


def test_dangling_reference_cannot_be_discarded_to_make_projection_succeed() -> None:
    from types import SimpleNamespace
    import pytest
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import project_legal_norms
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary, CanonicalContractError

    vocabulary = CanonicalAtomVocabulary(actors=("agency",), actions=("file",), objects=("notice",), qualifiers=())
    for reference in ("under .", {"value": "under .", "type": "section"}):
        data = {"modality": "obligation", "norm_type": "obligation", "actor": "agency",
                "action": "file notice", "action_verb": "file", "action_object": "notice",
                "conditions": [], "exceptions": [], "temporal_constraints": [],
                "cross_references": [reference]}
        norm = SimpleNamespace(to_dict=lambda: dict(data))
        with pytest.raises(CanonicalContractError, match="unsupported semantics"):
            project_legal_norms((norm,), vocabulary)


def test_recipient_is_not_preserved_by_matching_only_its_last_word() -> None:
    from types import SimpleNamespace
    import pytest
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import project_legal_norms
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary, CanonicalContractError

    data = {"modality": "obligation", "norm_type": "obligation", "actor": "agency",
            "action": "file notice", "action_verb": "file", "action_object": "notice",
            "conditions": [], "exceptions": [], "temporal_constraints": [],
            "recipient": [{"value": "other agency"}]}
    vocabulary = CanonicalAtomVocabulary(actors=("agency",), actions=("file",), objects=("notice",), qualifiers=())
    with pytest.raises(CanonicalContractError, match="unsupported semantics"):
        project_legal_norms((SimpleNamespace(to_dict=lambda: dict(data)),), vocabulary)


def test_matching_section_number_does_not_resolve_a_different_statute_reference() -> None:
    from types import SimpleNamespace
    import pytest
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import project_legal_norms
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary, CanonicalContractError

    data = {"modality": "obligation", "norm_type": "obligation", "actor": "agency",
            "action": "file notice", "action_verb": "file", "action_object": "notice",
            "conditions": [{"text": "section 4401"}], "exceptions": [], "temporal_constraints": [],
            "cross_references": [{"value": "a different statute section 4401",
                                  "resolution_status": "unresolved", "target_exists": False}]}
    vocabulary = CanonicalAtomVocabulary(actors=("agency",), actions=("file",), objects=("notice",),
                                         qualifiers=("section 4401",))
    with pytest.raises(CanonicalContractError, match="unsupported semantics"):
        project_legal_norms((SimpleNamespace(to_dict=lambda: dict(data)),), vocabulary)
