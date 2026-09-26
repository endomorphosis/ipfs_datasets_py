"""Autoencoder samples keep frame logic, and admission waits on a fixture."""

from __future__ import annotations

from ipfs_datasets_py.logic.autoformal.ontology_capture import (
    admit_after_sanitation,
    ontology_record,
    sanitize_fixture,
)
from ipfs_datasets_py.logic.autoformal.ontology_fragments import FragmentRegistry


class _Frame:
    def to_triples(self):
        return (
            {"subject": "notice", "predicate": "recipient", "object": "requester"},
            {"subject": "requester", "predicate": "type", "object": "person"},
        )


class _IR:
    frame_logic = _Frame()


class _Sample:
    sample_id = "notice-1"
    text = "The agency shall send the notice to the requester."
    modal_ir = _IR()


def test_schema_label_decompilation_is_not_the_clause() -> None:
    from ipfs_datasets_py.logic.autoformal.ontology_capture import (
        missing_qualifier_surfaces,
        schema_placeholders,
    )

    text = (
        "When vacancies happen in the Representation from any State, "
        "the Executive Authority thereof shall issue Writs of Election to fill such Vacancies."
    )
    assert schema_placeholders("Executive Authority must issue Writs if condition.") == ["if condition"]
    assert schema_placeholders("Agency must not disclose records.") == []
    missing = missing_qualifier_surfaces(
        text,
        "Executive Authority thereof must issue Writs of Election to fill such Vacancies if condition.",
    )
    assert any("vacancies happen" in item.lower() for item in missing)
    kept = missing_qualifier_surfaces(
        text,
        "Executive Authority thereof must issue Writs of Election to fill such Vacancies "
        "if vacancies happen in the representation from any state.",
    )
    assert kept == []


def test_capture_reads_frame_logic_already_on_the_sample() -> None:
    from ipfs_datasets_py.logic.autoformal.ontology_capture import capture_samples

    records = capture_samples([_Sample()])
    assert records[0]["admitted"] is False
    assert records[0]["recipient"]["sort_id"] == "requester"
    assert records[0]["sorts"] == ["person"]
    assert records[0]["triples"][0]["predicate"] == "recipient"


def test_a_recipient_fixture_fails_sanitation_until_the_sentence_round_trips() -> None:
    sanitation = sanitize_fixture(
        "The agency shall send the notice to the requester.",
        must_contain=["requester"],
        only_fields=["recipient"],
    )
    assert sanitation["passed"] is False
    assert sanitation["admitted"] is False
    assert "diagnostic_set" in sanitation["reasons"]
    assert any(reason.startswith("missing:") for reason in sanitation["reasons"])
    registry = FragmentRegistry()
    result = admit_after_sanitation(registry, {
        "relation": "recipient_of",
        "domain": "norm",
        "range": "sort",
        "attachment": "recipient",
        "decompiler_phrase": "to the requester",
        "fixture_id": "requester-notice",
    }, sanitation)
    assert result["admitted"] is False
    assert result["reason"] == "sanitation_failed"
    assert registry.visible_to_compiler() == []


def test_a_passing_fixture_is_required_before_a_fragment_is_admitted() -> None:
    sanitation = sanitize_fixture(
        "Company A shall submit backup report within 10 days unless emergency.",
        must_contain=["10 days", "emergency"],
        only_fields=[],
    )
    assert sanitation["passed"] is True
    assert "10 days" in sanitation["decompiled"]
    assert "emergency" in sanitation["decompiled"]
    registry = FragmentRegistry()
    refused = admit_after_sanitation(registry, {
        "relation": "deadline",
        "domain": "norm",
        "range": "duration",
        "attachment": "temporal",
        "decompiler_phrase": "within 10 days",
        "fixture_id": "backup-report",
    }, {"passed": False, "reasons": ["diagnostic_set"]})
    assert refused["admitted"] is False
    registry = FragmentRegistry()
    admitted = admit_after_sanitation(registry, {
        "relation": "deadline",
        "domain": "norm",
        "range": "duration",
        "attachment": "temporal",
        "decompiler_phrase": "within 10 days",
        "fixture_id": "backup-report",
    }, sanitation)
    assert admitted["admitted"] is True
    assert admitted["sanitation_passed"] is True
    assert registry.visible_to_compiler()[0]["relation"] == "deadline"


def test_partial_compile_keeps_the_clerk_without_becoming_the_default() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = "The officer shall give the file to the clerk."
    session = AutoformalSession()
    blocked = compile_span(session, text, "clerk-blocked")
    assert blocked["compiler_status"] == "abstain"
    assert blocked["fields"] == ["recipient"]
    allowed = compile_span(session, text, "clerk-partial", allow_partial=True)
    assert allowed["compiler_status"] == "compiled"
    assert "clerk" in allowed["decompiled"].lower()
    assert allowed.get("admitted") is not True


