"""Duty-bearer and nested body are both actors, frames, and entities."""

from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
from ipfs_datasets_py.logic.autoformal.embedded_actor import (
    EmbeddedActorFixture,
    clause_actors,
)
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import classify_legal_entity


_VICE = (
    "In every Case, after the Choice of the President, the Person having the "
    "greatest Number of Votes of the Electors shall be the Vice President."
)
_HOUSE = "The House of Representatives shall chuse the President by Ballot."


def test_the_person_and_the_electors_are_both_actors() -> None:
    actors = clause_actors(_VICE)
    roles = {actor["role"]: actor["surface"] for actor in actors}
    assert roles["duty"].lower().startswith("person")
    assert "electors" in roles["embedded"].lower()
    rendered = compile_span(AutoformalSession(), _VICE, "vice", allow_partial=True)["decompiled"]
    assert "person" in rendered.lower()
    assert "vice president" in rendered.lower()
    assert not rendered.lower().startswith("electors")


def test_representatives_are_an_actor_beside_the_house() -> None:
    actors = clause_actors(_HOUSE)
    surfaces = [actor["surface"].lower() for actor in actors]
    assert any("house" in surface for surface in surfaces)
    assert any(surface == "representatives" for surface in surfaces)
    assert {actor["role"] for actor in actors} == {"duty", "embedded"}


def test_both_actors_are_flogic_frames_and_graph_entities() -> None:
    fixture = EmbeddedActorFixture()
    stored = fixture.put(span_id="vice", surface="Electors", sort_id="elector")
    assert stored["result"] == "yes"
    assert stored["admitted"] is False
    projected = fixture.project(_VICE, span_id="vice")
    assert projected["admitted"] is False
    frames = {frame.object_id: frame for frame in projected["flogic"].frames}
    assert "electors" in frames
    assert frames["electors"].isa == "elector"
    assert frames["electors"].scalar_methods["role"] == "embedded"
    duty = next(frame for frame in frames.values() if frame.scalar_methods.get("role") == "duty")
    assert "person" in duty.object_id
    assert duty.isa is None
    names = " ".join(str(node.properties.get("flogic_id") or "").lower() for node in projected["graph"].nodes)
    assert "electors" in names
    assert "person" in names
    predicates = {relationship.type.upper() for relationship in projected["graph"].relationships}
    assert any("ACTOR" in predicate for predicate in predicates)
    assert classify_legal_entity("Electors") != "elector"
    missing = EmbeddedActorFixture().project(_VICE, span_id="vice")
    electors = next(frame for frame in missing["flogic"].frames if frame.object_id == "electors")
    assert electors.isa is None
    assert electors.scalar_methods["role"] == "embedded"
    unmapped = fixture.slot(_VICE, span_id="other")
    assert unmapped["result"] == "abstain"
    assert fixture.repository._connection is None
