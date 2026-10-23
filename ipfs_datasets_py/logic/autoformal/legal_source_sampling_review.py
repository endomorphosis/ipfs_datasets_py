"""Replay-bound source-sampling review intake; declarations never grant admission.

The sampler owns source extraction, occurrence identity and open context. This
adapter retains its complete report once and adds blank guides and separately
recorded, unverified reviewer declarations. No signer, trust policy, adjudicator,
model, loader callback, clock, persistence or external I/O is supplied here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime

SCHEMA = "legal-source-sampling-review-bundle/v1"
MANIFEST_SCHEMA = "legal-source-sampling-review-manifest/v1"
CATALOG_SCHEMA = "legal-source-sampling-review-questions/v1"
GUIDE_SCHEMA = "legal-source-sampling-review-blank-guide/v1"
RESPONSE_SCHEMA = "legal-source-sampling-review-declaration/v1"
POPULATION_SCHEMA = "legal-source-sampling-review-population/v1"
SAMPLING_SCHEMA = "legal-source-structured-sampling/v1"
UNIT_SCHEMA = "legal-source-structured-sample-unit/v1"
DEFAULT_LIMITS = {
    "max_bundle_bytes": 64 * 1024 * 1024,
    "max_subjects": 4096,
    "max_responses": 8192,
    "max_response_bytes": 1024 * 1024,
    "max_population_input_bytes": 64 * 1024 * 1024,
}
FALSE_FLAGS = dict.fromkeys(
    (
        "reviewer_identity_authenticated",
        "reviewer_independence_verified",
        "source_findings_verified",
        "source_context_resolved",
        "meaning_admitted",
        "semantic_graph_admitted",
        "training_gold_qualified",
        "evaluation_gold_qualified",
        "Lean_admitted",
        "proof_authority",
        "signature_verified",
    ),
    False,
)
CATALOG_PROVENANCE = {
    "artifact_name": "packet-fit-v01.json",
    "artifact_sha256": "72b2f94b893f36d6021822e48849259ed11db7fb64645a745c802ec5f1f5fb4a",
    "retained_question_count": 13,
    "added_norm_question_ids": ["meaning_statement", "meaning_arguments_qualifiers"],
    "authentication_or_admission_equivalence_claimed": False,
}
QUESTIONS = (
    (
        "source_role",
        "source",
        "Propose the source role of this exact occurrence: definition, introductory scope text, list/continuation, repeal marker, construction rule, note, other or unresolved. Name source evidence and keep extractor labels observational.",
    ),
    (
        "authority_edition",
        "source",
        "Identify publication, edition, legal time and governing-source evidence independently. Byte custody and an acquisition URL do not settle applicability or currentness.",
    ),
    (
        "scope_applicability",
        "source",
        "Identify exact scope-introduction text and any limiting subject, title, section, sense, event or date. Record inheritance as a proposal with evidence; do not default to section-local or global.",
    ),
    (
        "complete_meaning_unit",
        "source",
        "Identify every physical paragraph required for the proposed meaning unit, including introduction, enumerated members, exclusions, tail text and antecedents. Retain each source occurrence; paragraph boundaries do not certify completeness.",
    ),
    (
        "dependency_inventory",
        "source",
        "Record necessary definitions, authority, antecedents, shared qualifiers, temporal origin and referenced provisions; unavailable evidence remains unavailable. The six categories are a checklist, not an exhaustive inventory.",
    ),
    (
        "reference_targets",
        "source",
        "Record exact referenced provision/source identities or competing and unavailable targets. Distinguish a locator from an applicable reviewed definition binding.",
    ),
    (
        "notes_construction",
        "source",
        "Inspect retained notes, construction rules, repeal text and edition observations for potentially relevant evidence. Record unavailable or unsupported application rather than assuming notes are irrelevant.",
    ),
    (
        "definition_operator",
        "meaning",
        "Propose which source operator(s) occur: means, includes, exclusion, refers-to, construction rule, other or unresolved. Give exact selectors and rationale; no operator is automatically translated to biconditional.",
    ),
    (
        "term_and_sense",
        "meaning",
        "Propose the exact defined expression, senses and source occurrences. Repeated labels may denote distinct scoped senses; labels alone do not identify an entity or Lean symbol.",
    ),
    (
        "body_structure",
        "meaning",
        "Propose the complete definiens and constituent list/boolean/qualified structure with each source occurrence, including alternatives and exclusions. Preserve ambiguity and unsupported constructions.",
    ),
    (
        "legal_sort_arity",
        "meaning",
        "Propose the legal sort, arguments, relations and temporal parameters needed. Mark unsupported multi-argument, role-dependent, intensional or temporal meaning; do not squeeze into the existing unary profile.",
    ),
    (
        "definition_use",
        "meaning",
        "Propose any use-to-definition relation only by exact use occurrence, exact scoped sense/definition occurrence, proposed applicability and evidence. Cross-section lexical matches remain search observations.",
    ),
    (
        "formal_profile_fit",
        "meaning",
        "Identify whether the reviewed meaning fits an existing native profile or needs a separately specified extension. Formal ASTs, target symbols and assumptions remain blank until that profile and mapping exist.",
    ),
    (
        "meaning_statement",
        "meaning",
        "Propose the complete meaning, if supportable, without omitting material text; this is not an admitted target.",
    ),
    (
        "meaning_arguments_qualifiers",
        "meaning",
        "Account for arguments, quantifiers, conditions, exceptions, approvals, numbers and time, or explain non-applicability.",
    ),
)
ANSWER_FIELDS = {
    "question_id",
    "disposition",
    "finding",
    "rationale",
    "evidence_refs",
    "unresolved_requirements",
}
SOURCE_DISPOSITIONS = {
    "evidence_declared",
    "unresolved",
    "disputed",
    "unsupported",
    "not_applicable",
}
MEANING_DISPOSITIONS = {
    "proposal",
    "unresolved",
    "disputed",
    "unsupported",
    "not_applicable",
}
DECLARATION_FIELDS = {
    "bundle_sha256",
    "question_catalog_ref",
    "subject_ref",
    "reviewer_declaration",
    "exposure_declaration",
    "source_answers",
    "meaning_proposals",
}
REVIEWER_FIELDS = {
    "principal_id",
    "role",
    "issued_at_utc",
    "identity_evidence_refs",
    "independence_evidence_refs",
}
EXPOSURE_FIELDS = {
    "candidate_interpretations_exposed",
    "organizer_source_metadata_exposed",
    "other_exposure",
}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, fields, label):
    _need(
        type(value) is dict and set(value) == set(fields),
        "closed " + label + " fields required",
    )


def _sha(value, label):
    _need(
        type(value) is str and _SHA.fullmatch(value) is not None,
        "independent lowercase SHA256 required: " + label,
    )


def _text(value, label, *, maximum=16384):
    _need(
        type(value) is str
        and value.strip()
        and "\x00" not in value
        and len(value) <= maximum,
        "bounded nonblank text required: " + label,
    )
    try:
        _need(
            len(value.encode("utf-8")) <= maximum, "UTF8 byte bound exceeded: " + label
        )
    except UnicodeError as error:
        raise ValueError("valid UTF8 required: " + label) from error


def _wire(value, maximum):
    """Bound ordinary JSON before serialization, imports or source replay."""
    nodes, remaining = 2_000_000, maximum

    def visit(item, depth):
        nonlocal nodes, remaining
        nodes -= 1
        _need(nodes >= 0 and depth <= 64, "review JSON node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(
                    type(key) is str and "\x00" not in key,
                    "ordinary JSON keys required",
                )
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need(
                "\x00" not in item and len(item) <= remaining,
                "review JSON string/byte bound exceeded",
            )
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid review UTF8 required") from error
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded review integer required")
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite review JSON required")
            remaining -= 32
        else:
            raise ValueError("ordinary review JSON values required")
        _need(remaining >= 0, "review JSON byte bound exceeded")

    visit(value, 0)
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    _need(len(raw) <= maximum, "complete review JSON byte bound exceeded")
    return raw


def _digest(value, maximum=64 * 1024 * 1024):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _copy(value, maximum):
    return json.loads(_wire(value, maximum))


def _limits(value):
    _need(
        value is None or type(value) is dict and not (set(value) - set(DEFAULT_LIMITS)),
        "closed lowered review limits required",
    )
    result = dict(DEFAULT_LIMITS, **(value or {}))
    _need(
        all(type(v) is int and 0 < v <= DEFAULT_LIMITS[k] for k, v in result.items()),
        "positive lowered review limits required",
    )
    return result


def _owners():
    # Fixed operation owners; public module import itself remains stdlib-only.
    from . import legal_source_sampling
    from .corpus_contracts import seal_record

    return legal_source_sampling, seal_record


def _ref(record):
    return {
        "schema": record["schema"],
        "record_cid": record["record_cid"],
        "sha256": _digest(record),
    }


def _evidence(kind, index, value):
    return {"kind": kind, "index": index, "sha256": _digest(value)}


def _blank_answer(question_id):
    return dict(
        question_id=question_id,
        disposition=None,
        finding=None,
        rationale=None,
        evidence_refs=[],
        unresolved_requirements=[],
    )


def _input_snapshot(raw, expected_sampling_report_sha256, inputs):
    _sha(expected_sampling_report_sha256, "complete sampler report")
    required = {
        "descriptor",
        "expected_descriptor_sha256",
        "expected_raw_sha256",
        "expected_raw_bytes",
    }
    _need(
        type(inputs) is dict
        and required <= set(inputs) <= required | {"view_limits", "sampling_limits"},
        "closed sampler replay inputs required",
    )
    detached = _copy(inputs, 1024 * 1024)
    _sha(detached["expected_descriptor_sha256"], "acquisition descriptor")
    _sha(detached["expected_raw_sha256"], "raw source")
    count = detached["expected_raw_bytes"]
    _need(
        type(count) is int and 0 < count <= 8_000_000,
        "bounded acquisition raw size required",
    )
    _need(
        raw is None or type(raw) is bytes and len(raw) <= 8_000_000,
        "immutable bounded raw bytes or explicit missing source required",
    )
    if raw is not None:
        _need(
            len(raw) == count
            and hashlib.sha256(raw).hexdigest() == detached["expected_raw_sha256"],
            "independent raw source pin differs",
        )
    return detached


def _subjects(report):
    units = [r for r in report["records"] if r["schema"] == UNIT_SCHEMA]
    _need(
        [_ref(r) for r in units] == report["unit_refs"],
        "complete ordered sampler unit references required",
    )
    for index, unit in enumerate(units):
        _need(
            type(unit["ordinal"]) is int and unit["ordinal"] == index,
            "original DOM order required",
        )
        yield {"kind": "unit", "index": index, "sha256": _digest(unit)}, unit
    for index, retained in enumerate(report["withheld_paragraph_contexts"]):
        yield (
            {"kind": "withheld_context", "index": index, "sha256": _digest(retained)},
            retained,
        )


def _subject_evidence(report, subject, value, shared):
    # Full view is shared evidence; occurrence-specific selectors remain distinct.
    refs = [shared["view"]]
    cids = {
        value[k]["record_cid"]
        for k in ("source_version_ref", "source_occurrence_ref", "context_ref")
        if k in value
    }
    if subject["kind"] == "unit":
        cids.add(value["record_cid"])
    for index, retained in enumerate(report["withheld_paragraph_contexts"]):
        if (
            subject["kind"] == "withheld_context"
            and subject["index"] == index
            or subject["kind"] == "unit"
            and value["ordinal"] in retained["block_indices"]
        ):
            refs.append(shared["withheld"][index])
            cids.update(
                retained[k]["record_cid"]
                for k in ("source_occurrence_ref", "context_ref")
            )
    cids.update(shared["versions"])
    _need(
        all(cid in shared["records"] for cid in cids),
        "complete sampler occurrence/context/version closure required",
    )
    selected = [ref for cid in cids for ref in shared["records"][cid]]
    refs.extend(sorted(selected, key=lambda ref: ref["index"]))
    return refs


def _build(report, expected_report, binding, bounds, seal):
    catalog = seal(
        dict(
            schema=CATALOG_SCHEMA,
            catalog_provenance=CATALOG_PROVENANCE,
            questions=[
                dict(question_id=q, category=k, prompt=p) for q, k, p in QUESTIONS
            ],
            authority=dict(FALSE_FLAGS),
        )
    )
    subjects = list(_subjects(report))
    _need(
        len(subjects) <= bounds["max_subjects"],
        "complete unit plus withheld subject population exceeds bound",
    )
    # Hash the complete shared view and each record once, not once per guide.
    shared = dict(
        view=_evidence("document_view", 0, report["document_view_report"]),
        records={},
        versions=[],
        withheld=[
            _evidence("withheld_context", i, row)
            for i, row in enumerate(report["withheld_paragraph_contexts"])
        ],
    )
    for index, row in enumerate(report["records"]):
        shared["records"].setdefault(row["record_cid"], []).append(
            _evidence("sampling_record", index, row)
        )
        if row["schema"] == "legal-corpus-source-version/v1":
            shared["versions"].append(row["record_cid"])
    catalog_ref = _ref(catalog)
    guides = []
    used = len(_wire(report, 32 * 1024 * 1024)) + len(_wire(catalog, 1024 * 1024))
    for subject, value in subjects:
        # The final bundle digest cannot appear inside its own hashed template.
        # Reviewers must fill this placeholder explicitly after preparation.
        template = dict(
            bundle_sha256=None,
            question_catalog_ref=catalog_ref,
            subject_ref=subject,
            source_answers=[
                _blank_answer(q) for q, kind, _ in QUESTIONS if kind == "source"
            ],
            meaning_proposals=[
                _blank_answer(q) for q, kind, _ in QUESTIONS if kind == "meaning"
            ],
            reviewer_declaration={k: None for k in REVIEWER_FIELDS},
            exposure_declaration={k: None for k in EXPOSURE_FIELDS},
        )
        guide = seal(
            dict(
                schema=GUIDE_SCHEMA,
                subject_ref=subject,
                question_catalog_ref=catalog_ref,
                source_occurrence_ref=value["source_occurrence_ref"],
                context_ref=value["context_ref"],
                sampling_stratum=value.get(
                    "sampling_stratum", "withheld_parent_context"
                ),
                evidence_refs=_subject_evidence(report, subject, value, shared),
                response_template=template,
                unanswered_question_ids=[q for q, _, _ in QUESTIONS],
                unresolved=True,
                status="blank_not_a_review",
                authority=dict(FALSE_FLAGS),
                training_mask=0,
                evaluation_gold_mask=0,
            )
        )
        used += len(_wire(guide, 1024 * 1024))
        _need(
            used <= bounds["max_bundle_bytes"],
            "complete review bundle byte bound exceeded; truncation refused",
        )
        guides.append(guide)
    manifest = seal(
        dict(
            schema=MANIFEST_SCHEMA,
            sampling_report_sha256=expected_report,
            input_binding=binding,
            question_catalog_ref=_ref(catalog),
            guides_sha256=_digest(guides),
            counts=dict(
                units=len(report["unit_refs"]),
                withheld_contexts=len(report["withheld_paragraph_contexts"]),
                subjects=len(subjects),
                strata=dict(report["counts"]["strata"]),
            ),
            source_status=report["status"],
            sampling_report_stored_once=True,
            coordinate_profile="sampler_markup_v2_only_not_native_v1_or_raw_HTML_offsets",
            status="blank_bundle_not_a_review",
            authority=dict(FALSE_FLAGS),
            training_mask=0,
            evaluation_gold_mask=0,
        )
    )
    bundle = dict(
        schema=SCHEMA,
        limits=bounds,
        manifest=manifest,
        sampling_report=report,
        question_catalog=catalog,
        guides=guides,
    )
    return _copy(bundle, bounds["max_bundle_bytes"])


def prepare_sampling_review_bundle(
    raw, *, expected_sampling_report_sha256, limits=None, **sampling_inputs
):
    """Regenerate the pinned sampler once; retain every unit and withheld parent."""
    bounds = _limits(limits)
    binding = _input_snapshot(raw, expected_sampling_report_sha256, sampling_inputs)
    sampler, seal = _owners()
    args = dict(binding)
    args["limits"] = args.pop("sampling_limits", None)
    report = sampler.prepare_source_sampling(raw, **args)
    report = _copy(report, 32 * 1024 * 1024)
    _need(
        report.get("schema") == SAMPLING_SCHEMA
        and _digest(report) == expected_sampling_report_sha256,
        "independent full regenerated sampling report pin differs",
    )
    return _build(report, expected_sampling_report_sha256, binding, bounds, seal)


def sampling_review_bundle_sha256(bundle):
    """Hash the complete bounded canonical bundle, including its blank templates."""
    _need(
        type(bundle) is dict and bundle.get("schema") == SCHEMA,
        "sampling review bundle required",
    )
    bounds = _limits(bundle.get("limits"))
    return _digest(bundle, bounds["max_bundle_bytes"])


def validate_sampling_review_bundle(
    bundle, raw, *, expected_bundle_sha256, **replay_inputs
):
    """Bound and pin offered bytes before fixed-owner source regeneration."""
    _sha(expected_bundle_sha256, "complete review bundle")
    _need(type(bundle) is dict, "review bundle object required")
    _keys(
        bundle,
        {
            "schema",
            "limits",
            "manifest",
            "sampling_report",
            "question_catalog",
            "guides",
        },
        "review bundle",
    )
    bounds = _limits(bundle["limits"])
    offered = _copy(bundle, bounds["max_bundle_bytes"])
    _need(
        type(offered["guides"]) is list
        and len(offered["guides"]) <= bounds["max_subjects"],
        "bounded complete guide population required",
    )
    _need(
        _digest(offered, bounds["max_bundle_bytes"]) == expected_bundle_sha256,
        "independent review bundle pin differs",
    )
    _need(
        "limits" not in replay_inputs,
        "bundle limits are taken from its independently pinned value",
    )
    expected = prepare_sampling_review_bundle(raw, limits=bounds, **replay_inputs)
    _need(
        offered == expected,
        "review bundle differs from exact complete sampler regeneration",
    )
    return expected


def _declaration_snapshot(value, bounds):
    _keys(value, DECLARATION_FIELDS, "reviewer declaration")
    return _copy(value, bounds["max_response_bytes"])


def _checked_declaration(value, bundle, bundle_sha, *, _extra_evidence_refs=()):
    _keys(value, DECLARATION_FIELDS, "reviewer declaration")
    _sha(value["bundle_sha256"], "reviewer-declared complete bundle")
    _need(
        value["bundle_sha256"] == bundle_sha,
        "reviewer declaration binds another bundle",
    )
    subject = value["subject_ref"]
    _keys(subject, {"kind", "index", "sha256"}, "sampler review subject")
    _need(
        type(subject["kind"]) is str
        and subject["kind"] in ("unit", "withheld_context")
        and type(subject["index"]) is int
        and subject["index"] >= 0,
        "typed sampler subject kind/index required",
    )
    _sha(subject["sha256"], "sampler review subject")
    matches = [g for g in bundle["guides"] if g["subject_ref"] == value["subject_ref"]]
    _need(len(matches) == 1, "exact current unit or withheld subject required")
    guide = matches[0]
    _need(
        value["question_catalog_ref"] == guide["question_catalog_ref"],
        "reviewer declaration binds another question catalog",
    )
    reviewer, exposure = value["reviewer_declaration"], value["exposure_declaration"]
    _keys(reviewer, REVIEWER_FIELDS, "explicit reviewer declaration")
    _text(reviewer["principal_id"], "declared principal", maximum=256)
    _need(
        reviewer["role"] in ("source_reviewer", "legal_reviewer", "formal_reviewer"),
        "declared review role required",
    )
    stamp = reviewer["issued_at_utc"]
    _need(
        type(stamp) is str
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp) is not None,
        "explicit UTC declaration time required",
    )
    try:
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError("valid UTC declaration time required") from error
    for key in ("identity_evidence_refs", "independence_evidence_refs"):
        refs = reviewer[key]
        _need(
            type(refs) is list
            and len(refs) <= 32
            and all(type(r) is str for r in refs)
            and len(set(refs)) == len(refs),
            "bounded distinct declared evidence IDs required",
        )
        for ref in refs:
            _text(ref, "external evidence ID", maximum=512)
    _keys(exposure, EXPOSURE_FIELDS, "explicit exposure declaration")
    _need(
        all(
            exposure[k] is None or type(exposure[k]) is bool
            for k in (
                "candidate_interpretations_exposed",
                "organizer_source_metadata_exposed",
            )
        ),
        "exposure must be declared true/false or explicitly unknown",
    )
    _need(
        exposure["other_exposure"] is None
        or type(exposure["other_exposure"]) is list
        and len(exposure["other_exposure"]) <= 32,
        "other exposure must be an explicit list or unknown",
    )
    for item in exposure["other_exposure"] or []:
        _text(item, "other exposure", maximum=4096)
    allowed = {_digest(ref) for ref in guide["evidence_refs"]}
    # Only the separately replayed context profile supplies these scoped refs.
    # The v1 entry points always retain the original, empty extension.
    allowed.update(_digest(ref) for ref in _extra_evidence_refs)
    for field, kind, dispositions in (
        ("source_answers", "source", SOURCE_DISPOSITIONS),
        ("meaning_proposals", "meaning", MEANING_DISPOSITIONS),
    ):
        answers = value[field]
        ids = [q for q, category, _ in QUESTIONS if category == kind]
        _need(
            type(answers) is list and len(answers) == len(ids),
            "complete distinct source and meaning question coverage required",
        )
        for answer, question_id in zip(answers, ids, strict=True):
            _keys(answer, ANSWER_FIELDS, "typed answer")
            _need(
                answer["question_id"] == question_id
                and type(answer["disposition"]) is str
                and answer["disposition"] in dispositions,
                "fixed ordered question/category/disposition required",
            )
            _text(answer["finding"], "finding or proposal")
            _text(answer["rationale"], "rationale")
            refs = answer["evidence_refs"]
            _need(
                type(refs) is list and len(refs) <= len(allowed),
                "bounded available evidence references required",
            )
            hashes = [_digest(ref) for ref in refs]
            _need(
                len(set(hashes)) == len(hashes) and all(h in allowed for h in hashes),
                "exact subject-scoped or shared-view evidence required",
            )
            if answer["disposition"] in ("evidence_declared", "proposal"):
                _need(
                    bool(refs),
                    "a substantive declaration needs cited available evidence",
                )
            unresolved = answer["unresolved_requirements"]
            _need(
                type(unresolved) is list and len(unresolved) <= 32,
                "structured unresolved requirements required",
            )
            for item in unresolved:
                _text(item, "unresolved requirement", maximum=4096)
            if answer["disposition"] == "unresolved":
                _need(bool(unresolved), "unresolved disposition requires explicit gaps")
            if answer["disposition"] in (
                "evidence_declared",
                "proposal",
                "not_applicable",
            ):
                _need(
                    not unresolved,
                    "substantive or nonapplicable declarations cannot conceal structured unresolved gaps",
                )
    return guide


def _response(value, bundle, bundle_sha, seal):
    _checked_declaration(value, bundle, bundle_sha)
    return seal(
        dict(
            schema=RESPONSE_SCHEMA,
            **value,
            status="recorded_unverified_declaration",
            authority=dict(FALSE_FLAGS),
            training_mask=0,
            evaluation_gold_mask=0,
        )
    )


def record_sampling_review_response(
    bundle, declaration, raw, *, expected_bundle_sha256, **replay_inputs
):
    """Record supplied answers, not a signature, verified meaning or gold target."""
    bounds = _limits(bundle.get("limits") if type(bundle) is dict else None)
    value = _declaration_snapshot(declaration, bounds)
    _need(
        value["bundle_sha256"] == expected_bundle_sha256,
        "reviewer declaration binds another bundle",
    )
    expected = validate_sampling_review_bundle(
        bundle, raw, expected_bundle_sha256=expected_bundle_sha256, **replay_inputs
    )
    _, seal = _owners()
    return _response(value, expected, expected_bundle_sha256, seal)


def _response_snapshot(response, expected_pin, bounds):
    _sha(expected_pin, "complete reviewer response")
    value = _copy(response, bounds["max_response_bytes"])
    fields = DECLARATION_FIELDS | {
        "schema",
        "bundle_sha256",
        "question_catalog_ref",
        "status",
        "authority",
        "training_mask",
        "evaluation_gold_mask",
        "record_cid",
        "cid_scope",
    }
    _keys(value, fields, "sealed unverified response")
    _need(
        _digest(value, bounds["max_response_bytes"]) == expected_pin,
        "independent complete response pin differs",
    )
    return value


def _validate_response(response, bundle, bundle_sha, seal):
    _need(
        response["schema"] == RESPONSE_SCHEMA
        and response["bundle_sha256"] == bundle_sha,
        "response belongs to another schema/bundle",
    )
    value = {k: response[k] for k in DECLARATION_FIELDS}
    expected = _response(value, bundle, bundle_sha, seal)
    _need(
        response == expected,
        "response differs from exact typed declaration regeneration",
    )
    return expected


def validate_sampling_review_response(
    response,
    bundle,
    raw,
    *,
    expected_response_sha256,
    expected_bundle_sha256,
    **replay_inputs,
):
    """Replay the bundle and regenerate the independently pinned declaration."""
    bounds = _limits(bundle.get("limits") if type(bundle) is dict else None)
    offered = _response_snapshot(response, expected_response_sha256, bounds)
    expected = validate_sampling_review_bundle(
        bundle, raw, expected_bundle_sha256=expected_bundle_sha256, **replay_inputs
    )
    _, seal = _owners()
    return _validate_response(offered, expected, expected_bundle_sha256, seal)


def _population_state(responses):
    if not responses:
        return "pending", ["no_declaration"]
    disagreements, gaps, unsupported = [], [], []
    for question_id, category, _ in QUESTIONS:
        field = "source_answers" if category == "source" else "meaning_proposals"
        answers = [
            next(a for a in r[field] if a["question_id"] == question_id)
            for r in responses
        ]
        positions = {a["disposition"] for a in answers}
        if "disputed" in positions or len(positions - {"unresolved"}) > 1:
            disagreements.append("structured_disagreement:" + question_id)
        if "unsupported" in positions:
            unsupported.append("declared_unsupported_not_legally_false:" + question_id)
        if "unresolved" in positions:
            gaps.append("unresolved_question:" + question_id)
    for field in sorted(EXPOSURE_FIELDS):
        if any(r["exposure_declaration"][field] is None for r in responses):
            gaps.append("unknown_exposure:" + field)
    # State precedence must not erase open-question or unknown-exposure reasons.
    reasons = disagreements + unsupported + gaps
    if disagreements:
        return "disputed", reasons
    if unsupported:
        return "unsupported", reasons
    if gaps:
        return "pending", reasons
    return "declarations_recorded", [
        "unverified_declarations_only_not_consensus_or_admission"
    ]


def summarize_sampling_review_population(
    bundle,
    responses,
    raw,
    *,
    expected_bundle_sha256,
    expected_response_sha256s,
    **replay_inputs,
):
    """Account for every subject; preserve disagreement without selecting a winner."""
    bounds = _limits(bundle.get("limits") if type(bundle) is dict else None)
    _need(
        type(responses) is list and len(responses) <= bounds["max_responses"],
        "bounded complete response population required",
    )
    _need(
        type(expected_response_sha256s) is list
        and len(expected_response_sha256s) == len(responses),
        "one independent ordered response pin per response required",
    )
    offered = []
    remaining = bounds["max_population_input_bytes"]
    for response, pin in zip(responses, expected_response_sha256s, strict=True):
        value = _response_snapshot(response, pin, bounds)
        remaining -= len(_wire(value, bounds["max_response_bytes"]))
        _need(
            remaining >= 0,
            "whole response population byte bound exceeded before replay",
        )
        offered.append(value)
    _need(
        len(set(expected_response_sha256s)) == len(offered),
        "duplicate exact responses cannot inflate review population",
    )
    expected = validate_sampling_review_bundle(
        bundle, raw, expected_bundle_sha256=expected_bundle_sha256, **replay_inputs
    )
    _, seal = _owners()
    checked = [
        _validate_response(r, expected, expected_bundle_sha256, seal) for r in offered
    ]
    population = []
    for guide in expected["guides"]:
        selected = [r for r in checked if r["subject_ref"] == guide["subject_ref"]]
        state, reasons = _population_state(selected)
        population.append(
            dict(
                subject_ref=guide["subject_ref"],
                state=state,
                reasons=reasons,
                response_refs=[_ref(r) for r in selected],
            )
        )
    counts = {
        key: 0
        for key in ("pending", "disputed", "unsupported", "declarations_recorded")
    }
    counts.update(Counter(item["state"] for item in population))
    return seal(
        dict(
            schema=POPULATION_SCHEMA,
            bundle_sha256=expected_bundle_sha256,
            subjects=population,
            counts=counts,
            subject_count=len(population),
            response_count=len(checked),
            source_status=expected["manifest"]["source_status"],
            population_accounted=True,
            all_subjects_have_declarations=bool(population)
            and all(item["response_refs"] for item in population),
            population_issue=None
            if population
            else "no_review_subjects_or_source_unavailable_not_vacuous_completion",
            review_completed=False,
            adjudication_performed=False,
            latest_response_selected=False,
            authority=dict(FALSE_FLAGS),
            training_mask=0,
            evaluation_gold_mask=0,
        )
    )


def prepare_sampling_review_context(
    sources, attachments, *, expected_attachments_sha256, limits=None
):
    """Nominate cross-bundle evidence without resolving source or meaning review."""
    from .legal_source_sampling_review_context import prepare

    return prepare(
        sources, attachments,
        expected_attachments_sha256=expected_attachments_sha256, limits=limits,
    )


def sampling_review_context_sha256(packet):
    """Commit the complete separately versioned context packet."""
    from .legal_source_sampling_review_context import packet_sha256

    return packet_sha256(packet)


def validate_sampling_review_context(
    packet, sources, attachments, *, expected_context_sha256,
    expected_attachments_sha256, limits=None,
):
    """Replay every complete source bundle and the independently pinned selection."""
    from .legal_source_sampling_review_context import validate

    return validate(
        packet, sources, attachments,
        expected_context_sha256=expected_context_sha256,
        expected_attachments_sha256=expected_attachments_sha256, limits=limits,
    )


def record_sampling_review_context_response(
    packet, declaration, sources, attachments, *, expected_context_sha256,
    expected_declaration_sha256, expected_attachments_sha256, limits=None,
):
    """Record an explicit declaration using target-specific attached evidence."""
    from .legal_source_sampling_review_context import record_response

    return record_response(
        packet, declaration, sources, attachments,
        expected_context_sha256=expected_context_sha256,
        expected_declaration_sha256=expected_declaration_sha256,
        expected_attachments_sha256=expected_attachments_sha256, limits=limits,
    )


def validate_sampling_review_context_response(
    response, packet, declaration, sources, attachments, *, expected_response_sha256,
    expected_context_sha256, expected_declaration_sha256,
    expected_attachments_sha256, limits=None,
):
    """Validate a distinct context response against its original declaration."""
    from .legal_source_sampling_review_context import validate_response

    return validate_response(
        response, packet, declaration, sources, attachments,
        expected_response_sha256=expected_response_sha256,
        expected_context_sha256=expected_context_sha256,
        expected_declaration_sha256=expected_declaration_sha256,
        expected_attachments_sha256=expected_attachments_sha256, limits=limits,
    )


def summarize_sampling_review_context_population(
    packet, responses, sources, attachments, *, expected_context_sha256,
    expected_response_sha256s, expected_attachments_sha256, limits=None,
):
    """Retain the full source population, including unreviewed supporting subjects."""
    from .legal_source_sampling_review_context import summarize

    return summarize(
        packet, responses, sources, attachments,
        expected_context_sha256=expected_context_sha256,
        expected_response_sha256s=expected_response_sha256s,
        expected_attachments_sha256=expected_attachments_sha256, limits=limits,
    )


__all__ = [
    "prepare_sampling_review_bundle",
    "record_sampling_review_response",
    "sampling_review_bundle_sha256",
    "summarize_sampling_review_population",
    "validate_sampling_review_bundle",
    "validate_sampling_review_response",
    "prepare_sampling_review_context",
    "sampling_review_context_sha256",
    "validate_sampling_review_context",
    "record_sampling_review_context_response",
    "validate_sampling_review_context_response",
    "summarize_sampling_review_context_population",
]