def test_give_to_the_clerk_is_only_recipient_and_still_fails_sanitation() -> None:
    text = "The officer shall give the file to the clerk."
    sanitation = sanitize_fixture(text, must_contain=["clerk"], only_fields=["recipient"])
    assert sanitation["fields"] == ["recipient"]
    assert sanitation["passed"] is False
    assert sanitation["admitted"] is False
    assert any(reason.startswith("missing:") for reason in sanitation["reasons"])
    registry = FragmentRegistry()
    result = admit_after_sanitation(registry, {
        "relation": "recipient_of",
        "domain": "norm",
        "range": "sort",
        "attachment": "recipient",
        "decompiler_phrase": "to the clerk",
        "fixture_id": "give-file-to-clerk",
    }, sanitation)
    assert result["admitted"] is False
    assert registry.visible_to_compiler() == []


def test_reserved_powers_and_citizenship_are_declarative_norms() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    session = AutoformalSession()
    reserved = compile_span(
        session,
        "The powers not delegated to the United States are reserved to the States, or to the people.",
        "reserved",
        allow_partial=True,
    )
    assert "reserved" in reserved["decompiled"].lower()
    assert reserved.get("fields") != ["unsupported_norm_type"]
    citizens = compile_span(
        session,
        "All persons born in the United States are citizens of the United States.",
        "citizens",
        allow_partial=True,
    )
    assert "citizens" in citizens["decompiled"].lower()


def test_a_semicolon_and_shall_keeps_both_clauses() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The Senate of the United States shall be composed of two Senators from each State, "
        "for six Years; and each Senator shall have one Vote."
    )
    rendered = compile_span(AutoformalSession(), text, "senate-join", allow_partial=True)["decompiled"].lower()
    assert "six years" in rendered
    assert "one vote" in rendered


def test_a_long_hereby_prohibited_keeps_the_conduct_and_the_word() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The transportation or importation into any State, Territory, or possession of the "
        "United States for delivery or use therein of intoxicating liquors, in violation of "
        "the laws thereof, is hereby prohibited."
    )
    rendered = compile_span(AutoformalSession(), text, "liquor-import", allow_partial=True)["decompiled"].lower()
    assert "is hereby prohibited" in rendered
    assert "importation" in rendered
    assert "violation" in rendered
    assert "must not be done" not in rendered
    beverage = (
        "After one year from the ratification of this article the manufacture, sale, or "
        "transportation of intoxicating liquors within, the importation thereof into, or the "
        "exportation thereof from the United States and all territory subject to the jurisdiction "
        "thereof for beverage purposes is hereby prohibited."
    )
    rendered = compile_span(AutoformalSession(), beverage, "beverage", allow_partial=True)["decompiled"].lower()
    assert "is hereby prohibited" in rendered
    assert "beverage purposes" in rendered
    assert "if the jurisdiction" not in rendered
    assert "must not be done" not in rendered


def test_hereby_prohibited_stays_a_prohibition() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = "The transportation of intoxicating liquors is hereby prohibited."
    rendered = compile_span(AutoformalSession(), text, "hereby", allow_partial=True)["decompiled"].lower()
    assert "is hereby prohibited" in rendered
    assert "intoxicating liquors" in rendered
    assert "must not be done" not in rendered
    assert "must not prohibit" not in rendered


def test_a_comma_before_shall_is_still_a_norm() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = "The President, Vice President and all civil Officers of the United States, shall be removed from Office on Impeachment for Treason."
    out = compile_span(AutoformalSession(), text, "removed", allow_partial=True)
    assert out["compiler_status"] == "compiled"
    assert "removed" in out["decompiled"].lower()


def test_a_later_shall_not_keeps_its_own_verb() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "They shall in all Cases, except Treason, Felony and Breach of the Peace, "
        "be privileged from Arrest during their Attendance at the Session of their respective Houses, "
        "and in going to and returning from the same; and for any Speech or Debate in either House, "
        "they shall not be questioned in any other Place."
    )
    rendered = compile_span(AutoformalSession(), text, "speech-debate", allow_partial=True)["decompiled"].lower()
    assert "privileged" in rendered
    assert "questioned" in rendered
    assert "speech" in rendered
    assert "debate" in rendered
    assert "must not be privileged" not in rendered
    assert "felony" in rendered


def test_a_colon_nor_shall_keeps_the_vessels() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "No Preference shall be given by any Regulation of Commerce or Revenue to the Ports of one State "
        "over those of another: nor shall Vessels bound to, or from, one State, be obliged to enter, "
        "clear, or pay Duties in another."
    )
    rendered = compile_span(AutoformalSession(), text, "vessels", allow_partial=True)["decompiled"].lower()
    assert "preference" in rendered
    assert "must not" in rendered
    assert "vessels" in rendered
    assert "obliged" in rendered
    assert "duties" in rendered


