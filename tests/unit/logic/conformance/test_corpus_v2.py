"""Unit tests for LogicConformanceCorpus@2 (LFP2-004).

Acceptance:

* Manifest is deterministic, schema-validated, source-licensed, and
  profile-specific.
* Rejects missing expected evidence or unbounded inputs.
* Covers positive, negative, ambiguous, adversarial, round-trip, witness,
  model, trace, attack, proof, and resource-limit fixture contracts.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.logic.conformance.corpus_v2 import (
    ALLOWED_AUTHORITIES,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_MAX_PAYLOAD_BYTES,
    FIXTURE_SCHEMA_VERSION,
    LOGIC_CONFORMANCE_CORPUS_INTERFACE,
    LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION,
    REQUIRED_FIXTURE_KINDS,
    ConformanceFixture,
    CorpusError,
    CorpusIntegrityError,
    ExpectedDisposition,
    ExpectedEvidence,
    FixtureKind,
    LabelDisposition,
    LogicConformanceCorpus,
    build_corpus,
    build_fixture,
    default_manifest_path,
    digest_bytes,
    digest_text,
    load_corpus,
    require_safe_relative_path,
    resolve_label_disposition,
    validate_corpus,
)
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY

FIXTURES_ROOT = (
    Path(__file__).resolve().parents[3] / "fixtures" / "logic_conformance_v2"
)
MANIFEST_PATH = FIXTURES_ROOT / "manifest.json"
KNOWN_SHA256_TEST_VECTORS = frozenset(
    {
        "abc",
        "message digest",
        "abcdefghijklmnopqrstuvwxyz",
        "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
    }
)


def _base_fixture_dict(**overrides: Any) -> dict[str, Any]:
    payload = "((p -> q) & p) -> q"
    record: dict[str, Any] = {
        "authority": "none",
        "expected_diagnostics": [],
        "expected_evidence": ["parse", "execute"],
        "fixture_id": "prop_positive_true",
        "kind": "positive",
        "path": "synthetic/propositional/true.prop",
        "content_digest": digest_text(payload),
        "size_bytes": len(payload.encode("utf-8")),
        "family_label": "propositional",
        "expected_disposition": "accept",
        "source": "project-authored synthetic fixture",
        "license": "CC0-1.0",
        "media_type": "text/plain",
        "notation": "canonical_text",
        "payload": payload,
        "profile": "classical",
        "schema_version": FIXTURE_SCHEMA_VERSION,
    }
    record.update(overrides)
    return record


def _base_manifest(fixtures: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "corpus_id": "test-corpus-v2",
        "version": "2.0.0",
        "interface": LOGIC_CONFORMANCE_CORPUS_INTERFACE,
        "schema_version": LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION,
        "max_payload_bytes": DEFAULT_MAX_PAYLOAD_BYTES,
        "max_fixtures": 64,
        "objective": "LFP2-G010",
        "task": "LFP2-004",
        "description": "unit test corpus v2",
        "fixtures": fixtures if fixtures is not None else [_base_fixture_dict()],
    }


# ---------------------------------------------------------------------------
# Frozen repository manifest
# ---------------------------------------------------------------------------


def test_default_manifest_path_matches_fixture_tree() -> None:
    assert default_manifest_path() == DEFAULT_MANIFEST_PATH
    assert MANIFEST_PATH.is_file()
    assert DEFAULT_MANIFEST_PATH.resolve() == MANIFEST_PATH.resolve()


def test_frozen_manifest_loads_and_covers_required_kinds() -> None:
    corpus = load_corpus(MANIFEST_PATH)
    assert corpus.interface == LOGIC_CONFORMANCE_CORPUS_INTERFACE
    assert corpus.schema_version == LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION
    assert corpus.task == "LFP2-004"
    assert corpus.objective == "LFP2-G010"
    assert corpus.max_payload_bytes == DEFAULT_MAX_PAYLOAD_BYTES
    assert REQUIRED_FIXTURE_KINDS <= corpus.covered_kinds()
    assert len(corpus) >= len(REQUIRED_FIXTURE_KINDS)
    assert corpus.covered_kinds() == REQUIRED_FIXTURE_KINDS

    validated = validate_corpus(corpus, require_all_kinds=True)
    assert validated is corpus


def test_frozen_manifest_is_deterministic_and_content_addressed() -> None:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    corpus = load_corpus(MANIFEST_PATH)
    rebuilt = LogicConformanceCorpus.from_dict(corpus.to_dict())
    assert rebuilt.content_digest() == corpus.content_digest()
    assert rebuilt.content_digest() == LogicConformanceCorpus.from_dict(raw).content_digest()

    assert len(raw["fixtures"]) == len(corpus)
    for record, fixture in zip(raw["fixtures"], corpus, strict=True):
        assert "payload" in record
        assert isinstance(fixture.payload, str)
        assert fixture.payload.strip()
        assert fixture.payload not in KNOWN_SHA256_TEST_VECTORS

        payload_bytes = fixture.payload.encode("utf-8")
        assert fixture.size_bytes == len(payload_bytes)
        assert fixture.size_bytes <= corpus.max_payload_bytes
        assert fixture.content_digest == digest_bytes(payload_bytes)

        digest_hex = fixture.content_digest.removeprefix("sha256:")
        assert digest_hex[:-1] != "0" * 63


def test_frozen_manifest_is_source_licensed_and_profile_specific() -> None:
    corpus = load_corpus(MANIFEST_PATH)
    for fixture in corpus:
        assert fixture.source.startswith("project-authored synthetic")
        assert fixture.license == "CC0-1.0"
        assert fixture.profile
        assert fixture.profile == fixture.profile.strip()
        assert fixture.authority in ALLOWED_AUTHORITIES
        assert fixture.expected_evidence
        for evidence in fixture.expected_evidence:
            assert isinstance(evidence, ExpectedEvidence)


def test_frozen_manifest_covers_expanded_fixture_contracts() -> None:
    corpus = load_corpus(MANIFEST_PATH)
    expected_ids = {
        FixtureKind.POSITIVE: "prop_positive_modus_ponens",
        FixtureKind.NEGATIVE: "fol_negative_unbound",
        FixtureKind.AMBIGUOUS: "modal_ambiguous_box",
        FixtureKind.ADVERSARIAL: "deontic_adversarial_confusable",
        FixtureKind.ROUND_TRIP: "temporal_round_trip_ltl_monitor",
        FixtureKind.WITNESS: "fol_witness_reflexive",
        FixtureKind.MODEL: "tla_model_counterexample",
        FixtureKind.TRACE: "concurrency_trace_interleaving",
        FixtureKind.ATTACK: "protocol_attack_interleaving",
        FixtureKind.PROOF: "hol_proof_identity",
        FixtureKind.RESOURCE_LIMIT: "parser_resource_limit_identity",
    }
    for kind, fixture_id in expected_ids.items():
        matches = corpus.by_kind(kind)
        assert len(matches) == 1
        assert matches[0].fixture_id == fixture_id

    positive = corpus.get("prop_positive_modus_ponens")
    assert "p -> q" in positive.payload
    assert ExpectedEvidence.PARSE in positive.expected_evidence

    negative = corpus.get("fol_negative_unbound")
    assert "forall x" in negative.payload
    assert negative.label_disposition is LabelDisposition.ALIAS
    assert negative.family_id == "first_order"

    round_trip = json.loads(corpus.get("temporal_round_trip_ltl_monitor").payload)
    assert round_trip["bound"] == 4
    assert round_trip["source"]["formula"] == "G(request -> F grant)"
    assert round_trip["translation"] == "ltl_to_bounded_monitor"
    assert ExpectedEvidence.ROUND_TRIP in corpus.get(
        "temporal_round_trip_ltl_monitor"
    ).expected_evidence
    assert ExpectedEvidence.TRANSLATE in corpus.get(
        "temporal_round_trip_ltl_monitor"
    ).expected_evidence

    witness = corpus.get("fol_witness_reflexive")
    assert "knows(x, x)" in witness.payload
    assert ExpectedEvidence.WITNESS in witness.expected_evidence

    model = json.loads(corpus.get("tla_model_counterexample").payload)
    assert model["trace"][0] == model["initial"]
    assert "safe" not in model["labels"][model["trace"][-1]]

    attack = json.loads(corpus.get("protocol_attack_interleaving").payload)
    assert attack["schedule"] == ["e1", "e2", "e3"]
    assert attack["happens_before"] == [["e1", "e2"], ["e2", "e3"]]
    assert ExpectedEvidence.ATTACK in corpus.get(
        "protocol_attack_interleaving"
    ).expected_evidence
    assert corpus.get("protocol_attack_interleaving").profile == "dolev_yao"

    proof = corpus.get("hol_proof_identity").payload
    assert "P -> P" in proof
    assert ExpectedEvidence.KERNEL in corpus.get("hol_proof_identity").expected_evidence

    resource = corpus.get("parser_resource_limit_identity")
    assert resource.payload == "p -> p"
    assert resource.profile == "classical_bounded"
    assert ExpectedEvidence.RESOURCE_BOUND in resource.expected_evidence
    assert resource.expected_diagnostics == ("LFP2.PARSE.RESOURCE_LIMIT",)


def test_frozen_manifest_resolves_labels_and_profiles() -> None:
    corpus = load_corpus(MANIFEST_PATH)
    prop = corpus.get("prop_positive_modus_ponens")
    assert prop.label_disposition is LabelDisposition.CANONICAL
    assert prop.profile == "classical"
    assert corpus.by_profile("classical")[0].fixture_id == prop.fixture_id

    fol = corpus.get("fol_negative_unbound")
    assert fol.label_disposition is LabelDisposition.ALIAS
    assert DEFAULT_REGISTRY.resolve("fol").family_id == "first_order"
    assert "closed_formula" in corpus.covered_profiles()


def test_frozen_manifest_round_trips_json() -> None:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    corpus = LogicConformanceCorpus.from_dict(raw)
    rebuilt = LogicConformanceCorpus.from_dict(corpus.to_dict())
    assert rebuilt.content_digest() == corpus.content_digest()
    assert [item.fixture_id for item in rebuilt] == [
        item.fixture_id for item in corpus
    ]


# ---------------------------------------------------------------------------
# Fail-closed rejection cases
# ---------------------------------------------------------------------------


def test_rejects_missing_digest() -> None:
    record = _base_fixture_dict()
    del record["content_digest"]
    del record["payload"]
    with pytest.raises(CorpusError, match="missing content_digest|missing digests"):
        ConformanceFixture.from_dict(record)


def test_rejects_missing_expected_evidence() -> None:
    record = _base_fixture_dict()
    del record["expected_evidence"]
    with pytest.raises(CorpusError, match="expected_evidence|missing expected evidence"):
        ConformanceFixture.from_dict(record)

    record = _base_fixture_dict(expected_evidence=[])
    with pytest.raises(CorpusError, match="expected_evidence|missing expected evidence"):
        ConformanceFixture.from_dict(record)


def test_rejects_missing_profile() -> None:
    record = _base_fixture_dict()
    del record["profile"]
    with pytest.raises(CorpusError, match="profile"):
        ConformanceFixture.from_dict(record)

    record = _base_fixture_dict(profile="")
    with pytest.raises(CorpusError, match="profile"):
        ConformanceFixture.from_dict(record)


def test_rejects_missing_source_or_license() -> None:
    record = _base_fixture_dict()
    del record["source"]
    with pytest.raises(CorpusError, match="source"):
        ConformanceFixture.from_dict(record)

    record = _base_fixture_dict()
    del record["license"]
    with pytest.raises(CorpusError, match="license"):
        ConformanceFixture.from_dict(record)


def test_rejects_duplicate_fixture_ids() -> None:
    first = _base_fixture_dict(fixture_id="dup_case")
    second = _base_fixture_dict(
        fixture_id="dup_case",
        path="synthetic/propositional/other.prop",
    )
    with pytest.raises(CorpusIntegrityError, match="duplicate fixture_id"):
        LogicConformanceCorpus.from_dict(_base_manifest([first, second]))


def test_rejects_unsafe_paths() -> None:
    unsafe_paths = [
        "../escape.prop",
        "/absolute/path.prop",
        "foo/../bar.prop",
        "foo\\bar.prop",
        "foo//bar.prop",
        "./relative.prop",
    ]
    for path in unsafe_paths:
        with pytest.raises(CorpusIntegrityError, match="unsafe path"):
            require_safe_relative_path(path)
        record = _base_fixture_dict(path=path)
        with pytest.raises(CorpusIntegrityError, match="unsafe path"):
            ConformanceFixture.from_dict(record)


def test_rejects_unbounded_payloads() -> None:
    oversized = DEFAULT_MAX_PAYLOAD_BYTES + 1
    record = _base_fixture_dict(
        payload="",
        content_digest=digest_text("external oversized formal fixture"),
        size_bytes=oversized,
    )
    with pytest.raises(CorpusIntegrityError, match="unbounded payload"):
        ConformanceFixture.from_dict(
            record, max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES
        )

    with pytest.raises(CorpusIntegrityError, match="unbounded payload"):
        build_fixture(
            fixture_id="too_big",
            kind="positive",
            path="synthetic/big.prop",
            family_label="propositional",
            expected_disposition="accept",
            expected_evidence=["parse"],
            source="project-authored synthetic fixture",
            license="CC0-1.0",
            profile="classical",
            content_digest=digest_text("external oversized formal fixture"),
            size_bytes=oversized,
            max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES,
        )


def test_rejects_unbounded_fixture_count() -> None:
    fixtures = [
        _base_fixture_dict(
            fixture_id=f"case_{index}",
            path=f"synthetic/propositional/case_{index}.prop",
        )
        for index in range(3)
    ]
    document = _base_manifest(fixtures)
    document["max_fixtures"] = 2
    with pytest.raises(CorpusIntegrityError, match="unbounded input|max_fixtures"):
        LogicConformanceCorpus.from_dict(document)


def test_rejects_fixture_without_expected_disposition() -> None:
    record = _base_fixture_dict()
    del record["expected_disposition"]
    with pytest.raises(
        CorpusError, match="expected_disposition|without expected disposition"
    ):
        ConformanceFixture.from_dict(record)


def test_rejects_payload_digest_mismatch() -> None:
    payload = "p & q"
    record = _base_fixture_dict(
        payload=payload,
        content_digest=digest_text("p | q"),
        size_bytes=len(payload.encode("utf-8")),
    )
    with pytest.raises(CorpusIntegrityError, match="content_digest"):
        ConformanceFixture.from_dict(record)


def test_rejects_unknown_evidence_id() -> None:
    record = _base_fixture_dict(expected_evidence=["parse", "not_a_real_evidence"])
    with pytest.raises(CorpusError, match="expected_evidence"):
        ConformanceFixture.from_dict(record)


def test_rejects_unknown_manifest_and_fixture_fields() -> None:
    document = _base_manifest()
    document["extra_field"] = True
    with pytest.raises(CorpusError, match="unknown manifest field"):
        LogicConformanceCorpus.from_dict(document)

    fixture = _base_fixture_dict(unexpected=1)
    with pytest.raises(CorpusError, match="unknown fixture field"):
        ConformanceFixture.from_dict(fixture)


# ---------------------------------------------------------------------------
# Builder / loader helpers
# ---------------------------------------------------------------------------


def test_resolve_label_disposition_canonical_alias_unknown() -> None:
    disposition, family_id = resolve_label_disposition("first_order")
    assert disposition is LabelDisposition.CANONICAL
    assert family_id == "first_order"

    disposition, family_id = resolve_label_disposition("FOL")
    assert disposition is LabelDisposition.ALIAS
    assert family_id == "first_order"

    disposition, family_id = resolve_label_disposition("typed_first_order")
    assert disposition is LabelDisposition.UNKNOWN
    assert family_id is None


def test_build_fixture_computes_digest_from_payload() -> None:
    payload = "p -> p"
    fixture = build_fixture(
        fixture_id="built_positive",
        kind="positive",
        path="synthetic/propositional/built.prop",
        family_label="propositional",
        expected_disposition="accept",
        expected_evidence=["parse"],
        source="project-authored synthetic fixture",
        license="CC0-1.0",
        profile="classical",
        payload=payload,
    )
    assert fixture.content_digest == digest_text(payload)
    assert fixture.size_bytes == len(payload.encode("utf-8"))
    assert fixture.kind is FixtureKind.POSITIVE
    assert fixture.expected_evidence == (ExpectedEvidence.PARSE,)


def test_build_and_validate_corpus_covers_all_kinds() -> None:
    fixtures = [
        build_fixture(
            fixture_id=f"kind_{kind.value}",
            kind=kind,
            path=f"synthetic/all/{kind.value}.txt",
            family_label="propositional",
            expected_disposition=(
                ExpectedDisposition.ACCEPT
                if kind is not FixtureKind.NEGATIVE
                else ExpectedDisposition.REJECT
            ),
            expected_evidence=["parse"],
            source="project-authored synthetic fixture",
            license="CC0-1.0",
            profile="classical",
            payload=f"case({kind.value})",
        )
        for kind in FixtureKind
    ]
    corpus = build_corpus(
        corpus_id="builder-corpus-v2",
        version="2.0.0",
        fixtures=fixtures,
        description="covers every kind",
    )
    validate_corpus(corpus, require_all_kinds=True)
    assert corpus.by_kind(FixtureKind.ATTACK)[0].fixture_id == "kind_attack"
    assert len(corpus.by_kind("resource_limit")) == 1


def test_load_corpus_missing_file() -> None:
    missing = Path("synthetic/missing/logic-conformance-v2-manifest.json")
    with pytest.raises(CorpusError, match="not found"):
        load_corpus(missing)


def test_load_corpus_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    path = Path("synthetic/invalid/logic-conformance-v2-manifest.json")
    monkeypatch.setattr(Path, "is_file", lambda self: self == path)
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda _self, **_kwargs: "{not-json",
    )
    with pytest.raises(CorpusError, match="valid JSON"):
        load_corpus(path)


def test_digest_helpers_are_stable() -> None:
    assert digest_text("p -> p") == (
        "sha256:bed07f9054ba55b5d5229a8cd31688238cba373aa51d453e431ece408a72ab28"
    )
    assert digest_bytes(b"forall x. p(x)") == (
        "sha256:4e0b28631ed4ba6bcf701f406d9136283d91c3b742e56cb5de467277e8b0ebd4"
    )


def test_corpus_get_and_iteration_order() -> None:
    corpus = load_corpus(MANIFEST_PATH)
    ids = [fixture.fixture_id for fixture in corpus]
    assert len(ids) == len(set(ids))
    assert corpus.get(ids[0]).fixture_id == ids[0]
    with pytest.raises(KeyError):
        corpus.get("does_not_exist")


def test_validate_corpus_from_mapping_copy_is_independent() -> None:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(raw)
    corpus = validate_corpus(mutated, require_all_kinds=True)
    mutated["fixtures"].clear()
    assert len(corpus) > 0
