"""Strict source-owned training cohorts for the unchanged scalar 384D trainer.

Labels come from separate native source and checker owners. Connected lineage
groups are frozen before fitting; neither intent nor predictions are accepted
as labels. A checked property is finite ProgramIR/state correspondence, never
Python runtime equivalence or a security specification.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import weakref

from . import codebase_source_384 as source384
from ..formalization.autoencoder import source_state_lake
from ..formalization.autoencoder.security import source_program_binding_384_v2 as binding

SCHEMA = "codebase-training-corpus@1"
PROFILE = "source384-scalar-connected-lineage@1"
_ISSUED = weakref.WeakKeyDictionary()
_raw, _sha, _require = source384._raw, source384._sha, source384._require


def _pins():
    return dict(corpus_owner=_sha(Path(__file__).read_bytes()), source_owner=source384._pins(),
                checked_property_owner=source_state_lake._pins())


def _alpha(source):
    """Normalize exactly the reviewed scalar program's bound local names."""
    source384._target(source)
    tree = ast.parse(source)
    function = tree.body[0]
    names = {argument.arg: "parameter_" + str(i) for i, argument in enumerate(function.args.args)}
    assigned = sorted({node.id for node in ast.walk(function) if isinstance(node, ast.Name)
                       and isinstance(node.ctx, ast.Store)})
    names.update({name: "local_" + str(i) for i, name in enumerate(assigned)})
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and node.id in names:
            node.id = names[node.id]
        elif isinstance(node, ast.arg) and node.arg in names:
            node.arg = names[node.arg]
    function.name = "function"
    return _sha(ast.dump(tree, include_attributes=False).encode())


def _components(rows, lineage_edges):
    by_path = {row["path"]: row for row in rows}
    _require(type(lineage_edges) in (list, tuple) and len(lineage_edges) <= 1024,
             "bounded declared lineage required")
    parent = {path: path for path in by_path}

    def find(path):
        while parent[path] != path:
            parent[path] = parent[parent[path]]
            path = parent[path]
        return path

    def union(left, right):
        left, right = find(left), find(right)
        parent[max(left, right)] = min(left, right)

    edges, seen = [], {}
    for row in rows:
        for kind, value in (("exact_source", row["source_sha256"]),
                            ("alpha_clone", _alpha(row["source_text"])),
                            ("declared_group", row["group_id"])):
            prior = seen.setdefault((kind, value), row["path"])
            if prior != row["path"]:
                union(prior, row["path"])
                edges.append(dict(left=prior, right=row["path"], relation=kind, identity=value))
    declared = []
    for edge in lineage_edges:
        _require(type(edge) is dict and set(edge) == {"left", "right", "relation"}
            and edge["left"] in by_path and edge["right"] in by_path and edge["left"] != edge["right"]
            and edge["relation"] in {"rename", "revision", "conservative_related"},
            "closed conservative lineage edge required")
        item = dict(left=min(edge["left"], edge["right"]), right=max(edge["left"], edge["right"]),
                    relation=edge["relation"])
        union(item["left"], item["right"])
        declared.append(item)
    groups = {}
    for path in sorted(by_path):
        groups.setdefault(find(path), []).append(path)
    components = []
    for paths in groups.values():
        roles = {by_path[path]["role"] for path in paths}
        _require(len(roles) == 1, "connected source/rename/lineage component crosses corpus splits")
        components.append(dict(component_id=_sha(_raw(paths)), paths=paths, role=next(iter(roles))))
    return sorted(components, key=lambda x: x["component_id"]), sorted(edges + declared, key=_raw)


def property_rows(source_corpus, input_domains):
    _require(type(input_domains) is dict and len(input_domains) <= source_state_lake.MAX_ROWS,
             "bounded explicit checked-property selection required")
    by_path = {row["path"]: row for row in source_corpus["rows"]}
    _require(set(input_domains) <= set(by_path), "checked property outside captured corpus")
    return [dict(id=by_path[path]["id"], source_text=by_path[path]["source_text"],
        candidate_ir=deepcopy(by_path[path]["target"]), input_domains=deepcopy(input_domains[path]))
        for path in sorted(input_domains)]


def check_properties(index, *, expected_head, selections, input_domains,
                     lake_executable, timeout_seconds=60, output_directory=None,
                     scheduler=None, parent_lease=None, cancel_event=None):
    """Issue an independent native handle for the complete selected finite table."""
    corpus = source384.prepare_corpus(index, expected_head=expected_head, selections=selections)
    rows = property_rows(corpus, input_domains)
    _require(bool(rows), "nonempty property check required")
    from .codebase_resources import acquire_codebase_resources
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(30, timeout_seconds), memory_mb=1024) as lease:
        _require(not lease.combined_cancellation_signal(cancel_event).is_set(), "property check cancelled")
        result = source_state_lake.build_source_state_lake(rows, lake_executable=lake_executable,
            timeout_seconds=timeout_seconds, output_directory=output_directory)
        _require(not lease.combined_cancellation_signal(cancel_event).is_set(), "property check cancelled")
        return result


