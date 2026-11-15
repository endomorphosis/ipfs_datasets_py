"""Project fully replayed captured kernel propositions into typed candidates.

Each statement retains the entire closed Lean forall type and its universe
inventory. Proposition parameters remain inside that type, with explicit source
and telescope associations; they are not duplicated as external assumptions.
Historical packet evidence is kept outside stable claim metadata. This module
constructs no backend request, attempt, result, proof receipt or legal artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "legal-corpus-v2-preservation-kernel-claim-projection/v1"
PROFILE = "retained-corpus-preservation-closed-kernel-claims/v1"
STATEMENT_SCHEMA = "lean-kernel-proposition/v1"
STATEMENT_KIND = "lean_kernel_proposition_json"
DOMAIN = "engineering_corpus_preservation"
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_CLAIMS = 15
_READER_ARGUMENTS = frozenset({
    "expected_native_receipt_file_sha256", "expected_type_payload_file_sha256", "expected_native_bundle_sha256",
    "expected_elaboration_preparation_sha256", "expected_lineage_sha256", "expected_packet_observation_sha256",
    "expected_preparation_sha256", "expected_corpus_preparation_sha256", "expected_assessment_file_sha256",
    "expected_receipt_file_sha256", "expected_bundle_sha256", "review_inputs", "toolchain", "expected_binary_sha256",
})
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FALSE_FLAGS = dict.fromkeys((
    "source_authenticity_verified", "publisher_authenticity_verified", "legal_currentness_verified",
    "source_semantics_verified", "applicability_verified", "context_closure_verified", "independently_reviewed",
    "human_identity_verified", "human_independence_verified", "meaning_admitted", "admitted", "formalized",
    "semantic_graph_admitted", "proof_authority", "training_qualified", "training_gold_qualified",
    "evaluation_gold_qualified", "Lean_admitted", "model_executed", "learned_translation",
    "source_to_model_equivalence_proved", "source_fidelity_proved", "translation_preservation_proved",
    "cross_family_equivalence_verified", "general_emitter_preservation_proved",
    "general_serialized_AST_lowering_preservation_proved", "json_bytes_parser_verified",
    "json_bytes_parser_preservation_proved", "model_convergence_proved", "convergence_proved",
    "backend_executed", "lean_compilation_verified", "proof_checked", "kernel_proofs_checked",
    "corpus_native_AST_preservation_proved", "conditional_proofs_verified", "alias_assumption_proved",
    "legal_proof_cache_compatible", "proof_cache_admission_verified", "semantic_definition_binding_verified",
    "per_occurrence_lookup_verified", "accepted_view_eligible", "combined_use_review_verified",
    "native_execution_performed", "fresh_native_execution_performed", "proof_validation_performed",
    "olean_kernel_rechecked", "installed_compiler_revalidated", "cryptographic_authenticity_verified",
    "elaborated_type_verified", "elaborated_type_equality_verified", "kernel_definitional_equality_verified",
    "kernel_probe_aliases_checked", "executable_kernel_target_prepared", "formalization_artifact_created",
    "backend_request_prepared", "typed_native_attempt_observed", "typed_theorem_result_observed",
    "theorem_receipt_issued", "compiled_artifact_execution_reused", "elaborated_term_dependencies_verified",
    "source_prose_correspondence_proved", "installed_stdlib_artifact_closure_verified",
    "kernel_proposition_elaborated_by_projection", "external_proposition_hypotheses_established",
), False)
AUTHORITY = dict.fromkeys(
    ("source", "legal", "review", "proof", "model", "training", "gold", "corpus_admission"), False)


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
          "independent lowercase SHA256 required: " + label)


def _wire(value):
    from . import legal_corpus_definition_use_preservation_theorem_lineage_v2 as storage
    return storage._wire(value)


def _parse(raw):
    from . import legal_corpus_definition_use_preservation_theorem_lineage_v2 as storage
    return storage._parse(raw)


@dataclass(frozen=True, slots=True)
class KernelClaimProjection:
    projection_json: str
    claims: tuple[object, ...]

    def to_dict(self):
        _need(type(self.projection_json) is str and 0 < len(self.projection_json) <= MAX_RECORD_BYTES,
              "bounded kernel-claim projection text required")
        try:
            raw = self.projection_json.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("valid kernel-claim projection UTF8 required") from error
        return _parse(raw)


FrozenKernelClaimProjection = KernelClaimProjection


def _projection_storage(projection):
    _need(type(projection) is KernelClaimProjection, "exact kernel-claim projection storage type required")
    from . import legal_corpus_definition_use_preservation_theorem_lineage_v2 as storage
    document = KernelClaimProjection.to_dict(projection)
    snapshot = storage._claim_snapshot(projection.claims)
    snapshot_raw = _wire(snapshot)
    _need(type(document) is dict and document.get("schema") == SCHEMA and document.get("profile") == PROFILE
          and _wire(document.get("claims")) == snapshot_raw,
          "serialized and genuine typed kernel-claim storage differ")
    return document, snapshot_raw


def projection_sha256(projection):
    """Address exact projection bytes and consistent typed storage; no replay."""
    _projection_storage(projection)
    return _sha(projection.projection_json.encode("utf-8"))


def _name(value):
    """Read only the already validated closed structured Name grammar."""
    _need(type(value) is dict, "closed captured Lean name required")
    kind = value.get("kind")
    if kind == "anonymous":
        _need(set(value) == {"kind"}, "closed anonymous Lean name required")
        return ""
    _need(kind in ("str", "num") and set(value) == {"kind", "parent", "value"},
          "closed captured Lean name component required")
    parent = _name(value["parent"])
    component = value["value"]
    if kind == "str":
        _need(type(component) is str and component and "\x00" not in component,
              "ordinary nonempty captured Lean name component required")
    else:
        _need(type(component) is int and 0 <= component < (1 << 63),
              "ordinary bounded captured Lean name index required")
    return (parent + "." if parent else "") + str(component)


def _telescope(expression, expected_arguments):
    """Retain original domains relative to their complete preceding telescope.

    Domains may contain de Bruijn references to earlier binders. They are not
    standalone closed propositions and are never lowered into external facts.
    """
    rows, current = [], expression
    while type(current) is dict and current.get("kind") == "forallE":
        _need(len(rows) < 16 and set(current) == {"kind", "binder_name", "binder_info", "binder_type", "body"},
              "bounded exact outer theorem telescope required")
        name = _name(current["binder_name"])
        _need(name and current["binder_info"] == ("implicit" if name in ("Entity", "Agent") else "default"),
              "exact original theorem binder identity and explicitness required")
        rows.append({"binder_index": len(rows), "binder_name": name,
                     "binder_name_json": current["binder_name"], "binder_info": current["binder_info"],
                     "binder_type": current["binder_type"]})
        current = current["body"]
    _need([row["binder_name"] for row in rows] == expected_arguments,
          "complete captured original theorem telescope differs from its source header")
    return rows


def _binder_context(rows, index):
    prefix = [{"binder_name": row["binder_name_json"], "binder_info": row["binder_info"],
               "binder_type": row["binder_type"]} for row in rows[:index]]
    context = {"schema": "lean-kernel-telescope-prefix/v1", "context_depth": index,
               "binders": prefix, "de_bruijn_domains_are_relative_to_preceding_binders": True}
    raw = _wire(context)
    return raw.decode("utf-8"), _sha(raw)


def _premise_domain(domain, qualified_target, rows, index):
    """Check this closed source profile's exact original formula application."""
    arguments, head = [], domain
    while type(head) is dict and head.get("kind") == "app":
        _need(set(head) == {"kind", "fn", "arg"} and len(arguments) < 8,
              "exact bounded proposition-domain application required")
        arguments.insert(0, head["arg"])
        head = head["fn"]
    _need(type(head) is dict and set(head) == {"kind", "name", "levels"} and head["kind"] == "const"
          and _name(head["name"]) == qualified_target and head["levels"] == [],
          "explicit proposition binder must target the exact original formula declaration")
    positions = {row["binder_name"]: row["binder_index"] for row in rows[:index]}
    _need(all(name in positions for name in ("Entity", "Agent", "i", "t")),
          "complete original carrier/interpretation/time telescope prefix required")
    expected = [{"kind": "bvar", "index": index - 1 - positions[name]} for name in ("Entity", "Agent", "i", "t")]
    _need(_wire(arguments) == _wire(expected),
          "original proposition-domain de Bruijn arguments differ from the complete binder context")


