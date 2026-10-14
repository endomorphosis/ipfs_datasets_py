"""Source custody tests use exact bytes and independently pinned fixture digests."""
import copy
import hashlib
import unittest

from ipfs_datasets_py.logic.autoformal.corpus_contracts import CorpusContractError, seal_record
from ipfs_datasets_py.logic.autoformal.corpus_source import (
    COORDINATE_SYSTEM,
    build_context_declaration,
    build_source_occurrence,
    build_source_version,
    validate_context_declaration,
    validate_source_occurrence,
    validate_source_version,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes


def digest(value):
    return hashlib.sha256(value).hexdigest()


def reseal(record):
    return seal_record({key: copy.deepcopy(value) for key, value in record.items()
                        if key not in ("record_cid", "cid_scope")})


class SourceCorpusTests(unittest.TestCase):
    def setUp(self):
        self.raw = b"<p>Clerk &amp; Clerk.</p>"
        self.text = "§ Café Clerk — Clerk."
        self.raw_sha = digest(self.raw)
        self.text_sha = digest(self.text.encode("utf-8"))
        self.version_arguments = dict(
            source_id="uscode/title-1/section-2", release_id="2024-01-01",
            edition="2024", provision_id="1 USC 2(a)", raw_bytes=self.raw,
            expected_raw_sha256=self.raw_sha, extracted_text=self.text,
            expected_extracted_sha256=self.text_sha, extraction_profile="fixture-html/v1",
            normalization_profile="visible-text/v1", media_type="text/html",
        )
        self.version = build_source_version(**self.version_arguments)

    def validate_version(self, record, **overrides):
        arguments = dict(expected_raw_sha256=self.raw_sha, extracted_text=self.text,
                         expected_extracted_sha256=self.text_sha)
        arguments.update(overrides)
        return validate_source_version(record, **arguments)

    def occurrence(self, start=None, end=None, **overrides):
        start = self.text.index("Clerk") if start is None else start
        end = start + len("Clerk") if end is None else end
        arguments = dict(expected_raw_sha256=self.raw_sha, extracted_text=self.text,
            expected_extracted_sha256=self.text_sha, start_char=start, end_char=end,
            start_utf8=len(self.text[:start].encode("utf-8")),
            end_utf8=len(self.text[:end].encode("utf-8")))
        arguments.update(overrides)
        return build_source_occurrence(self.version, **arguments)

    def validate_occurrence(self, record, **overrides):
        arguments = dict(source_version=self.version, expected_raw_sha256=self.raw_sha,
                         extracted_text=self.text, expected_extracted_sha256=self.text_sha)
        arguments.update(overrides)
        return validate_source_occurrence(record, **arguments)

    def test_exact_unicode_view_and_distinct_repeated_occurrences(self):
        first = self.occurrence()
        second = self.occurrence(self.text.rindex("Clerk"))
        self.assertEqual(first["span_text"], second["span_text"])
        self.assertEqual(first["span_cid"], second["span_cid"])
        self.assertNotEqual(first["record_cid"], second["record_cid"])
        self.assertNotEqual(first["start_utf8"], first["start_char"])
        self.assertEqual(self.validate_occurrence(second), second)
        self.assertEqual(first["coordinate_system"], COORDINATE_SYSTEM)
        self.assertNotIn("raw_offsets", first)

    def test_source_identity_changes_with_edition_scope_and_profiles(self):
        for field, replacement in (("edition", "2025"), ("release_id", "2025-01-01"),
                                   ("provision_id", "1 USC 2(b)"),
                                   ("normalization_profile", "other-normalization/v1")):
            with self.subTest(field=field):
                arguments = dict(self.version_arguments, **{field: replacement})
                other = build_source_version(**arguments)
                self.assertNotEqual(other["record_cid"], self.version["record_cid"])
                with self.assertRaises(CorpusContractError):
                    self.validate_occurrence(self.occurrence(), source_version=other)

    def test_raw_digest_and_cid_must_agree_without_raw_retrieval(self):
        altered = copy.deepcopy(self.version)
        altered["raw_artifact"]["cid"] = cid_for_bytes(b"another artifact")
        with self.assertRaises(CorpusContractError):
            self.validate_version(reseal(altered))
        self.assertEqual(self.validate_version(self.version), self.version)
        with self.assertRaises(CorpusContractError):
            self.validate_version(self.version, raw_bytes=b"stale artifact")

    def test_independently_expected_source_hashes_are_required(self):
        with self.assertRaises(CorpusContractError):
            self.validate_version(self.version, expected_raw_sha256=digest(b"different"))
        with self.assertRaises(CorpusContractError):
            self.validate_version(self.version, expected_extracted_sha256=digest(b"different"))
        with self.assertRaises(CorpusContractError):
            self.validate_version(self.version, extracted_text=self.text + " changed")
        with self.assertRaises(TypeError):
            validate_source_version(self.version, extracted_text=self.text)

    def test_constructor_refuses_stale_source_digest(self):
        with self.assertRaises(CorpusContractError):
            build_source_version(**dict(self.version_arguments, expected_raw_sha256=digest(b"old")))
        with self.assertRaises(CorpusContractError):
            build_source_version(**dict(self.version_arguments, expected_extracted_sha256=digest(b"old")))

    def test_resealed_view_mismatch_is_refused(self):
        for field, replacement in (("cid", cid_for_bytes(b"different")), ("byte_length", 1),
                                   ("character_length", 1), ("coordinate_system", "raw-html-bytes")):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.version)
                altered["extracted_view"][field] = replacement
                with self.assertRaises(CorpusContractError):
                    self.validate_version(reseal(altered))

    def test_unknown_fields_and_unsealed_parent_changes_fail(self):
        altered = copy.deepcopy(self.version)
        altered["edition"] = "tampered"
        with self.assertRaises(CorpusContractError):
            self.validate_version(altered)
        altered = copy.deepcopy(self.version)
        altered["guessed_scope"] = "chapter"
        with self.assertRaises(CorpusContractError):
            self.validate_version(reseal(altered))
        altered = self.occurrence()
        altered["raw_start_utf8"] = 0
        with self.assertRaises(CorpusContractError):
            self.validate_occurrence(reseal(altered))

    def test_boolean_empty_reversed_and_wrong_utf8_selectors_fail(self):
        first = self.occurrence()
        overrides = ({"start_char": True}, {"end_char": False},
                     {"start_utf8": True}, {"end_utf8": False},
                     {"end_char": first["start_char"]},
                     {"end_char": first["start_char"] - 1},
                     {"end_char": len(self.text) + 1},
                     {"start_utf8": first["start_char"]},
                     {"end_utf8": first["end_utf8"] + 1})
        for override in overrides:
            with self.subTest(override=override), self.assertRaises(CorpusContractError):
                self.occurrence(**override)

    def test_resealed_text_and_misbound_parent_are_refused(self):
        first = self.occurrence()
        altered = copy.deepcopy(first)
        altered["span_text"] = "Clerk".lower()
        with self.assertRaises(CorpusContractError):
            self.validate_occurrence(reseal(altered))
        altered = copy.deepcopy(first)
        altered["source_version_cid"] = cid_for_bytes(b"raw-cannot-be-parent")
        with self.assertRaises(CorpusContractError):
            self.validate_occurrence(reseal(altered))

    def test_historical_ids_remain_declared_unresolved_or_unsupported(self):
        aliases = [
            {"alias_id": "old-span-001", "status": "unresolved", "reason": "archive join pending"},
            {"alias_id": "old-span-002", "status": "unsupported", "reason": "unknown old selector"},
        ]
        occurrence = self.occurrence(historical_aliases=aliases)
        aliases[0]["status"] = "declared_alias"
        self.assertEqual(occurrence["historical_aliases"][0]["status"], "unresolved")
        self.assertEqual(self.validate_occurrence(occurrence), occurrence)
        with self.assertRaises(CorpusContractError):
            self.occurrence(historical_aliases=[dict(aliases[0], status="automatically_resolved")])
        with self.assertRaises(CorpusContractError):
            self.occurrence(historical_aliases=[aliases[0], aliases[0]])

    def test_records_are_detached_from_inputs_and_validation_result(self):
        validated = self.validate_version(self.version)
        validated["raw_artifact"]["media_type"] = "changed"
        self.assertEqual(self.version["raw_artifact"]["media_type"], "text/html")

    def test_context_declares_no_requirement_without_guessing(self):
        target = self.occurrence()
        context = build_context_declaration(target, expected_occurrence_cid=target["record_cid"],
            availability="none_required", reason="caller declares a self-contained fixture")
        self.assertEqual(context["dependency_verification"], "declaration_only")
        self.assertEqual(context["context_references"], [])
        self.assertEqual(validate_context_declaration(context, source_occurrence=target,
            expected_occurrence_cid=target["record_cid"]), context)

    def test_missing_context_is_explicit_and_partial_refs_are_preserved(self):
        target = self.occurrence()
        references = [{"record_cid": self.version["record_cid"],
                       "record_kind": "source_version", "purpose": "list introduction"}]
        context = build_context_declaration(target, expected_occurrence_cid=target["record_cid"],
            availability="required_unavailable", reason="definition unavailable",
            context_references=references, missing_requirements=["enclosing definition"])
        references[0]["purpose"] = "mutated"
        self.assertEqual(context["availability"], "required_unavailable")
        self.assertEqual(context["context_references"][0]["purpose"], "list introduction")
        self.assertEqual(context["missing_requirements"], ["enclosing definition"])

    def test_context_state_constraints_and_independent_target_binding(self):
        target = self.occurrence()
        base = dict(expected_occurrence_cid=target["record_cid"], reason="explicit declaration")
        reference = {"record_cid": self.version["record_cid"], "record_kind": "source_version",
                     "purpose": "chapter context"}
        bad = [dict(availability="inferred"), dict(availability="declared_context"),
               dict(availability="none_required", context_references=[reference]),
               dict(availability="required_unavailable"),
               dict(availability="declared_context", context_references=[reference],
                    missing_requirements=["definition"])]
        for arguments in bad:
            with self.subTest(arguments=arguments), self.assertRaises(CorpusContractError):
                build_context_declaration(target, **base, **arguments)
        with self.assertRaises(CorpusContractError):
            build_context_declaration(target, expected_occurrence_cid=self.version["record_cid"],
                availability="none_required", reason="wrong target")

    def test_context_consumption_checks_both_seals_and_claim_limit(self):
        target = self.occurrence()
        context = build_context_declaration(target, expected_occurrence_cid=target["record_cid"],
            availability="declared_context", reason="caller-supplied context",
            context_references=[{"record_cid": self.version["record_cid"],
                                 "record_kind": "source_version", "purpose": "heading"}])
        altered = copy.deepcopy(context)
        altered["dependency_verification"] = "authenticated"
        with self.assertRaises(CorpusContractError):
            validate_context_declaration(reseal(altered), source_occurrence=target,
                expected_occurrence_cid=target["record_cid"])
        target["span_text"] = "tamper"
        with self.assertRaises(CorpusContractError):
            validate_context_declaration(context, source_occurrence=target,
                expected_occurrence_cid=target["record_cid"])


if __name__ == "__main__":
    unittest.main()
