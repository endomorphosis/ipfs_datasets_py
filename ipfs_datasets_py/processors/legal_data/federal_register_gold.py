"""Sealed Federal Register retrieval/graph gold set loader and integrity seal (LCR-051).

This module owns the evaluator-facing gold labels for
``federal-register-ir-graphrag/v2``:

* temporally and agency-diverse document stubs;
* train/dev/test queries with relevance grades;
* agency / date / document-type filter expectations;
* citation and correction/withdrawal graph edges;
* hard negatives and missing-body cases;
* checksum / manifest-digest sealing.

It deliberately does **not** implement BM25, vector, hybrid, or metric
tuning. Downstream evaluators (LCR-063) load this sealed set read-only.

Design invariants
-----------------
* Labels are human-authored against official FR publication identity, not
  model relevance outputs.
* Every document carries ``legal_id`` (``fr:<document_number>:<date>``),
  ``entry_cid``, ``source_cid``, official URL, and ``source_checksum``.
* Missing-body dispositions never masquerade as full-text exact body hits.
* Hard negatives must not appear as exact gold judgments for the same query.
* Partitions are leak-free: query ids and query texts are partition-exclusive.
* The fixture is checksum-sealed: ``manifest_digest`` covers the sealed body
  excluding digest fields; tampering fails closed.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_OBSERVATION_CUTOFF,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    CorrectionRelation,
    DocumentType,
    TextAvailability,
    content_sha256,
    digest_mapping,
    normalize_sha256,
    validate_document_number,
    validate_legal_id,
    validate_official_url,
    validate_publication_date,
)

# ---------------------------------------------------------------------------
# Schema / fixture identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-gold-v1"
FIXTURE_ID: Final = "federal-register-gold-v1"
FIXTURE_FILENAME: Final = "federal_register_gold_v1.json"
TASK_ID: Final = "LCR-051"
GOAL_ID: Final = "LCR-G100"
PROGRAM_ID: Final = RELEASE_PROFILE

PARTITIONS: Final = ("train", "dev", "test")

REQUIRED_DOCUMENT_TYPES: Final = (
    "rule",
    "proposed_rule",
    "notice",
    "presidential_document",
    "correction",
)

REQUIRED_AGENCIES: Final = (
    "EPA",
    "HHS",
    "SEC",
    "DOT",
    "DOE",
    "DOL",
    "DOI",
    "DHS",
    "DOJ",
    "FCC",
    "EOP",
)

REQUIRED_QUERY_KINDS: Final = frozenset(
    {
        "exact_document_number",
        "agency_topic",
        "semantic",
        "lexical",
        "proposed_vs_final",
        "citation",
        "correction_path",
        "withdrawal_path",
        "presidential",
        "filter_agency",
        "filter_date",
        "filter_type",
        "time_sensitive",
        "missing_body",
        "hard_negative",
        "abstention",
    }
)

REQUIRED_LABEL_KINDS: Final = frozenset(
    {
        "exact_document",
        "relevant_document",
        "supporting_citation_path",
        "correction_relation",
        "withdrawal_relation",
        "agency_filter_match",
        "date_filter_match",
        "type_filter_match",
        "hard_negative",
        "missing_body",
        "known_ambiguity",
        "abstention",
        "time_sensitive",
    }
)

GRADES: Final = (
    "exact",
    "relevant",
    "ambiguous",
    "abstain_candidate",
    "not_relevant",
    "missing_body",
)

BODY_DISPOSITIONS_WITHOUT_FULL_TEXT: Final = frozenset(
    {
        TextAvailability.METADATA_ONLY.value,
        TextAvailability.UNAVAILABLE.value,
        TextAvailability.ABSTRACT_ONLY.value,
        TextAvailability.FAILED_FINAL.value,
    }
)

CURRENTNESS_DISCLAIMER: Final = (
    "Acquisition and publication timestamps record when a Federal Register "
    "package was retrieved or sealed; they are not a claim that the document "
    "is legally current as of wall-clock time. Retrieval output is a research "
    "aid and is not a substitute for the official FederalRegister.gov or "
    "GovInfo source. Time-sensitive gold queries must expose the observation "
    "cutoff / release pin rather than imply currentness."
)

GROUND_TRUTH_POLICY: Final = (
    "human_reviewed_official_publication_identity_grounding_no_model_labels"
)

_CID_RE = re.compile(r"^bafkrei[a-z0-9]+$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_AGENCY_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}$")

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

# Digest fields excluded from the sealed body hash.
_SEAL_EXCLUDED_KEYS: Final = frozenset(
    {"manifest_digest", "content_checksum", "seal"}
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterGoldError(ValueError):
    """Base error for Federal Register gold-set integrity failures."""


class GoldFixtureNotFoundError(FederalRegisterGoldError):
    """Raised when the sealed gold fixture path is missing."""


class GoldSchemaError(FederalRegisterGoldError):
    """Raised when the gold fixture schema or required fields are invalid."""


class GoldChecksumError(FederalRegisterGoldError):
    """Raised when checksum or manifest digest verification fails."""


class GoldDiversityError(FederalRegisterGoldError):
    """Raised when temporal/agency/type diversity requirements fail."""


class GoldLeakError(FederalRegisterGoldError):
    """Raised when train/dev/test leakage is detected."""


class GoldLabelError(FederalRegisterGoldError):
    """Raised when judgments, hard negatives, or missing-body cases are invalid."""


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def default_gold_fixture_path() -> Path:
    """Return the repository-default sealed gold fixture path."""

    # ipfs_datasets_py/processors/legal_data/this_file.py → repo root
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "tests" / "fixtures" / "legal_ir" / FIXTURE_FILENAME


def resolve_gold_fixture_path(path: Optional[PathLike] = None) -> Path:
    """Resolve *path* or fall back to the default sealed fixture."""

    if path is None:
        return default_gold_fixture_path()
    return Path(path)


# ---------------------------------------------------------------------------
# Sealing / digests
# ---------------------------------------------------------------------------


def sealed_body(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the digest-eligible body of a gold payload (no seal fields)."""

    return {k: v for k, v in payload.items() if k not in _SEAL_EXCLUDED_KEYS}