def _outer_bindings(entry, capture, expected_arguments):
    rows = _telescope(capture["original_type"], expected_arguments)
    source_premises = entry["proposition_premises"]
    by_name = {premise["binder_name"]: premise for premise in source_premises}
    _need(len(by_name) == len(source_premises), "unique original proposition-premise names required")
    outer, associations, stable_hypotheses = [], [], []
    for row in rows:
        index, name, domain = row["binder_index"], row["binder_name"], row["binder_type"]
        context_json, context_pin = _binder_context(rows, index)
        domain_raw = _wire(domain)
        descriptor = {
            "binder_index": index, "binder_path": ["body"] * index,
            "binder_name": name, "binder_info": row["binder_info"],
            "binder_type_json": domain_raw.decode("utf-8"), "binder_type_sha256": _sha(domain_raw),
            "context_depth": index, "prefix_context_json": context_json, "prefix_context_sha256": context_pin,
            "domain_is_standalone_closed_proposition": False,
            "binder_kind": "quantified_proposition_hypothesis" if name in by_name else "universal_parameter",
        }
        outer.append(descriptor)
        if name in by_name:
            premise = by_name[name]
            _premise_domain(domain, premise["qualified_target"], rows, index)
            stable_hypotheses.append({"binder_index": index, "binder_name": name, "binder_info": row["binder_info"],
                                      "binder_type_sha256": _sha(domain_raw), "prefix_context_sha256": context_pin,
                                      "qualified_target": premise["qualified_target"]})
            associations.append({**descriptor,
                "source_assumption_id": premise["assumption_id"],
                "source_binder": premise["binder"], "source_proposition": premise["proposition"],
                "source_qualified_target": premise["qualified_target"], "source_range": premise["range"],
                "hypothesis_established_as_fact": False, "external_assumption_created": False})
    _need([row["binder_name"] for row in associations] == [row["binder_name"] for row in source_premises],
          "complete ordered original proposition-premise association population required")
    _need(all(not row["binder_name"].startswith("h") or row["binder_name"] in by_name for row in rows),
          "unaccounted captured proposition hypothesis")
    return outer, associations, stable_hypotheses


