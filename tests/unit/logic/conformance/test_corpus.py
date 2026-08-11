"""Unit tests for LogicConformanceCorpus@1 (LFP-002).

Acceptance:

* Manifest rejects missing digests, duplicate IDs, unsafe paths, unbounded
  payloads, and fixtures without expected disposition.
* The frozen repository corpus is entirely inline and its byte sizes and
  SHA-256 digests are derived from meaningful, bounded logic payloads.
* Provenance, licensing, expected diagnostics, and evidence authority are
  explicit for every frozen fixture.
* Labels not yet known to the baseline registry are preserved losslessly with
  an explicit unknown disposition for LFP-003/LFP-010 closure.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.logic.conformance.corpus import (
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

FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "logic_conformance"
MANIFEST_PATH = FIXTURES_ROOT / "manifest.json"
KNOWN_SHA256_TEST_VECTORS = frozenset(
    {
        "abc",
        "message digest",
        "abcdefghijklmnopqrstuvwxyz",
        "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
    }
)
ALLOWED_AUTHORITIES = frozenset(
    {
        "none",
        "advisory",
        "bounded",
        "independently_checkable",
        "authoritative",
    }
)


def _base_fixture_dict(**overrides: Any) -> dict[str, Any]:
    payload = "((p -> q) & p) -> q"
    record: dict[str, Any] = {
        "authority": "none",
        "expected_diagnostics": [],
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
        "corpus_id": "test-corpus",
        "version": "1.0.0",
        "interface": LOGIC_CONFORMANCE_CORPUS_INTERFACE,
        "schema_version": LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION,
        "max_payload_bytes": DEFAULT_MAX_PAYLOAD_BYTES,
        "max_fixtures": 64,
        "objective": "LFP-G010",
        "task": "LFP-002",
        "description": "unit test corpus",
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
    assert corpus.task == "LFP-002"
    assert corpus.objective == "LFP-G010"
    assert corpus.max_payload_bytes == DEFAULT_MAX_PAYLOAD_BYTES
    assert REQUIRED_FIXTURE_KINDS <= corpus.covered_kinds()
    assert len(corpus) >= len(REQUIRED_FIXTURE_KINDS)

    validated = validate_corpus(corpus, require_all_kinds=True)
    assert validated is corpus


def test_frozen_manifest_payloads_are_inline_content_addressed_and_bounded() -> None:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    corpus = load_corpus(MANIFEST_PATH)

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


def test_frozen_manifest_has_explicit_provenance_and_expectations() -> None:
    corpus = load_corpus(MANIFEST_PATH)
    diagnostics_by_fixture = {
        "prop_positive_true": (),
        "fol_negative_unbound": ("LFP.PARSE.UNBOUND_VARIABLE",),
        "modal_ambiguous_box": ("LFP.PARSE.AMBIGUOUS_CONNECTIVE",),
        "deontic_adversarial_confusable": ("LFP.PARSE.ADVERSARIAL_INPUT",),
        "temporal_translation_ltl_to_monitor": (),
        "tla_model_counterexample": (),
        "hol_proof_identity": (),
        "concurrency_trace_interleaving": (),
        "unknown_label_typed_first_order": ("LFP.LABEL.UNKNOWN_FAMILY",),
        "unknown_label_workflow_temporal": ("LFP.LABEL.UNKNOWN_FAMILY",),
    }

    assert {fixture.fixture_id for fixture in corpus} == set(diagnostics_by_fixture)
    assert {fixture.expected_disposition for fixture in corpus} == set(
        ExpectedDisposition
    )
    for fixture in corpus:
        assert fixture.source.startswith("project-authored synthetic")
        assert fixture.license == "CC0-1.0"
        assert fixture.authority in ALLOWED_AUTHORITIES
        assert fixture.expected_diagnostics == diagnostics_by_fixture[
            fixture.fixture_id
        ]


def test_frozen_manifest_contains_meaningful_logic_artifacts() -> None:
    corpus = load_corpus(MANIFEST_PATH)

    positive = corpus.get("prop_positive_true")
    assert "p -> q" in positive.payload

    negative = corpus.get("fol_negative_unbound")
    assert "forall x" in negative.payload
    assert "knows(x, y)" in negative.payload

    ambiguous = corpus.get("modal_ambiguous_box")
    assert ambiguous.payload == "[] p -> q"

    adversarial = corpus.get("deontic_adversarial_confusable")
    assert "O(pay)" in adversarial.payload
    assert "\N{GREEK CAPITAL LETTER OMICRON}(not_pay)" in adversarial.payload

    translation = json.loads(
        corpus.get("temporal_translation_ltl_to_monitor").payload
    )
    assert translation["bound"] == 4
    assert translation["source"]["formula"] == "G(request -> F grant)"
    assert translation["target"]["accept_on_end"] == "no_pending_request"

    model = json.loads(corpus.get("tla_model_counterexample").payload)
    assert model["trace"][0] == model["initial"]
    assert model["transitions"] == [["s0", "s1"]]
    assert "safe" not in model["labels"][model["trace"][-1]]

    proof = corpus.get("hol_proof_identity").payload
    assert "P -> P" in proof
    assert proof.endswith("exact h")

    trace = json.loads(corpus.get("concurrency_trace_interleaving").payload)
    assert trace["schedule"] == ["e1", "e2", "e3"]
    assert trace["happens_before"] == [["e1", "e2"], ["e2", "e3"]]


def test_frozen_manifest_preserves_unknown_labels_losslessly() -> None:
    corpus = load_corpus(MANIFEST_PATH)
    unknown = corpus.unknown_labels()
    assert "typed_first_order" in unknown
    assert "workflow_temporal" in unknown

    typed = corpus.get("unknown_label_typed_first_order")
    assert typed.family_label == "typed_first_order"
    assert typed.label_disposition is LabelDisposition.UNKNOWN
    assert typed.family_id is None
    assert typed.expected_disposition is ExpectedDisposition.UNSUPPORTED

    workflow = corpus.get("unknown_label_workflow_temporal")
    assert workflow.family_label == "workflow_temporal"
    assert workflow.label_disposition is LabelDisposition.UNKNOWN
    assert workflow.family_id is None


def test_frozen_manifest_resolves_canonical_and_alias_labels() -> None:
    corpus = load_corpus(MANIFEST_PATH)
    prop = corpus.get("prop_positive_true")
    assert prop.label_disposition is LabelDisposition.CANONICAL
    assert prop.family_id == "propositional"
    assert prop.family_label == "propositional"

    fol = corpus.get("fol_negative_unbound")
    assert fol.label_disposition is LabelDisposition.ALIAS
    assert fol.family_id == "first_order"
    assert fol.family_label == "fol"
    assert DEFAULT_REGISTRY.resolve("fol").family_id == "first_order"


def test_frozen_manifest_round_trips_json() -> None:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    corpus = LogicConformanceCorpus.from_dict(raw)
    rebuilt = LogicConformanceCorpus.from_dict(corpus.to_dict())
    assert rebuilt.content_digest() == corpus.content_digest()
    assert [item.fixture_id for item in rebuilt] == [
        item.fixture_id for item in corpus
    ]


# ---------------------------------------------------------------------------
# Label disposition
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


def test_unknown_label_is_not_rewritten_by_build_fixture() -> None:
    fixture = build_fixture(
        fixture_id="unknown_drift_label",
        kind=FixtureKind.NEGATIVE,
        path="synthetic/unknown/drift.expr",
        family_label="graph_projection",
        expected_disposition=ExpectedDisposition.UNSUPPORTED,
        source="project-authored synthetic observed-label fixture",
        license="CC0-1.0",
        payload="forall node. reachable(node)",
    )
    assert fixture.family_label == "graph_projection"
    assert fixture.label_disposition is LabelDisposition.UNKNOWN
    assert fixture.family_id is None
    assert fixture.to_dict()["family_label"] == "graph_projection"


# ---------------------------------------------------------------------------
# Fail-closed rejection cases
# ---------------------------------------------------------------------------


def test_rejects_missing_digest() -> None:
    record = _base_fixture_dict()
    del record["content_digest"]
    del record["payload"]
    with pytest.raises(CorpusError, match="missing content_digest|missing digests"):
        ConformanceFixture.from_dict(record)


def test_rejects_duplicate_fixture_ids() -> None:
    first = _base_fixture_dict(fixture_id="dup_case")
    second = _base_fixture_dict(
        fixture_id="dup_case",
        path="synthetic/propositional/other.prop",
        family_label="propositional",
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
            source="project-authored synthetic fixture",
            license="CC0-1.0",
            content_digest=digest_text("external oversized formal fixture"),
            size_bytes=oversized,
            max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES,
        )


def test_rejects_fixture_without_expected_disposition() -> None:
    record = _base_fixture_dict()
    del record["expected_disposition"]
    with pytest.raises(
        CorpusError, match="expected_disposition|without expected disposition"
    ):
        ConformanceFixture.from_dict(record)

    record = _base_fixture_dict(expected_disposition="")
    with pytest.raises(
        CorpusError, match="expected_disposition|without expected disposition"
    ):
        ConformanceFixture.from_dict(record)


def test_rejects_unknown_label_with_invented_family_id() -> None:
    payload = "forall x:Person. knows(x, x)"
    record = _base_fixture_dict(
        fixture_id="bad_unknown",
        family_label="typed_first_order",
        family_id="first_order",
        label_disposition="unknown",
        path="synthetic/unknown/bad.expr",
        payload=payload,
        content_digest=digest_text(payload),
        size_bytes=len(payload.encode("utf-8")),
    )
    with pytest.raises(CorpusIntegrityError, match="must not invent"):
        ConformanceFixture.from_dict(record)


def test_rejects_claiming_canonical_for_unknown_label() -> None:
    payload = "after approve eventually archive"
    record = _base_fixture_dict(
        fixture_id="false_canonical",
        family_label="workflow_temporal",
        label_disposition="canonical",
        family_id="temporal",
        path="synthetic/unknown/false.expr",
        payload=payload,
        content_digest=digest_text(payload),
        size_bytes=len(payload.encode("utf-8")),
    )
    with pytest.raises(CorpusIntegrityError, match="unknown"):
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


# ---------------------------------------------------------------------------
# Builder / loader helpers
# ---------------------------------------------------------------------------


def test_build_fixture_computes_digest_from_payload() -> None:
    payload = "p -> p"
    fixture = build_fixture(
        fixture_id="built_positive",
        kind="positive",
        path="synthetic/propositional/built.prop",
        family_label="propositional",
        expected_disposition="accept",
        source="project-authored synthetic fixture",
        license="CC0-1.0",
        payload=payload,
        expected_diagnostics=(),
    )
    assert fixture.content_digest == digest_text(payload)
    assert fixture.size_bytes == len(payload.encode("utf-8"))
    assert fixture.kind is FixtureKind.POSITIVE


def test_build_and_validate_corpus() -> None:
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
            source="project-authored synthetic fixture",
            license="CC0-1.0",
            payload=f"case({kind.value})",
        )
        for kind in FixtureKind
    ]
    corpus = build_corpus(
        corpus_id="builder-corpus",
        version="1.0.0",
        fixtures=fixtures,
        description="covers every kind",
    )
    validate_corpus(corpus, require_all_kinds=True)
    assert corpus.by_kind(FixtureKind.PROOF)[0].fixture_id == "kind_proof"
    assert len(corpus.by_kind("trace")) == 1


def test_load_corpus_missing_file() -> None:
    missing = Path("synthetic/missing/logic-conformance-manifest.json")
    with pytest.raises(CorpusError, match="not found"):
        load_corpus(missing)


def test_load_corpus_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    path = Path("synthetic/invalid/logic-conformance-manifest.json")
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


def test_manifest_unknown_fields_rejected() -> None:
    document = _base_manifest()
    document["extra_field"] = True
    with pytest.raises(CorpusError, match="unknown manifest field"):
        LogicConformanceCorpus.from_dict(document)

    fixture = _base_fixture_dict(unexpected=1)
    with pytest.raises(CorpusError, match="unknown fixture field"):
        ConformanceFixture.from_dict(fixture)


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