def _build(index, *, expected_head, selections, lineage_edges, input_domains,
           checked_execution, transductive_source_context):
    _require(type(transductive_source_context) is bool, "explicit transductive-use flag required")
    source = source384.prepare_corpus(index, expected_head=expected_head, selections=selections)
    components, edges = _components(source["rows"], lineage_edges)
    if checked_execution is None:
        _require(input_domains == {}, "property domains require an independently issued checker handle")
        receipt, checked = None, {}
    else:
        receipt = source_state_lake.verify_source_state_lake(checked_execution,
            property_rows(source, input_domains))
        checked = {row["id"]: row for row in receipt["rows"]}
    component = {path: item["component_id"] for item in components for path in item["paths"]}
    representatives, rows = {}, []
    for row in source["rows"]:
        alpha = _alpha(row["source_text"])
        representative = representatives.setdefault(alpha, row["path"])
        semantic = binding.qualify_source_candidate(row["source_text"], row["target"])
        _require(semantic["status"] == "qualified", "source semantic label no longer qualifies")
        verified = checked.get(row["id"])
        prop = dict(status="missing", target=None, provenance=None,
                    reason="no_independent_checker_result")
        if verified is not None:
            passed = verified["finite_correspondence_kernel_checked"] is True
            prop = dict(status="checked_within_model" if passed else "unknown", target=(
                dict(property="finite_program_state_correspondence", cases=verified["model"]["cases"],
                     case_count=verified["case_count"], input_domains=input_domains[row["path"]],
                     assumptions=verified["model"]["assumptions"],
                     scope=receipt["scope"], source_program_sha256=verified["model"]["source_program_sha256"])
                if passed else None), reason=None if passed else verified["status"],
                provenance=dict(owner=source_state_lake.SCHEMA, receipt_sha256=_sha(_raw(receipt)),
                    source_sha256=verified["source_sha256"], candidate_sha256=verified["candidate_sha256"],
                    input_domains_sha256=verified["input_domains_sha256"],
                    producer=receipt["producer"], tools=receipt["tool_binary_sha256"],
                    finite_correspondence_kernel_checked=passed,
                    python_equivalence_proved=False, proof_authority=False))
        syntax = ast.dump(ast.parse(row["source_text"]), include_attributes=False)
        rows.append(dict(**deepcopy(row), alpha_clone_sha256=alpha, component_id=component[row["path"]],
            fit_eligible=representative == row["path"], duplicate_of=None if representative == row["path"] else representative,
            objectives=dict(syntax=dict(status="independent_source_parse", target=syntax),
                semantic=dict(status="independent_source_alignment", target=deepcopy(row["target"]),
                    native_program=semantic["projections"][0]["native_document"],
                    python_equivalence_proved=False), checked_property=prop),
            label_provenance=dict(kind="deterministic_reviewed_source_and_native_checker",
                source_cid=row["source_cid"], source_sha256=row["source_sha256"], learned_teacher_used=False,
                desired_intent_used=False, unchecked_prediction_used=False)))
    fit = [dict(path=row["path"], role=row["role"], group_id=row["component_id"])
           for row in rows if row["fit_eligible"]]
    fit_corpus = source384.prepare_corpus(index, expected_head=expected_head, selections=fit)
    value = dict(schema=SCHEMA, profile=PROFILE, producer=_pins(), source_corpus=source,
        rows=rows, components=components, lineage_edges=edges, fit_source_corpus=fit_corpus,
        split_policy="connected_exact_alpha_clone_group_and_declared_lineage_before_fit",
        deduplication="one_lexicographic_representative_per_alpha_clone_within_one_split",
        denominator=dict(enumerated=len(rows), fitted_representatives=len(fit),
            deduplicated=len(rows)-len(fit), missing_properties=sum(r["objectives"]["checked_property"]["status"] == "missing" for r in rows),
            unknown_properties=sum(r["objectives"]["checked_property"]["status"] == "unknown" for r in rows),
            checked_properties=sum(r["objectives"]["checked_property"]["status"] == "checked_within_model" for r in rows)),
        transductive_source_context=transductive_source_context,
        pretraining_exposure=dict(status="unknown", complete_parent_training_corpus_available=False),
        heldout_labels_used_for_fitting=False, teacher_predictions_accepted=False,
        declared_lineage_is_correctness_evidence=False, property_receipt=receipt,
        fixed_semantics_outside_latent_space=True, **source384.FALSE)
    value["corpus_sha256"] = _sha(_raw(value))
    _require(len(_raw(value)) <= source384.MAX_BYTES, "frozen corpus exceeds artifact byte budget")
    return value


@dataclass(frozen=True, eq=False)
class FrozenCodebaseCorpus:
    """Locally issued pre-fit cohort; persisted JSON has no issuing authority."""
    def to_dict(self):
        _require(self in _ISSUED, "locally issued frozen corpus required")
        return deepcopy(_ISSUED[self]["value"])


def freeze_corpus(index, *, expected_head, selections, lineage_edges=(),
                  input_domains=None, checked_execution=None, transductive_source_context=False):
    _require(input_domains is None or type(input_domains) is dict, "explicit property domain mapping required")
    arguments = dict(expected_head=expected_head, selections=deepcopy(selections),
        lineage_edges=deepcopy(lineage_edges), input_domains=deepcopy({} if input_domains is None else input_domains),
        checked_execution=checked_execution, transductive_source_context=transductive_source_context)
    value = _build(index, **arguments)
    handle = FrozenCodebaseCorpus()
    _ISSUED[handle] = dict(index=index, arguments=arguments, value=value)
    return handle


def verify_frozen_corpus(handle, index, *, expected_head):
    _require(type(handle) is FrozenCodebaseCorpus and handle in _ISSUED,
             "locally issued frozen corpus required before fitting")
    state = _ISSUED[handle]
    _require(state["index"] is index and state["arguments"]["expected_head"] == expected_head,
             "frozen corpus source owner/head differs")
    replayed = _build(index, **state["arguments"])
    _require(_raw(replayed) == _raw(state["value"]), "frozen corpus or source/checker producer changed")
    return replayed


__all__ = ["freeze_corpus", "verify_frozen_corpus", "check_properties", "FrozenCodebaseCorpus"]