def _semantic_context(manifest, observation, reader_arguments, review_tree_pin, producers):
    # New elaboration preparation and old opaque-lineage digests indirectly
    # commit aliases and historical native receipts. They belong in evidence,
    # not in stable kernel claim identity. Original PURE preparation pins do not.
    shared = manifest["shared_interpretation"]
    interpretation = {key: shared[key] for key in (
        "nominal_type", "prelude_module", "prelude_source", "semantics_module", "semantics_source", "semantics_body_sha256")}
    return {
        "schema": "legal-corpus-kernel-claim-semantic-context/v1", "profile": PROFILE,
        "statement_schema": STATEMENT_SCHEMA, "statement_kind": STATEMENT_KIND,
        "domain": DOMAIN, "logic_family": "lean4",
        "original_corpus_preparation_full_canonical_sha256": reader_arguments["expected_corpus_preparation_sha256"],
        "original_preservation_preparation_full_canonical_sha256": reader_arguments["expected_preparation_sha256"],
        "original_source_file_sha256": manifest["original_source_file_sha256"],
        "assessment_file_sha256": reader_arguments["expected_assessment_file_sha256"],
        "review_input_tree_sha256": review_tree_pin,
        "review_intake_binding": manifest["review_intake_binding"],
        "review_dependency_manifest": manifest["review_dependency_manifest"],
        "original_preparation_state_sha256": _sha(_wire(manifest["original_preparation_state"])),
        "native_families": manifest["native_families"], "shared_interpretation": interpretation,
        "toolchain": observation["toolchain"], "binary_sha256": observation["expected_binary_sha256"],
        "producer_source_sha256": producers,
        "type_grammar_profile": "closed-Lean-Expr-Level-Name-with-exact-binder-annotations/v1",
        "full_quantified_kernel_target": True, "external_assumptions": "none",
        "installed_stdlib_artifact_closure_verified": False,
        "installed_stdlib_and_dynamic_libraries_are_external_trust_premises": True,
        "proof_authority": False,
    }


def _producer_pins(observation, owners):
    result = dict(observation["current_producer_pins"])
    result[str(Path(__file__).resolve())] = _SELF_PIN
    for owner in owners:
        path = Path(owner.__file__).resolve()
        pin = _sha(path.read_bytes())
        _need(str(path) not in result or result[str(path)] == pin, "kernel-claim producer identity changed")
        result[str(path)] = pin
    return result