def test_a_shall_inside_and_those_is_not_its_own_duty() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "In all Cases affecting Ambassadors, other public Ministers and Consuls, and those in which "
        "a State shall be Party, the supreme Court shall have original Jurisdiction."
    )
    rendered = compile_span(AutoformalSession(), text, "ambassadors", allow_partial=True)["decompiled"].lower()
    assert "ambassadors" in rendered
    assert "consuls" in rendered
    assert "original jurisdiction" in rendered
    assert "must be party" not in rendered


def test_an_infinitive_subject_keeps_the_right_and_the_age() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The right of citizens of the United States, who are eighteen years of age or older, "
        "to vote shall not be denied or abridged by the United States or by any State on account of age."
    )
    rendered = compile_span(AutoformalSession(), text, "vote-age", allow_partial=True)["decompiled"].lower()
    assert "citizens" in rendered
    assert "eighteen" in rendered
    assert "vote" in rendered
    assert "must not" in rendered
    assert "denied" in rendered


def test_an_unless_or_keeps_the_coordinated_confession() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "No Person shall be convicted of Treason unless on the Testimony of two Witnesses "
        "to the same overt Act, or on Confession in open Court."
    )
    rendered = compile_span(AutoformalSession(), text, "treason", allow_partial=True)["decompiled"].lower()
    assert "two witnesses" in rendered
    assert "confession" in rendered
    assert "open court" in rendered
    assert rendered.count("unless") == 1


def test_an_elliptical_nor_keeps_wartime_quartering() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "No Soldier shall, in time of peace be quartered in any house, without the consent of the Owner, "
        "nor in time of war, but in a manner to be prescribed by law."
    )
    rendered = compile_span(AutoformalSession(), text, "quartering", allow_partial=True)["decompiled"].lower()
    assert "peace" in rendered
    assert "without the consent" in rendered
    assert "unless the consent" not in rendered
    assert "time of war" in rendered
    assert "prescribed" in rendered


def test_a_colon_object_keeps_the_elector_count() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The District constituting the seat of Government of the United States shall appoint "
        "in such manner as the Congress may direct: A number of electors of President and Vice President "
        "equal to the whole number of Senators and Representatives in Congress to which the District would "
        "be entitled if it were a State, but in no event more than the least populous State; they shall be "
        "in addition to those appointed by the States."
    )
    rendered = compile_span(AutoformalSession(), text, "electors", allow_partial=True)["decompiled"].lower()
    assert "appoint" in rendered
    assert "senators" in rendered
    assert "representatives" in rendered
    assert "least populous" in rendered
    assert "in addition" in rendered


def test_a_whenever_comma_keeps_the_written_declaration() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "Whenever the Vice President and a majority of either the principal officers of the executive "
        "departments or of such other body as Congress may by law provide, transmit to the President pro "
        "tempore of the Senate and the Speaker of the House of Representatives their written declaration "
        "that the President is unable to discharge the powers and duties of his office, the Vice President "
        "shall immediately assume the powers and duties of the office as Acting President."
    )
    rendered = compile_span(AutoformalSession(), text, "acting", allow_partial=True)["decompiled"].lower()
    assert "acting president" in rendered
    assert "transmit" in rendered
    assert "written declaration" in rendered
    assert "speaker" in rendered
    assert "unable" in rendered


def test_nor_shall_any_person_keeps_jeopardy_and_compensation() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "No person shall be held to answer for a capital, or otherwise infamous crime, "
        "unless on a presentment or indictment of a Grand Jury, except in cases arising in "
        "the land or naval forces, or in the Militia, when in actual service in time of War "
        "or public danger; nor shall any person be subject for the same offence to be twice "
        "put in jeopardy of life or limb; nor shall be compelled in any criminal case to be "
        "a witness against himself, nor be deprived of life, liberty, or property, without "
        "due process of law; nor shall private property be taken for public use, without just compensation."
    )
    rendered = compile_span(AutoformalSession(), text, "fifth", allow_partial=True)["decompiled"].lower()
    assert "jeopardy" in rendered
    assert "compelled" in rendered
    assert "due process" in rendered
    assert "just compensation" in rendered


def test_an_elliptical_and_shall_keeps_the_judges_compensation() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The Judges, both of the supreme and inferior Courts, shall hold their Offices during "
        "good Behaviour, and shall, at stated Times, receive for their Services, a Compensation, "
        "which shall not be diminished during their Continuance in Office."
    )
    rendered = compile_span(AutoformalSession(), text, "judges", allow_partial=True)["decompiled"].lower()
    assert "good behaviour" in rendered
    assert "compensation" in rendered
    assert "diminished" in rendered


def test_a_two_thirds_determination_keeps_the_vote_and_the_resume() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "If the Congress, within twenty-one days after receipt of the latter written declaration, "
        "or, if Congress is not in session, within twenty-one days after Congress is required to assemble, "
        "determines by two-thirds vote of both Houses that the President is unable to discharge the powers "
        "and duties of his office, the Vice President shall continue to discharge the same as Acting President; "
        "otherwise, the President shall resume the powers and duties of his office."
    )
    rendered = compile_span(AutoformalSession(), text, "two-thirds", allow_partial=True)["decompiled"].lower()
    assert "two-thirds" in rendered
    assert "both houses" in rendered
    assert "unable" in rendered
    assert "acting president" in rendered
    assert "resume" in rendered


