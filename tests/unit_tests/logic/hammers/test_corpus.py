"""Tests for the content-addressed premise corpus and theorem manifest
(HAMMER-003).

These tests cover:
- Theorems can only be ingested against a *declared* :class:`CorpusSource`
  (``UndeclaredCorpusSourceError`` otherwise).
- Re-registering a ``corpus_id`` with different metadata is rejected
  (``CorpusSourceConflictError``); re-registering with identical metadata is
  an idempotent no-op.
- Every ingested :class:`TheoremEntry` carries theorem identity, source ITP,
  imports, a normalized-statement digest, license metadata, and a content
  digest/CID that is *derived*, never caller-supplied.
- Re-ingesting the same ``theorem_id`` with the same (even
  whitespace-different) statement is an idempotent no-op; re-ingesting it
  with a genuinely different statement, corpus, or ITP raises
  ``DuplicateTheoremIdentityError``.
- ``CorpusManifest.revision`` is a deterministic digest that changes if and
  only if manifest content changes, and is stable across independently
  constructed, content-identical manifests.
- ``to_dict``/``from_dict`` (and ``to_json``/``from_json``/``save``/``load``)
  round-trip a manifest without losing any of the above guarantees.
- ``verify_hammer_result_corpus`` ties a ``HammerResult`` to a specific
  corpus manifest snapshot: it accepts a result whose ``corpus_revision``
  (and its premises') matches the manifest and whose premises all exist in
  it, and rejects revision mismatches and missing premises.
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.hammers.corpus import (
    CorpusManifest,
    CorpusRevisionMismatchError,
    CorpusSource,
    CorpusSourceConflictError,
    DuplicateTheoremIdentityError,
    TheoremEntry,
    UndeclaredCorpusSourceError,
    compute_content_digest,
    compute_statement_digest,
    normalize_statement,
    verify_hammer_result_corpus,
)
from ipfs_datasets_py.logic.hammers.models import (
    HammerPolicy,
    HammerRequest,
    HammerResult,
    HammerResultStatus,
    ITPKind,
    PremiseRecord,
)

MATHLIB_STATEMENT = "forall a b : Nat, a + b = b + a"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_source(**overrides) -> CorpusSource:
    defaults = dict(
        corpus_id="mathlib4",
        name="Mathlib4",
        source_itp=ITPKind.LEAN,
        version_ref="abcdef1234567890",
        license_id="Apache-2.0",
        license_url="https://github.com/leanprover-community/mathlib4/blob/master/LICENSE",
    )
    defaults.update(overrides)
    return CorpusSource(**defaults)


def make_manifest_with_source(**source_overrides) -> CorpusManifest:
    manifest = CorpusManifest(manifest_id="itp-hammer-corpus")
    manifest.register_source(make_source(**source_overrides))
    return manifest


# ---------------------------------------------------------------------------
# normalize_statement / compute_statement_digest
# ---------------------------------------------------------------------------


class TestNormalizeStatement:
    def test_collapses_whitespace_and_blank_lines(self):
        raw = "forall a b : Nat,\r\n\n  a  +  b   = b + a  \n\n"
        normalized = normalize_statement(raw)
        assert normalized == "forall a b : Nat,\na + b = b + a"

    def test_unicode_nfc_normalization(self):
        # "e" + combining acute accent vs precomposed "é" should normalize
        # to the same string.
        decomposed = "th\u0065\u0301orem"
        precomposed = "th\u00e9orem"
        assert normalize_statement(decomposed) == normalize_statement(precomposed)

    def test_rejects_empty_statement(self):
        with pytest.raises(ValueError, match="non-empty"):
            normalize_statement("   \n  ")

    def test_rejects_non_string(self):
        with pytest.raises(ValueError):
            normalize_statement(None)  # type: ignore[arg-type]


class TestComputeStatementDigest:
    def test_deterministic_for_identical_input(self):
        normalized = normalize_statement(MATHLIB_STATEMENT)
        assert compute_statement_digest(normalized) == compute_statement_digest(normalized)

    def test_differs_for_different_statements(self):
        d1 = compute_statement_digest(normalize_statement("a = a"))
        d2 = compute_statement_digest(normalize_statement("a = b"))
        assert d1 != d2

    def test_has_sha256_prefix(self):
        digest = compute_statement_digest(normalize_statement(MATHLIB_STATEMENT))
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64


class TestComputeContentDigest:
    def test_deterministic_regardless_of_key_order(self):
        d1 = compute_content_digest({"a": 1, "b": 2})
        d2 = compute_content_digest({"b": 2, "a": 1})
        assert d1 == d2

    def test_differs_for_different_payloads(self):
        d1 = compute_content_digest({"a": 1})
        d2 = compute_content_digest({"a": 2})
        assert d1 != d2

    def test_returns_nonempty_string(self):
        digest = compute_content_digest({"x": "y"})
        assert isinstance(digest, str) and digest


# ---------------------------------------------------------------------------
# CorpusSource
# ---------------------------------------------------------------------------


class TestCorpusSource:
    def test_valid_source_passes_validation(self):
        make_source().validate()

    def test_empty_corpus_id_rejected(self):
        with pytest.raises(ValueError, match="corpus_id"):
            make_source(corpus_id="").validate()

    def test_empty_license_id_rejected(self):
        with pytest.raises(ValueError, match="license_id"):
            make_source(license_id="").validate()

    def test_empty_version_ref_rejected(self):
        with pytest.raises(ValueError, match="version_ref"):
            make_source(version_ref="").validate()

    def test_non_itp_kind_rejected(self):
        with pytest.raises(ValueError, match="source_itp"):
            make_source(source_itp="lean").validate()  # type: ignore[arg-type]

    def test_to_dict_from_dict_round_trip(self):
        source = make_source()
        restored = CorpusSource.from_dict(source.to_dict())
        assert restored == source
        assert restored.source_itp is ITPKind.LEAN


# ---------------------------------------------------------------------------
# CorpusManifest.register_source
# ---------------------------------------------------------------------------


class TestRegisterSource:
    def test_registers_new_source(self):
        manifest = CorpusManifest(manifest_id="m1")
        registered = manifest.register_source(make_source())
        assert manifest.get_source("mathlib4") is registered

    def test_reregistering_identical_source_is_noop(self):
        manifest = make_manifest_with_source()
        manifest.register_source(make_source())  # should not raise
        assert len(manifest.sources) == 1

    def test_reregistering_conflicting_source_rejected(self):
        manifest = make_manifest_with_source()
        with pytest.raises(CorpusSourceConflictError):
            manifest.register_source(make_source(version_ref="different-ref"))

    def test_reregistering_with_different_license_rejected(self):
        manifest = make_manifest_with_source()
        with pytest.raises(CorpusSourceConflictError):
            manifest.register_source(make_source(license_id="MIT"))

    def test_get_source_missing_raises_keyerror(self):
        manifest = CorpusManifest(manifest_id="m1")
        with pytest.raises(KeyError):
            manifest.get_source("nope")


# ---------------------------------------------------------------------------
# CorpusManifest.add_theorem — declared-corpus enforcement
# ---------------------------------------------------------------------------


class TestAddTheoremDeclaredCorpusOnly:
    def test_ingest_against_undeclared_corpus_rejected(self):
        manifest = CorpusManifest(manifest_id="m1")
        with pytest.raises(UndeclaredCorpusSourceError):
            manifest.add_theorem(
                theorem_id="Nat.add_comm",
                corpus_id="mathlib4",
                statement=MATHLIB_STATEMENT,
            )

    def test_ingest_against_declared_corpus_succeeds(self):
        manifest = make_manifest_with_source()
        entry = manifest.add_theorem(
            theorem_id="Nat.add_comm",
            corpus_id="mathlib4",
            statement=MATHLIB_STATEMENT,
            imports=["Mathlib.Data.Nat.Basic"],
        )
        assert manifest.get_theorem("Nat.add_comm") is entry

    def test_explicit_source_itp_mismatch_rejected(self):
        manifest = make_manifest_with_source()  # registered as LEAN
        with pytest.raises(ValueError, match="source_itp"):
            manifest.add_theorem(
                theorem_id="Nat.add_comm",
                corpus_id="mathlib4",
                statement=MATHLIB_STATEMENT,
                source_itp=ITPKind.COQ,
            )


# ---------------------------------------------------------------------------
# TheoremEntry content — identity, imports, digests, license
# ---------------------------------------------------------------------------


class TestTheoremEntryContent:
    def test_entry_carries_identity_source_itp_and_imports(self):
        manifest = make_manifest_with_source()
        entry = manifest.add_theorem(
            theorem_id="Nat.add_comm",
            corpus_id="mathlib4",
            statement=MATHLIB_STATEMENT,
            imports=["Mathlib.Data.Nat.Basic", "Mathlib.Algebra.Group.Defs"],
        )
        assert entry.theorem_id == "Nat.add_comm"
        assert entry.corpus_id == "mathlib4"
        assert entry.source_itp is ITPKind.LEAN
        assert entry.imports == sorted(
            ["Mathlib.Data.Nat.Basic", "Mathlib.Algebra.Group.Defs"]
        )

    def test_imports_are_deduplicated(self):
        manifest = make_manifest_with_source()
        entry = manifest.add_theorem(
            theorem_id="Nat.add_comm",
            corpus_id="mathlib4",
            statement=MATHLIB_STATEMENT,
            imports=["A", "B", "A"],
        )
        assert entry.imports == ["A", "B"]

    def test_entry_carries_normalized_statement_digest(self):
        manifest = make_manifest_with_source()
        entry = manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        expected = compute_statement_digest(normalize_statement(MATHLIB_STATEMENT))
        assert entry.statement_digest == expected

    def test_entry_inherits_license_from_source_by_default(self):
        manifest = make_manifest_with_source(license_id="Apache-2.0")
        entry = manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        assert entry.license_id == "Apache-2.0"
        assert entry.license_url == make_source().license_url

    def test_entry_license_can_be_overridden_per_theorem(self):
        manifest = make_manifest_with_source(license_id="Apache-2.0")
        entry = manifest.add_theorem(
            theorem_id="Nat.add_comm",
            corpus_id="mathlib4",
            statement=MATHLIB_STATEMENT,
            license_id="MIT",
            license_url="https://opensource.org/license/mit/",
        )
        assert entry.license_id == "MIT"
        assert entry.license_url == "https://opensource.org/license/mit/"

    def test_entry_content_digest_is_derived_not_caller_supplied(self):
        manifest = make_manifest_with_source()
        entry = manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        assert entry.content_digest
        expected = compute_content_digest(entry._identity_payload())
        assert entry.content_digest == expected

    def test_content_digest_changes_when_statement_changes(self):
        manifest = make_manifest_with_source()
        entry1 = manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        manifest2 = make_manifest_with_source()
        entry2 = manifest2.add_theorem(
            theorem_id="Nat.add_comm",
            corpus_id="mathlib4",
            statement="forall a b : Nat, a * b = b * a",
        )
        assert entry1.content_digest != entry2.content_digest

    def test_theorem_entry_create_rejects_missing_license(self):
        with pytest.raises(ValueError, match="license_id"):
            TheoremEntry.create(
                theorem_id="x",
                corpus_id="mathlib4",
                source_itp=ITPKind.LEAN,
                statement=MATHLIB_STATEMENT,
                license_id="",
            )


# ---------------------------------------------------------------------------
# Duplicate identity rejection
# ---------------------------------------------------------------------------


class TestDuplicateIdentityRejection:
    def test_identical_statement_reingest_is_idempotent(self):
        manifest = make_manifest_with_source()
        entry1 = manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        entry2 = manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        assert entry1 is entry2
        assert len(manifest.entries) == 1

    def test_whitespace_only_difference_reingest_is_idempotent(self):
        manifest = make_manifest_with_source()
        entry1 = manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        entry2 = manifest.add_theorem(
            theorem_id="Nat.add_comm",
            corpus_id="mathlib4",
            statement="  forall a b : Nat,   a  +  b = b + a   ",
        )
        assert entry1.content_digest == entry2.content_digest
        assert len(manifest.entries) == 1

    def test_different_statement_same_identity_rejected(self):
        manifest = make_manifest_with_source()
        manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        with pytest.raises(DuplicateTheoremIdentityError):
            manifest.add_theorem(
                theorem_id="Nat.add_comm",
                corpus_id="mathlib4",
                statement="forall a b : Nat, a * b = b * a",
            )
        # The original entry must be preserved, not overwritten.
        assert manifest.get_theorem("Nat.add_comm").statement == MATHLIB_STATEMENT

    def test_different_corpus_same_identity_rejected(self):
        manifest = make_manifest_with_source()
        manifest.register_source(
            make_source(corpus_id="rocq-stdlib", name="Rocq stdlib", version_ref="ref2")
        )
        manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        with pytest.raises(DuplicateTheoremIdentityError):
            manifest.add_theorem(
                theorem_id="Nat.add_comm",
                corpus_id="rocq-stdlib",
                statement=MATHLIB_STATEMENT,
            )

    def test_different_itp_same_identity_rejected(self):
        manifest = make_manifest_with_source()
        manifest.register_source(
            make_source(
                corpus_id="afp",
                name="AFP",
                source_itp=ITPKind.ISABELLE,
                version_ref="ref3",
            )
        )
        manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        with pytest.raises(DuplicateTheoremIdentityError):
            manifest.add_theorem(
                theorem_id="Nat.add_comm",
                corpus_id="afp",
                statement=MATHLIB_STATEMENT,
                source_itp=ITPKind.ISABELLE,
            )


# ---------------------------------------------------------------------------
# Manifest revision
# ---------------------------------------------------------------------------


class TestManifestRevision:
    def test_revision_stable_for_identical_content(self):
        m1 = make_manifest_with_source()
        m1.add_theorem(theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT)

        m2 = make_manifest_with_source()
        m2.add_theorem(theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT)

        assert m1.revision == m2.revision

    def test_revision_changes_when_theorem_added(self):
        manifest = make_manifest_with_source()
        revision_before = manifest.revision
        manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        assert manifest.revision != revision_before

    def test_revision_unchanged_by_idempotent_reingest(self):
        manifest = make_manifest_with_source()
        manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        revision_before = manifest.revision
        manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        assert manifest.revision == revision_before

    def test_revision_independent_of_manifest_id(self):
        m1 = CorpusManifest(manifest_id="corpus-a")
        m1.register_source(make_source())
        m1.add_theorem(theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT)

        m2 = CorpusManifest(manifest_id="corpus-b")
        m2.register_source(make_source())
        m2.add_theorem(theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT)

        assert m1.revision == m2.revision


# ---------------------------------------------------------------------------
# Serialization round-trips
# ---------------------------------------------------------------------------


class TestSerializationRoundTrip:
    def _sample_manifest(self) -> CorpusManifest:
        manifest = make_manifest_with_source()
        manifest.add_theorem(
            theorem_id="Nat.add_comm",
            corpus_id="mathlib4",
            statement=MATHLIB_STATEMENT,
            imports=["Mathlib.Data.Nat.Basic"],
        )
        manifest.add_theorem(
            theorem_id="Nat.add_zero",
            corpus_id="mathlib4",
            statement="forall a : Nat, a + 0 = a",
        )
        return manifest

    def test_to_dict_from_dict_preserves_revision(self):
        manifest = self._sample_manifest()
        restored = CorpusManifest.from_dict(manifest.to_dict())
        assert restored.revision == manifest.revision
        assert set(restored.entries) == set(manifest.entries)
        assert set(restored.sources) == set(manifest.sources)

    def test_to_dict_includes_revision_key(self):
        manifest = self._sample_manifest()
        data = manifest.to_dict()
        assert data["revision"] == manifest.revision

    def test_to_json_from_json_round_trip(self):
        manifest = self._sample_manifest()
        text = manifest.to_json()
        parsed = json.loads(text)
        assert parsed["manifest_id"] == "itp-hammer-corpus"
        restored = CorpusManifest.from_json(text)
        assert restored.revision == manifest.revision

    def test_save_load_round_trip(self, tmp_path):
        manifest = self._sample_manifest()
        path = tmp_path / "corpus_manifest.json"
        manifest.save(str(path))
        restored = CorpusManifest.load(str(path))
        assert restored.revision == manifest.revision
        assert restored.get_theorem("Nat.add_comm").statement == MATHLIB_STATEMENT

    def test_from_dict_rejects_theorem_referencing_undeclared_corpus(self):
        manifest = self._sample_manifest()
        data = manifest.to_dict()
        data["sources"] = {}  # drop the declared source
        with pytest.raises(ValueError, match="undeclared"):
            CorpusManifest.from_dict(data)


# ---------------------------------------------------------------------------
# iter_theorems / theorems_for_corpus ordering
# ---------------------------------------------------------------------------


class TestIteration:
    def test_iter_theorems_sorted_by_id(self):
        manifest = make_manifest_with_source()
        manifest.add_theorem(theorem_id="Z.last", corpus_id="mathlib4", statement="z = z")
        manifest.add_theorem(theorem_id="A.first", corpus_id="mathlib4", statement="a = a")
        ids = [entry.theorem_id for entry in manifest.iter_theorems()]
        assert ids == ["A.first", "Z.last"]

    def test_theorems_for_corpus_filters_by_corpus(self):
        manifest = make_manifest_with_source()
        manifest.register_source(
            make_source(corpus_id="rocq-stdlib", name="Rocq stdlib", version_ref="ref2")
        )
        manifest.add_theorem(theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT)
        manifest.add_theorem(theorem_id="nat_add_comm", corpus_id="rocq-stdlib", statement=MATHLIB_STATEMENT)

        mathlib_ids = [e.theorem_id for e in manifest.theorems_for_corpus("mathlib4")]
        assert mathlib_ids == ["Nat.add_comm"]


# ---------------------------------------------------------------------------
# verify_hammer_result_corpus
# ---------------------------------------------------------------------------


def make_request(corpus_revision: str, **overrides) -> HammerRequest:
    defaults = dict(
        request_id="req-1",
        itp=ITPKind.LEAN,
        theorem_id="goal-1",
        goal_statement="forall a b : Nat, a + b = b + a",
        corpus_revision=corpus_revision,
        policy=HammerPolicy(),
    )
    defaults.update(overrides)
    return HammerRequest(**defaults)


class TestVerifyHammerResultCorpus:
    def _manifest_with_entry(self) -> CorpusManifest:
        manifest = make_manifest_with_source()
        manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        return manifest

    def test_accepts_matching_result(self):
        manifest = self._manifest_with_entry()
        request = make_request(manifest.revision)
        premise = PremiseRecord(
            premise_id="Nat.add_comm",
            statement=MATHLIB_STATEMENT,
            source_itp=ITPKind.LEAN,
            corpus_revision=manifest.revision,
            rank=0,
            score=1.0,
        )
        result = HammerResult(
            result_id="result-1",
            request=request,
            status=HammerResultStatus.UNKNOWN,
            corpus_revision=manifest.revision,
            premises=[premise],
        )
        verify_hammer_result_corpus(result, manifest)  # must not raise

    def test_rejects_result_revision_mismatch(self):
        manifest = self._manifest_with_entry()
        request = make_request("some-other-revision")
        result = HammerResult(
            result_id="result-1",
            request=request,
            status=HammerResultStatus.UNKNOWN,
            corpus_revision="some-other-revision",
        )
        with pytest.raises(CorpusRevisionMismatchError):
            verify_hammer_result_corpus(result, manifest)

    def test_rejects_premise_revision_mismatch(self):
        manifest = self._manifest_with_entry()
        request = make_request(manifest.revision)
        premise = PremiseRecord(
            premise_id="Nat.add_comm",
            statement=MATHLIB_STATEMENT,
            source_itp=ITPKind.LEAN,
            corpus_revision="stale-revision",
            rank=0,
            score=1.0,
        )
        result = HammerResult(
            result_id="result-1",
            request=request,
            status=HammerResultStatus.UNKNOWN,
            corpus_revision=manifest.revision,
            premises=[premise],
        )
        with pytest.raises(CorpusRevisionMismatchError):
            verify_hammer_result_corpus(result, manifest)

    def test_rejects_premise_not_in_manifest(self):
        manifest = self._manifest_with_entry()
        request = make_request(manifest.revision)
        premise = PremiseRecord(
            premise_id="Nat.does_not_exist",
            statement="bogus",
            source_itp=ITPKind.LEAN,
            corpus_revision=manifest.revision,
            rank=0,
            score=1.0,
        )
        result = HammerResult(
            result_id="result-1",
            request=request,
            status=HammerResultStatus.UNKNOWN,
            corpus_revision=manifest.revision,
            premises=[premise],
        )
        with pytest.raises(CorpusRevisionMismatchError):
            verify_hammer_result_corpus(result, manifest)


# ---------------------------------------------------------------------------
# CorpusManifest.validate() direct checks
# ---------------------------------------------------------------------------


class TestManifestValidate:
    def test_empty_manifest_id_rejected(self):
        with pytest.raises(ValueError, match="manifest_id"):
            CorpusManifest(manifest_id="").validate()

    def test_manifest_with_consistent_content_validates(self):
        manifest = make_manifest_with_source()
        manifest.add_theorem(
            theorem_id="Nat.add_comm", corpus_id="mathlib4", statement=MATHLIB_STATEMENT
        )
        manifest.validate()  # must not raise

    def test_get_theorem_missing_raises_keyerror(self):
        manifest = make_manifest_with_source()
        with pytest.raises(KeyError):
            manifest.get_theorem("nope")