def prepare_definition_use_preservation_kernel_claims_v2(
        native_packet_files, lineage, preservation_packet_files, corpus_preparation, assessment_raw, *,
        expected_elaboration_observation_sha256, **reader_arguments):
    """Replay retained elaboration twice and project fifteen closed candidates.

    All external assumptions are empty because proposition hypotheses already
    occur inside the complete quantified kernel type. Historical observations
    are evidence for the captured type, never a new request-scoped proof result.
    """
    _pin(expected_elaboration_observation_sha256, "exact current elaboration packet observation")
    _need(set(reader_arguments) == _READER_ARGUMENTS, "complete closed elaboration packet reader arguments required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "kernel-claim projection owner changed since import")
    from . import legal_corpus_definition_use_preservation_elaboration_packet_v2 as reader
    from . import legal_corpus_definition_use_preservation_packet_v2 as old_reader
    from . import legal_corpus_definition_use_preservation_theorem_lineage_v2 as storage
    from . import legal_corpus_definition_use_preservation_index_v2 as index
    old_reader._bound_tree(reader_arguments, old_reader.MAX_INPUT_BYTES, allow_bytes=True)
    input_pin = index._tree_digest(reader_arguments)
    review_tree_pin = index._tree_digest(reader_arguments["review_inputs"])
    old_corpus = old_reader._wire(old_reader._corpus_document(corpus_preparation), 20 * old_reader.MAX_RECORD_BYTES)
    lineage_pin = storage.lineage_sha256(lineage)
    lineage_claims = storage._wire(storage._claim_snapshot(lineage.claims))
    native_pin = reader.packet_sha256(native_packet_files)
    preservation_pin = old_reader.packet_sha256(preservation_packet_files)
    retained = reader.validate_definition_use_preservation_elaboration_packet_v2(
        native_packet_files, lineage, preservation_packet_files, corpus_preparation, assessment_raw, **reader_arguments)
    observation_raw = retained.observation_json.encode("utf-8")
    _need(_sha(observation_raw) == expected_elaboration_observation_sha256,
          "independent exact current elaboration observation pin differs")
    old_reader._bound_tree(reader_arguments, old_reader.MAX_INPUT_BYTES, allow_bytes=True)
    _need(index._tree_digest(reader_arguments) == input_pin and storage.lineage_sha256(lineage) == lineage_pin
          and storage._wire(storage._claim_snapshot(lineage.claims)) == lineage_claims,
          "original typed lineage or complete packet arguments changed across kernel projection replay")
    observation = retained.to_dict()
    _need(all(observation[field] is False for field in reader.FALSE_FLAGS)
          and _wire(observation["authority"]) == _wire(AUTHORITY)
          and all(value is False for value in observation["authority"].values())
          and type(observation["training_mask"]) is int and observation["training_mask"] == 0
          and type(observation["evaluation_gold_mask"]) is int and observation["evaluation_gold_mask"] == 0,
          "historical elaboration readback cannot grant kernel-claim proof authority")
    files = dict(retained.files)
    manifest = old_reader._parse(files["project/corpus-manifest.json"])
    captures = old_reader._parse(files["type-checks.json"])
    source_lineage = storage.RetainedCorpusTheoremLineage.to_dict(lineage)
    from . import corpus_contracts as contracts
    from ..ir_core import claims as claim_owner
    producers = _producer_pins(observation, (reader, old_reader, storage, index, contracts, claim_owner))
    semantic_context = _semantic_context(manifest, observation, reader_arguments, review_tree_pin, producers)
    semantic_pin = _sha(_wire(semantic_context))
    by_name = {row["original_theorem_name"]: row for row in manifest["probe_bindings"]}
    _need(len(by_name) == MAX_CLAIMS and list(by_name) == manifest["original_theorems"]
          and list(by_name) == [entry["theorem_name"] for entry in source_lineage["entries"]]
          and set(captures) == set(by_name), "exact fifteen original source/kernel binding population required")
    entries, claims = [], []
    for source_entry, old_claim in zip(source_lineage["entries"], lineage.claims, strict=True):
        theorem = source_entry["theorem_name"]
        capture, probe = captures[theorem], by_name[theorem]
        _need(capture["original_name"] == theorem and capture["alias_name"] == probe["probe_theorem_name"]
              and _wire(capture["original_type"]) == _wire(capture["alias_type"])
              and _wire(capture["original_level_params"]) == _wire(capture["alias_level_params"]),
              "exact captured complete original kernel type and universe inventory required")
        outer, associations, stable_hypotheses = _outer_bindings(source_entry, capture, probe["argument_names"])
        statement = {"schema": STATEMENT_SCHEMA, "type": capture["original_type"],
                     "level_parameters": capture["original_level_params"]}
        statement_raw = _wire(statement)
        type_pin = _sha(_wire(capture["original_type"]))
        levels_pin = _sha(_wire(capture["original_level_params"]))
        import_sources = [{"module": row["module"], "direct_imports": row["direct_imports"], "source": row["source"]}
                          for row in source_entry["declared_import_closure"]]
        source_bindings = {
            "theorem_name": theorem, "source_namespace": source_entry["source_namespace"],
            "role": source_entry["role"], "native_family": source_entry["native_family"],
            "target_declaration": source_entry["target_declaration"],
            "original_header_sha256": source_entry["byte_ranges"]["header"]["sha256"],
            "declared_import_sources": import_sources,
            "dependency_scope": "declared_transitive_import_source_closure_not_elaborated_term_dependencies",
        }
        kernel_context = {"semantic_context_sha256": semantic_pin, "semantic_source_bindings": source_bindings,
                          "kernel_statement_sha256": _sha(statement_raw), "quantified_hypotheses": stable_hypotheses,
                          "external_assumption_ids": []}
        kernel_pin = _sha(_wire(kernel_context))
        claim_id, obligation_id = "lean_kernel_claim:" + kernel_pin, "lean_kernel_obligation:" + kernel_pin
        metadata = claim_owner.FrozenMap({
            "statement_kind": STATEMENT_KIND, "statement_schema": STATEMENT_SCHEMA,
            "semantic_context_sha256": semantic_pin, "kernel_context_sha256": kernel_pin,
            "kernel_statement_sha256": _sha(statement_raw), "kernel_type_sha256": type_pin,
            "level_parameters_sha256": levels_pin, "source_namespace": source_entry["source_namespace"],
            "theorem_name": theorem, "quantified_hypothesis_count": len(associations),
            "external_assumption_count": 0, "closed_quantified_target": True,
            "proof_authority": False, "backend_request_prepared": False,
            "kernel_proposition_elaborated_by_projection": False,
            "elaborated_type_verified": False,
            "installed_stdlib_artifact_closure_verified": False,
        })
        source_refs = (source_entry["byte_ranges"]["header"]["path"],)
        obligation = claim_owner.ProofObligation(
            obligation_id=obligation_id, statement=statement_raw.decode("utf-8"), assumption_ids=(),
            logic_family="lean4", source_refs=source_refs, metadata=metadata)
        claim = claim_owner.IRClaim(
            claim_id=claim_id, statement=statement_raw.decode("utf-8"), assumptions=(), obligations=(obligation,),
            domain=DOMAIN, declaration_id=theorem, source_refs=source_refs, metadata=metadata)
        entries.append({
            "theorem_name": theorem, "source_namespace": source_entry["source_namespace"],
            "role": source_entry["role"], "native_family": source_entry["native_family"],
            "statement_kind": STATEMENT_KIND, "logic_family": "lean4",
            "kernel_statement_json": statement_raw.decode("utf-8"), "kernel_statement_sha256": _sha(statement_raw),
            "kernel_type_sha256": type_pin, "level_parameters_sha256": levels_pin,
            "kernel_context_sha256": kernel_pin, "kernel_context": kernel_context,
            "semantic_source_bindings": source_bindings,
            "claim_id": claim_id, "claim_digest": claim.digest, "declaration_id": theorem,
            "obligation_id": obligation_id, "obligation_digest": obligation.digest,
            "external_assumption_ids": [], "outer_binders": outer,
            "proposition_premise_associations": associations,
            "universal_parameter_count": len(outer) - len(associations),
            "source_header_claim": {
                "claim_id": old_claim.claim_id, "claim_digest": old_claim.digest,
                "declaration_id": old_claim.declaration_id, "declaration_header": old_claim.statement,
                "obligation_id": old_claim.obligations[0].obligation_id,
                "obligation_digest": old_claim.obligations[0].digest,
                "assumption_ids": list(old_claim.obligations[0].assumption_ids),
            },
            "evidence_refs": {
                "native_bundle_sha256": observation["native_bundle_sha256"],
                "native_receipt_file_sha256": observation["native_receipt_file_sha256"],
                "type_payload_file_sha256": observation["type_payload_file_sha256"],
                "elaboration_observation_sha256": expected_elaboration_observation_sha256,
                "elaboration_preparation_full_canonical_sha256": observation["elaboration_preparation_full_canonical_sha256"],
                "source_lineage_file_sha256": observation["lineage_file_sha256"],
                "original_record_sha256": _sha(_wire(capture)),
                "original_record_bytes": len(_wire(capture)),
                "probe_theorem_name": capture["alias_name"],
            },
            "status": "candidate", "proof_usable": False,
        })
        claims.append(claim)
    outer_count = sum(len(entry["outer_binders"]) for entry in entries)
    premise_count = sum(len(entry["proposition_premise_associations"]) for entry in entries)
    universal_count = sum(entry["universal_parameter_count"] for entry in entries)
    _need(len(claims) == MAX_CLAIMS and outer_count == 34 and premise_count == 5 and universal_count == 29
          and all(claim.assumptions == () and claim.obligations[0].assumption_ids == () for claim in claims),
          "exact fifteen closed kernel candidates, thirty-four binders and five quantified hypotheses required")
    record = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "statement_kind": STATEMENT_KIND, "logic_family": "lean4",
        "elaboration_observation_sha256": expected_elaboration_observation_sha256,
        "elaboration_observation_reference": {"sha256": _sha(observation_raw), "bytes": len(observation_raw), "schema": observation["schema"]},
        "native_bundle_sha256": observation["native_bundle_sha256"],
        "native_receipt_file_sha256": observation["native_receipt_file_sha256"],
        "type_payload_file_sha256": observation["type_payload_file_sha256"],
        "source_lineage_file_sha256": observation["lineage_file_sha256"],
        "elaboration_preparation_full_canonical_sha256": observation["elaboration_preparation_full_canonical_sha256"],
        "complete_reader_arguments_sha256": input_pin,
        "semantic_context": semantic_context, "semantic_context_sha256": semantic_pin,
        "producer_pins": producers, "original_preparation_state": manifest["original_preparation_state"],
        "entries": entries, "claims": [claim.to_dict() for claim in claims],
        "kernel_claim_count": MAX_CLAIMS, "external_assumption_count": 0,
        "outer_binder_count": outer_count, "universal_parameter_count": universal_count,
        "proposition_premise_association_count": premise_count,
        "kernel_claim_projection_prepared": True, "kernel_claim_prepared": True,
        "current_elaboration_packet_replayed": True,
        "original_opaque_claims_unchanged": True,
        "source_custody": {
            "full_current_elaboration_packet_replayed_before_and_after": True,
            "all_original_source_review_dependencies_replayed": True,
            "full_quantified_types_and_universe_inventories_retained": True,
            "proposition_domains_remain_scoped_to_complete_telescope_prefix": True,
            "stable_claim_identity_excludes_transient_native_observation_identity": True,
            "historical_process_liveness_inspected": False, "filesystem_acquisition_performed": False,
        },
        "trust_boundary": [
            "Independently trusted native receipt, type-payload and complete packet pins are provenance premises; self-sealed invented evidence is not authenticated.",
            "The statement is canonical full captured Lean kernel type plus universe parameters. No opaque source header is reinterpreted and no kernel elaboration runs here.",
            "The complete proposition already quantifies donor, consumer and alias hypotheses. External assumptions are empty; binder associations retain exact open domains and preceding de Bruijn contexts without establishing any fact.",
            "Original opaque header claim identities remain unchanged and are linked as evidence outside the new stable kernel claim metadata.",
            "Stable claim identity includes original pure source/preparation, assessment/review, interpretation, import-source, type grammar, toolchain/binary and external-library trust policy commitments. Native receipts, bundles, logs, PIDs, compiled artifacts, generated alias identities and opaque-claim digests remain separate evidence.",
            "Installed standard/dynamic libraries remain external trust premises; complete installed library and elaborated-term dependency closures are not verified.",
            "No BackendRequest, BackendAttempt, ProofResult, ProofReceipt or FormalizationArtifact is created; no compiler, cache, database, model or process-liveness operation occurs.",
        ],
        "proof_usable": False, "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **{key: value for key, value in reader.FALSE_FLAGS.items() if key != "kernel_claim_prepared"},
        **FALSE_FLAGS,
    })
    again = reader.validate_definition_use_preservation_elaboration_packet_v2(
        native_packet_files, lineage, preservation_packet_files, corpus_preparation, assessment_raw, **reader_arguments)
    old_reader._bound_tree(reader_arguments, old_reader.MAX_INPUT_BYTES, allow_bytes=True)
    _need(again.observation_json.encode("utf-8") == observation_raw
          and again.files == retained.files and _sha(observation_raw) == expected_elaboration_observation_sha256
          and index._tree_digest(reader_arguments) == input_pin
          and index._tree_digest(reader_arguments["review_inputs"]) == review_tree_pin
          and reader.packet_sha256(native_packet_files) == native_pin
          and old_reader.packet_sha256(preservation_packet_files) == preservation_pin
          and old_reader._wire(old_reader._corpus_document(corpus_preparation), 20 * old_reader.MAX_RECORD_BYTES) == old_corpus
          and storage.lineage_sha256(lineage) == lineage_pin
          and storage._wire(storage._claim_snapshot(lineage.claims)) == lineage_claims
          and all(_sha(Path(path).read_bytes()) == pin for path, pin in producers.items())
          and _sha(Path(__file__).read_bytes()) == _SELF_PIN,
          "complete kernel projection input, typed source lineage, observation or producer state changed")
    result = KernelClaimProjection(_wire(record).decode("utf-8"), tuple(claims))
    storage._check_claim_types(result.claims, claim_owner)
    projection_sha256(result)
    return result