def test_a_quorum_keeps_adjournment_attendance_and_penalties() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "Each House shall be the Judge of the Elections, Returns and Qualifications of its own Members, "
        "and a Majority of each shall constitute a Quorum to do Business; but a smaller Number may adjourn "
        "from day to day, and may be authorized to compel the Attendance of absent Members, in such Manner, "
        "and under such Penalties as each House may provide."
    )
    rendered = compile_span(AutoformalSession(), text, "quorum", allow_partial=True)["decompiled"].lower()
    assert "judge" in rendered
    assert "quorum" in rendered
    assert "adjourn" in rendered
    assert "absent" in rendered
    assert "penalties" in rendered
    assert "unless members" not in rendered


def test_without_apportionment_is_not_an_exception_to_the_tax() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The Congress shall have power to lay and collect taxes on incomes, from whatever source derived, "
        "without apportionment among the several States, and without regard to any census or enumeration."
    )
    rendered = compile_span(AutoformalSession(), text, "income-tax", allow_partial=True)["decompiled"].lower()
    assert "without apportionment" in rendered
    assert "without regard" in rendered
    assert "census" in rendered
    assert "unless apportionment" not in rendered
    assert "unless regard" not in rendered


def test_a_senate_vacancy_during_recess_keeps_the_temporary_appointment() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The Seats of the Senators of the first Class shall be vacated at the Expiration of the second Year; "
        "and if Vacancies happen by Resignation, or otherwise, during the Recess of the Legislature of any State, "
        "the Executive thereof may make temporary Appointments until the next Meeting of the Legislature, "
        "which shall then fill such Vacancies."
    )
    rendered = compile_span(AutoformalSession(), text, "recess", allow_partial=True)["decompiled"].lower()
    assert "temporary appointments" in rendered
    assert "or otherwise" in rendered
    assert "during the recess" in rendered
    assert "any state" in rendered


def test_a_proviso_keeps_the_word_provided() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "When vacancies happen in the representation of any State in the Senate, the executive authority "
        "of such State shall issue writs of election to fill such vacancies: Provided, That the legislature "
        "of any State may empower the executive thereof to make temporary appointments until the people fill "
        "the vacancies by election as the legislature may direct."
    )
    rendered = compile_span(AutoformalSession(), text, "proviso", allow_partial=True)["decompiled"].lower()
    assert "writs of election" in rendered
    assert "provided, that the legislature" in rendered
    assert "temporary appointments" in rendered


def test_an_equal_number_of_votes_goes_to_the_house() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "And if there be more than one who have such Majority, and have an equal Number of Votes, "
        "then the House of Representatives shall immediately chuse by Ballot one of them for President."
    )
    rendered = compile_span(AutoformalSession(), text, "equal-votes", allow_partial=True)["decompiled"].lower()
    assert "equal number of votes" in rendered
    assert "house of representatives" in rendered
    assert "chuse" in rendered or "choose" in rendered


def test_the_president_transmits_that_no_inability_exists() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "Thereafter, when the President transmits to the President pro tempore of the Senate and the "
        "Speaker of the House of Representatives his written declaration that no inability exists, he "
        "shall resume the powers and duties of his office unless the Vice President and a majority of "
        "either the principal officers of the executive department or of such other body as Congress may "
        "by law provide, transmit within four days to the President pro tempore of the Senate and the "
        "Speaker of the House of Representatives their written declaration that the President is unable "
        "to discharge the powers and duties of his office."
    )
    rendered = compile_span(AutoformalSession(), text, "resume", allow_partial=True)["decompiled"].lower()
    assert "thereafter" in rendered
    assert "transmits" in rendered
    assert "no inability exists" in rendered
    assert "transmit within four days" in rendered
    assert "resume" in rendered


def test_vesting_is_not_a_recipient_and_writs_are_not_a_procedure() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    vested = compile_span(
        AutoformalSession(),
        "All legislative Powers herein granted shall be vested in a Congress of the United States, "
        "which shall consist of a Senate and House of Representatives.",
        "vest",
    )
    assert vested["compiler_status"] == "compiled"
    assert "recipient" not in vested.get("fields", [])
    assert "congress" in vested["decompiled"].lower()
    writs = compile_span(
        AutoformalSession(),
        "When vacancies happen in the Representation from any State, the Executive Authority thereof "
        "shall issue Writs of Election to fill such Vacancies.",
        "writs",
    )
    assert writs["compiler_status"] == "compiled"
    assert "procedure" not in writs.get("fields", [])
    clerk = compile_span(
        AutoformalSession(),
        "The officer shall give the file to the clerk.",
        "clerk",
    )
    assert clerk["compiler_status"] == "abstain"
    assert "recipient" in clerk.get("fields", [])


