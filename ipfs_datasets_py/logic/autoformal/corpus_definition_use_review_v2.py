"""Fixed-domain review evidence for an explicit V2 definition-use assumption.

Both original definitions, the complete joint AST and all physical contexts are
replayed before authentication through the existing review engine. No registry,
signer, clock, actual legal review or admission authority is supplied by default.
Public import loads no operation owner, compiler or resolver.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ipfs_datasets_py.utils import cid_utils
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import corpus_definition_use_v2 as use

PREPARATION_SCHEMA = "legal-corpus-v2-definition-use-review-evidence/v1"
SUBJECT_SCHEMA = "legal-corpus-v2-definition-use-review-subject/v1"
CLAIM_SCHEMA = "legal-corpus-v2-definition-use-review-signed-claim/v1"
ACTION = "record_v2_definition_use_review_evidence/v1"
AUDIENCE = "legal-autoformalization-v2-definition-use-review/v1"
SCHEMA = "legal-corpus-v2-definition-use-review-assessment/v1"
PARENT_PREPARATION_SCHEMA = "legal-corpus-parent-definition-use-review-evidence/v1"
PARENT_SUBJECT_SCHEMA = "legal-corpus-parent-definition-use-review-subject/v1"
PARENT_CLAIM_SCHEMA = "legal-corpus-parent-definition-use-review-signed-claim/v1"
PARENT_ACTION = "record_parent_definition_use_review_evidence/v1"
PARENT_AUDIENCE = "legal-autoformalization-parent-definition-use-review/v1"
PARENT_SCHEMA = "legal-corpus-parent-definition-use-review-assessment/v1"
PARENT_PROFILE = "complete-parent-combined-definition-use-alias-review/v1"
PARENT_SCOPE_SCHEMA = "legal-corpus-parent-definition-use-review-scope/v1"
PARENT_POLICY_BINDING_SCHEMA = "legal-corpus-parent-definition-use-review-policy-binding/v1"
PROFILE = "complete-v2-combined-definition-use-alias-review/v1"
SCOPE_SCHEMA = "legal-corpus-v2-definition-use-review-scope/v1"
POLICY_BINDING_SCHEMA = "legal-corpus-v2-definition-use-review-policy-binding/v1"
REVIEW_CONTRACT = {
    "original_interpretations_unchanged": True,
    "alias_assumed_not_proved": True,
    "lookup_coverage": use.LOOKUP_COVERAGE,
    "per_occurrence_lookup_verified": False,
    "legal_review": "explicit declaration about the exact combined source interpretation and unproved alias assumption",
    "formal_review": "explicit declaration about the exact joint representation, source bindings and complete declared context population",
    "authentication_establishes_legal_truth": False,
    "original_endpoint_reviews_authorize_combination": False,
    "native_Lean_or_admission_established": False,
}
PARENT_REVIEW_CONTRACT = {
    **REVIEW_CONTRACT,
    "source_profile": "independently_replayed_literal_parent_endpoints",
    "scope_relation": "unreviewed_caller_declared_route",
    "matching_unknown_editions_establish_compatibility": False,
    "contributor_completeness_established": False,
    "source_region_roles_established": False,
}
MAX_INPUT_BYTES = 48 * 1024 * 1024
MAX_CONTEXT_OCCURRENCES = 256
MAX_CONTEXT_OBLIGATIONS = 1536
COMPONENT_PIN_FIELDS = {
    "component_sha256",
    "component_cid",
    "graph_cid",
    "joint_ast_sha256",
}
USE_INPUT_FIELDS = {
    "request_raw",
    "expected_request_sha256",
    "donor_evidence_inputs",
    "consumer_evidence_inputs",
    "registry_raw",
    "expected_registry_sha256",
    "expected_registry_cid",
    "lookup_raw",
    "expected_lookup_sha256",
    "expected_lookup_cid",
    "query_raw",
    "expected_query_sha256",
}
FALSE_FLAGS = {
    **use.FALSE_FLAGS,
    **dict.fromkeys(
        (
            "human_identity_verified",
            "human_independence_verified",
            "applicability_semantics_verified",
            "external_definition_resolution_verified",
            "legal_dependency_inventory_exhaustive",
        ),
        False,
    ),
}
PARENT_FALSE_FLAGS = {
    **FALSE_FLAGS,
    **use.PARENT_FALSE_FLAGS,
    "source_region_roles_verified": False,
}
FIELDS = {
    "review_profile",
    "profile",
    "family",
    "component_pin",
    "component_canonical_sha256",
    "graph_id",
    "graph_sha256",
    "ast_sha256",
    "alias_ast_sha256",
    "scope_id",
    "scope_binding",
    "policy_binding",
    "review_contract",
    "original_definitions",
    "binding_record",
    "alias_record",
    "interpretation_record",
    "native_ast",
    "contexts",
    "context_slot_ids",
    "producer_pins",
    "artifacts",
    "edges",
    "expected_artifact_ids",
    "required_dependency_ids",
    "view",
    "source_geometry_replayed",
    "context_packet_population_complete",
    "lookup_coverage",
    "hash_recipes",
    *FALSE_FLAGS,
}
PARENT_FIELDS = FIELDS | set(PARENT_FALSE_FLAGS)
SUBJECT_FIELDS = {
    "schema",
    "graph_id",
    "graph_sha256",
    "ast_sha256",
    "scope_id",
    "context_slot_ids",
    "dependency_manifest_sha256",
    "required_dependency_ids",
    "dependency_artifacts",
    "graph_declared_dependency_refs",
    "native_binding",
}
HASH_RECIPES = {
    "original_component_source_and_packets": "SHA256 of independently pinned complete original bytes",
    "canonical_graph_scope_joint_AST_and_records": "SHA256 of full canonical DAG JSON including record envelopes",
    "sampling_and_descriptor": "original raw JSON hashes remain distinct from full canonical hashes in original candidate pins",
    "subject_claim_population_and_assessment": "existing legal_graph_review sorted compact UTF8 JSON digest",
    "dependency_manifest": "existing legal_graph_dependencies manifest_sha256 recipe",
}

PARENT_HASH_RECIPES = {
    **{key: value for key, value in HASH_RECIPES.items() if key != "sampling_and_descriptor"},
    "parent_transport": "complete literal-parent bundles, original report bytes, replay inputs and independent source/context pins retained through both original endpoint preparations",
}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _need(value, message):
    if not value:
        _fail(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(canonical_dag_json_bytes(value))


def _pure_pins():
    return {
        str(path): _sha(path.read_bytes())
        for path in (
            Path(__file__).resolve(),
            Path(contracts.__file__).resolve(),
            Path(cid_utils.__file__).resolve(),
        )
    } | use._pure_pins()


_IMPORTED_PURE_PINS = _pure_pins()
_OPERATION_PINS = None


def _owners():
    from . import legal_graph_dependencies, legal_graph_review

    return legal_graph_dependencies, legal_graph_review


def _pins(owners):
    global _OPERATION_PINS
    actual = _pure_pins()
    _need(
        actual == _IMPORTED_PURE_PINS,
        "combined-use review pure owners changed since import",
    )
    extra = {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in owners
    }
    signature_owner = Path(owners[1].__file__).resolve().parent.parent / "profile_g.py"
    extra[str(signature_owner)] = _sha(signature_owner.read_bytes())
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(extra)
    _need(
        extra == _OPERATION_PINS,
        "combined-use review operation owners changed since first use",
    )
    return actual | extra


def _preflight(component_raw, expected_component_pin, use_inputs, *, parent=False):
    """Check the full two-source byte/metadata budget before operation imports."""
    _need(
        _pure_pins() == _IMPORTED_PURE_PINS,
        "combined-use review pure owners changed since import",
    )
    pins = contracts.clone_json(expected_component_pin)
    contracts.require_keys(
        pins, COMPONENT_PIN_FIELDS, "independent combined-use component pins"
    )
    for field in ("component_sha256", "joint_ast_sha256"):
        contracts.require_sha256(pins[field], field)
    for field in ("component_cid", "graph_cid"):
        contracts.require_cid(pins[field], field, codecs=("dag-json",))
    use._bounded(
        component_raw,
        pins["component_sha256"],
        contracts.MAX_RECORD_BYTES,
        "combined use component",
    )
    contracts.require_keys(
        use_inputs, USE_INPUT_FIELDS, "original combined-use replay inputs"
    )
    total = len(component_raw) + len(canonical_dag_json_bytes(pins))
    for label in ("request", "registry", "lookup", "query"):
        raw = use_inputs[label + "_raw"]
        use._bounded(
            raw,
            use_inputs["expected_" + label + "_sha256"],
            contracts.MAX_RECORD_BYTES,
            label,
        )
        total += len(raw)
    for label in ("registry", "lookup"):
        contracts.require_cid(
            use_inputs["expected_" + label + "_cid"],
            "independent " + label + " CID",
            codecs=("dag-json",),
        )
    if parent:
        endpoint_transports = tuple(
            use._parent_use_preflight(use_inputs[role + "_evidence_inputs"])
            for role in ("donor", "consumer")
        )
        total += sum(row[0] for row in endpoint_transports)
    else:
        total += use._preflight(use_inputs["donor_evidence_inputs"])
        total += use._preflight(use_inputs["consumer_evidence_inputs"])
    _need(
        total <= MAX_INPUT_BYTES, "complete combined-use review input budget exceeded"
    )
    if parent:
        # Snapshot all declared transport commitments, including both complete
        # logical endpoint populations even when they share physical storage.
        # This does not promise an atomic external-filesystem snapshot.
        return pins, {
            "endpoints": endpoint_transports,
            "original_inputs": {
                label: {"sha256": use_inputs["expected_" + label + "_sha256"],
                        "bytes": len(use_inputs[label + "_raw"])}
                for label in ("request", "registry", "lookup", "query")
            },
            "registry_cid": use_inputs["expected_registry_cid"],
            "lookup_cid": use_inputs["expected_lookup_cid"],
        }
    return pins


def _scope_and_originals(component, use_inputs, *, parent=False):
    originals = []
    for role in ("donor", "consumer"):
        evidence = use_inputs[role + "_evidence_inputs"]
        candidate = contracts.load_record_bytes(
            evidence["candidate_inputs"]["candidate_raw"],
            expected_sha256=evidence["expected_candidate_pin"]["candidate_sha256"],
        )
        originals.append(
            {
                "role": role,
                "candidate_pin": evidence["expected_candidate_pin"],
                "preparation_cid": evidence["expected_preparation_cid"],
                "source_version": candidate["source_version"],
                "scope_record": candidate["scope_record"],
                "symbol_record": candidate["symbol_record"],
                "source_bindings": candidate["source_bindings"],
                "definition_cid": candidate["definition_record"]["record_cid"],
                "ast_record_cid": candidate["ast_record"]["record_cid"],
                "interpretation_cid": candidate["report_record"]["record_cid"],
                **({
                    "parent_source_binding": candidate["parent_source_binding"],
                    "candidate_input_binding": candidate["input_binding"],
                    "source_occurrences": candidate["source_occurrences"],
                } if parent else {}),
            }
        )
    scope = contracts.seal_record(
        {
            "schema": PARENT_SCOPE_SCHEMA if parent else SCOPE_SCHEMA,
            "review_profile": PARENT_PROFILE if parent else PROFILE,
            "binding_cid": component["binding_record"]["record_cid"],
            "scopes": [
                {
                    "role": row["role"],
                    "source_version_cid": row["source_version"]["record_cid"],
                    "scope_record_cid": row["scope_record"]["record_cid"],
                    "scope_key": row["scope_record"]["scope_key"],
                    **({
                        "source_version": row["source_version"],
                        "edition": row["source_version"]["edition"],
                        "scope_declaration": row["scope_record"]["scope_declaration"],
                        "candidate_pin": row["candidate_pin"],
                        "preparation_cid": row["preparation_cid"],
                        "parent_source_binding": row["parent_source_binding"],
                    } if parent else {}),
                }
                for row in originals
            ],
            **({
                "scope_relation": "unreviewed_caller_declared_route",
                "governing_scope_verified": False,
                "governing_edition_verified": False,
                "contributor_completeness_verified": False,
                "source_region_roles_verified": False,
            } if parent else {
                "declared_applicability": originals[0]["scope_record"]["declared_applicability"],
            }),
            "lookup_coverage": use.LOOKUP_COVERAGE,
            "governing_applicability_verified": False,
        }
    )
    return scope, originals


def _inventory(component, scope, policy_binding, pins, producers, dependencies, *, parent=False):
    artifacts = contracts.clone_json(component["dependency_manifest"]["artifacts"])
    root = component["graph"]["record_cid"]
    _need(
        artifacts[0]["artifact_id"] == root,
        "combined-use graph must start its complete inventory",
    )
    component_canonical = _digest(component)
    for identity, digest, policy in (
        (pins["component_cid"], pins["component_sha256"], []),
        (
            ("parent-use-review-component-canonical:sha256:" if parent else
             "v2-use-review-component-canonical:sha256:") + component_canonical,
            component_canonical,
            [],
        ),
        (scope["record_cid"], _digest(scope), []),
        (
            policy_binding["record_cid"],
            _digest(policy_binding),
            [
                {"key": ("parent-use-review-owner:" if parent else "v2-use-review-owner:") + path,
                 "sha256": digest}
                for path, digest in sorted(producers.items())
            ],
        ),
    ):
        _need(
            identity not in {row["artifact_id"] for row in artifacts},
            "duplicate combined-use review dependency identity",
        )
        artifacts.append(
            {
                "artifact_id": identity,
                "artifact_sha256": digest,
                "dependency_pins": {
                    kind: policy if kind == "policy" else []
                    for kind in dependencies.PIN_KINDS
                },
            }
        )
    ids = [row["artifact_id"] for row in artifacts]
    edges = contracts.clone_json(component["dependency_manifest"]["edges"])
    edges.extend(
        {"dependent_id": root, "dependency_id": identity} for identity in ids[-4:]
    )
    dependencies.build_dependency_manifest(artifacts, edges, expected_artifact_ids=ids)
    return artifacts, edges, ids


def _prepare_definition_use_review_evidence(
    component_raw, *, expected_component_pin, use_inputs, parent=False
):
    """Replay the complete source/use candidate and bind a new review scope."""
    before = _preflight(component_raw, expected_component_pin, use_inputs, parent=parent)
    pins = before[0] if parent else before
    component = contracts.load_record_bytes(
        component_raw, expected_sha256=pins["component_sha256"]
    )
    replay = dict(use_inputs)
    request_raw = replay.pop("request_raw")
    validate_component = (use.validate_parent_definition_use_candidate_v1 if parent
                          else use.validate_definition_use_candidate_v2)
    component = validate_component(component, request_raw, **replay)
    _need(
        component["record_cid"] == pins["component_cid"]
        and component["graph"]["record_cid"] == pins["graph_cid"]
        and _digest(component["joint_native"]["native_ast"])
        == pins["joint_ast_sha256"],
        "combined-use candidate, graph or full joint AST differs from independent pins",
    )
    contexts, slots = component["context_population"], component["context_slot_ids"]
    _need(
        len(contexts) <= MAX_CONTEXT_OCCURRENCES
        and len(slots) <= MAX_CONTEXT_OBLIGATIONS
        and len(slots) == 6 * len(contexts)
        and len(set(slots)) == len(slots),
        "complete combined context population exceeds review profile",
    )
    owners = _owners()
    producers = _pins(owners)
    scope, originals = _scope_and_originals(component, use_inputs, parent=parent)
    policy_binding = contracts.seal_record(
        {
            "schema": PARENT_POLICY_BINDING_SCHEMA if parent else POLICY_BINDING_SCHEMA,
            "review_profile": PARENT_PROFILE if parent else PROFILE,
            "subject_schema": PARENT_SUBJECT_SCHEMA if parent else SUBJECT_SCHEMA,
            "claim_schema": PARENT_CLAIM_SCHEMA if parent else CLAIM_SCHEMA,
            "action": PARENT_ACTION if parent else ACTION,
            "audience": PARENT_AUDIENCE if parent else AUDIENCE,
            "assessment_schema": PARENT_SCHEMA if parent else SCHEMA,
            "producer_pins": producers,
            "review_contract": PARENT_REVIEW_CONTRACT if parent else REVIEW_CONTRACT,
        }
    )
    artifacts, edges, ids = _inventory(
        component, scope, policy_binding, pins, producers, owners[0], parent=parent
    )
    manifest = owners[0].build_dependency_manifest(
        artifacts, edges, expected_artifact_ids=ids
    )
    required, _ = owners[1]._closure(
        manifest, pins["graph_cid"], _digest(component["graph"])
    )
    _need(
        _pins(owners) == producers,
        "combined-use review producers changed during preparation",
    )
    if parent:
        _need(before == _preflight(component_raw, expected_component_pin, use_inputs, parent=True),
              "parent combined-use original transport changed during preparation")
    return contracts.seal_record(
        {
            "schema": PARENT_PREPARATION_SCHEMA if parent else PREPARATION_SCHEMA,
            "review_profile": PARENT_PROFILE if parent else PROFILE,
            "profile": component["profile"],
            "family": component["family"],
            "component_pin": pins,
            "component_canonical_sha256": _digest(component),
            "graph_id": pins["graph_cid"],
            "graph_sha256": _digest(component["graph"]),
            "ast_sha256": pins["joint_ast_sha256"],
            "alias_ast_sha256": _digest(component["alias_native"]["native_ast"]),
            "scope_id": scope["record_cid"],
            "scope_binding": scope,
            "policy_binding": policy_binding,
            "review_contract": PARENT_REVIEW_CONTRACT if parent else REVIEW_CONTRACT,
            "original_definitions": originals,
            "binding_record": component["binding_record"],
            "alias_record": component["alias_record"],
            "interpretation_record": component["interpretation_record"],
            "native_ast": component["joint_native"]["native_ast"],
            "contexts": contexts,
            "context_slot_ids": slots,
            "producer_pins": producers,
            "artifacts": artifacts,
            "edges": edges,
            "expected_artifact_ids": ids,
            "required_dependency_ids": required,
            "view": "candidate",
            "source_geometry_replayed": True,
            "context_packet_population_complete": True,
            "lookup_coverage": use.LOOKUP_COVERAGE,
            "hash_recipes": PARENT_HASH_RECIPES if parent else HASH_RECIPES,
            **(PARENT_FALSE_FLAGS if parent else FALSE_FLAGS),
        }
    )


def _validate_definition_use_review_evidence(
    preparation, component_raw, *, expected_component_pin, use_inputs, parent=False
):
    checked = contracts.validate_record(
        preparation, schema=PARENT_PREPARATION_SCHEMA if parent else PREPARATION_SCHEMA,
        fields=PARENT_FIELDS if parent else FIELDS,
    )
    expected = _prepare_definition_use_review_evidence(
        component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs, parent=parent,
    )
    _need(
        checked == expected,
        "combined-use review evidence differs from complete independent regeneration",
    )
    return checked


def _manifest_binding(preparation, manifest, required_dependency_ids, owner, *, parent=False):
    _need(
        manifest["artifacts"] == preparation["artifacts"]
        and manifest["edges"] == preparation["edges"],
        "exact complete combined-use dependency generation required",
    )
    reachable, artifacts = owner._closure(
        manifest, preparation["graph_id"], preparation["graph_sha256"]
    )
    _need(
        type(required_dependency_ids) is list
        and owner.wire(required_dependency_ids) == owner.wire(reachable)
        and reachable == preparation["required_dependency_ids"],
        "independent ordered combined-use closure differs",
    )
    refs = [
        {
            "origin": "/native_binding/artifacts/" + str(index),
            "reference": {
                "artifact_id": row["artifact_id"],
                "artifact_sha256": row["artifact_sha256"],
                "role": ("complete-parent-definition-use-review-evidence" if parent else
                         "complete-v2-definition-use-review-evidence"),
            },
        }
        for index, row in enumerate(preparation["artifacts"][1:], 1)
    ]
    owner._check_declared_dependencies(refs, reachable, artifacts)
    return reachable, artifacts, refs


def _subject(subject, manifest, *, parent=False):
    contracts.require_keys(subject, SUBJECT_FIELDS, "combined-use review subject")
    _need(
        subject["schema"] == (PARENT_SUBJECT_SCHEMA if parent else SUBJECT_SCHEMA),
        "distinct combined-use review subject required",
    )
    preparation = contracts.validate_record(
        subject["native_binding"],
        schema=PARENT_PREPARATION_SCHEMA if parent else PREPARATION_SCHEMA,
        fields=PARENT_FIELDS if parent else FIELDS,
    )
    _need(
        preparation["review_profile"] == (PARENT_PROFILE if parent else PROFILE)
        and preparation["scope_id"] == preparation["scope_binding"]["record_cid"]
        and preparation["ast_sha256"] == _digest(preparation["native_ast"]),
        "combined-use scope or full AST binding differs",
    )
    for field in (
        "graph_id",
        "graph_sha256",
        "ast_sha256",
        "scope_id",
        "context_slot_ids",
    ):
        _need(
            subject[field] == preparation[field],
            "subject differs from exact combined-use evidence",
        )
    _, owner = _owners()
    reachable, artifacts, refs = _manifest_binding(
        preparation, manifest, subject["required_dependency_ids"], owner, parent=parent
    )
    _need(
        subject["dependency_artifacts"] == artifacts
        and subject["graph_declared_dependency_refs"] == refs
        and subject["dependency_manifest_sha256"] == manifest["manifest_sha256"]
        and reachable,
        "combined-use subject dependency binding differs",
    )


def _parent_subject(subject, manifest):
    return _subject(subject, manifest, parent=True)


def _build_definition_use_review_subject(
    preparation,
    dependency_manifest,
    *,
    component_raw,
    expected_component_pin,
    use_inputs,
    expected_manifest_sha256,
    required_dependency_ids,
    parent=False,
):
    checked = _validate_definition_use_review_evidence(
        preparation,
        component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs, parent=parent,
    )
    dependencies, owner = _owners()
    manifest = dependencies.validate_dependency_manifest(
        dependency_manifest, expected_manifest_sha256=expected_manifest_sha256
    )
    reachable, artifacts, refs = _manifest_binding(
        checked, manifest, required_dependency_ids, owner, parent=parent
    )
    subject = {
        "schema": PARENT_SUBJECT_SCHEMA if parent else SUBJECT_SCHEMA,
        **{
            field: checked[field]
            for field in (
                "graph_id",
                "graph_sha256",
                "ast_sha256",
                "scope_id",
                "context_slot_ids",
            )
        },
        "dependency_manifest_sha256": expected_manifest_sha256,
        "required_dependency_ids": reachable,
        "dependency_artifacts": artifacts,
        "graph_declared_dependency_refs": refs,
        "native_binding": checked,
    }
    _subject(subject, manifest, parent=parent)
    return contracts.clone_json(subject)


def _assess_definition_use_reviews(
    subject,
    registry,
    policy,
    reviews,
    dependency_manifest,
    *,
    component_raw,
    expected_component_pin,
    use_inputs,
    expected_subject_sha256,
    expected_registry_sha256,
    expected_policy_sha256,
    expected_reviews_sha256,
    expected_manifest_sha256,
    at_time_utc,
    observed_artifact_sha256s,
    observed_pins,
    evidence_artifacts,
    parent=False,
):
    """Replay original evidence before invoking the fixed shared verifier."""
    before = _preflight(component_raw, expected_component_pin, use_inputs, parent=parent)
    owners = _owners()
    producers = _pins(owners)
    checked = contracts.clone_json(subject)
    contracts.require_keys(checked, SUBJECT_FIELDS, "combined-use review subject")
    expected = _build_definition_use_review_subject(
        checked["native_binding"],
        dependency_manifest,
        component_raw=component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs,
        expected_manifest_sha256=expected_manifest_sha256,
        required_dependency_ids=checked["required_dependency_ids"], parent=parent,
    )
    _need(
        checked == expected and checked["native_binding"]["producer_pins"] == producers,
        "combined-use subject or producer pins differ from independent regeneration",
    )
    _need(
        _pins(owners) == producers,
        "combined-use producers changed before authentication",
    )
    owner = owners[1]
    domain = owner._ReviewDomain(
        PARENT_SUBJECT_SCHEMA if parent else SUBJECT_SCHEMA,
        PARENT_CLAIM_SCHEMA if parent else CLAIM_SCHEMA,
        PARENT_ACTION if parent else ACTION,
        PARENT_AUDIENCE if parent else AUDIENCE,
        PARENT_SCHEMA if parent else SCHEMA,
        _parent_subject if parent else _subject,
        MAX_CONTEXT_OBLIGATIONS,
    )
    result = owner._assess_reviews(
        checked,
        registry,
        policy,
        reviews,
        dependency_manifest,
        domain=domain,
        expected_subject_sha256=expected_subject_sha256,
        expected_registry_sha256=expected_registry_sha256,
        expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
        at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s,
        observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts,
    )
    preparation = checked["native_binding"]
    body = {key: value for key, value in result.items() if key != "assessment_sha256"}
    body.update(
        {
            "review_profile": PARENT_PROFILE if parent else PROFILE,
            "native_profile": preparation["profile"],
            "native_family": preparation["family"],
            "component_cid": preparation["component_pin"]["component_cid"],
            "component_sha256": preparation["component_pin"]["component_sha256"],
            "graph_cid": preparation["graph_id"],
            "preparation_cid": preparation["record_cid"],
            "scope_binding_cid": preparation["scope_id"],
            "joint_ast_sha256": preparation["ast_sha256"],
            "alias_record_cid": preparation["alias_record"]["record_cid"],
            "binding_record_cid": preparation["binding_record"]["record_cid"],
            "original_definition_cids": [
                row["definition_cid"] for row in preparation["original_definitions"]
            ],
            "lookup_coverage": preparation["lookup_coverage"],
            "alias_assumed_not_proved": True,
            "context_population_sha256": _digest(preparation["contexts"]),
            "signature_owner_source_pinned": True,
            "cryptographic_distribution_authenticated": False,
            **(PARENT_FALSE_FLAGS if parent else FALSE_FLAGS),
        }
    )
    report = {**body, "assessment_sha256": owner.digest(body)}
    owner.wire(report)
    _need(
        _pins(owners) == producers,
        "combined-use review producers changed during authentication",
    )
    if parent:
        _need(before == _preflight(component_raw, expected_component_pin, use_inputs, parent=True),
              "parent combined-use original transport changed during authentication")
    return report


def _validate_definition_use_review_assessment(report, *args, parent=False, **kwargs):
    expected = _assess_definition_use_reviews(*args, parent=parent, **kwargs)
    owner = _owners()[1]
    _need(
        owner.wire(report) == owner.wire(expected),
        "combined-use review assessment differs from exact regeneration",
    )
    return expected


def prepare_definition_use_review_evidence_v2(
    component_raw,
    *,
    expected_component_pin,
    use_inputs,
):
    """Preserve the official V2 combined-use review profile."""
    return _prepare_definition_use_review_evidence(
        component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs
    )


def prepare_parent_definition_use_review_evidence_v1(
    component_raw,
    *,
    expected_component_pin,
    use_inputs,
):
    """Replay complete literal-parent combined evidence under its distinct fixed domain."""
    return _prepare_definition_use_review_evidence(
        component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs,
        parent=True
    )


def validate_definition_use_review_evidence_v2(
    preparation,
    component_raw,
    *,
    expected_component_pin,
    use_inputs,
):
    """Preserve the official V2 combined-use review profile."""
    return _validate_definition_use_review_evidence(
        preparation,
        component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs
    )


def validate_parent_definition_use_review_evidence_v1(
    preparation,
    component_raw,
    *,
    expected_component_pin,
    use_inputs,
):
    """Replay complete literal-parent combined evidence under its distinct fixed domain."""
    return _validate_definition_use_review_evidence(
        preparation,
        component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs,
        parent=True
    )


def build_definition_use_review_subject_v2(
    preparation,
    dependency_manifest,
    *,
    component_raw,
    expected_component_pin,
    use_inputs,
    expected_manifest_sha256,
    required_dependency_ids,
):
    """Preserve the official V2 combined-use review profile."""
    return _build_definition_use_review_subject(
        preparation,
        dependency_manifest,
        component_raw=component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs,
        expected_manifest_sha256=expected_manifest_sha256,
        required_dependency_ids=required_dependency_ids
    )


def build_parent_definition_use_review_subject_v1(
    preparation,
    dependency_manifest,
    *,
    component_raw,
    expected_component_pin,
    use_inputs,
    expected_manifest_sha256,
    required_dependency_ids,
):
    """Replay complete literal-parent combined evidence under its distinct fixed domain."""
    return _build_definition_use_review_subject(
        preparation,
        dependency_manifest,
        component_raw=component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs,
        expected_manifest_sha256=expected_manifest_sha256,
        required_dependency_ids=required_dependency_ids,
        parent=True
    )


def assess_definition_use_reviews_v2(
    subject,
    registry,
    policy,
    reviews,
    dependency_manifest,
    *,
    component_raw,
    expected_component_pin,
    use_inputs,
    expected_subject_sha256,
    expected_registry_sha256,
    expected_policy_sha256,
    expected_reviews_sha256,
    expected_manifest_sha256,
    at_time_utc,
    observed_artifact_sha256s,
    observed_pins,
    evidence_artifacts,
):
    """Preserve the official V2 combined-use review profile."""
    return _assess_definition_use_reviews(
        subject,
        registry,
        policy,
        reviews,
        dependency_manifest,
        component_raw=component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs,
        expected_subject_sha256=expected_subject_sha256,
        expected_registry_sha256=expected_registry_sha256,
        expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
        at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s,
        observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts
    )


def assess_parent_definition_use_reviews_v1(
    subject,
    registry,
    policy,
    reviews,
    dependency_manifest,
    *,
    component_raw,
    expected_component_pin,
    use_inputs,
    expected_subject_sha256,
    expected_registry_sha256,
    expected_policy_sha256,
    expected_reviews_sha256,
    expected_manifest_sha256,
    at_time_utc,
    observed_artifact_sha256s,
    observed_pins,
    evidence_artifacts,
):
    """Replay complete literal-parent combined evidence under its distinct fixed domain."""
    return _assess_definition_use_reviews(
        subject,
        registry,
        policy,
        reviews,
        dependency_manifest,
        component_raw=component_raw,
        expected_component_pin=expected_component_pin,
        use_inputs=use_inputs,
        expected_subject_sha256=expected_subject_sha256,
        expected_registry_sha256=expected_registry_sha256,
        expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
        at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s,
        observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts,
        parent=True
    )


def validate_definition_use_review_assessment_v2(report, *args, **kwargs):
    """Preserve the official V2 combined-use review profile."""
    return _validate_definition_use_review_assessment(
        report,
        *args,
        parent=False,
        **kwargs
    )


def validate_parent_definition_use_review_assessment_v1(report, *args, **kwargs):
    """Replay complete literal-parent combined evidence under its distinct fixed domain."""
    return _validate_definition_use_review_assessment(
        report,
        *args,
        parent=True,
        **kwargs
    )


__all__ = [
    "prepare_definition_use_review_evidence_v2",
    "validate_definition_use_review_evidence_v2",
    "build_definition_use_review_subject_v2",
    "assess_definition_use_reviews_v2",
    "validate_definition_use_review_assessment_v2",
    "prepare_parent_definition_use_review_evidence_v1",
    "validate_parent_definition_use_review_evidence_v1",
    "build_parent_definition_use_review_subject_v1",
    "assess_parent_definition_use_reviews_v1",
    "validate_parent_definition_use_review_assessment_v1",
]