def validate_definition_use_preservation_kernel_claims_v2(
        projection, native_packet_files, lineage, preservation_packet_files, corpus_preparation, assessment_raw, *,
        expected_projection_sha256, expected_elaboration_observation_sha256, **reader_arguments):
    """Require exact regenerated projection bytes and genuine typed candidates."""
    _pin(expected_projection_sha256, "exact complete kernel-claim projection")
    document, snapshot_raw = _projection_storage(projection)
    original_raw = projection.projection_json.encode("utf-8")
    _need(_sha(original_raw) == expected_projection_sha256, "independent exact kernel-claim projection pin differs")
    _need(all(document.get(key) is False for key in FALSE_FLAGS)
          and document.get("kernel_claim_prepared") is True
          and document.get("kernel_claim_projection_prepared") is True
          and document.get("proof_usable") is False and _wire(document.get("authority")) == _wire(AUTHORITY)
          and type(document.get("training_mask")) is int and document["training_mask"] == 0
          and type(document.get("evaluation_gold_mask")) is int and document["evaluation_gold_mask"] == 0
          and type(document.get("entries")) is list and len(document["entries"]) == MAX_CLAIMS
          and type(document.get("external_assumption_count")) is int and document["external_assumption_count"] == 0,
          "closed non-authorizing kernel candidate projection required")
    regenerated = prepare_definition_use_preservation_kernel_claims_v2(
        native_packet_files, lineage, preservation_packet_files, corpus_preparation, assessment_raw,
        expected_elaboration_observation_sha256=expected_elaboration_observation_sha256, **reader_arguments)
    from . import legal_corpus_definition_use_preservation_theorem_lineage_v2 as storage
    from ..ir_core import claims as claim_owner
    storage._check_claim_types(projection.claims, claim_owner)
    _need(projection.projection_json.encode("utf-8") == original_raw == regenerated.projection_json.encode("utf-8")
          and storage._wire(storage._claim_snapshot(projection.claims)) == snapshot_raw
          and snapshot_raw == storage._wire(storage._claim_snapshot(regenerated.claims)),
          "complete current kernel projection or typed identities differ from regeneration")
    return regenerated


__all__ = ["KernelClaimProjection", "FrozenKernelClaimProjection", "projection_sha256",
           "prepare_definition_use_preservation_kernel_claims_v2",
           "validate_definition_use_preservation_kernel_claims_v2"]