def test_as_follows_introduces_the_electors() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "He shall hold his Office during the Term of four Years, and, together with the Vice "
        "President, chosen for the same Term, be elected, as follows Each State shall appoint "
        "a Number of Electors."
    )
    rendered = compile_span(AutoformalSession(), text, "as-follows", allow_partial=True)["decompiled"].lower()
    assert "be elected, as follows" in rendered or "be elected as follows" in rendered
    assert "appoint" in rendered
    assert "electors" in rendered


def test_otherwise_the_president_resumes() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The Vice President shall continue to discharge the same as Acting President; "
        "otherwise, the President shall resume the powers and duties of his office."
    )
    rendered = compile_span(AutoformalSession(), text, "otherwise", allow_partial=True)["decompiled"].lower()
    assert "acting president" in rendered
    assert "otherwise" in rendered
    assert "resume" in rendered


def test_raising_armies_keeps_the_two_year_appropriation() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "To raise and support Armies, but no Appropriation of Money to that Use shall be for a "
        "longer Term than two Years."
    )
    rendered = compile_span(AutoformalSession(), text, "armies", allow_partial=True)["decompiled"].lower()
    assert "raise and support armies" in rendered
    assert "appropriation of money" in rendered
    assert "two years" in rendered
    assert "must not" in rendered


def test_article_five_provisos_are_prohibitions() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "Provided that no Amendment which may be made prior to the Year One thousand eight hundred "
        "and eight shall in any Manner affect the first and fourth Clauses in the Ninth Section of "
        "the first Article; and that no State, without its Consent, shall be deprived of its equal "
        "Suffrage in the Senate."
    )
    rendered = compile_span(AutoformalSession(), text, "article-five-proviso", allow_partial=True)["decompiled"].lower()
    assert "provided that" in rendered
    assert "must not" in rendered
    assert "affect" in rendered
    assert "first and fourth" in rendered
    assert "equal suffrage" in rendered
    assert "without its consent" in rendered
    assert "must be deprived" not in rendered


def test_migration_or_importation_is_not_only_importation() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The Migration or Importation of such Persons as any of the States now existing shall think "
        "proper to admit, shall not be prohibited by the Congress prior to the Year one thousand eight "
        "hundred and eight, but a Tax or duty may be imposed on such Importation, not exceeding ten "
        "dollars for each Person."
    )
    rendered = compile_span(AutoformalSession(), text, "migration", allow_partial=True)["decompiled"].lower()
    assert "migration" in rendered
    assert "importation" in rendered
    assert "must not" in rendered
    assert "prohibited" in rendered
    assert "eight hundred" in rendered
    assert "ten dollars" in rendered
    assert "think proper to admit" in rendered
    assert "states now existing" in rendered


def test_suits_at_common_law_keep_the_forum() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "In Suits at common law, where the value in controversy shall exceed twenty dollars, the right "
        "of trial by jury shall be preserved, and no fact tried by a jury, shall be otherwise re-examined "
        "in any Court of the United States, than according to the rules of the common law."
    )
    rendered = compile_span(AutoformalSession(), text, "suits", allow_partial=True)["decompiled"].lower()
    assert "suits" in rendered
    assert "common law" in rendered
    assert "twenty dollars" in rendered
    assert "jury" in rendered
    assert "re-examined" in rendered or "reexamined" in rendered


def test_the_house_deadline_keeps_the_fourth_of_march() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "And if the House of Representatives shall not choose a President whenever the right of choice "
        "shall devolve upon them, before the fourth day of March next following, then the Vice-President "
        "shall act as President, as in the case of the death or other constitutional disability of the President."
    )
    rendered = compile_span(AutoformalSession(), text, "march", allow_partial=True)["decompiled"].lower()
    assert "vice-president" in rendered or "vice president" in rendered
    assert "before the fourth day of march" in rendered
    assert "act as president" in rendered


def test_a_denied_vote_reduces_the_basis_of_representation() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "But when the right to vote at any election for the choice of electors for President and "
        "Vice-President of the United States, Representatives in Congress, the Executive and Judicial "
        "officers of a State, or the members of the Legislature thereof, is denied to any of the male "
        "inhabitants of such State, being twenty-one years of age, and citizens of the United States, or "
        "in any way abridged, except for participation in rebellion, or other crime, the basis of "
        "representation therein shall be reduced in the proportion which the number of such male citizens "
        "shall bear to the whole number of male citizens twenty-one years of age in such State."
    )
    rendered = compile_span(AutoformalSession(), text, "apportion", allow_partial=True)["decompiled"].lower()
    assert "basis of representation" in rendered
    assert "reduced" in rendered
    assert "representatives in congress" in rendered
    assert "executive and judicial" in rendered
    assert "legislature" in rendered
    assert "denied" in rendered
    assert "twenty-one" in rendered