def compute_manifest_digest(payload: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical sealed body (excludes digest fields)."""

    return digest_mapping(sealed_body(payload))


def compute_content_checksum(payload: Mapping[str, Any]) -> str:
    """Alias of :func:`compute_manifest_digest` for dual-field seal contracts."""

    return compute_manifest_digest(payload)


def document_source_checksum(
    *,
    document_number: str,
    publication_date: str,
    official_source_url: str,
    title: str,
) -> str:
    """Deterministic source checksum for a sealed gold document stub."""

    material = (
        f"fr-gold-source|{document_number}|{publication_date}|"
        f"{official_source_url}|{title}"
    )
    return content_sha256(material)


def sealed_entry_cid(document_number: str, publication_date: str) -> str:
    """Stable synthetic entry CID for a gold document stub."""

    digest = content_sha256(f"fr-gold-entry|{document_number}|{publication_date}")
    return f"bafkreie{digest[:47]}"


def sealed_source_cid(document_number: str, publication_date: str) -> str:
    """Stable synthetic source CID for a gold document stub."""

    digest = content_sha256(f"fr-gold-source-cid|{document_number}|{publication_date}")
    return f"bafkreis{digest[:47]}"


def apply_seal(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *payload* with checksum seal fields applied."""

    body = sealed_body(payload)
    digest = digest_mapping(body)
    sealed = dict(body)
    sealed["manifest_digest"] = digest
    sealed["content_checksum"] = digest
    sealed["seal"] = {
        "algorithm": "sha256",
        "canonicalization": "json-sort-keys-separators-comma-colon",
        "excluded_fields": sorted(_SEAL_EXCLUDED_KEYS),
        "task_id": TASK_ID,
        "schema_version": SCHEMA_VERSION,
    }
    return sealed


def verify_checksum_seal(payload: Mapping[str, Any]) -> str:
    """Verify manifest_digest / content_checksum; return the verified digest."""

    expected = compute_manifest_digest(payload)
    declared_manifest = payload.get("manifest_digest")
    declared_content = payload.get("content_checksum")
    if not declared_manifest:
        raise GoldChecksumError("missing manifest_digest on sealed gold fixture")
    if not declared_content:
        raise GoldChecksumError("missing content_checksum on sealed gold fixture")
    try:
        manifest = normalize_sha256(declared_manifest, name="manifest_digest")
        content = normalize_sha256(declared_content, name="content_checksum")
    except Exception as exc:  # noqa: BLE001 - surface as gold checksum error
        raise GoldChecksumError(str(exc)) from exc
    if manifest != expected:
        raise GoldChecksumError(
            f"manifest_digest mismatch: declared={manifest} expected={expected}"
        )
    if content != expected:
        raise GoldChecksumError(
            f"content_checksum mismatch: declared={content} expected={expected}"
        )
    return expected


# ---------------------------------------------------------------------------
# Compact recipe → materialization
# ---------------------------------------------------------------------------


def _fr_url(document_number: str) -> str:
    return f"https://www.federalregister.gov/documents/{document_number}"


def _govinfo_url(document_number: str, publication_date: str) -> str:
    # Compact sealed stub; real package ids are acquisition-task concerns.
    year = publication_date[:4]
    return (
        f"https://www.govinfo.gov/content/pkg/FR-{publication_date}/pdf/"
        f"FR-{publication_date}.pdf#{document_number}-{year}"
    )


def _doc(
    *,
    document_id: str,
    document_number: str,
    publication_date: str,
    document_type: str,
    agency_code: str,
    agency_name: str,
    title: str,
    abstract: str,
    text_availability: str = "full_text",
    correction_relation: str = "none",
    related_document_number: Optional[str] = None,
    cfr_citations: Optional[Sequence[str]] = None,
    topics: Optional[Sequence[str]] = None,
    era: Optional[str] = None,
    notes: str = "",
    body_present: Optional[bool] = None,
) -> dict[str, Any]:
    DocumentType.coerce(document_type)
    TextAvailability.coerce(text_availability)
    CorrectionRelation.coerce(correction_relation)
    document_number = validate_document_number(document_number)
    publication_date = validate_publication_date(publication_date)
    legal_id = validate_legal_id(f"fr:{document_number}:{publication_date}")
    official_url = validate_official_url(_fr_url(document_number))
    secondary_url = validate_official_url(
        _govinfo_url(document_number, publication_date)
    )
    availability = TextAvailability.coerce(text_availability).value
    if body_present is None:
        body_present = availability not in BODY_DISPOSITIONS_WITHOUT_FULL_TEXT
    year = int(publication_date[:4])
    if era is None:
        if year < 2015:
            era = "early_2010s"
        elif year < 2020:
            era = "late_2010s"
        else:
            era = "2020s"
    return {
        "document_id": document_id,
        "legal_id": legal_id,
        "entry_cid": sealed_entry_cid(document_number, publication_date),
        "source_cid": sealed_source_cid(document_number, publication_date),
        "document_number": document_number,
        "publication_date": publication_date,
        "year_month": publication_date[:7],
        "document_type": DocumentType.coerce(document_type).value,
        "agency_code": agency_code,
        "agency_name": agency_name,
        "title": title,
        "abstract": abstract,
        "official_source_url": official_url,
        "secondary_source_url": secondary_url,
        "source_checksum": document_source_checksum(
            document_number=document_number,
            publication_date=publication_date,
            official_source_url=official_url,
            title=title,
        ),
        "text_availability": availability,
        "body_present": bool(body_present),
        "correction_relation": CorrectionRelation.coerce(correction_relation).value,
        "related_document_number": related_document_number,
        "cfr_citations": list(cfr_citations or []),
        "topics": list(topics or []),
        "era": era,
        "notes": notes,
    }


def _query(
    *,
    query_id: str,
    partition: str,
    query_kind: str,
    query_text: str,
    expectation: str,
    primary_agency: Optional[str] = None,
    primary_document_type: Optional[str] = None,
    filters: Optional[Mapping[str, Any]] = None,
    must_expose_cutoff: bool = False,
    abstain_if_unscoped: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    if partition not in PARTITIONS:
        raise GoldSchemaError(f"unknown partition: {partition!r}")
    return {
        "query_id": query_id,
        "partition": partition,
        "query_kind": query_kind,
        "query_text": query_text,
        "expectation": expectation,
        "primary_agency": primary_agency,
        "primary_document_type": primary_document_type,
        "filters": dict(filters or {}),
        "must_expose_cutoff": must_expose_cutoff,
        "abstain_if_unscoped": abstain_if_unscoped,
        "notes": notes,
    }


def _judgment(
    *,
    query_id: str,
    document_id: str,
    legal_id: str,
    entry_cid: str,
    grade: str,
    label_kind: str,
    rank_ceiling: Optional[int] = None,
    notes: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query_id": query_id,
        "document_id": document_id,
        "legal_id": legal_id,
        "entry_cid": entry_cid,
        "grade": grade,
        "label_kind": label_kind,
        "notes": notes,
    }
    if rank_ceiling is not None:
        payload["rank_ceiling"] = rank_ceiling
    return payload


def build_gold_documents() -> list[dict[str, Any]]:
    """Compact recipe of temporally and agency-diverse FR document stubs."""

    return [
        _doc(
            document_id="doc:epa-rule-2020-12345",
            document_number="2020-12345",
            publication_date="2020-06-15",
            document_type="rule",
            agency_code="EPA",
            agency_name="Environmental Protection Agency",
            title="National Emission Standards for Hazardous Air Pollutants: Final Rule",
            abstract=(
                "EPA finalizes emission standards for hazardous air pollutants "
                "from certain industrial sources under the Clean Air Act."
            ),
            cfr_citations=["40 CFR 63"],
            topics=["emissions", "clean_air_act", "hazardous_air_pollutants"],
            notes="Canonical EPA final rule for exact and semantic retrieval.",
        ),
        _doc(
            document_id="doc:epa-proposed-2019-09876",
            document_number="2019-09876",
            publication_date="2019-11-01",
            document_type="proposed_rule",
            agency_code="EPA",
            agency_name="Environmental Protection Agency",
            title="National Emission Standards for Hazardous Air Pollutants: Proposed Rule",
            abstract=(
                "EPA proposes emission standards for hazardous air pollutants; "
                "this is not the final rule."
            ),
            cfr_citations=["40 CFR 63"],
            topics=["emissions", "clean_air_act", "proposed"],
            notes="Proposed predecessor of the 2020 EPA final rule.",
        ),
        _doc(
            document_id="doc:epa-correction-2020-13000",
            document_number="2020-13000",
            publication_date="2020-07-01",
            document_type="correction",
            agency_code="EPA",
            agency_name="Environmental Protection Agency",
            title="National Emission Standards: Correction",
            abstract="Corrects technical errors in document 2020-12345.",
            correction_relation="corrects",
            related_document_number="2020-12345",
            cfr_citations=["40 CFR 63"],
            topics=["emissions", "correction"],
            notes="Correction identity linked to the 2020 EPA final rule.",
        ),
        _doc(
            document_id="doc:hhs-notice-2021-04567",
            document_number="2021-04567",
            publication_date="2021-03-12",
            document_type="notice",
            agency_code="HHS",
            agency_name="Department of Health and Human Services",
            title="Medicare Program: Public Meeting Notice on Payment Policies",
            abstract="HHS announces a public meeting on Medicare payment policies.",
            topics=["medicare", "public_meeting"],
            notes="HHS notice for agency-topic and filter cases.",
        ),
        _doc(
            document_id="doc:sec-rule-2018-11234",
            document_number="2018-11234",
            publication_date="2018-08-20",
            document_type="rule",
            agency_code="SEC",
            agency_name="Securities and Exchange Commission",
            title="Disclosure of Hedging by Employees, Officers and Directors",
            abstract=(
                "SEC adopts rules requiring disclosure of hedging policies for "
                "employees, officers, and directors."
            ),
            cfr_citations=["17 CFR 229", "17 CFR 240"],
            topics=["securities", "disclosure", "hedging"],
            era="late_2010s",
        ),
        _doc(
            document_id="doc:dot-proposed-2022-05678",
            document_number="2022-05678",
            publication_date="2022-04-05",
            document_type="proposed_rule",
            agency_code="DOT",
            agency_name="Department of Transportation",
            title="Airline Passenger Protections: Proposed Amendments",
            abstract="DOT proposes amendments to airline passenger protection rules.",
            cfr_citations=["14 CFR 259"],
            topics=["aviation", "consumer_protection", "proposed"],
        ),
        _doc(
            document_id="doc:dot-withdraw-2022-06000",
            document_number="2022-06000",
            publication_date="2022-05-10",
            document_type="notice",
            agency_code="DOT",
            agency_name="Department of Transportation",
            title="Airline Passenger Protections: Withdrawal of Proposed Rule",
            abstract="DOT withdraws the proposed amendments in document 2022-05678.",
            correction_relation="withdraws",
            related_document_number="2022-05678",
            topics=["aviation", "withdrawal"],
            notes="Withdrawal notice linked to DOT proposed rule.",
        ),
        _doc(
            document_id="doc:eop-presidential-2021-01234",
            document_number="2021-01234",
            publication_date="2021-01-27",
            document_type="presidential_document",
            agency_code="EOP",
            agency_name="Executive Office of the President",
            title="Executive Order on Tackling the Climate Crisis at Home and Abroad",
            abstract=(
                "Presidential executive order directing agencies on climate "
                "crisis policy coordination."
            ),
            topics=["climate", "executive_order", "presidential"],
        ),
        _doc(
            document_id="doc:fda-rule-2015-08900",
            document_number="2015-08900",
            publication_date="2015-09-10",
            document_type="rule",
            agency_code="HHS",
            agency_name="Food and Drug Administration, Department of Health and Human Services",
            title="Food Labeling: Nutrition Labeling of Standard Menu Items",
            abstract="FDA finalizes nutrition labeling requirements for standard menu items.",
            cfr_citations=["21 CFR 101"],
            topics=["food_labeling", "nutrition", "fda"],
            era="late_2010s",
            notes="FDA operating component under HHS agency code for diversity.",
        ),
        _doc(
            document_id="doc:doe-notice-2012-03456",
            document_number="2012-03456",
            publication_date="2012-02-14",
            document_type="notice",
            agency_code="DOE",
            agency_name="Department of Energy",
            title="Energy Conservation Program: Public Meeting and Availability of Framework",
            abstract="DOE announces a public meeting on energy conservation standards.",
            topics=["energy_conservation", "public_meeting"],
            era="early_2010s",
        ),
        _doc(
            document_id="doc:dol-rule-2023-07890",
            document_number="2023-07890",
            publication_date="2023-01-10",
            document_type="rule",
            agency_code="DOL",
            agency_name="Department of Labor",
            title="Updating the Davis-Bacon and Related Acts Regulations",
            abstract="DOL finalizes updates to Davis-Bacon prevailing wage regulations.",
            cfr_citations=["29 CFR 1", "29 CFR 5"],
            topics=["prevailing_wage", "davis_bacon"],
        ),
        _doc(
            document_id="doc:doi-proposed-2016-10111",
            document_number="2016-10111",
            publication_date="2016-06-22",
            document_type="proposed_rule",
            agency_code="DOI",
            agency_name="Department of the Interior",
            title="Endangered and Threatened Wildlife: Proposed Listing",
            abstract="DOI proposes listing determinations under the Endangered Species Act.",
            cfr_citations=["50 CFR 17"],
            topics=["endangered_species", "wildlife"],
            era="late_2010s",
        ),
        _doc(
            document_id="doc:dhs-notice-2017-05555",
            document_number="2017-05555",
            publication_date="2017-08-30",
            document_type="notice",
            agency_code="DHS",
            agency_name="Federal Emergency Management Agency, Department of Homeland Security",
            title="Flood Hazard Determinations; Notice",
            abstract="FEMA publishes flood hazard determination notices for certain communities.",
            topics=["flood_hazard", "fema"],
            era="late_2010s",
        ),
        _doc(
            document_id="doc:doj-rule-2014-06666",
            document_number="2014-06666",
            publication_date="2014-11-05",
            document_type="rule",
            agency_code="DOJ",
            agency_name="Department of Justice",
            title="Nondiscrimination on the Basis of Disability: Accessibility Standards",
            abstract="DOJ adopts accessibility standards under the Americans with Disabilities Act.",
            cfr_citations=["28 CFR 35", "28 CFR 36"],
            topics=["ada", "accessibility"],
            era="early_2010s",
        ),
        _doc(
            document_id="doc:fcc-meta-2024-01111",
            document_number="2024-01111",
            publication_date="2024-01-15",
            document_type="notice",
            agency_code="FCC",
            agency_name="Federal Communications Commission",
            title="Media Bureau Action: Metadata-Only Notice Stub",
            abstract="Official metadata is available; full body text is not admitted.",
            text_availability="metadata_only",
            body_present=False,
            topics=["media", "metadata_only"],
            notes="Missing-body case: metadata_only must not masquerade as full text.",
        ),
        _doc(
            document_id="doc:fcc-unavail-2024-02222",
            document_number="2024-02222",
            publication_date="2024-02-20",
            document_type="notice",
            agency_code="FCC",
            agency_name="Federal Communications Commission",
            title="Wireline Competition Bureau: Unavailable Body Disposition",
            abstract="",
            text_availability="unavailable",
            body_present=False,
            topics=["wireline", "unavailable"],
            notes="Missing-body case: unavailable body disposition.",
        ),
        _doc(
            document_id="doc:sba-abstract-2011-03333",
            document_number="2011-03333",
            publication_date="2011-05-05",
            document_type="notice",
            agency_code="SBA",
            agency_name="Small Business Administration",
            title="Interest Rates: Abstract-Only Historical Notice",
            abstract="SBA publishes interest rate notice; only abstract admitted in gold stub.",
            text_availability="abstract_only",
            body_present=False,
            topics=["interest_rates", "abstract_only"],
            era="early_2010s",
            notes="Missing-body case: abstract_only is not full text.",
        ),
        _doc(
            document_id="doc:epa-rule-2019-20000",
            document_number="2019-20000",
            publication_date="2019-12-12",
            document_type="rule",
            agency_code="EPA",
            agency_name="Environmental Protection Agency",
            title="Renewable Fuel Standard Program: Standards for 2020",
            abstract="EPA establishes renewable fuel standards and related CFR amendments.",
            cfr_citations=["40 CFR 80"],
            topics=["renewable_fuel", "rfs"],
            era="late_2010s",
            notes="CFR citation-path document for lexical/citation queries.",
        ),
    ]


def _index_docs(documents: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(doc["document_id"]): dict(doc) for doc in documents}


def build_gold_queries_and_labels(
    documents: Sequence[Mapping[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Build queries, judgments, graph paths, hard negatives, and missing-body cases."""

    by_id = _index_docs(documents)

    def J(
        query_id: str,
        document_id: str,
        grade: str,
        label_kind: str,
        rank_ceiling: Optional[int] = None,
        notes: str = "",
    ) -> dict[str, Any]:
        doc = by_id[document_id]
        return _judgment(
            query_id=query_id,
            document_id=document_id,
            legal_id=doc["legal_id"],
            entry_cid=doc["entry_cid"],
            grade=grade,
            label_kind=label_kind,
            rank_ceiling=rank_ceiling,
            notes=notes,
        )

    queries: list[dict[str, Any]] = [
        # ---- train ----
        _query(
            query_id="q-train-epa-exact-docnum",
            partition="train",
            query_kind="exact_document_number",
            query_text="Federal Register document 2020-12345",
            expectation="exact_document",
            primary_agency="EPA",
            primary_document_type="rule",
        ),
        _query(
            query_id="q-train-epa-semantic-emissions",
            partition="train",
            query_kind="semantic",
            query_text="EPA final hazardous air pollutant emission standards Clean Air Act",
            expectation="exact_document",
            primary_agency="EPA",
            primary_document_type="rule",
        ),
        _query(
            query_id="q-train-sec-hedging-rule",
            partition="train",
            query_kind="agency_topic",
            query_text="SEC rule on disclosure of hedging by officers and directors",
            expectation="exact_document",
            primary_agency="SEC",
            primary_document_type="rule",
        ),
        _query(
            query_id="q-train-hhs-medicare-notice",
            partition="train",
            query_kind="agency_topic",
            query_text="HHS Medicare public meeting notice payment policies",
            expectation="exact_document",
            primary_agency="HHS",
            primary_document_type="notice",
        ),
        _query(
            query_id="q-train-filter-agency-epa",
            partition="train",
            query_kind="filter_agency",
            query_text="emission standards documents",
            expectation="agency_filter_match",
            primary_agency="EPA",
            filters={"agency_code": "EPA"},
        ),
        _query(
            query_id="q-train-dol-davis-bacon",
            partition="train",
            query_kind="lexical",
            query_text="Davis-Bacon prevailing wage regulations final rule",
            expectation="exact_document",
            primary_agency="DOL",
            primary_document_type="rule",
        ),
        _query(
            query_id="q-train-doe-energy-notice",
            partition="train",
            query_kind="semantic",
            query_text="Department of Energy conservation program public meeting framework",
            expectation="exact_document",
            primary_agency="DOE",
            primary_document_type="notice",
        ),
        _query(
            query_id="q-train-hard-neg-fabricated-docnum",
            partition="train",
            query_kind="hard_negative",
            query_text="Federal Register document 2099-99999 imaginary emissions rule",
            expectation="hard_negative",
            notes="Fabricated document number must not exact-match real rows.",
        ),
        # ---- dev ----
        _query(
            query_id="q-dev-proposed-vs-final-epa",
            partition="dev",
            query_kind="proposed_vs_final",
            query_text="EPA proposed hazardous air pollutant standards not the final rule",
            expectation="exact_document",
            primary_agency="EPA",
            primary_document_type="proposed_rule",
            notes="Must prefer proposed_rule 2019-09876 over final 2020-12345.",
        ),
        _query(
            query_id="q-dev-correction-path-epa",
            partition="dev",
            query_kind="correction_path",
            query_text="correction to EPA emission standards document 2020-12345",
            expectation="correction_relation",
            primary_agency="EPA",
            primary_document_type="correction",
        ),
        _query(
            query_id="q-dev-presidential-climate-eo",
            partition="dev",
            query_kind="presidential",
            query_text="executive order tackling the climate crisis at home and abroad",
            expectation="exact_document",
            primary_agency="EOP",
            primary_document_type="presidential_document",
        ),
        _query(
            query_id="q-dev-filter-type-notice",
            partition="dev",
            query_kind="filter_type",
            query_text="public meeting announcements",
            expectation="type_filter_match",
            primary_document_type="notice",
            filters={"document_type": "notice"},
        ),
        _query(
            query_id="q-dev-filter-date-2020",
            partition="dev",
            query_kind="filter_date",
            query_text="Federal Register documents published in June 2020",
            expectation="date_filter_match",
            filters={
                "publication_date_from": "2020-06-01",
                "publication_date_to": "2020-06-30",
            },
        ),
        _query(
            query_id="q-dev-citation-40-cfr-80",
            partition="dev",
            query_kind="citation",
            query_text="40 CFR part 80 renewable fuel standard program",
            expectation="supporting_citation_path",
            primary_agency="EPA",
            primary_document_type="rule",
        ),
        _query(
            query_id="q-dev-doi-endangered-species",
            partition="dev",
            query_kind="semantic",
            query_text="Interior proposed listing endangered threatened wildlife",
            expectation="exact_document",
            primary_agency="DOI",
            primary_document_type="proposed_rule",
        ),
        _query(
            query_id="q-dev-hard-neg-wrong-agency",
            partition="dev",
            query_kind="hard_negative",
            query_text="SEC final rule on hazardous air pollutant emission standards",
            expectation="hard_negative",
            primary_agency="SEC",
            notes="SEC must not be exact for an EPA emissions topic.",
        ),
        # ---- test ----
        _query(
            query_id="q-test-dot-withdrawal-path",
            partition="test",
            query_kind="withdrawal_path",
            query_text="DOT withdrawal of airline passenger protections proposed rule",
            expectation="withdrawal_relation",
            primary_agency="DOT",
            primary_document_type="notice",
        ),
        _query(
            query_id="q-test-doj-ada-accessibility",
            partition="test",
            query_kind="agency_topic",
            query_text="DOJ ADA accessibility standards nondiscrimination disability",
            expectation="exact_document",
            primary_agency="DOJ",
            primary_document_type="rule",
        ),
        _query(
            query_id="q-test-dhs-flood-notice",
            partition="test",
            query_kind="lexical",
            query_text="FEMA flood hazard determinations notice",
            expectation="exact_document",
            primary_agency="DHS",
            primary_document_type="notice",
        ),
        _query(
            query_id="q-test-fda-menu-labeling",
            partition="test",
            query_kind="semantic",
            query_text="FDA nutrition labeling requirements for standard menu items",
            expectation="exact_document",
            primary_agency="HHS",
            primary_document_type="rule",
        ),
        _query(
            query_id="q-test-missing-body-metadata",
            partition="test",
            query_kind="missing_body",
            query_text="FCC media bureau action document 2024-01111 full text body",
            expectation="missing_body",
            primary_agency="FCC",
            primary_document_type="notice",
            notes="Metadata-only disposition: do not treat as full-text body hit.",
        ),
        _query(
            query_id="q-test-missing-body-unavailable",
            partition="test",
            query_kind="missing_body",
            query_text="FCC wireline notice 2024-02222 complete official body text",
            expectation="missing_body",
            primary_agency="FCC",
            notes="Unavailable body: retrieval may surface metadata but not full body.",
        ),
        _query(
            query_id="q-test-time-sensitive-current",
            partition="test",
            query_kind="time_sensitive",
            query_text="current EPA emission standards text as of today",
            expectation="time_sensitive",
            primary_agency="EPA",
            must_expose_cutoff=True,
            abstain_if_unscoped=True,
            notes="Must expose observation cutoff; no wall-clock currentness claim.",
        ),
        _query(
            query_id="q-test-abstain-individualized",
            partition="test",
            query_kind="abstention",
            query_text=(
                "what is the currently effective DOT passenger rule for my "
                "airline complaint filed today"
            ),
            expectation="abstention",
            primary_agency="DOT",
            must_expose_cutoff=True,
            abstain_if_unscoped=True,
        ),
        _query(
            query_id="q-test-hard-neg-wrong-type",
            partition="test",
            query_kind="hard_negative",
            query_text="presidential executive order updating Davis-Bacon wage regulations",
            expectation="hard_negative",
            notes="Presidential docs must not exact-match DOL Davis-Bacon rule.",
        ),
        _query(
            query_id="q-test-filter-agency-dot",
            partition="test",
            query_kind="filter_agency",
            query_text="airline passenger protection rulemaking documents",
            expectation="agency_filter_match",
            primary_agency="DOT",
            filters={"agency_code": "DOT"},
        ),
        _query(
            query_id="q-test-known-ambiguity-rfs-vintage",
            partition="test",
            query_kind="semantic",
            query_text=(
                "which Federal Register renewable fuel standard applies for "
                "compliance year 2020 versus later vintages"
            ),
            expectation="known_ambiguity",
            primary_agency="EPA",
            primary_document_type="rule",
            must_expose_cutoff=True,
            abstain_if_unscoped=True,
            notes=(
                "Multiple FR vintages can match RFS language; do not force a "
                "single exact hit without edition/cutoff scope."
            ),
        ),
    ]

    judgments: list[dict[str, Any]] = [
        J("q-train-epa-exact-docnum", "doc:epa-rule-2020-12345", "exact", "exact_document", 1),
        J(
            "q-train-epa-exact-docnum",
            "doc:epa-correction-2020-13000",
            "relevant",
            "correction_relation",
            5,
            "Correction is related support, not the exact primary hit.",
        ),
        J(
            "q-train-epa-semantic-emissions",
            "doc:epa-rule-2020-12345",
            "exact",
            "exact_document",
            3,
        ),
        J(
            "q-train-epa-semantic-emissions",
            "doc:epa-proposed-2019-09876",
            "relevant",
            "relevant_document",
            10,
            "Proposed rule is related but not the final standards hit.",
        ),
        J("q-train-sec-hedging-rule", "doc:sec-rule-2018-11234", "exact", "exact_document", 1),
        J(
            "q-train-hhs-medicare-notice",
            "doc:hhs-notice-2021-04567",
            "exact",
            "exact_document",
            1,
        ),
        J(
            "q-train-filter-agency-epa",
            "doc:epa-rule-2020-12345",
            "exact",
            "agency_filter_match",
            5,
        ),
        J(
            "q-train-filter-agency-epa",
            "doc:epa-rule-2019-20000",
            "relevant",
            "agency_filter_match",
            10,
        ),
        J("q-train-dol-davis-bacon", "doc:dol-rule-2023-07890", "exact", "exact_document", 1),
        J(
            "q-train-doe-energy-notice",
            "doc:doe-notice-2012-03456",
            "exact",
            "exact_document",
            3,
        ),
        # hard negative train: no exact judgments; not_relevant against near misses
        J(
            "q-train-hard-neg-fabricated-docnum",
            "doc:epa-rule-2020-12345",
            "not_relevant",
            "hard_negative",
            notes="Fabricated doc number must not exact-match real EPA rule.",
        ),
        J(
            "q-dev-proposed-vs-final-epa",
            "doc:epa-proposed-2019-09876",
            "exact",
            "exact_document",
            1,
        ),
        J(
            "q-dev-proposed-vs-final-epa",
            "doc:epa-rule-2020-12345",
            "relevant",
            "relevant_document",
            10,
            "Final rule is related but query seeks proposed.",
        ),
        J(
            "q-dev-correction-path-epa",
            "doc:epa-correction-2020-13000",
            "exact",
            "correction_relation",
            1,
        ),
        J(
            "q-dev-correction-path-epa",
            "doc:epa-rule-2020-12345",
            "relevant",
            "supporting_citation_path",
            5,
        ),
        J(
            "q-dev-presidential-climate-eo",
            "doc:eop-presidential-2021-01234",
            "exact",
            "exact_document",
            1,
        ),
        J(
            "q-dev-filter-type-notice",
            "doc:hhs-notice-2021-04567",
            "exact",
            "type_filter_match",
            5,
        ),
        J(
            "q-dev-filter-type-notice",
            "doc:doe-notice-2012-03456",
            "relevant",
            "type_filter_match",
            10,
        ),
        J(
            "q-dev-filter-date-2020",
            "doc:epa-rule-2020-12345",
            "exact",
            "date_filter_match",
            5,
        ),
        J(
            "q-dev-citation-40-cfr-80",
            "doc:epa-rule-2019-20000",
            "exact",
            "supporting_citation_path",
            3,
        ),
        J(
            "q-dev-doi-endangered-species",
            "doc:doi-proposed-2016-10111",
            "exact",
            "exact_document",
            3,
        ),
        J(
            "q-dev-hard-neg-wrong-agency",
            "doc:sec-rule-2018-11234",
            "not_relevant",
            "hard_negative",
            notes="SEC hedging rule is not an emissions exact hit.",
        ),
        J(
            "q-dev-hard-neg-wrong-agency",
            "doc:epa-rule-2020-12345",
            "relevant",
            "hard_negative",
            10,
            "EPA may be preferred but query is a hard negative control for SEC exact.",
        ),
        J(
            "q-test-dot-withdrawal-path",
            "doc:dot-withdraw-2022-06000",
            "exact",
            "withdrawal_relation",
            1,
        ),
        J(
            "q-test-dot-withdrawal-path",
            "doc:dot-proposed-2022-05678",
            "relevant",
            "supporting_citation_path",
            5,
        ),
        J(
            "q-test-doj-ada-accessibility",
            "doc:doj-rule-2014-06666",
            "exact",
            "exact_document",
            1,
        ),
        J(
            "q-test-dhs-flood-notice",
            "doc:dhs-notice-2017-05555",
            "exact",
            "exact_document",
            1,
        ),
        J(
            "q-test-fda-menu-labeling",
            "doc:fda-rule-2015-08900",
            "exact",
            "exact_document",
            3,
        ),
        J(
            "q-test-missing-body-metadata",
            "doc:fcc-meta-2024-01111",
            "missing_body",
            "missing_body",
            notes="May surface metadata identity; must not claim full-text body.",
        ),
        J(
            "q-test-missing-body-unavailable",
            "doc:fcc-unavail-2024-02222",
            "missing_body",
            "missing_body",
            notes="Unavailable body disposition.",
        ),
        J(
            "q-test-time-sensitive-current",
            "doc:epa-rule-2020-12345",
            "relevant",
            "time_sensitive",
            5,
            "Retrieve only with cutoff exposure; no wall-clock currentness.",
        ),
        J(
            "q-test-abstain-individualized",
            "doc:dot-proposed-2022-05678",
            "abstain_candidate",
            "abstention",
            notes="Individualized current advice boundary.",
        ),
        J(
            "q-test-hard-neg-wrong-type",
            "doc:eop-presidential-2021-01234",
            "not_relevant",
            "hard_negative",
        ),
        J(
            "q-test-hard-neg-wrong-type",
            "doc:dol-rule-2023-07890",
            "relevant",
            "hard_negative",
            10,
            "DOL is the topical match but query type is presidential hard negative.",
        ),
        J(
            "q-test-filter-agency-dot",
            "doc:dot-proposed-2022-05678",
            "exact",
            "agency_filter_match",
            5,
        ),
        J(
            "q-test-filter-agency-dot",
            "doc:dot-withdraw-2022-06000",
            "relevant",
            "agency_filter_match",
            10,
        ),
        J(
            "q-test-known-ambiguity-rfs-vintage",
            "doc:epa-rule-2019-20000",
            "ambiguous",
            "known_ambiguity",
            notes=(
                "RFS 2020 standards row is a plausible hit but vintage ambiguity "
                "requires cutoff/edition exposure rather than a forced exact grade."
            ),
        ),
        J(
            "q-test-known-ambiguity-rfs-vintage",
            "doc:epa-rule-2020-12345",
            "ambiguous",
            "known_ambiguity",
            notes="Unrelated emissions final rule must not be forced exact for RFS vintage questions.",
        ),
    ]

    graph_paths: list[dict[str, Any]] = [
        {
            "path_id": "path-dev-epa-correction",
            "query_id": "q-dev-correction-path-epa",
            "partition": "dev",
            "nodes": [
                "doc:epa-correction-2020-13000",
                "doc:epa-rule-2020-12345",
            ],
            "node_refs": [
                {
                    "document_id": "doc:epa-correction-2020-13000",
                    "legal_id": by_id["doc:epa-correction-2020-13000"]["legal_id"],
                    "entry_cid": by_id["doc:epa-correction-2020-13000"]["entry_cid"],
                    "source_cid": by_id["doc:epa-correction-2020-13000"]["source_cid"],
                    "document_number": "2020-13000",
                },
                {
                    "document_id": "doc:epa-rule-2020-12345",
                    "legal_id": by_id["doc:epa-rule-2020-12345"]["legal_id"],
                    "entry_cid": by_id["doc:epa-rule-2020-12345"]["entry_cid"],
                    "source_cid": by_id["doc:epa-rule-2020-12345"]["source_cid"],
                    "document_number": "2020-12345",
                },
            ],
            "edges": [
                {
                    "source": "doc:epa-correction-2020-13000",
                    "target": "doc:epa-rule-2020-12345",
                    "relation": "corrects",
                    "notes": "Correction document corrects the final EPA rule.",
                }
            ],
        },
        {
            "path_id": "path-test-dot-withdrawal",
            "query_id": "q-test-dot-withdrawal-path",
            "partition": "test",
            "nodes": [
                "doc:dot-withdraw-2022-06000",
                "doc:dot-proposed-2022-05678",
            ],
            "node_refs": [
                {
                    "document_id": "doc:dot-withdraw-2022-06000",
                    "legal_id": by_id["doc:dot-withdraw-2022-06000"]["legal_id"],
                    "entry_cid": by_id["doc:dot-withdraw-2022-06000"]["entry_cid"],
                    "source_cid": by_id["doc:dot-withdraw-2022-06000"]["source_cid"],
                    "document_number": "2022-06000",
                },
                {
                    "document_id": "doc:dot-proposed-2022-05678",
                    "legal_id": by_id["doc:dot-proposed-2022-05678"]["legal_id"],
                    "entry_cid": by_id["doc:dot-proposed-2022-05678"]["entry_cid"],
                    "source_cid": by_id["doc:dot-proposed-2022-05678"]["source_cid"],
                    "document_number": "2022-05678",
                },
            ],
            "edges": [
                {
                    "source": "doc:dot-withdraw-2022-06000",
                    "target": "doc:dot-proposed-2022-05678",
                    "relation": "withdraws",
                    "notes": "Withdrawal notice withdraws the DOT proposed rule.",
                }
            ],
        },
        {
            "path_id": "path-train-epa-proposed-final",
            "query_id": "q-train-epa-semantic-emissions",
            "partition": "train",
            "nodes": [
                "doc:epa-proposed-2019-09876",
                "doc:epa-rule-2020-12345",
            ],
            "node_refs": [
                {
                    "document_id": "doc:epa-proposed-2019-09876",
                    "legal_id": by_id["doc:epa-proposed-2019-09876"]["legal_id"],
                    "entry_cid": by_id["doc:epa-proposed-2019-09876"]["entry_cid"],
                    "source_cid": by_id["doc:epa-proposed-2019-09876"]["source_cid"],
                    "document_number": "2019-09876",
                },
                {
                    "document_id": "doc:epa-rule-2020-12345",
                    "legal_id": by_id["doc:epa-rule-2020-12345"]["legal_id"],
                    "entry_cid": by_id["doc:epa-rule-2020-12345"]["entry_cid"],
                    "source_cid": by_id["doc:epa-rule-2020-12345"]["source_cid"],
                    "document_number": "2020-12345",
                },
            ],
            "edges": [
                {
                    "source": "doc:epa-proposed-2019-09876",
                    "target": "doc:epa-rule-2020-12345",
                    "relation": "proposed_then_finalized_as",
                    "notes": "Proposed rule is the rulemaking predecessor of the final rule.",
                }
            ],
        },
    ]

    hard_negatives: list[dict[str, Any]] = [
        {
            "control_id": "hn-fabricated-document-number",
            "control_kind": "fabricated_document_number",
            "partition": "train",
            "query_id": "q-train-hard-neg-fabricated-docnum",
            "query_text": "Federal Register document 2099-99999 imaginary emissions rule",
            "expected_behavior": "no_exact_hit",
            "must_not_grade_exact_document_ids": [
                "doc:epa-rule-2020-12345",
                "doc:epa-proposed-2019-09876",
                "doc:epa-rule-2019-20000",
            ],
            "rationale": (
                "Fabricated document numbers must not receive exact grades "
                "against real Federal Register rows."
            ),
        },
        {
            "control_id": "hn-wrong-agency-emissions",
            "control_kind": "wrong_agency",
            "partition": "dev",
            "query_id": "q-dev-hard-neg-wrong-agency",
            "query_text": "SEC final rule on hazardous air pollutant emission standards",
            "expected_behavior": "reject_mismatched_agency_as_exact",
            "must_not_grade_exact_document_ids": ["doc:sec-rule-2018-11234"],
            "preferred_document_ids": ["doc:epa-rule-2020-12345"],
            "rationale": (
                "Emissions standards are EPA subject matter; SEC hedging rule "
                "must not be an exact hit."
            ),
        },
        {
            "control_id": "hn-wrong-document-type-presidential",
            "control_kind": "wrong_document_type",
            "partition": "test",
            "query_id": "q-test-hard-neg-wrong-type",
            "query_text": (
                "presidential executive order updating Davis-Bacon wage regulations"
            ),
            "expected_behavior": "reject_mismatched_type_as_exact",
            "must_not_grade_exact_document_ids": ["doc:eop-presidential-2021-01234"],
            "preferred_document_ids": ["doc:dol-rule-2023-07890"],
            "rationale": (
                "Davis-Bacon is a DOL rulemaking topic; presidential documents "
                "must not be exact hits for that type-mismatched query."
            ),
        },
        {
            "control_id": "hn-wrong-type-proposed-as-final",
            "control_kind": "proposed_final_confusion",
            "partition": "dev",
            "query_id": "q-dev-proposed-vs-final-epa",
            "query_text": (
                "EPA proposed hazardous air pollutant standards not the final rule"
            ),
            "expected_behavior": "prefer_proposed_over_final_as_exact",
            "must_not_grade_exact_document_ids": ["doc:epa-rule-2020-12345"],
            "preferred_document_ids": ["doc:epa-proposed-2019-09876"],
            "rationale": (
                "When the query explicitly seeks the proposed rule, the final "
                "rule must not receive an exact grade."
            ),
        },
        {
            "control_id": "hn-out-of-cutoff-fabricated-future",
            "control_kind": "out_of_cutoff",
            "partition": "test",
            "query_id": "q-test-time-sensitive-current",
            "query_text": "current EPA emission standards text as of today",
            "expected_behavior": "expose_cutoff_or_abstain",
            "must_not_claim_wall_clock_currentness": True,
            "must_not_grade_exact_document_ids": [],
            "rationale": (
                "Time-sensitive currentness queries must expose the sealed "
                "observation cutoff and must not claim wall-clock currency."
            ),
        },
        {
            "control_id": "hn-lexical-decoy-section-230-style",
            "control_kind": "lexical_decoy",
            "partition": "train",
            "query_id": "q-train-hard-neg-fabricated-docnum",
            "query_text": "Federal Register document 2099-99999 imaginary emissions rule",
            "expected_behavior": "no_exact_hit",
            "must_not_grade_exact_document_ids": ["doc:doj-rule-2014-06666"],
            "rationale": (
                "Lexical decoys and fabricated identifiers must not force "
                "unrelated exact hits such as ADA accessibility rules."
            ),
        },
    ]

    missing_body_cases: list[dict[str, Any]] = [
        {
            "case_id": "mb-fcc-metadata-only",
            "query_id": "q-test-missing-body-metadata",
            "document_id": "doc:fcc-meta-2024-01111",
            "legal_id": by_id["doc:fcc-meta-2024-01111"]["legal_id"],
            "text_availability": "metadata_only",
            "body_present": False,
            "expected_behavior": "surface_metadata_not_full_text",
            "must_not_claim_full_text": True,
            "rationale": (
                "Metadata-only Federal Register items must never masquerade "
                "as full-text body retrieval hits."
            ),
        },
        {
            "case_id": "mb-fcc-unavailable",
            "query_id": "q-test-missing-body-unavailable",
            "document_id": "doc:fcc-unavail-2024-02222",
            "legal_id": by_id["doc:fcc-unavail-2024-02222"]["legal_id"],
            "text_availability": "unavailable",
            "body_present": False,
            "expected_behavior": "disposition_unavailable_no_body",
            "must_not_claim_full_text": True,
            "rationale": (
                "Unavailable body dispositions are explicit missing-body "
                "cases for evaluation."
            ),
        },
        {
            "case_id": "mb-sba-abstract-only",
            "query_id": "q-test-missing-body-metadata",
            "document_id": "doc:sba-abstract-2011-03333",
            "legal_id": by_id["doc:sba-abstract-2011-03333"]["legal_id"],
            "text_availability": "abstract_only",
            "body_present": False,
            "expected_behavior": "abstract_not_full_text",
            "must_not_claim_full_text": True,
            "rationale": (
                "Abstract-only historical notices are not full-text bodies "
                "and must remain typed as non-body dispositions."
            ),
        },
    ]

    return queries, judgments, graph_paths, hard_negatives, missing_body_cases


def materialize_gold_payload() -> dict[str, Any]:
    """Materialize the full sealed gold payload from the compact recipe."""

    documents = build_gold_documents()
    (
        queries,
        judgments,
        graph_paths,
        hard_negatives,
        missing_body_cases,
    ) = build_gold_queries_and_labels(documents)

    partition_index: dict[str, list[str]] = {p: [] for p in PARTITIONS}
    for query in queries:
        partition_index[query["partition"]].append(query["query_id"])

    eras = sorted({str(doc["era"]) for doc in documents})
    agencies = sorted({str(doc["agency_code"]) for doc in documents})
    doc_types = sorted({str(doc["document_type"]) for doc in documents})
    years = sorted({str(doc["publication_date"])[:4] for doc in documents})

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "fixture_id": FIXTURE_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "description": (
            "Sealed temporally and agency-diverse Federal Register retrieval "
            "and graph gold set. Labels freeze exact document-number, "
            "agency/topic, proposed-vs-final, citation, correction/withdrawal, "
            "filter, hard-negative, missing-body, time-sensitive, and "
            "abstention expectations before retrieval tuning."
        ),
        "release_authority": {
            "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
            "provider": "federalregister.gov",
            "official_sources": ["federalregister.gov", "govinfo.gov"],
            "pinned_baseline_revision": PREVIOUS_PUBLIC_PIN,
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "role": "approved_exact",
        },
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "identity_contract": {
            "legal_id_format": "fr:<document_number>:<publication_date>[:qualifier...]",
            "entry_cid_role": "retrieval primary key for the sealed gold document stub",
            "source_cid_role": "content address of normalized official-source evidence stub",
            "entry_cid_algorithm": (
                "sha256-derived synthetic CIDv1-style token; prefix bafkreie; "
                "immutable for this fixture schema revision"
            ),
            "source_cid_algorithm": (
                "sha256-derived synthetic CIDv1-style token; prefix bafkreis; "
                "immutable for this fixture schema revision"
            ),
            "stability_rule": (
                "legal_id is publication-identity oriented and independent of "
                "content version; entry_cid and source_cid are stable fixture "
                "identities sealed with this schema revision."
            ),
        },
        "required_document_types": list(REQUIRED_DOCUMENT_TYPES),
        "required_agencies": list(REQUIRED_AGENCIES),
        "partitions": list(PARTITIONS),
        "partition_policy": {
            "train": (
                "Development examples for qualitative inspection and "
                "non-reporting iteration only; not used for final sealed metrics."
            ),
            "dev": (
                "Hyperparameter, fusion-weight, and probe-count selection. "
                "Metrics may guide tuning but are not the final reported numbers."
            ),
            "test": (
                "Sealed evaluation split. Tunable weights selected on dev are "
                "reported once on this split; no post-hoc label edits for score chasing."
            ),
        },
        "label_kinds": sorted(REQUIRED_LABEL_KINDS),
        "query_kinds": sorted(REQUIRED_QUERY_KINDS),
        "grades": list(GRADES),
        "diversity": {
            "agencies": agencies,
            "document_types": doc_types,
            "eras": eras,
            "publication_years": years,
            "min_agencies": len(REQUIRED_AGENCIES),
            "min_document_types": len(REQUIRED_DOCUMENT_TYPES),
            "min_publication_years": 5,
        },
        "documents": documents,
        "queries": queries,
        "judgments": judgments,
        "graph_paths": graph_paths,
        "hard_negatives": hard_negatives,
        "missing_body_cases": missing_body_cases,
        "filter_catalog": {
            "agency_codes": agencies,
            "document_types": doc_types,
            "date_bounds": {
                "earliest_publication_date": min(
                    d["publication_date"] for d in documents
                ),
                "latest_publication_date": max(
                    d["publication_date"] for d in documents
                ),
            },
        },
        "partition_index": partition_index,
        "counts": {
            "documents": len(documents),
            "queries": len(queries),
            "judgments": len(judgments),
            "graph_paths": len(graph_paths),
            "hard_negatives": len(hard_negatives),
            "missing_body_cases": len(missing_body_cases),
            "agencies": len(agencies),
            "document_types": len(doc_types),
            "partition_query_counts": {
                p: len(partition_index[p]) for p in PARTITIONS
            },
        },
        "frozen": True,
        "ground_truth_policy": GROUND_TRUTH_POLICY,
    }
    return apply_seal(payload)


def write_gold_fixture(path: Optional[PathLike] = None) -> Path:
    """Materialize and write the sealed gold fixture JSON; return the path."""

    target = resolve_gold_fixture_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = materialize_gold_payload()
    # Pretty-printed for review; seal is over the in-memory mapping, not the
    # pretty text, so reloads must parse JSON then verify digests.
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    target.write_text(text, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Load / validate
# ---------------------------------------------------------------------------


def is_recipe_fixture(payload: Mapping[str, Any]) -> bool:
    """Return True when *payload* is a compact recipe pointer (not fully expanded)."""

    if payload.get("use_builtin_recipe") is True:
        return True
    if payload.get("format") == "sealed_recipe_v1":
        return True
    # Fully expanded fixtures always carry documents + seal digests.
    if "documents" not in payload and payload.get("schema_version") == SCHEMA_VERSION:
        return True
    return False


def load_gold_fixture(path: Optional[PathLike] = None) -> dict[str, Any]:
    """Load the sealed gold fixture JSON as a plain dict.

    Compact recipe fixtures (``use_builtin_recipe`` / ``sealed_recipe_v1``)
    expand through :func:`materialize_gold_payload` so digests stay
    deterministic without bulk golden dumps in the recipe file.
    """

    target = resolve_gold_fixture_path(path)
    if not target.is_file():
        raise GoldFixtureNotFoundError(f"missing gold fixture: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise GoldSchemaError("gold fixture root must be a JSON object")
    if is_recipe_fixture(payload):
        if payload.get("schema_version") not in (None, SCHEMA_VERSION):
            raise GoldSchemaError(
                f"recipe schema_version must be {SCHEMA_VERSION!r}; "
                f"got {payload.get('schema_version')!r}"
            )
        if payload.get("task_id") not in (None, TASK_ID):
            raise GoldSchemaError(
                f"recipe task_id must be {TASK_ID!r}; got {payload.get('task_id')!r}"
            )
        return materialize_gold_payload()
    return payload

def _require_mapping_list(
    payload: Mapping[str, Any], key: str, *, minimum: int = 1
) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise GoldSchemaError(f"gold fixture missing non-empty list field {key!r}")
    if len(value) < minimum:
        raise GoldSchemaError(f"{key} must contain at least {minimum} items")
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise GoldSchemaError(f"{key}[{i}] must be an object")
    return list(value)


def validate_source_citations(documents: Sequence[Mapping[str, Any]]) -> None:
    """Every document must be source-cited with official URL and checksum."""

    for doc in documents:
        doc_id = doc.get("document_id")
        for field_name in (
            "document_id",
            "legal_id",
            "entry_cid",
            "source_cid",
            "document_number",
            "publication_date",
            "document_type",
            "agency_code",
            "agency_name",
            "title",
            "official_source_url",
            "source_checksum",
            "text_availability",
        ):
            if doc.get(field_name) in (None, ""):
                raise GoldSchemaError(f"document {doc_id!r} missing {field_name}")

        try:
            legal_id = validate_legal_id(doc["legal_id"])
            document_number = validate_document_number(doc["document_number"])
            publication_date = validate_publication_date(doc["publication_date"])
            official_url = validate_official_url(doc["official_source_url"])
            DocumentType.coerce(doc["document_type"])
            TextAvailability.coerce(doc["text_availability"])
            CorrectionRelation.coerce(doc.get("correction_relation", "none"))
        except Exception as exc:  # noqa: BLE001
            raise GoldSchemaError(f"document {doc_id!r}: {exc}") from exc

        if legal_id != f"fr:{document_number}:{publication_date}":
            # allow qualifier-bearing legal_ids that still start correctly
            if not legal_id.startswith(f"fr:{document_number}:{publication_date}"):
                raise GoldSchemaError(
                    f"document {doc_id!r} legal_id does not bind document_number/"
                    f"publication_date: {legal_id!r}"
                )

        if not _CID_RE.match(str(doc["entry_cid"])):
            raise GoldSchemaError(f"document {doc_id!r} invalid entry_cid")
        if not _CID_RE.match(str(doc["source_cid"])):
            raise GoldSchemaError(f"document {doc_id!r} invalid source_cid")
        if doc["entry_cid"] == doc["source_cid"]:
            raise GoldSchemaError(
                f"document {doc_id!r} entry_cid and source_cid must differ"
            )
        if not _SHA256_RE.match(str(doc["source_checksum"]).lower()):
            raise GoldSchemaError(f"document {doc_id!r} invalid source_checksum")
        if not _AGENCY_CODE_RE.match(str(doc["agency_code"])):
            raise GoldSchemaError(f"document {doc_id!r} invalid agency_code")

        expected_checksum = document_source_checksum(
            document_number=document_number,
            publication_date=publication_date,
            official_source_url=official_url,
            title=str(doc["title"]),
        )
        if str(doc["source_checksum"]).lower() != expected_checksum:
            raise GoldChecksumError(
                f"document {doc_id!r} source_checksum mismatch"
            )

        secondary = doc.get("secondary_source_url")
        if secondary:
            try:
                validate_official_url(secondary)
            except Exception as exc:  # noqa: BLE001
                raise GoldSchemaError(
                    f"document {doc_id!r} secondary_source_url: {exc}"
                ) from exc


def validate_diversity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Require temporal, agency, and document-type diversity."""

    documents = _require_mapping_list(payload, "documents", minimum=10)
    agencies = {str(d["agency_code"]) for d in documents}
    doc_types = {str(d["document_type"]) for d in documents}
    years = {str(d["publication_date"])[:4] for d in documents}
    eras = {str(d.get("era") or "") for d in documents}
    eras.discard("")

    missing_types = set(REQUIRED_DOCUMENT_TYPES) - doc_types
    if missing_types:
        raise GoldDiversityError(
            f"missing required document types: {sorted(missing_types)}"
        )
    missing_agencies = set(REQUIRED_AGENCIES) - agencies
    if missing_agencies:
        raise GoldDiversityError(
            f"missing required agencies: {sorted(missing_agencies)}"
        )
    if len(years) < 5:
        raise GoldDiversityError(
            f"expected at least 5 publication years for temporal diversity; got {sorted(years)}"
        )
    if len(eras) < 2:
        raise GoldDiversityError(
            f"expected multiple eras for temporal diversity; got {sorted(eras)}"
        )

    # Withdrawal coverage via correction_relation
    relations = {str(d.get("correction_relation") or "none") for d in documents}
    if "corrects" not in relations:
        raise GoldDiversityError("gold set must include a correction (corrects) document")
    if "withdraws" not in relations:
        raise GoldDiversityError("gold set must include a withdrawal (withdraws) document")

    return {
        "agencies": sorted(agencies),
        "document_types": sorted(doc_types),
        "publication_years": sorted(years),
        "eras": sorted(eras),
        "correction_relations": sorted(relations),
    }


def validate_partitions_leak_free(payload: Mapping[str, Any]) -> None:
    """Ensure train/dev/test query partitions are exclusive and leak-free."""

    queries = _require_mapping_list(payload, "queries", minimum=3)
    partition_index = payload.get("partition_index")
    if not isinstance(partition_index, dict):
        raise GoldLeakError("missing partition_index")

    for partition in PARTITIONS:
        if partition not in partition_index:
            raise GoldLeakError(f"partition_index missing {partition!r}")
        if not partition_index[partition]:
            raise GoldLeakError(f"partition {partition!r} has no queries")

    query_ids = [q["query_id"] for q in queries]
    if len(query_ids) != len(set(query_ids)):
        raise GoldLeakError("duplicate query_id values")

    seen: set[str] = set()
    for partition in PARTITIONS:
        for qid in partition_index[partition]:
            if qid in seen:
                raise GoldLeakError(
                    f"query {qid!r} assigned to multiple partitions"
                )
            seen.add(qid)
    if seen != set(query_ids):
        raise GoldLeakError("partition_index does not cover all queries exactly once")

    for query in queries:
        partition = query.get("partition")
        if partition not in PARTITIONS:
            raise GoldLeakError(f"query {query.get('query_id')!r} bad partition")
        if query["query_id"] not in partition_index[partition]:
            raise GoldLeakError(
                f"query {query['query_id']!r} not listed under its partition"
            )

    # Query-text leakage: identical texts must not cross partitions.
    text_to_partitions: dict[str, set[str]] = {}
    for query in queries:
        text = " ".join(str(query.get("query_text") or "").lower().split())
        if not text:
            raise GoldSchemaError(f"query {query['query_id']!r} empty query_text")
        text_to_partitions.setdefault(text, set()).add(query["partition"])
    for text, parts in text_to_partitions.items():
        if len(parts) > 1:
            raise GoldLeakError(
                f"query text crosses partitions {sorted(parts)}: {text[:80]!r}"
            )

    # Test judgments must not be editable via train-only query ids.
    judgments = _require_mapping_list(payload, "judgments", minimum=1)
    query_partition = {q["query_id"]: q["partition"] for q in queries}
    for judgment in judgments:
        qid = judgment.get("query_id")
        if qid not in query_partition:
            raise GoldLabelError(f"judgment references unknown query {qid!r}")


def validate_judgments_and_identities(payload: Mapping[str, Any]) -> None:
    """Judgments must join stable document identities; every query judged."""

    documents = _require_mapping_list(payload, "documents")
    queries = _require_mapping_list(payload, "queries")
    judgments = _require_mapping_list(payload, "judgments")

    docs_by_id = {d["document_id"]: d for d in documents}
    if len(docs_by_id) != len(documents):
        raise GoldSchemaError("duplicate document_id values")
    legal_ids = [d["legal_id"] for d in documents]
    if len(legal_ids) != len(set(legal_ids)):
        raise GoldSchemaError("duplicate legal_id values")
    entry_cids = [d["entry_cid"] for d in documents]
    if len(entry_cids) != len(set(entry_cids)):
        raise GoldSchemaError("duplicate entry_cid values")

    query_ids = {q["query_id"] for q in queries}
    judged: set[str] = set()
    for judgment in judgments:
        for field_name in (
            "query_id",
            "document_id",
            "legal_id",
            "entry_cid",
            "grade",
            "label_kind",
        ):
            if judgment.get(field_name) in (None, ""):
                raise GoldLabelError(f"judgment missing {field_name}")
        doc = docs_by_id.get(judgment["document_id"])
        if doc is None:
            raise GoldLabelError(
                f"judgment references unknown document {judgment['document_id']!r}"
            )
        if judgment["legal_id"] != doc["legal_id"]:
            raise GoldLabelError(
                f"judgment legal_id mismatch for {judgment['document_id']!r}"
            )
        if judgment["entry_cid"] != doc["entry_cid"]:
            raise GoldLabelError(
                f"judgment entry_cid mismatch for {judgment['document_id']!r}"
            )
        if judgment["query_id"] not in query_ids:
            raise GoldLabelError(
                f"judgment references unknown query {judgment['query_id']!r}"
            )
        judged.add(judgment["query_id"])

    missing = query_ids - judged
    if missing:
        raise GoldLabelError(
            f"queries without judgments: {sorted(missing)}"
        )


def validate_hard_negatives(payload: Mapping[str, Any]) -> None:
    """Hard negatives must exist, span partitions, and not exact-label banned docs."""

    hard_negatives = _require_mapping_list(payload, "hard_negatives", minimum=3)
    documents = _require_mapping_list(payload, "documents")
    judgments = _require_mapping_list(payload, "judgments")
    docs_by_id = {d["document_id"]: d for d in documents}

    exact_pairs = {
        (j["query_id"], j["document_id"])
        for j in judgments
        if j.get("grade") == "exact"
    }

    control_ids: list[str] = []
    partitions: Counter[str] = Counter()
    for control in hard_negatives:
        cid = control.get("control_id")
        if not cid:
            raise GoldLabelError("hard negative missing control_id")
        control_ids.append(str(cid))
        partition = control.get("partition")
        if partition not in PARTITIONS:
            raise GoldLabelError(f"hard negative {cid!r} bad partition")
        partitions[str(partition)] += 1
        for field_name in ("control_kind", "query_text", "expected_behavior", "rationale"):
            if control.get(field_name) in (None, ""):
                raise GoldLabelError(f"hard negative {cid!r} missing {field_name}")

        banned = control.get("must_not_grade_exact_document_ids") or []
        query_id = control.get("query_id")
        for doc_id in banned:
            if doc_id not in docs_by_id:
                raise GoldLabelError(
                    f"hard negative {cid!r} bans unknown document {doc_id!r}"
                )
            if query_id and (query_id, doc_id) in exact_pairs:
                raise GoldLabelError(
                    f"hard negative {cid!r} contradicts exact judgment for "
                    f"query={query_id!r} document={doc_id!r}"
                )

        preferred = control.get("preferred_document_ids") or []
        for doc_id in preferred:
            if doc_id not in docs_by_id:
                raise GoldLabelError(
                    f"hard negative {cid!r} prefers unknown document {doc_id!r}"
                )

    if len(control_ids) != len(set(control_ids)):
        raise GoldLabelError("duplicate hard-negative control_id values")
    for partition in PARTITIONS:
        if partitions[partition] < 1:
            raise GoldLabelError(
                f"hard negatives missing coverage for partition {partition!r}"
            )


def validate_missing_body_cases(payload: Mapping[str, Any]) -> None:
    """Missing-body cases must bind non-full-text dispositions and no full-text claim."""

    cases = _require_mapping_list(payload, "missing_body_cases", minimum=2)
    documents = _require_mapping_list(payload, "documents")
    docs_by_id = {d["document_id"]: d for d in documents}

    # At least one document in the corpus must itself be a non-body disposition.
    non_body_docs = [
        d
        for d in documents
        if str(d.get("text_availability")) in BODY_DISPOSITIONS_WITHOUT_FULL_TEXT
        or d.get("body_present") is False
    ]
    if len(non_body_docs) < 2:
        raise GoldLabelError(
            "expected at least two missing-body documents in the gold corpus"
        )

    case_ids: list[str] = []
    for case in cases:
        case_id = case.get("case_id")
        if not case_id:
            raise GoldLabelError("missing_body case missing case_id")
        case_ids.append(str(case_id))
        doc_id = case.get("document_id")
        doc = docs_by_id.get(doc_id)
        if doc is None:
            raise GoldLabelError(
                f"missing_body case {case_id!r} unknown document {doc_id!r}"
            )
        availability = str(case.get("text_availability") or doc.get("text_availability"))
        if availability not in BODY_DISPOSITIONS_WITHOUT_FULL_TEXT:
            raise GoldLabelError(
                f"missing_body case {case_id!r} must use a non-full-text disposition"
            )
        if case.get("must_not_claim_full_text") is not True:
            raise GoldLabelError(
                f"missing_body case {case_id!r} must set must_not_claim_full_text=true"
            )
        if case.get("body_present") is True or doc.get("body_present") is True:
            if availability in BODY_DISPOSITIONS_WITHOUT_FULL_TEXT:
                raise GoldLabelError(
                    f"missing_body case {case_id!r} cannot claim body_present with "
                    f"disposition {availability!r}"
                )
        if case.get("legal_id") != doc["legal_id"]:
            raise GoldLabelError(
                f"missing_body case {case_id!r} legal_id mismatch"
            )
        for field_name in ("expected_behavior", "rationale"):
            if case.get(field_name) in (None, ""):
                raise GoldLabelError(
                    f"missing_body case {case_id!r} missing {field_name}"
                )

    if len(case_ids) != len(set(case_ids)):
        raise GoldLabelError("duplicate missing_body case_id values")

    # No exact full-text grade on missing-body documents.
    judgments = _require_mapping_list(payload, "judgments")
    missing_body_doc_ids = {c["document_id"] for c in cases}
    for judgment in judgments:
        if judgment["document_id"] not in missing_body_doc_ids:
            continue
        if judgment.get("grade") == "exact" and judgment.get("label_kind") not in {
            "missing_body",
        }:
            raise GoldLabelError(
                f"missing-body document {judgment['document_id']!r} must not receive "
                f"an exact non-missing-body grade"
            )
        if judgment.get("grade") == "exact" and judgment.get("label_kind") == "exact_document":
            raise GoldLabelError(
                f"missing-body document {judgment['document_id']!r} exact_document grade forbidden"
            )


def validate_graph_paths(payload: Mapping[str, Any]) -> None:
    """Graph paths must reference stable nodes and include edges."""

    paths = _require_mapping_list(payload, "graph_paths", minimum=2)
    documents = _require_mapping_list(payload, "documents")
    queries = _require_mapping_list(payload, "queries")
    docs_by_id = {d["document_id"]: d for d in documents}
    query_ids = {q["query_id"] for q in queries}

    path_ids: list[str] = []
    for path in paths:
        path_id = path.get("path_id")
        if not path_id:
            raise GoldLabelError("graph path missing path_id")
        path_ids.append(str(path_id))
        if path.get("query_id") not in query_ids:
            raise GoldLabelError(
                f"graph path {path_id!r} references unknown query"
            )
        if path.get("partition") not in PARTITIONS:
            raise GoldLabelError(f"graph path {path_id!r} bad partition")
        nodes = path.get("nodes") or []
        node_refs = path.get("node_refs") or []
        edges = path.get("edges") or []
        if len(nodes) < 2:
            raise GoldLabelError(f"graph path {path_id!r} needs >= 2 nodes")
        if len(node_refs) != len(nodes):
            raise GoldLabelError(f"graph path {path_id!r} node_refs length mismatch")
        if not edges:
            raise GoldLabelError(f"graph path {path_id!r} missing edges")
        for node_id, ref in zip(nodes, node_refs):
            doc = docs_by_id.get(node_id)
            if doc is None:
                raise GoldLabelError(
                    f"graph path {path_id!r} unknown node {node_id!r}"
                )
            if ref.get("document_id") != node_id:
                raise GoldLabelError(
                    f"graph path {path_id!r} node_ref document_id mismatch"
                )
            if ref.get("legal_id") != doc["legal_id"]:
                raise GoldLabelError(
                    f"graph path {path_id!r} legal_id mismatch for {node_id!r}"
                )
            if ref.get("entry_cid") != doc["entry_cid"]:
                raise GoldLabelError(
                    f"graph path {path_id!r} entry_cid mismatch for {node_id!r}"
                )
        node_set = set(nodes)
        for edge in edges:
            if edge.get("source") not in node_set or edge.get("target") not in node_set:
                raise GoldLabelError(
                    f"graph path {path_id!r} edge endpoints must be path nodes"
                )
            if not edge.get("relation"):
                raise GoldLabelError(f"graph path {path_id!r} edge missing relation")

    if len(path_ids) != len(set(path_ids)):
        raise GoldLabelError("duplicate graph path_id values")


def validate_query_kind_coverage(payload: Mapping[str, Any]) -> None:
    """Require the sealed query and label kind taxonomies."""

    queries = _require_mapping_list(payload, "queries")
    judgments = _require_mapping_list(payload, "judgments")
    query_kinds = {q.get("query_kind") for q in queries}
    label_kinds = {j.get("label_kind") for j in judgments}
    missing_q = REQUIRED_QUERY_KINDS - query_kinds
    if missing_q:
        raise GoldSchemaError(f"missing query kinds: {sorted(missing_q)}")
    missing_l = REQUIRED_LABEL_KINDS - label_kinds
    if missing_l:
        raise GoldSchemaError(f"missing label kinds: {sorted(missing_l)}")


def validate_counts(payload: Mapping[str, Any]) -> None:
    """Reconcile declared counts with list lengths."""

    counts = payload.get("counts")
    if not isinstance(counts, dict):
        raise GoldSchemaError("missing counts object")
    mapping = {
        "documents": "documents",
        "queries": "queries",
        "judgments": "judgments",
        "graph_paths": "graph_paths",
        "hard_negatives": "hard_negatives",
        "missing_body_cases": "missing_body_cases",
    }
    for count_key, list_key in mapping.items():
        items = payload.get(list_key)
        if not isinstance(items, list):
            raise GoldSchemaError(f"missing list {list_key!r}")
        if counts.get(count_key) != len(items):
            raise GoldSchemaError(
                f"counts.{count_key}={counts.get(count_key)} != len({list_key})={len(items)}"
            )
    partition_counts = counts.get("partition_query_counts") or {}
    partition_index = payload.get("partition_index") or {}
    for partition in PARTITIONS:
        expected = len(partition_index.get(partition) or [])
        if partition_counts.get(partition) != expected:
            raise GoldSchemaError(
                f"partition_query_counts[{partition}] mismatch"
            )


def validate_gold_payload(payload: Mapping[str, Any], *, verify_seal: bool = True) -> str:
    """Run the full gold integrity suite; return the verified manifest digest."""

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise GoldSchemaError(
            f"schema_version must be {SCHEMA_VERSION!r}; got {payload.get('schema_version')!r}"
        )
    if payload.get("fixture_id") != FIXTURE_ID:
        raise GoldSchemaError(f"fixture_id must be {FIXTURE_ID!r}")
    if payload.get("task_id") != TASK_ID:
        raise GoldSchemaError(f"task_id must be {TASK_ID!r}")
    if payload.get("frozen") is not True:
        raise GoldSchemaError("gold fixture must be frozen=true")
    if not payload.get("ground_truth_policy"):
        raise GoldSchemaError("missing ground_truth_policy")
    if not payload.get("currentness_disclaimer"):
        raise GoldSchemaError("missing currentness_disclaimer")
    release = payload.get("release_authority")
    if not isinstance(release, dict) or not release.get("observation_cutoff"):
        raise GoldSchemaError("release_authority.observation_cutoff required")
    if not release.get("pinned_baseline_revision"):
        raise GoldSchemaError("release_authority.pinned_baseline_revision required")

    documents = _require_mapping_list(payload, "documents", minimum=10)
    validate_source_citations(documents)
    validate_diversity(payload)
    validate_partitions_leak_free(payload)
    validate_judgments_and_identities(payload)
    validate_hard_negatives(payload)
    validate_missing_body_cases(payload)
    validate_graph_paths(payload)
    validate_query_kind_coverage(payload)
    validate_counts(payload)

    digest = ""
    if verify_seal:
        digest = verify_checksum_seal(payload)
    return digest


def load_and_validate_gold(
    path: Optional[PathLike] = None,
    *,
    verify_seal: bool = True,
) -> dict[str, Any]:
    """Load the sealed fixture and validate all acceptance invariants."""

    payload = load_gold_fixture(path)
    validate_gold_payload(payload, verify_seal=verify_seal)
    return payload


# ---------------------------------------------------------------------------
# Typed evaluator view
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FederalRegisterGoldSet:
    """Immutable evaluator-facing view of the sealed gold fixture."""

    payload: Mapping[str, Any]
    path: Optional[Path] = None
    manifest_digest: str = ""

    @property
    def documents(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.payload["documents"])

    @property
    def queries(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.payload["queries"])

    @property
    def judgments(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.payload["judgments"])

    @property
    def hard_negatives(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.payload["hard_negatives"])

    @property
    def missing_body_cases(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.payload["missing_body_cases"])

    @property
    def graph_paths(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.payload["graph_paths"])

    def documents_by_id(self) -> Mapping[str, Mapping[str, Any]]:
        return MappingProxyType(
            {d["document_id"]: d for d in self.payload["documents"]}
        )

    def queries_for_partition(self, partition: str) -> tuple[Mapping[str, Any], ...]:
        if partition not in PARTITIONS:
            raise GoldSchemaError(f"unknown partition: {partition!r}")
        return tuple(q for q in self.queries if q["partition"] == partition)

    def judgments_for_query(self, query_id: str) -> tuple[Mapping[str, Any], ...]:
        return tuple(j for j in self.judgments if j["query_id"] == query_id)

    def filter_documents(
        self,
        *,
        agency_code: Optional[str] = None,
        document_type: Optional[str] = None,
        publication_date_from: Optional[str] = None,
        publication_date_to: Optional[str] = None,
    ) -> tuple[Mapping[str, Any], ...]:
        """Apply agency/date/type filters used by sealed filter queries."""

        results: list[Mapping[str, Any]] = []
        for doc in self.documents:
            if agency_code is not None and doc["agency_code"] != agency_code:
                continue
            if document_type is not None and doc["document_type"] != document_type:
                continue
            pub = str(doc["publication_date"])
            if publication_date_from is not None and pub < publication_date_from:
                continue
            if publication_date_to is not None and pub > publication_date_to:
                continue
            results.append(doc)
        return tuple(results)


def load_gold_set(
    path: Optional[PathLike] = None,
    *,
    verify_seal: bool = True,
) -> FederalRegisterGoldSet:
    """Load and validate the sealed gold set for evaluators."""

    resolved = resolve_gold_fixture_path(path)
    payload = load_and_validate_gold(resolved, verify_seal=verify_seal)
    digest = str(payload.get("manifest_digest") or "")
    if verify_seal and not digest:
        digest = compute_manifest_digest(payload)
    return FederalRegisterGoldSet(
        payload=MappingProxyType(dict(payload)),
        path=resolved,
        manifest_digest=digest,
    )


def diversity_report(payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Return a compact diversity report for diagnostics."""

    data = payload if payload is not None else load_gold_fixture()
    return validate_diversity(data)


__all__ = [
    "BODY_DISPOSITIONS_WITHOUT_FULL_TEXT",
    "CURRENTNESS_DISCLAIMER",
    "FIXTURE_FILENAME",
    "FIXTURE_ID",
    "GOAL_ID",
    "GRADES",
    "GROUND_TRUTH_POLICY",
    "PARTITIONS",
    "PROGRAM_ID",
    "REQUIRED_AGENCIES",
    "REQUIRED_DOCUMENT_TYPES",
    "REQUIRED_LABEL_KINDS",
    "REQUIRED_QUERY_KINDS",
    "SCHEMA_VERSION",
    "TASK_ID",
    "FederalRegisterGoldError",
    "FederalRegisterGoldSet",
    "GoldChecksumError",
    "GoldDiversityError",
    "GoldFixtureNotFoundError",
    "GoldLabelError",
    "GoldLeakError",
    "GoldSchemaError",
    "apply_seal",
    "build_gold_documents",
    "build_gold_queries_and_labels",
    "compute_content_checksum",
    "compute_manifest_digest",
    "default_gold_fixture_path",
    "diversity_report",
    "document_source_checksum",
    "is_recipe_fixture",
    "load_and_validate_gold",
    "load_gold_fixture",
    "load_gold_set",
    "materialize_gold_payload",
    "resolve_gold_fixture_path",
    "sealed_body",
    "sealed_entry_cid",
    "sealed_source_cid",
    "validate_counts",
    "validate_diversity",
    "validate_gold_payload",
    "validate_graph_paths",
    "validate_hard_negatives",
    "validate_judgments_and_identities",
    "validate_missing_body_cases",
    "validate_partitions_leak_free",
    "validate_query_kind_coverage",
    "validate_source_citations",
    "verify_checksum_seal",
    "write_gold_fixture",
]


if __name__ == "__main__":
    out = write_gold_fixture()
    gold = load_and_validate_gold(out)
    print(f"wrote {out}")
    print(f"manifest_digest={gold['manifest_digest']}")
    print(
        "counts=",
        json.dumps(gold["counts"], sort_keys=True),
    )