def test_neither_the_united_states_nor_any_state_is_the_debtor() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "But neither the United States nor any State shall assume or pay any debt or obligation "
        "incurred in aid of insurrection or rebellion against the United States, or any claim for "
        "the loss or emancipation of any slave; but all such debts, obligations and claims shall "
        "be held illegal and void."
    )
    rendered = compile_span(AutoformalSession(), text, "debts", allow_partial=True)["decompiled"].lower()
    assert "neither the united states nor any state" in rendered
    assert "must not" in rendered
    assert "insurrection" in rendered
    assert "illegal and void" in rendered


def test_a_pocket_veto_keeps_the_case_where_it_is_not_a_law() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "If any Bill shall not be returned by the President within ten Days (Sundays excepted) "
        "after it shall have been presented to him, the Same shall be a Law, in like Manner as if "
        "he had signed it, unless the Congress by their Adjournment prevent its Return, in which "
        "Case it shall not be a Law."
    )
    rendered = compile_span(AutoformalSession(), text, "pocket", allow_partial=True)["decompiled"].lower()
    assert "ten days" in rendered
    assert "be a law" in rendered
    assert "in which case" in rendered
    assert "shall not be a law" in rendered
    assert rendered.count("unless") == 1


def test_ratification_keeps_as_provided_in_the_constitution() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "This article shall be inoperative unless it shall have been ratified as an amendment to "
        "the Constitution by conventions in the several States, as provided in the Constitution, "
        "within seven years from the date of the submission hereof to the States by the Congress."
    )
    rendered = compile_span(AutoformalSession(), text, "ratify-21", allow_partial=True)["decompiled"].lower()
    assert "inoperative" in rendered
    assert "as provided in the constitution" in rendered
    assert "within seven years" in rendered


def test_election_regulations_keep_except_as_to_the_places() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The Times, Places and Manner of holding Elections for Senators and Representatives, "
        "shall be prescribed in each State by the Legislature thereof; but the Congress may at any "
        "time by Law make or alter such Regulations, except as to the Places of chusing Senators."
    )
    rendered = compile_span(AutoformalSession(), text, "elections", allow_partial=True)["decompiled"].lower()
    assert "prescribed" in rendered
    assert "except as to the places" in rendered
    assert "chusing" in rendered or "choosing" in rendered
    assert "unless as to the places" not in rendered


def test_in_case_of_removal_keeps_the_case_and_the_inability() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    removal = (
        "In case of the removal of the President from office or of his death or resignation, "
        "the Vice President shall become President."
    )
    rendered = compile_span(AutoformalSession(), removal, "case-25", allow_partial=True)["decompiled"].lower()
    assert "in case of the removal" in rendered
    assert "death" in rendered
    assert "resignation" in rendered
    assert "become president" in rendered
    devolve = (
        "In Case of the Removal of the President from Office, or of his Death, Resignation, or "
        "Inability to discharge the Powers and Duties of the said Office, the Same shall devolve "
        "on the Vice President."
    )
    rendered = compile_span(AutoformalSession(), devolve, "case-2", allow_partial=True)["decompiled"].lower()
    assert "in case of the removal" in rendered
    assert "inability" in rendered
    assert "discharge" in rendered
    assert "powers" in rendered
    assert "duties" in rendered
    assert "devolve" in rendered


def test_appellate_jurisdiction_keeps_the_regulations() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "In all the other Cases before mentioned, the supreme Court shall have appellate "
        "Jurisdiction, both as to Law and Fact, with such Exceptions, and under such Regulations "
        "as the Congress shall make."
    )
    rendered = compile_span(AutoformalSession(), text, "appellate", allow_partial=True)["decompiled"].lower()
    assert "appellate" in rendered
    assert "regulations" in rendered
    assert "exceptions" in rendered
    assert "congress must make" not in rendered


def test_conviction_keeps_without_the_concurrence() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "When the President of the United States is tried, the Chief Justice shall preside: "
        "And no Person shall be convicted without the Concurrence of two thirds of the Members present."
    )
    rendered = compile_span(AutoformalSession(), text, "convict", allow_partial=True)["decompiled"].lower()
    assert "chief justice" in rendered
    assert "must not" in rendered
    assert "convicted" in rendered
    assert "without the concurrence" in rendered
    assert "two thirds" in rendered
    assert "unless the concurrence" not in rendered


def test_neither_house_must_not_adjourn() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "Neither House, during the Session of Congress, shall, without the Consent of the other, "
        "adjourn for more than three days, nor to any other Place than that in which the two Houses "
        "shall be sitting."
    )
    rendered = compile_span(AutoformalSession(), text, "adjourn-neither", allow_partial=True)["decompiled"].lower()
    assert "must not" in rendered
    assert "adjourn" in rendered
    assert "three days" in rendered
    assert "without the consent" in rendered
    assert "unless the consent" not in rendered
    assert "other place" in rendered
    assert "must adjourn" not in rendered


def test_no_person_held_to_service_must_not_be_discharged() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "No Person held to Service or Labour in one State, under the Laws thereof, escaping into another, "
        "shall, in Consequence of any Law or Regulation therein, be discharged from such Service or Labour, "
        "but shall be delivered up on Claim of the Party to whom such Service or Labour may be due."
    )
    rendered = compile_span(AutoformalSession(), text, "service", allow_partial=True)["decompiled"].lower()
    assert "must not" in rendered
    assert "discharged" in rendered
    assert "delivered up" in rendered
    assert "must be discharged" not in rendered
    assert "consequence" in rendered or "regulation" in rendered


def test_electors_keep_the_senator_count_and_the_office_bar() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "He shall hold his Office during the Term of four Years, and, together with the Vice President, "
        "chosen for the same Term, be elected, as follows Each State shall appoint, in such Manner as the "
        "Legislature thereof may direct, a Number of Electors, equal to the whole Number of Senators and "
        "Representatives to which the State may be entitled in the Congress: but no Senator or Representative, "
        "or Person holding an Office of Trust or Profit under the United States, shall be appointed an Elector."
    )
    rendered = compile_span(AutoformalSession(), text, "electors-count", allow_partial=True)["decompiled"].lower()
    assert "four years" in rendered
    assert "appoint" in rendered
    assert "senators" in rendered
    assert "representatives" in rendered
    assert "trust" in rendered
    assert "profit" in rendered
    assert "must not" in rendered
    assert "appointed an elector" in rendered


def test_judicial_power_is_not_reduced_to_the_united_states() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The Judicial power of the United States shall not be construed to extend to any suit "
        "in law or equity, commenced or prosecuted against one of the United States by Citizens "
        "of another State, or by Citizens or Subjects of any Foreign State."
    )
    rendered = compile_span(AutoformalSession(), text, "amend-11", allow_partial=True)["decompiled"].lower()
    assert "judicial power" in rendered
    assert "must not be construed" in rendered
    assert "foreign state" in rendered


def test_a_majority_of_the_states_is_not_reduced_to_the_states() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "But in chusing the President, the Votes shall be taken by States, the Representation "
        "from each State having one Vote; A quorum for this Purpose shall consist of a Member "
        "or Members from two thirds of the States, and a Majority of all the States shall be "
        "necessary to a Choice."
    )
    rendered = compile_span(AutoformalSession(), text, "choice", allow_partial=True)["decompiled"].lower()
    assert "chusing" in rendered or "choosing" in rendered
    assert "president" in rendered
    assert "majority of all the states" in rendered
    assert "necessary to a choice" in rendered


def test_every_order_resolution_or_vote_is_presented() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "Every Order, Resolution, or Vote to which the Concurrence of the Senate and House of "
        "Representatives may be necessary (except on a question of Adjournment) shall be presented "
        "to the President of the United States; and before the Same shall take Effect, shall be "
        "approved by him, or being disapproved by him, shall be repassed by two thirds of the Senate "
        "and House of Representatives, according to the Rules and Limitations prescribed in the Case of a Bill."
    )
    rendered = compile_span(AutoformalSession(), text, "order", allow_partial=True)["decompiled"].lower()
    assert "order" in rendered
    assert "resolution" in rendered
    assert "vote" in rendered
    assert "presented" in rendered
    assert "adjournment" in rendered
    assert "concurrence" in rendered
    assert "necessary" in rendered
    assert "before the same shall take effect" in rendered
    assert "approved" in rendered
    assert "disapproved" in rendered
    assert "repassed" in rendered
    assert "two thirds" in rendered


def test_the_oath_keeps_before_he_enters() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "Before he enter on the Execution of his Office, he shall take the following Oath or "
        'Affirmation:—"I do solemnly swear (or affirm) that I will faithfully execute the Office '
        "of President of the United States, and will to the best of my Ability, preserve, protect "
        'and defend the Constitution of the United States."'
    )
    rendered = compile_span(AutoformalSession(), text, "oath", allow_partial=True)["decompiled"].lower()
    assert "oath" in rendered
    assert "before" in rendered
    assert "execution" in rendered
    assert "preserve" in rendered


def test_in_every_case_stays_on_the_duty() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "In every Case, after the Choice of the President, the Person having the greatest "
        "Number of Votes of the Electors shall be the Vice President."
    )
    rendered = compile_span(AutoformalSession(), text, "vice-president", allow_partial=True)["decompiled"].lower()
    assert "vice president" in rendered
    assert "electors" in rendered
    assert "choice" in rendered
    assert "every case" in rendered


def test_no_capitation_stays_a_prohibition() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "No Capitation, or other direct, Tax shall be laid, unless in Proportion to the Census "
        "or enumeration herein before directed to be taken."
    )
    rendered = compile_span(AutoformalSession(), text, "capitation", allow_partial=True)["decompiled"].lower()
    assert "capitation" in rendered
    assert "direct" in rendered
    assert "must not" in rendered
    assert "must be laid" not in rendered
    assert "census" in rendered


def test_a_manner_as_they_shall_stays_on_the_enumeration() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "The actual Enumeration shall be made within three Years after the first Meeting of the "
        "Congress of the United States, and within every subsequent Term of ten Years, in such "
        "Manner as they shall by Law direct."
    )
    rendered = compile_span(AutoformalSession(), text, "enumeration", allow_partial=True)["decompiled"].lower()
    assert "three years" in rendered
    assert "ten years" in rendered
    assert "manner" in rendered
    assert "direct" in rendered


def test_a_without_consent_list_keeps_the_earlier_verbs() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "No State shall, without the Consent of Congress, lay any Duty of Tonnage, keep Troops, "
        "or Ships of War in time of Peace, enter into any Agreement or Compact with another State, "
        "or with a foreign Power, or engage in War, unless actually invaded, or in such imminent "
        "Danger as will not admit of delay."
    )
    rendered = compile_span(AutoformalSession(), text, "tonnage", allow_partial=True)["decompiled"].lower()
    assert "tonnage" in rendered
    assert "troops" in rendered
    assert "ships" in rendered
    assert "consent" in rendered
    assert "engage" in rendered
    assert "invaded" in rendered


def test_a_semicolon_or_continuation_keeps_speech_and_press() -> None:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

    text = (
        "Congress shall make no law respecting an establishment of religion, "
        "or prohibiting the free exercise thereof; or abridging the freedom of speech, "
        "or of the press."
    )
    out = compile_span(AutoformalSession(), text, "amend-speech", allow_partial=True)
    assert "speech" in out["decompiled"].lower()
    assert "press" in out["decompiled"].lower()


def test_the_first_amendment_source_drops_speech_when_only_religion_is_decompiled() -> None:
    from ipfs_datasets_py.logic.autoformal.ontology_capture import dropped_clauses

    source = (
        "Congress shall make no law respecting an establishment of religion, "
        "or prohibiting the free exercise thereof; or abridging the freedom of speech, "
        "or of the press; or the right of the people peaceably to assemble, "
        "and to petition the Government for a redress of grievances."
    )
    decompiled = (
        "Congress must make no law respecting an establishment of religion "
        "or prohibiting the free exercise thereof."
    )
    missing = dropped_clauses(source, decompiled)
    assert "speech" in missing
    assert "press" in missing
    assert "religion" not in missing


def test_coordinated_objects_must_survive_and_a_dropped_one_fails() -> None:
    from ipfs_datasets_py.logic.autoformal.ontology_capture import dropped_clauses

    source = "The agency shall not disclose records or files."
    assert dropped_clauses(source, "Agency must not disclose records or files.") == []
    assert "files" in dropped_clauses(source, "Agency must not disclose records.")
    sanitation = sanitize_fixture(source, must_contain=["records", "files"], only_fields=[])
    assert sanitation["passed"] is True
    assert "dropped_clause" not in sanitation["reasons"]


def test_an_unfinished_autoencoder_pass_is_not_projected() -> None:
    from ipfs_datasets_py.logic.autoformal.ontology_capture import project_finished_document

    spans = [{"id": "a", "text": "Company A shall submit backup report within 10 days unless emergency."}, {"id": "b", "text": "next"}]
    projected = project_finished_document(spans, [{"sample_id": "a", "triples": [], "recipient": {}, "admitted": False}])
    assert projected["finished"] is False
    assert projected["formalized"] is False
    assert projected["rows"] == []
    assert projected["missing"] == ["b"]


def test_a_finished_capture_is_projected_and_the_compiler_still_decides() -> None:
    from ipfs_datasets_py.logic.autoformal.ontology_capture import project_finished_document

    text = "Company A shall submit backup report within 10 days unless emergency."
    capture = ontology_record(
        sample_id="backup",
        text=text,
        triples=[
            {"subject": "backup", "predicate": "actor", "object": "Company A"},
            {"subject": "backup", "predicate": "action", "object": "submit"},
            {"subject": "backup", "predicate": "object", "object": "backup report"},
            {"subject": "backup", "predicate": "type", "object": "obligation"},
        ],
    )
    projected = project_finished_document([{"id": "backup", "text": text}], [capture])
    assert projected["finished"] is True
    assert projected["formalized"] is False
    assert projected["admitted"] is False
    assert projected["rows"][0]["compiler_status"] == "compiled"
    assert "10 days" in projected["rows"][0]["decompiled"]
    assert "emergency" in projected["rows"][0]["decompiled"]
    assert projected["rows"][0]["roundtrip_ok"] is True
    assert projected["document_complete"] is True


def test_record_without_a_surface_is_not_an_admit() -> None:
    record = ontology_record(sample_id="x", text="hello", triples=[])
    assert record["admitted"] is False
    assert record["recipient"]["sort_id"] == ""
