"""Bounded supervisor loop: autoformal errors become ingestible todos and goals.

The accelerate supervisor owns claims and completion. This adapter runs the
autoformal script, converts remaining gaps into todos, synthesizes related
todos into goals, and re-ingests. A strict round-trip is an engineering
receipt, not a legal proof or admit. JSONL is not written.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .supervisor_todo import (
    GOAL_PREFIX,
    agreement_from_spans,
    agreement_from_strict_spans,
    discrepancy_tasks,
    submit_discrepancies,
)


SCHEMA = "uscode-autoformal-supervisor-loop/v1"
ARCHITECTURE_MODES = frozenset(
    {
        "no_parser_elements",
        "compiler_abstain",
        "schema_placeholder",
        "strict_roundtrip_failed",
    }
)
MAX_ROUNDS = 8
OBJECTIVE_ID = "objective:uscode-autoformal"
CAMPAIGN_GOAL_ID = f"{GOAL_PREFIX}000"
POPULATION_SCHEMA = "ipfs_accelerate_py.agent_supervisor.database_task_source.population/v1"


class SupervisorLoopError(RuntimeError):
    """The autoformal supervisor loop cannot continue without inventing work."""


def prepare_handoff_execution_packet_v1(
    *,
    programme_links: Mapping[str, Any],
    current_directives: Mapping[str, Any],
    current_task_metadata: Mapping[str, Any],
    execution_envelope: Mapping[str, Any],
) -> dict[str, Any]:
    """Prepare a detached 9001–9004 review preview; never claim or admit work.

    Inputs are supplied JSON metadata, not authenticated native readback. A
    complete envelope still needs the original owners to verify its bytes,
    current revisions, scope, exhausted-attempt disposition and acceptance.
    No descriptor is opened, no CID is created and no command is invoked.
    Profiles keep source width, actual bottleneck, sidecars, schema and task
    separate. Target-derived material cannot be labelled inference input.
    Explicit control_metadata_only previews carry no decoder profile, model
    assets, inference inputs or supervision inputs.
    """
    supplied = {}
    for name, value in (("programme_links", programme_links), ("current_directives", current_directives),
                        ("current_task_metadata", current_task_metadata), ("execution_envelope", execution_envelope)):
        if not isinstance(value, Mapping):
            raise ValueError(f"{name} must be a JSON mapping")
        try:
            supplied[name] = json.loads(json.dumps(dict(value), allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must contain finite JSON data") from exc
    programme, directives, task, envelope = (supplied[name] for name in
        ("programme_links", "current_directives", "current_task_metadata", "execution_envelope"))
    missing: list[str] = []

    def require(condition: bool, reason: str) -> None:
        if not condition and reason not in missing:
            missing.append(reason)

    def text(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip()) and "\x00" not in value

    def positive(value: Any) -> bool:
        return type(value) is int and value > 0

    def strings(value: Any, *, empty: bool = False) -> bool:
        return (isinstance(value, list) and (empty or bool(value))
                and all(text(item) for item in value) and len(value) == len(set(value)))

    def arguments(value: Any) -> bool:
        return isinstance(value, list) and 0 < len(value) <= 128 and all(text(item) for item in value)

    def path(value: Any, *, absolute: bool = False) -> bool:
        return (text(value) and (not absolute or value.startswith("/"))
                and ".." not in value.split("/") and not any(c in value for c in "*?[]"))

    def descriptor(value: Any) -> bool:
        return (isinstance(value, dict) and set(value) == {"path", "bytes", "sha256"}
                and path(value.get("path")) and type(value.get("bytes")) is int and value["bytes"] >= 0
                and isinstance(value.get("sha256"), str) and len(value["sha256"]) == 64
                and all(c in "0123456789abcdef" for c in value["sha256"]))

    def dependencies(value: Any) -> bool:
        return (isinstance(value, list) and all(isinstance(item, dict)
                and set(item) == {"task_cid", "revision"} and text(item.get("task_cid"))
                and positive(item.get("revision")) for item in value)
                and len({item["task_cid"] for item in value}) == len(value))

    alias = envelope.get("task_alias")
    require(isinstance(alias, str) and alias in {"LIR-9001", "LIR-9002", "LIR-9003", "LIR-9004"}, "unsupported_handoff_task")
    require(programme.get("schema") == "legal-ir-existing-native-programme-links/v1", "programme_schema_missing")
    links = programme.get("unparented_handoff_and_engineering_task_links", [])
    selected = [item for item in links if isinstance(item, dict) and item.get("task_alias") == alias] if isinstance(links, list) else []
    require(len(selected) == 1, "exact_programme_task_link_required")
    link = selected[0] if len(selected) == 1 else {}
    for key in ("task_alias", "task_cid", "goal_cid"):
        require(text(task.get(key)) and task.get(key) == envelope.get(key) == link.get(key), f"identity_mismatch:{key}")
    require(link.get("goal_alias") == "LIR-G090", "handoff_goal_mismatch")
    for key, programme_key in (("plan_cid", "historical_plan_root_cid"), ("repository_tree_id", "historical_repository_tree_id")):
        require(text(task.get(key)) and task.get(key) == envelope.get(key) == programme.get(programme_key), f"identity_mismatch:{key}")
    require(positive(task.get("revision")) and task.get("revision") == envelope.get("revision"), "current_revision_binding_required")
    require(dependencies(task.get("dependencies")) and dependencies(envelope.get("dependencies"))
            and task.get("dependencies") == envelope.get("dependencies"), "exact_dependency_revisions_required")
    directive_ids = envelope.get("directive_ids")
    require(strings(directive_ids), "directive_ids_required")
    if isinstance(directive_ids, list):
        for identifier in directive_ids:
            directive = directives.get(identifier) if isinstance(identifier, str) else None
            require(isinstance(directive, dict) and directive.get("schema") == "legal-ir-existing-task-directive/v1",
                    f"current_directive_required:{identifier}")
    history = task.get("attempt_history")
    require(isinstance(history, dict), "attempt_history_required")
    if isinstance(history, dict):
        require(type(history.get("attempts")) is int and history["attempts"] >= 0
                and positive(history.get("max_attempts")) and type(history.get("exhausted")) is bool
                and isinstance(history.get("history"), list), "attempt_history_invalid")
        spent = history.get("exhausted") is True or (type(history.get("attempts")) is int
                and positive(history.get("max_attempts")) and history["attempts"] >= history["max_attempts"])
        if spent:
            disposition = task.get("original_owner_disposition")
            require(isinstance(disposition, dict) and disposition.get("task_cid") == task.get("task_cid")
                    and disposition.get("revision") == task.get("revision")
                    and disposition.get("action") == "review_preview_only"
                    and descriptor(disposition.get("receipt")), "exhausted_attempt_original_owner_disposition_required")
    for flag in ("dispatch", "rearm", "start_workers", "admitted", "native_admission",
                 "task_completion_authority", "goal_completion_authority"):
        require(flag not in envelope or envelope[flag] is False, f"authority_request_forbidden:{flag}")
    execution_kind = envelope.get("execution_kind", "model")
    require(isinstance(execution_kind, str) and execution_kind in {"model", "control_metadata_only"},
            "execution_kind_invalid")
    control_metadata_only = execution_kind == "control_metadata_only"
    profile = envelope.get("profile")
    if control_metadata_only:
        require(profile is None, "control_metadata_profile_forbidden")
    else:
        profile_keys = {"ir_family", "schema_version", "decoder_task", "source_dimension", "actual_bottleneck_dimension",
                        "sidecars", "input_token_limit", "output_token_limit"}
        require(isinstance(profile, dict) and profile_keys <= set(profile), "profile_identity_required")
        if isinstance(profile, dict):
            require(profile.get("ir_family") == "legal_ir" and text(profile.get("schema_version"))
                    and text(profile.get("decoder_task")) and type(profile.get("source_dimension")) is int
                    and profile["source_dimension"] in {8, 384, 768, 4096}
                    and positive(profile.get("actual_bottleneck_dimension"))
                    and strings(profile.get("sidecars"), empty=True)
                    and positive(profile.get("input_token_limit")) and positive(profile.get("output_token_limit")), "profile_identity_invalid")
    inputs = envelope.get("inputs")
    require(isinstance(inputs, list) and bool(inputs), "role_bound_inputs_required")
    if isinstance(inputs, list):
        # A second label/path cannot turn the same committed target bytes into
        # inference context. Combined files need a separately reviewed selector
        # contract; a caller's target_derived=False is not such a projection.
        protected_content = set()
        for item in inputs:
            if (isinstance(item, dict) and descriptor(item.get("descriptor"))
                    and (item.get("role") == "target" or item.get("role") == "review"
                         or item.get("target_derived") is True)):
                pin = item["descriptor"]
                protected_content.add((pin["bytes"], pin["sha256"]))
        roles = {"source", "context", "representation", "checkpoint", "target", "review", "code", "directives", "prior_evidence"}
        for index, item in enumerate(inputs):
            require(isinstance(item, dict), f"input_invalid:{index}")
            if not isinstance(item, dict):
                continue
            role, use = item.get("role"), item.get("use")
            require(isinstance(role, str) and role in roles and isinstance(use, str)
                    and use in {"inference", "supervision", "verification", "provenance"}
                    and descriptor(item.get("descriptor")), f"input_binding_invalid:{index}")
            if control_metadata_only:
                require(role != "representation" and role != "checkpoint", f"control_metadata_model_asset_forbidden:{index}")
                require("profile" not in item, f"control_metadata_input_profile_forbidden:{index}")
                require(use != "inference" and use != "supervision", f"control_metadata_model_use_forbidden:{index}")
            elif role == "representation" or role == "checkpoint" or "profile" in item:
                require(item.get("profile") == profile and isinstance(profile, dict), f"input_profile_mismatch:{index}")
            if "target_derived" in item:
                require(type(item["target_derived"]) is bool, f"target_derivation_flag_invalid:{index}")
            if use == "inference":
                require(role != "target" and role != "review" and item.get("target_derived") is False,
                        f"target_inference_leak:{index}")
                pin = item.get("descriptor")
                require(not descriptor(pin) or (pin["bytes"], pin["sha256"]) not in protected_content,
                        f"cross_input_target_inference_leak:{index}")
                if role == "context":
                    require(descriptor(item.get("permission_evidence")), f"inference_context_permission_required:{index}")
    require(arguments(envelope.get("argv")), "exact_argv_required")
    require(path(envelope.get("cwd"), absolute=True), "absolute_cwd_required")
    for key in ("outputs", "code_allowlist", "test_allowlist"):
        values = envelope.get(key)
        require(strings(values, empty=key == "code_allowlist")
                and all(path(value) for value in values), f"explicit_paths_required:{key}")
    require(strings(envelope.get("exclusive_keys")), "exclusive_keys_required")
    budgets = envelope.get("budgets")
    budget_keys = {"cpu_threads", "memory_mib", "storage_bytes", "max_children", "max_tokens", "deadline_seconds", "max_attempts"}
    require(isinstance(budgets, dict) and set(budgets) == budget_keys
            and all(positive(value) for value in budgets.values()), "finite_positive_budgets_required")
    worker, verifier = envelope.get("worker"), envelope.get("verifier")
    require(isinstance(worker, dict) and text(worker.get("role")) and text(worker.get("principal")), "worker_role_required")
    require(isinstance(verifier, dict) and verifier.get("role") == "independent_acceptance"
            and text(verifier.get("principal")) and isinstance(worker, dict)
            and verifier.get("principal") != worker.get("principal") and arguments(verifier.get("argv")), "independent_verifier_required")
    gates = ["original_owner_current_revision_dependencies_and_scope_verification_required",
             "independent_input_bytes_profile_permissions_and_acceptance_verification_required"]
    return {
        "schema": "legal-ir-supervisor-handoff-execution-packet-preview/v1", "scope": "review_preview_only",
        "metadata_complete": not missing, "metadata_blockers": missing, "independent_verification_gates": gates,
        "independently_verified": False, "descriptor_hashes_verified": False, "native_status_verified": False,
        "dispatch_authorized": False, "rearm_authorized": False, "native_admission": False,
        "workers_started": False, "task_completion_authority": False, "goal_completion_authority": False,
        "completion_authority": False, "admitted": False, "formalized": False,
        "training_authorized": False, "semantic_review_verified": False,
        "supervision_masks": {"training": 0, "evaluation_gold": 0}, "supplied_metadata": supplied,
    }


def _handoff_reconciliation_bytes_v2(value: Any) -> bytes:
    """Canonical bounded JSON used by the factual report and its freeze."""
    try:
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("handoff metadata must be finite JSON") from exc
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("handoff metadata exceeds its byte bound")
    return raw


def _handoff_reconciliation_facts_v2(
    *, original_population: Mapping[str, Any], current_snapshot: Mapping[str, Any],
    backlog: Mapping[str, Any], work_catalog: Mapping[str, Any],
    prior_task_metadata: Mapping[str, Any], producer_principal: str,
    expected_task_revision: int = 14, reviewed_current_task_amendments: Any = None,
) -> dict[str, Any]:
    """Check supplied metadata joins; authentication stays with native owners."""
    def need(condition: bool, reason: str) -> None:
        if not condition:
            raise ValueError(reason)

    def text(value: Any) -> bool:
        return type(value) is str and 0 < len(value) <= 512 and not any(ord(c) < 32 for c in value)

    def index(rows: Any, key: str, count: int) -> dict[str, Any]:
        need(type(rows) is list and len(rows) == count, "population count differs: " + key)
        need(all(type(row) is dict and text(row.get(key)) for row in rows), "invalid row: " + key)
        result = {row[key]: row for row in rows}
        need(len(result) == count, "duplicate identity: " + key)
        return result

    supplied = {"original_population": original_population, "current_snapshot": current_snapshot,
                "backlog": backlog, "work_catalog": work_catalog,
                "prior_task_metadata": prior_task_metadata,
                "reviewed_current_task_amendments": [] if reviewed_current_task_amendments is None else reviewed_current_task_amendments}
    detached = {}
    commitments = {}
    for name, value in supplied.items():
        if name == "reviewed_current_task_amendments":
            need(type(value) is list, "reviewed amendments must be a list")
            raw = _handoff_reconciliation_bytes_v2(value)
        else:
            need(isinstance(value, Mapping), "metadata mapping required: " + name)
            raw = _handoff_reconciliation_bytes_v2(dict(value))
        detached[name] = json.loads(raw)
        commitments[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    old, current, maintained, catalog, prior = (detached[k] for k in
        ("original_population", "current_snapshot", "backlog", "work_catalog", "prior_task_metadata"))
    need(text(producer_principal), "producer principal required")
    need(type(expected_task_revision) is int and expected_task_revision == 14,
         "this replacement contract requires task revision 14")
    need(old.get("schema") == "legal-ir-native-task-population/v1", "original population schema differs")
    need(current.get("schema") == "legal-ir-current-native-programme-snapshot/v2", "current snapshot schema differs")
    for key in ("board_namespace", "plan_root_cid", "repository_tree_id"):
        need(text(old.get(key)) and old[key] == current.get(key), "programme binding differs: " + key)
    need(maintained.get("schema") == "legal-ir-active-work-items/v1", "backlog schema differs")
    programme = maintained.get("supervisor_programme")
    need(type(programme) is dict and programme.get("schema") == "legal-ir-existing-native-programme-links/v1",
         "programme crosswalk missing")
    for old_key, current_key in (("board_namespace", "historical_board_namespace"),
                                 ("plan_root_cid", "historical_plan_root_cid"),
                                 ("repository_tree_id", "historical_repository_tree_id")):
        need(old[old_key] == programme.get(current_key), "maintained programme identity differs")
    before = index(old.get("tasks"), "task_alias", 64)
    now = index(current.get("tasks"), "task_alias", 64)
    need(set(before) == set(now), "task aliases differ")
    need(all(text(row.get("task_cid")) for row in list(before.values()) + list(now.values())), "task CID missing")
    need(len({row.get("task_cid") for row in before.values()}) == 64, "duplicate original task CID")
    need(len({row.get("task_cid") for row in now.values()}) == 64, "duplicate current task CID")
    allowed_amendments = {
        "LIR-0101": {"existing_owners", "objective", "inputs", "acceptance_criteria", "acceptance"},
        "LIR-0201": {"existing_owners", "objective", "inputs", "acceptance_criteria", "acceptance", "title"},
        "LIR-0202": {"existing_owners", "objective", "inputs", "acceptance_criteria", "acceptance"},
        "LIR-0502": {"acceptance_criteria", "acceptance"},
    }
    approval_rows = detached["reviewed_current_task_amendments"]
    need(len(approval_rows) in (0, 4), "reviewed authoring amendment population differs")
    approvals = {}
    approved_fields = {"task_alias", "task_cid", "revision", "original_authored_sha256", "current_authored_sha256", "review"}
    def is_sha(value: Any) -> bool:
        return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    for row in approval_rows:
        need(type(row) is dict and set(row) == approved_fields and row.get("task_alias") in allowed_amendments
             and row["task_alias"] not in approvals and row["task_alias"] in before,
             "reviewed authoring amendment identity differs")
        need(row.get("task_cid") == before[row["task_alias"]]["task_cid"] and type(row.get("revision")) is int
             and row["revision"] == 3 and is_sha(row.get("original_authored_sha256"))
             and is_sha(row.get("current_authored_sha256")), "reviewed authoring amendment binding differs")
        proof = row.get("review")
        need(type(proof) is dict and set(proof) == {"path", "bytes", "sha256"} and text(proof.get("path"))
             and type(proof.get("bytes")) is int and proof["bytes"] > 0 and is_sha(proof.get("sha256")),
             "reviewed authoring descriptor missing")
        approvals[row["task_alias"]] = row
    need(not approvals or set(approvals) == set(allowed_amendments), "exact four reviewed amendments required")
    need(not approval_rows or all(row["review"] == approval_rows[0]["review"] for row in approval_rows),
         "reviewed authoring source descriptors differ")
    authoring_differences = []
    old_goals = index(old.get("goals"), "goal_cid", 34)
    new_goals = index(current.get("goals"), "goal_cid", 34)
    need(set(old_goals) == set(new_goals), "goal identities differ")
    need(all(text(row.get("goal_alias")) for row in old_goals.values()), "goal alias missing")
    need(len({row.get("goal_alias") for row in old_goals.values()}) == 34, "duplicate goal alias")
    for cid, goal in old_goals.items():
        other = new_goals[cid]
        for key in ("goal_alias", "parent_goal_cid", "objective_id"):
            need(goal.get(key) == other.get(key), "goal binding differs: " + key)
    old_edges, new_edges = old.get("goal_edges"), current.get("goal_edges")
    need(type(old_edges) is list and type(new_edges) is list and len(old_edges) == len(new_edges) == 33,
         "goal edge count differs")
    edge_keys = {"parent_goal_cid", "child_goal_cid", "edge_kind"}
    need(all(type(edge) is dict and set(edge) == edge_keys and edge.get("edge_kind") == "goal_parent"
             and edge.get("parent_goal_cid") in old_goals and edge.get("child_goal_cid") in old_goals
             and old_goals[edge["child_goal_cid"]].get("parent_goal_cid") == edge["parent_goal_cid"]
             for edge in old_edges + new_edges), "goal edge endpoint differs")
    edge_identity = lambda rows: sorted(_handoff_reconciliation_bytes_v2(row) for row in rows)
    need(edge_identity(old_edges) == edge_identity(new_edges) and len(set(edge_identity(old_edges))) == 33,
         "goal edges differ or repeat")
    for start in old_goals:
        seen = set()
        at = start
        while at:
            need(at in old_goals and at not in seen, "goal parent cycle or missing goal")
            seen.add(at)
            at = old_goals[at].get("parent_goal_cid")
    need(sum(not row.get("parent_goal_cid") for row in old_goals.values()) == 1, "goal root count differs")
    need(all(text(row.get("task_cid")) and text(row.get("goal_cid")) and text(row.get("plan_cid"))
             and text(row.get("objective_id")) for row in before.values()), "task identity missing")
    cids = {row["task_cid"] for row in before.values()}
    dependencies = {}
    states = []
    for alias, original in before.items():
        selected = now[alias]
        for key in ("task_cid", "goal_cid", "plan_cid", "objective_id", "legacy_parent_task"):
            need(original.get(key) == selected.get(key), "task binding differs: " + alias + ":" + key)
        original_authored, current_authored = original.get("authored_task"), selected.get("authored_task")
        if original_authored != current_authored:
            approval = approvals.get(alias)
            need(type(original_authored) is dict and type(current_authored) is dict and approval is not None,
                 "unreviewed task authoring changed: " + alias)
            changed_fields = {key for key in set(original_authored) | set(current_authored)
                              if original_authored.get(key) != current_authored.get(key)}
            old_sha = hashlib.sha256(_handoff_reconciliation_bytes_v2(original_authored)[:-1]).hexdigest()
            current_sha = hashlib.sha256(_handoff_reconciliation_bytes_v2(current_authored)[:-1]).hexdigest()
            need(changed_fields == allowed_amendments[alias] and selected.get("revision") == approval["revision"]
                 and old_sha == approval["original_authored_sha256"] and current_sha == approval["current_authored_sha256"],
                 "reviewed task authoring content differs: " + alias)
            authoring_differences.append({**approval, "changed_fields": sorted(changed_fields),
                                         "scope": "retained_current_directive_strengthening_only"})
        need(selected.get("goal_cid") in old_goals and selected.get("plan_cid") == old["plan_root_cid"],
             "task goal or plan differs")
        need(type(selected.get("revision")) is int and selected["revision"] > 0 and text(selected.get("status")),
             "current task revision/status missing")
        for row in (original, selected):
            deps = row.get("dependencies")
            need(type(deps) is list and all(type(dep) is str and dep in cids for dep in deps)
                 and len(deps) == len(set(deps)) and row["task_cid"] not in deps, "task dependencies invalid")
        need(sorted(original["dependencies"]) == sorted(selected["dependencies"]), "task dependencies changed")
        dependencies[selected["task_cid"]] = list(selected["dependencies"])
        states.append({"task_alias": alias, "task_cid": selected["task_cid"],
                       "revision": selected["revision"], "status": selected["status"]})
    need({row["task_alias"] for row in authoring_differences} == set(approvals), "unused authoring amendment approval")
    need(sum(map(len, dependencies.values())) == 115, "task dependency count differs")
    visited, visiting = set(), set()
    def visit(cid: str) -> None:
        need(cid not in visiting, "task dependency cycle")
        if cid not in visited:
            visiting.add(cid)
            for dep in dependencies[cid]:
                visit(dep)
            visiting.remove(cid)
            visited.add(cid)
    for cid in dependencies:
        visit(cid)
    plans = old.get("plans")
    need(type(plans) is list and len(plans) == 1 and type(plans[0]) is dict
         and plans[0].get("plan_cid") == old["plan_root_cid"],
         "original plan missing")
    parents = index(plans[0].get("legacy_parent_crosswalk"), "id", 24)
    maintained_parents = index(maintained.get("tasks"), "id", 24)
    expected_parents = {"LIR-" + str(n).zfill(2) for n in range(1, 25)}
    need(set(parents) == set(maintained_parents) == expected_parents, "original 24 parent IDs differ")
    crosswalk, linked = [], set()
    for parent in sorted(parents):
        original, selected = parents[parent], maintained_parents[parent]
        need(original.get("related_lac_equivalence") == "unreviewed_related_scope_only",
             "LAC equivalence was promoted")
        need(selected.get("related_lac_equivalence", "unreviewed_related_scope_only") == "unreviewed_related_scope_only",
             "current LAC equivalence was promoted")
        need(original.get("depends_on") == selected.get("depends_on"), "parent dependencies changed")
        need(type(selected.get("supervisor_execution")) is dict, "parent execution crosswalk missing")
        links = selected["supervisor_execution"].get("task_links")
        need(type(links) is list and links, "native parent task links missing")
        aliases = []
        for link in links:
            need(type(link) is dict and link.get("task_alias") in before, "unknown parent child")
            child = before[link["task_alias"]]
            need(all(link.get(k) == child.get(k) for k in ("task_cid", "goal_cid", "legacy_parent_task"))
                 and child.get("legacy_parent_task") == parent and link["task_alias"] not in linked,
                 "parent child identity differs")
            linked.add(link["task_alias"])
            aliases.append(link["task_alias"])
        need(sorted(aliases) == sorted(original.get("subtasks", [])), "parent child population changed")
        crosswalk.append({"parent_id": parent, "task_aliases": sorted(aliases),
                          "related_lac_tasks": original.get("related_lac_tasks", []),
                          "related_lac_equivalence": "unreviewed_related_scope_only"})
    unparented = programme.get("unparented_handoff_and_engineering_task_links")
    need(type(unparented) is list and len(unparented) == 12, "unparented population differs")
    for link in unparented:
        need(type(link) is dict and link.get("task_alias") in before and link["task_alias"] not in linked,
             "unparented child invalid or repeated")
        child = before[link["task_alias"]]
        need(child.get("legacy_parent_task") is None and all(link.get(k) == child.get(k)
             for k in ("task_cid", "goal_cid")), "unparented child identity differs")
        linked.add(link["task_alias"])
    need(linked == set(before), "crosswalk does not cover all tasks")
    selected = now.get("LIR-9001")
    need(type(selected) is dict and selected["revision"] == expected_task_revision
         and selected["status"] == "blocked" and selected["dependencies"] == [], "replacement task revision/status differs")
    for key in ("task_alias", "task_cid", "goal_cid", "plan_cid"):
        need(prior.get(key) == selected.get(key), "prior task identity differs")
    need(prior.get("repository_tree_id") == old["repository_tree_id"] and prior.get("revision") == 13
         and type(prior.get("revision")) is int and prior.get("status") == "blocked", "prior task revision differs")
    need(prior.get("attempt_history") == {"attempts": 2, "max_attempts": 2, "outcome": "UNKNOWN"},
         "spent attempt history differs")
    receipt = prior.get("completion_receipt")
    need(type(receipt) is dict and receipt.get("task_cid") == selected["task_cid"]
         and receipt.get("operation") == "database_task_claim_failure"
         and type(receipt.get("attempt_number")) is int and receipt["attempt_number"] == 2
         and receipt.get("automatic_retry_admitted") is False
         and receipt.get("failure_kind") == "administrative_operator_stop_outcome_unknown",
         "prior UNKNOWN failure receipt differs")
    need(selected.get("completion_receipt") == receipt, "amendment overwrote the old failure receipt")
    history = selected.get("retained_execution_outcomes")
    need(type(history) is list and 1 <= len(history) <= 16, "retained execution history missing")
    receipt_hash = hashlib.sha256(_handoff_reconciliation_bytes_v2(receipt)[:-1]).hexdigest()
    matches = []
    seen_revisions = set()
    for entry in history:
        need(type(entry) is dict and set(entry) == {"task_cid", "task_revision", "completion_receipt", "sha256"}
             and entry.get("task_cid") == selected["task_cid"]
             and type(entry.get("task_revision")) is int and 0 < entry["task_revision"] < expected_task_revision
             and entry["task_revision"] not in seen_revisions and type(entry.get("completion_receipt")) is dict,
             "retained execution entry differs")
        seen_revisions.add(entry["task_revision"])
        need(entry.get("sha256") == hashlib.sha256(
            _handoff_reconciliation_bytes_v2(entry["completion_receipt"])[:-1]).hexdigest(), "retained receipt digest differs")
        if entry["task_revision"] == 13:
            matches.append(entry)
    need(len(matches) == 1 and matches[0]["completion_receipt"] == receipt and matches[0]["sha256"] == receipt_hash,
         "exact old UNKNOWN receipt is not retained")
    need(catalog.get("schema") == "legal-autoformal-work-catalog/v1", "work catalog schema differs")
    components, evidence = catalog.get("components"), catalog.get("selected_evidence")
    need(type(components) is list and 1 <= len(components) <= 512
         and type(evidence) is list and 1 <= len(evidence) <= 2048, "catalog bounds differ")
    evidence_ids = [item.get("id") for item in evidence if type(item) is dict]
    need(all(text(v) for v in evidence_ids) and len(evidence_ids) == len(evidence) == len(set(evidence_ids)),
         "catalog evidence identities differ")
    reuse, component_ids = [], set()
    for component in components:
        need(type(component) is dict and text(component.get("id")) and component["id"] not in component_ids
             and text(component.get("path")) and text(component.get("status")), "catalog component invalid")
        component_ids.add(component["id"])
        refs = component.get("evidence_ids")
        need(type(refs) is list and all(type(v) is str and v in evidence_ids for v in refs), "catalog evidence link missing")
        reuse.append({"component_id": component["id"], "owner_path": component["path"],
                      "recorded_qualification": component["status"], "evidence_ids": refs})
    return {"task_scope": {"task_alias": "LIR-9001", "task_cid": selected["task_cid"],
                           "goal_cid": selected["goal_cid"], "plan_cid": selected["plan_cid"],
                           "repository_tree_id": old["repository_tree_id"], "revision": expected_task_revision},
            "producer_principal": producer_principal, "input_commitments": commitments,
            "counts": {"tasks": 64, "goals": 34, "goal_edges": 33, "dependencies": 115, "parents": 24},
            "current_task_states": sorted(states, key=lambda row: row["task_alias"]),
            "parent_crosswalk": crosswalk, "reuse_candidates": sorted(reuse, key=lambda row: row["component_id"]),
            "retained_execution_outcomes": history,
            "reviewed_current_authoring_differences": sorted(authoring_differences, key=lambda row: row["task_alias"]),
            "authoring_review_authenticated": False,
            "prior_attempt_history": prior["attempt_history"], "prior_provider_outcome": "UNKNOWN",
            "native_status_verified": False, "descriptor_files_authenticated": False,
            "old_provider_outcome_resolved": False, "old_provider_success_claimed": False,
            "attempts_rearmed": False, "attempt_budget_reset": False,
            "task_or_goal_status_changed": False, "completion_authority": False,
            "dispatch_authorized": False, "native_admission": False,
            "training_authorized": False, "formalized": False,
            "supervision_masks": {"training": 0, "evaluation_gold": 0}}


def prepare_current_handoff_reconciliation_v2(**inputs: Any) -> dict[str, Any]:
    """Prepare factual reconciliation from supplied metadata, without effects.

    Original owners must authenticate snapshots, bytes, principals and current
    scope. Recorded catalogue qualification is attributed history; this report
    neither transfers it nor resolves the earlier UNKNOWN provider invocation.
    """
    return {"schema": "legal-ir-current-handoff-reconciliation/v2",
            **_handoff_reconciliation_facts_v2(**inputs)}


def verify_current_handoff_reconciliation_v2(
    report: Mapping[str, Any], *, producer_freeze: Mapping[str, Any],
    verifier_principal: str, **independent_inputs: Any,
) -> dict[str, Any]:
    """Reconstruct one frozen report from independently supplied metadata.

    This pure verifier checks content equality and declared role separation.
    Native owners must additionally authenticate principals, source custody and
    the actual prepare/freeze/verify ordering before accepting its result.
    """
    expected = prepare_current_handoff_reconciliation_v2(**independent_inputs)
    if (type(verifier_principal) is not str or not 0 < len(verifier_principal) <= 512
            or any(ord(c) < 32 for c in verifier_principal) or verifier_principal == expected["producer_principal"]):
        raise ValueError("independent verifier principal required")
    raw = _handoff_reconciliation_bytes_v2(report)
    if json.loads(raw) != expected:
        raise ValueError("frozen report does not reproduce current factual metadata")
    digest = hashlib.sha256(raw).hexdigest()
    freeze = {"schema": "legal-ir-handoff-producer-freeze/v2", "report_sha256": digest,
              "report_bytes": len(raw), "producer_principal": expected["producer_principal"],
              "frozen_before_verification": True}
    if not isinstance(producer_freeze, Mapping) or dict(producer_freeze) != freeze:
        raise ValueError("producer freeze differs")
    return {"schema": "legal-ir-current-handoff-verification/v2", "valid": True,
            "task_scope": expected["task_scope"], "report_sha256": digest,
            "report_bytes": len(raw), "producer_principal": expected["producer_principal"],
            "verifier_principal": verifier_principal, "input_commitments": expected["input_commitments"],
            "checked_scope": "factual_metadata_only", "native_status_verified": False,
            "principals_authenticated": False, "freeze_chronology_authenticated": False,
            "old_provider_outcome_resolved": False, "task_or_goal_status_changed": False,
            "completion_authority": False, "dispatch_authorized": False, "native_admission": False,
            "training_authorized": False, "formalized": False,
            "supervision_masks": {"training": 0, "evaluation_gold": 0}}



def prepare_current_capability_and_purpose_map_v1(
    *, original_snapshot: Mapping[str, Any], current_snapshot: Mapping[str, Any],
    inventory: Mapping[str, Any], producer_principal: str, expected_task_revision: int = 3,
) -> dict[str, Any]:
    """Reconstruct one detached LIR-9002 factual inventory from supplied JSON.

    Native/source owners authenticate snapshots, descriptor bytes and actual
    roles separately. An unavailable capability is a valid inventory result,
    never permission to run that capability or to change another task.
    """
    def need(value: bool, reason: str) -> None:
        if not value:
            raise ValueError(reason)

    def text(value: Any) -> bool:
        return type(value) is str and 0 < len(value) <= 4096 and not any(ord(c) < 32 for c in value)

    def path(value: Any) -> bool:
        return (text(value) and value.startswith("/") and value != "/"
                and all(part not in {"", ".", ".."} for part in value.split("/")[1:])
                and not any(c in value for c in "*?[]\\"))

    def sha(value: Any) -> bool:
        return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)

    def descriptor(value: Any) -> bool:
        return (type(value) is dict and set(value) == {"path", "bytes", "sha256"}
                and path(value["path"]) and type(value["bytes"]) is int
                and 0 < value["bytes"] <= 4 * 1024**2 and sha(value["sha256"]))

    def strings(value: Any, *, empty: bool = False) -> bool:
        return (type(value) is list and len(value) <= 64 and (empty or bool(value))
                and all(text(item) for item in value) and len(value) == len(set(value)))

    def decode_unique(raw: bytes) -> Any:
        def pairs(items):
            result = {}
            for key, value in items:
                need(key not in result, "duplicate dependency evidence key")
                result[key] = value
            return result
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite dependency evidence")))

    need(type(expected_task_revision) is int and expected_task_revision == 3, "LIR-9002 inventory revision must be3")
    need(text(producer_principal), "bounded inventory producer principal required")
    supplied = json.loads(_handoff_reconciliation_bytes_v2({
        "original_snapshot": original_snapshot, "current_snapshot": current_snapshot, "inventory": inventory}))
    original, current, data = (supplied[key] for key in ("original_snapshot", "current_snapshot", "inventory"))
    need(all(type(value) is dict for value in (original, current, data)), "inventory metadata objects required")
    need(original.get("schema") == current.get("schema") == "ipfs_accelerate_py/agent-supervisor/intent-plan-projection@1",
         "original native projection schema required")

    def population(value):
        tasks, goals, edges, plans = (value.get(key) for key in ("tasks", "goals", "goal_edges", "plans"))
        need(type(tasks) is list and len(tasks) == 64 and type(goals) is list and len(goals) == 34
             and type(edges) is list and len(edges) == 33 and type(plans) is list and len(plans) == 1,
             "exact64/34/33/1 native population required")
        need(all(type(row) is dict and text(row.get("task_alias")) and text(row.get("task_cid")) for row in tasks),
             "bounded native task identities required")
        by_alias = {row["task_alias"]: row for row in tasks}
        by_cid = {row["task_cid"]: row for row in tasks}
        need(len(by_alias) == len(by_cid) == 64 and {"LIR-9001", "LIR-9002"} <= set(by_alias),
             "unique existing handoff identities required")
        goal_ids = {row.get("goal_cid") for row in goals if type(row) is dict}
        need(len(goal_ids) == 34 and None not in goal_ids, "unique native goal identities required")
        dependency_count = 0
        for row in tasks:
            deps = row.get("dependencies")
            need(type(deps) is list and all(type(d) is dict and set(d) == {"dependency_task_cid", "kind"}
                 and d["kind"] == "depends_on" and d["dependency_task_cid"] in by_cid
                 and d["dependency_task_cid"] != row["task_cid"] for d in deps), "native dependency binding required")
            need(len({d["dependency_task_cid"] for d in deps}) == len(deps) and row.get("goal_cid") in goal_ids,
                 "unique native dependencies and owning goals required")
            dependency_count += len(deps)
        need(dependency_count == 115, "exact115 original dependencies required")
        return by_alias

    before, after = population(original), population(current)
    need(set(original) == set(current) and all(original[key] == current[key]
         for key in original if key not in {"tasks", "projection_cid"}), "native programme metadata changed")
    need(set(before) == set(after) and all(before[key] == after[key] for key in before if key != "LIR-9002"),
         "other63 native task rows must remain unchanged")
    old, task, dependency = before["LIR-9002"], after["LIR-9002"], after["LIR-9001"]
    need(old.get("revision") == 2 and old.get("status") == "blocked"
         and task.get("revision") == expected_task_revision and task.get("status") == "blocked",
         "exact blocked9002 revision2→3 contract required")
    need(set(old) == set(task) and all(old[key] == task.get(key) for key in old
         if key not in {"revision", "spec_cid", "body", "outputs", "acceptance"}), "9002 native identity or dependencies changed")
    need(task["dependencies"] == [{"dependency_task_cid": dependency["task_cid"], "kind": "depends_on"}],
         "9002 must depend only on existing9001")
    need(dependency.get("revision") == 15 and dependency.get("status") == "completed", "completed9001 revision15 required")
    body, old_body = task.get("body"), old.get("body")
    need(type(body) is dict and type(old_body) is dict and body.get("authored_task") == old_body.get("authored_task")
         and body.get("completion") == "manual" and "completion_receipt" not in body,
         "original manual9002 authoring and absent prior completion receipt required")
    changed_body = {"control_capability_purpose_inventory_v1", "owned_paths", "validation", "validation_commands"}
    need({key: value for key, value in body.items() if key not in changed_body}
         == {key: value for key, value in old_body.items() if key not in changed_body}, "9002 history or unrelated metadata changed")
    criteria = ["Unavailable capabilities remain explicit blockers.",
        "Validation replay cannot authorize training; semantic_review is a proposed reviewer stage until its capability adapter is bound."]
    need([row.get("criterion") for row in old.get("acceptance", [])] == criteria
         and [row.get("criterion") for row in task.get("acceptance", [])] == criteria, "two original inventory criteria required")
    kind = "legal_ir_capability_purpose_inventory_independent_v1"
    for ordinal, row in enumerate(task["acceptance"]):
        policy = row.get("evidence_policy", {})
        need(row.get("ordinal") == old["acceptance"][ordinal].get("ordinal") == ordinal
             and policy.get("evidence_kind") == kind and policy.get("independent_post_freeze_validation_required") is True
             and policy.get("scope") == "factual_capability_inventory_only", "independent inventory evidence policy required")
    contract = body.get("control_capability_purpose_inventory_v1", {})
    need(contract.get("schema") == "legal-ir-native-capability-purpose-contract/v1"
         and contract.get("execution_kind") == "control_metadata_only"
         and contract.get("provider_execution_allowed") is False and contract.get("new_provider_attempt_allowed") is False
         and contract.get("replacement_evidence_kind") == kind
         and contract.get("history_copied_from_other_tasks") is False
         and contract.get("prior_outputs") == old.get("outputs")
         and contract.get("prior_validations") == old.get("validations")
         and contract.get("prior_owned_paths") == old_body.get("owned_paths"),
         "model-free manual inventory contract required")
    need(set(data) == {"schema", "repository_roots", "source_descriptors", "capabilities", "input_role_policy",
                       "dependency_evidence", "runtime_outputs", "input_roots"}
         and data["schema"] == "legal-ir-capability-purpose-inputs/v1", "closed capability inventory input schema required")
    roots = data["repository_roots"]
    need(type(roots) is dict and set(roots) == {"datasets_metadata", "native_control", "runtime_resources"}
         and all(path(value) for value in roots.values()) and len(set(roots.values())) == 3,
         "three exact current repository roots required")
    relative_sources = {
        "source_lease": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_source_lease.py"),
        "resource_scheduler": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py"),
        "existing_scheduler": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/existing_resource_scheduler.py"),
        "daemon_owner": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py"),
        "parented_owner": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/parented_phase_resources.py"),
        "validation_owner": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py"),
        "validation_cli": ("runtime_resources", "scripts/ops/legal_ir/run_owned_validation.py"),
        "runtime_observer": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_owned_runtime.py"),
        "pipeline_scheduler": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/pipeline_stage_scheduler.py"),
        "training_preparer": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_owned_training.py"),
        "training_executor": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_owned_execution.py"),
        "inference_route": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_inference.py"),
        "inference4096": ("runtime_resources", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_4096_device_inference.py"),
        "lean_backend": ("runtime_resources", "ipfs_datasets_py/logic/backends/kernel/lean.py"),
        "native_task_source": ("native_control", "ipfs_accelerate_py/agent_supervisor/task_sources/database_task_source.py"),
        "native_intent_owner": ("native_control", "ipfs_accelerate_py/agent_supervisor/task_sources/intent_repository.py"),
        "pure_packet_preparer": ("datasets_metadata", "ipfs_datasets_py/logic/autoformal/supervisor_loop.py"),
        "canonical_metadata_cli": ("datasets_metadata", "scripts/ops/legal_ir/run_autoformal_supervisor.py"),
    }
    sources = data["source_descriptors"]
    need(type(sources) is dict and set(sources) == set(relative_sources), "exact selected purpose owner sources required")
    for key, (root, relative) in relative_sources.items():
        need(descriptor(sources[key]) and sources[key]["path"] == roots[root] + "/" + relative,
             "purpose owner source path or descriptor mismatch: " + key)
    outputs = data["runtime_outputs"]
    need(type(outputs) is dict and set(outputs) == {"report", "freeze", "verification"}
         and all(path(value) and value.startswith(roots["runtime_resources"] + "/workspace/test-logs/")
                 for value in outputs.values()), "bounded versioned inventory output paths required")
    suffix = "/outputs/LIR-9002/capability-and-purpose-map-current-v1"
    need(outputs["report"].endswith(suffix + ".json")
         and outputs["freeze"] == outputs["report"][:-5] + ".freeze.json"
         and outputs["verification"] == outputs["report"][:-5] + ".verification.json", "exact9002 versioned output companions required")
    need(contract.get("output_paths") == {key: value[len(roots["runtime_resources"]) + 1:] for key, value in outputs.items()}
         and contract.get("publication_root") == roots["runtime_resources"]
         and [row.get("path") for row in task.get("outputs", [])]
             == [outputs[key][len(roots["runtime_resources"]) + 1:] for key in ("report", "freeze", "verification")],
         "native9002 outputs do not match inventory")
    verifier_argv = contract.get("verification_argv")
    need(type(verifier_argv) is list and len(verifier_argv) == 15 and all(text(value) for value in verifier_argv)
         and path(verifier_argv[0]) and verifier_argv[1:3] == ["-B", sources["canonical_metadata_cli"]["path"]]
         and verifier_argv[3:6] == ["capability-purpose", "verify", "--inputs"]
         and path(verifier_argv[6]) and verifier_argv[7:12] == ["--report", outputs["report"], "--freeze", outputs["freeze"], "--verifier-principal"]
         and verifier_argv[12] != producer_principal and verifier_argv[13] == "--output" and path(verifier_argv[14])
         and body.get("validation") == [verifier_argv] and body.get("validation_commands") == [{"argv": verifier_argv}],
         "exact canonical independent inventory validation argv required")
    role_policy = {"target_as_inference_input": False, "review_as_inference_input": False,
        "target_derived_context_as_inference_input": False, "evaluation_reference_requires_output_freeze": True,
        "training_requires_distinct_native_owner": True, "semantic_review_requires_authorized_adapter": True}
    need(data["input_role_policy"] == role_policy, "source/context/target purpose separation required")
    input_roots = data["input_roots"]
    need(type(input_roots) is dict and set(input_roots) == {"source_metadata", "model_source", "context", "targets", "evaluation_reference"}
         and input_roots["source_metadata"] == sorted(set(roots.values()))
         and all(input_roots[key] == [] for key in input_roots if key != "source_metadata"),
         "this inventory binds metadata roots only; scientific input roots remain unbound")
    evidence = data["dependency_evidence"]
    need(type(evidence) is dict and set(evidence) == {"completion_result", "independent_verification", "independent_owner_closeout", "completion_terminal"},
         "exact9001 acceptance evidence set required")
    values = {}
    evidence_descriptors = {}
    for key, item in evidence.items():
        need(type(item) is dict and set(item) == {"descriptor", "json_text"} and descriptor(item["descriptor"])
             and type(item["json_text"]) is str, "byte-bound dependency evidence required")
        raw = item["json_text"].encode("utf-8")
        need(len(raw) == item["descriptor"]["bytes"] and hashlib.sha256(raw).hexdigest() == item["descriptor"]["sha256"],
             "dependency evidence descriptor/content mismatch")
        values[key] = decode_unique(raw);evidence_descriptors[key] = item["descriptor"]
        need(type(values[key]) is dict, "dependency evidence object required")
    receipt = dependency.get("body", {}).get("completion_receipt", {})
    need(receipt.get("schema") == "legal-ir-native-independent-factual-completion/v2"
         and receipt.get("task_cid") == dependency["task_cid"] and receipt.get("reviewed_revision") == 14
         and receipt.get("operation") == "independent_factual_metadata_completion_v2"
         and receipt.get("prior_provider_outcome") == "UNKNOWN" and receipt.get("old_provider_outcome_resolved") is False
         and receipt.get("provider_success_claimed") is False, "completed9001 factual receipt and UNKNOWN history required")
    old_failure = receipt.get("old_failure_receipt")
    history = dependency.get("body", {}).get("retained_execution_outcomes")
    need(type(old_failure) is dict and old_failure.get("attempt_number") == 2
         and old_failure.get("task_cid") == dependency["task_cid"]
         and type(history) is list and len(history) <= 16
         and any(entry == {"task_cid": dependency["task_cid"], "task_revision": 13,
                 "completion_receipt": old_failure,
                 "sha256": hashlib.sha256(_handoff_reconciliation_bytes_v2(old_failure)[:-1]).hexdigest()}
                 for entry in history), "original9001 UNKNOWN failure history must remain bound")
    completion, checked, closed, terminal = (values[key] for key in ("completion_result", "independent_verification", "independent_owner_closeout", "completion_terminal"))
    need(completion.get("schema") == "legal-ir-native-independent-factual-completion-result/v2"
         and completion.get("completed_revision") == 15 and completion.get("task_cid") == dependency["task_cid"]
         and completion.get("evidence_digest") == receipt.get("evidence_digest")
         and completion.get("all_other63_tasks_unchanged") is True and completion.get("native_DAG_unchanged") is True,
         "actual9001 completion-result binding required")
    need(receipt.get("independent_verification") == evidence_descriptors["independent_verification"]
         and receipt.get("independent_closed_owner_receipt") == evidence_descriptors["independent_owner_closeout"]
         and checked.get("schema") == "legal-ir-current-handoff-verification/v2" and checked.get("valid") is True
         and checked.get("task_scope", {}).get("task_cid") == dependency["task_cid"]
         and checked["task_scope"].get("revision") == 14 and checked.get("checked_scope") == "factual_metadata_only"
         and checked.get("old_provider_outcome_resolved") is False, "actual9001 independent factual evidence required")
    need(closed.get("schema") == "f18-original-owner-control-closeout/v1" and type(closed.get("returncode")) is int
         and closed["returncode"] == 0 and closed.get("request_unchanged") is True and closed.get("source_pins_unchanged") is True
         and closed.get("source_READ_retained_through_owner_exit_and_closing_source_check") is True
         and closed.get("custody", {}).get("source_custody_closed") is True
         and closed["custody"].get("original_storage_status") == "released", "closed9001 independent source/native owner required")
    need(terminal.get("schema") == "legal-ir-original-native-control-terminal/v1"
         and terminal.get("completed") is True and type(terminal.get("child_returncode")) is int and terminal["child_returncode"] == 0
         and terminal.get("source_READ_closed") is True and terminal.get("original_native_compute_closed") is True
         and terminal.get("storage_status") == "released" and terminal.get("cleanup_errors") == [],
         "closed actual9001 native completion terminal required")
    specs = {
        "source_custody": (["source_lease"], ["source_metadata"]),
        "control_metadata_analysis": (["existing_scheduler", "daemon_owner", "parented_owner", "native_task_source", "native_intent_owner"], ["source_metadata", "prior_evidence"]),
        "metadata_validation": (["validation_owner", "validation_cli"], ["source_metadata", "prior_evidence"]),
        "training": (["training_preparer", "training_executor", "pipeline_scheduler"], ["source_text", "permitted_context", "reviewed_training_target"]),
        "inference_8D_384D_768D_4096D": (["inference_route", "inference4096"], ["source_text", "permitted_context", "representation", "checkpoint"]),
        "lean_kernel_and_library_build": (["lean_backend", "resource_scheduler"], ["candidate_formalization", "source_metadata"]),
        "semantic_review": ([], ["source_text", "permitted_context", "candidate_formalization"]),
        "runtime_filesystem_observation": (["runtime_observer"], ["source_metadata"]),
        "task_manual_acceptance": (["native_task_source", "native_intent_owner"], ["source_metadata", "prior_evidence"]),
    }
    rows = data["capabilities"]
    need(type(rows) is list and len(rows) == 9 and all(type(row) is dict for row in rows), "exact nine purpose dispositions required")
    by_purpose = {row.get("purpose"): row for row in rows if type(row.get("purpose")) is str}
    need(set(by_purpose) == set(specs), "unique canonical purpose rows required")
    for purpose, (owners, roles) in specs.items():
        row = by_purpose[purpose]
        need(set(row) == {"purpose", "owners", "owner_sources", "disposition", "blockers", "evidence_ids", "permitted_input_roles", "new_execution_authorized"}
             and row["owners"] == owners and row["owner_sources"] == [sources[key] for key in owners]
             and row["permitted_input_roles"] == roles and row["new_execution_authorized"] is False,
             "owner/source/roles must match exact purpose: " + purpose)
        need(row["disposition"] in {"retained_scope_only", "implementation_unbound", "unavailable"}
             and strings(row["blockers"]) and strings(row["evidence_ids"], empty=True)
             and set(row["evidence_ids"]) <= set(evidence), "explicit unavailable/unbound purpose disposition required")
        if purpose in {"training", "inference_8D_384D_768D_4096D", "lean_kernel_and_library_build", "runtime_filesystem_observation"}:
            need(row["disposition"] in {"implementation_unbound", "unavailable"} and row["evidence_ids"] == [],
                 "retained metadata validation cannot qualify scientific or runtime execution")
        elif purpose == "semantic_review":
            need(row["disposition"] == "unavailable" and row["owners"] == [] and row["evidence_ids"] == [],
                 "semantic_review stays unavailable until an authorized adapter is bound")
        elif row["disposition"] == "retained_scope_only":
            need(bool(row["evidence_ids"]), "retained capability scope needs exact dependency evidence")
    # Native upsert allocates the selected specification/projection identities.
    # Do not invent those IDs in a pre-CAS rehearsal or make a semantic report
    # depend on a guessed native CID. All other63 complete rows were compared
    # above; the real owner separately authenticates the exact native readback.
    current_commitment = {key: value for key, value in current.items() if key != "projection_cid"}
    current_commitment["tasks"] = [({key: value for key, value in row.items() if key != "spec_cid"}
        if row["task_alias"] == "LIR-9002" else row) for row in current["tasks"]]
    commitments = {key: hashlib.sha256(_handoff_reconciliation_bytes_v2(
        current_commitment if key == "current_snapshot" else value)).hexdigest() for key, value in supplied.items()}
    return {"schema": "legal-ir-current-capability-and-purpose-map/v1", "producer_principal": producer_principal,
        "task_scope": {key: task[key] for key in ("task_alias", "task_cid", "goal_cid", "plan_cid", "revision")},
        "dependency_scope": {key: dependency[key] for key in ("task_alias", "task_cid", "revision", "status")},
        "dependency_evidence": evidence_descriptors, "counts": {"tasks": 64, "goals": 34, "goal_edges": 33, "dependencies": 115, "purposes": 9},
        "repository_roots": roots, "selected_owner_sources": sources, "input_roots": input_roots,
        "input_role_policy": role_policy, "runtime_outputs": outputs,
        "capabilities": [by_purpose[key] for key in specs], "input_commitments": commitments,
        "current_snapshot_commitment_omits_native_generated_ids": ["projection_cid", "tasks[LIR-9002].spec_cid"],
        "unavailable_capabilities_remain_explicit_blockers": True, "all_capabilities_required_runnable": False,
        "prior_provider_outcome": "UNKNOWN", "old_provider_outcome_resolved": False,
        "descriptor_files_authenticated": False, "native_status_verified": False, "principals_authenticated": False,
        "semantic_review_verified": False, "training_authorized": False, "completion_authority": False,
        "dispatch_authorized": False, "native_admission": False, "task_or_goal_status_changed": False,
        "formalized": False, "supervision_masks": {"training": 0, "evaluation_gold": 0}}


def verify_current_capability_and_purpose_map_v1(
    report: Mapping[str, Any], *, producer_freeze: Mapping[str, Any], verifier_principal: str,
    **independent_inputs: Any,
) -> dict[str, Any]:
    """Independently reconstruct frozen9002 inventory; grant no native authority."""
    expected = prepare_current_capability_and_purpose_map_v1(**independent_inputs)
    if (type(verifier_principal) is not str or not 0 < len(verifier_principal) <= 4096
            or any(ord(c) < 32 for c in verifier_principal) or verifier_principal == expected["producer_principal"]):
        raise ValueError("distinct bounded inventory verifier principal required")
    raw = _handoff_reconciliation_bytes_v2(report)
    if json.loads(raw) != expected:
        raise ValueError("frozen capability inventory does not reproduce")
    digest = hashlib.sha256(raw).hexdigest()
    freeze = {"schema": "legal-ir-capability-purpose-producer-freeze/v1", "report_sha256": digest,
              "report_bytes": len(raw), "producer_principal": expected["producer_principal"], "frozen_before_verification": True}
    if not isinstance(producer_freeze, Mapping) or dict(producer_freeze) != freeze:
        raise ValueError("capability inventory producer freeze differs")
    return {"schema": "legal-ir-current-capability-purpose-verification/v1", "valid": True,
        "task_scope": expected["task_scope"], "dependency_scope": expected["dependency_scope"],
        "report_sha256": digest, "report_bytes": len(raw), "producer_principal": expected["producer_principal"],
        "verifier_principal": verifier_principal, "input_commitments": expected["input_commitments"],
        "checked_scope": "factual_capability_inventory_only", "native_status_verified": False,
        "descriptor_files_authenticated": False, "principals_authenticated": False, "freeze_chronology_authenticated": False,
        "old_provider_outcome_resolved": False, "semantic_review_verified": False, "training_authorized": False,
        "task_or_goal_status_changed": False, "completion_authority": False, "dispatch_authorized": False,
        "native_admission": False, "formalized": False, "supervision_masks": {"training": 0, "evaluation_gold": 0}}


def prepare_current_job_packet_index_v1(
    *, current_snapshot: Mapping[str, Any], capability_report: Mapping[str, Any],
    capability_verification: Mapping[str, Any], packet_proposals: list[Mapping[str, Any]],
    producer_principal: str, expected_task_revision: int = 2,
) -> dict[str, Any]:
    """Inventory current9003 packets and explicit gaps; never admit or complete.

    This pure metadata owner reads no descriptor or native store. A complete
    supplied packet is still unreviewed and unadmitted. Full index coverage,
    including negative dispositions, cannot satisfy9003's executable-packet
    acceptance or make a productive task runnable.
    """
    def need(condition: bool, reason: str) -> None:
        if not condition:
            raise ValueError(reason)

    def text(value: Any) -> bool:
        return type(value) is str and 0 < len(value) <= 4096 and not any(ord(c) < 32 for c in value)

    def positive(value: Any) -> bool:
        return type(value) is int and value > 0

    def path(value: Any, *, absolute: bool = False) -> bool:
        if not text(value) or (absolute and not value.startswith("/")):
            return False
        parts = value.split("/")[1:] if value.startswith("/") else value.split("/")
        return all(part not in {"", ".", ".."} for part in parts) and not any(char in value for char in "*?[]\\")

    def strings(value: Any, *, empty: bool = False) -> bool:
        return (type(value) is list and len(value) <= 128 and (empty or bool(value))
                and all(text(item) for item in value) and len(set(value)) == len(value))

    def argv(value: Any) -> bool:
        return type(value) is list and 0 < len(value) <= 128 and all(text(item) for item in value)

    def descriptor(value: Any) -> bool:
        return (type(value) is dict and set(value) == {"path", "bytes", "sha256"}
                and path(value["path"], absolute=True) and positive(value["bytes"])
                and value["bytes"] <= 4 * 1024**2 and type(value["sha256"]) is str
                and len(value["sha256"]) == 64 and all(c in "0123456789abcdef" for c in value["sha256"]))

    def commitment(value: Any) -> str:
        return hashlib.sha256(_handoff_reconciliation_bytes_v2(value)).hexdigest()

    supplied = json.loads(_handoff_reconciliation_bytes_v2({"current_snapshot": current_snapshot,
        "capability_report": capability_report, "capability_verification": capability_verification,
        "packet_proposals": packet_proposals}))
    current, report, checked, proposals = (supplied[key] for key in
        ("current_snapshot", "capability_report", "capability_verification", "packet_proposals"))
    need(text(producer_principal) and positive(expected_task_revision), "bounded producer and exact9003 revision required")
    need(type(current) is dict and current.get("schema") == "ipfs_accelerate_py/agent-supervisor/intent-plan-projection@1",
         "current native projection metadata required")
    tasks, goals, edges, plans = (current.get(key) for key in ("tasks", "goals", "goal_edges", "plans"))
    need(type(tasks) is list and len(tasks) == 64 and type(goals) is list and len(goals) == 34
         and type(edges) is list and len(edges) == 33 and type(plans) is list and len(plans) == 1,
         "exact64/34/33/1 native programme required")
    need(all(type(row) is dict and all(text(row.get(key)) for key in
         ("task_alias", "task_cid", "goal_cid", "plan_cid", "status")) and positive(row.get("revision")) for row in tasks),
         "exact current task identities and revisions required")
    by_alias, by_cid = ({row[key]: row for row in tasks} for key in ("task_alias", "task_cid"))
    need(all(type(row) is dict and text(row.get("goal_cid")) for row in goals), "bounded goal identities required")
    goal_ids = {row["goal_cid"] for row in goals}
    need(len(by_alias) == len(by_cid) == 64 and len(goal_ids) == 34 and None not in goal_ids
         and {"LIR-9001", "LIR-9002", "LIR-9003", "LIR-9004"} <= set(by_alias), "unique original programme identities required")
    need(all(type(row) is dict and row.get("edge_kind") == "goal_parent"
         and text(row.get("parent_goal_cid")) and text(row.get("child_goal_cid"))
         and row["parent_goal_cid"] in goal_ids and row["child_goal_cid"] in goal_ids for row in edges),
         "original owning goal edges required")
    need(len({row["child_goal_cid"] for row in edges}) == 33 and all(row["parent_goal_cid"] != row["child_goal_cid"] for row in edges)
         and type(plans[0]) is dict and text(plans[0].get("plan_cid"))
         and all(row["plan_cid"] == plans[0]["plan_cid"] and type(row.get("body")) is dict
                 and type(row.get("outputs")) is list and all(type(output) is dict and path(output.get("path"))
                     for output in row["outputs"]) for row in tasks),
         "original single-plan ownership and distinct parent edges required")
    dependencies = {}
    for row in tasks:
        values = row.get("dependencies")
        need(row["goal_cid"] in goal_ids and type(values) is list and all(type(item) is dict
             and set(item) == {"dependency_task_cid", "kind"} and item["kind"] == "depends_on"
             and text(item["dependency_task_cid"]) and item["dependency_task_cid"] in by_cid
             and item["dependency_task_cid"] != row["task_cid"] for item in values),
             "exact existing dependency bindings required")
        ids = [item["dependency_task_cid"] for item in values]
        need(len(set(ids)) == len(ids), "duplicate task dependency")
        dependencies[row["task_cid"]] = ids
    need(sum(map(len, dependencies.values())) == 115, "exact115 native dependencies required")
    visiting, visited = set(), set()

    def visit(cid: str) -> None:
        need(cid not in visiting, "cyclic native dependency metadata")
        if cid not in visited:
            visiting.add(cid)
            for dependency in dependencies[cid]:
                visit(dependency)
            visiting.remove(cid)
            visited.add(cid)

    for cid in by_cid:
        visit(cid)
    task, dependency, first = (by_alias[key] for key in ("LIR-9003", "LIR-9002", "LIR-9001"))
    need(task["revision"] == expected_task_revision and task["status"] == "blocked"
         and task.get("body", {}).get("completion") == "manual"
         and dependencies[task["task_cid"]] == [dependency["task_cid"]], "exact blocked manual9003 frontier required")
    receipt = dependency.get("body", {}).get("completion_receipt", {})
    need(dependency["revision"] == 4 and dependency["status"] == "completed"
         and receipt.get("operation") == "independent_capability_purpose_inventory_completion_v1"
         and receipt.get("scope") == "factual_capability_inventory_only" and receipt.get("reviewed_revision") == 3,
         "accepted factual9002 revision4 required")
    need(type(report) is dict and report.get("schema") == "legal-ir-current-capability-and-purpose-map/v1"
         and type(checked) is dict and checked.get("schema") == "legal-ir-current-capability-purpose-verification/v1"
         and checked.get("valid") is True and checked.get("checked_scope") == "factual_capability_inventory_only"
         and checked.get("task_scope") == report.get("task_scope")
         and report.get("task_scope") == {key: (3 if key == "revision" else dependency[key])
             for key in ("task_alias", "task_cid", "goal_cid", "plan_cid", "revision")}
         and checked.get("report_sha256") == commitment(report)
         and checked.get("report_bytes") == len(_handoff_reconciliation_bytes_v2(report))
         and text(report.get("producer_principal"))
         and checked.get("producer_principal") == report.get("producer_principal")
         and text(checked.get("verifier_principal")) and checked["verifier_principal"] != report.get("producer_principal"),
         "exact accepted capability report and distinct verifier metadata required")
    verification_pin = receipt.get("independent_verification", {})
    need(descriptor(verification_pin) and verification_pin["sha256"] == commitment(checked)
         and verification_pin["bytes"] == len(_handoff_reconciliation_bytes_v2(checked)), "9002 receipt verification commitment differs")
    for value in (report, checked, receipt):
        need(all(value.get(flag) is False for flag in
             ("training_authorized", "semantic_review_verified", "dispatch_authorized", "native_admission", "formalized"))
             and value.get("supervision_masks") == {"training": 0, "evaluation_gold": 0}, "9002 limited authority must remain explicit")
    old = first.get("body", {}).get("completion_receipt", {})
    old_failure = old.get("old_failure_receipt")
    history = first.get("body", {}).get("retained_execution_outcomes")
    need(first["revision"] == 15 and first["status"] == "completed"
         and old.get("old_provider_outcome_resolved") is False and old.get("provider_success_claimed") is False
         and type(old_failure) is dict and old_failure.get("task_cid") == first["task_cid"]
         and old_failure.get("failure_kind") == "administrative_operator_stop_outcome_unknown"
         and old_failure.get("automatic_retry_admitted") is False and type(history) is list
         and {"task_cid": first["task_cid"], "task_revision": 13, "completion_receipt": old_failure,
              "sha256": hashlib.sha256(_handoff_reconciliation_bytes_v2(old_failure)[:-1]).hexdigest()} in history,
         "9001 unresolved historical outcome must remain retained")
    purposes = report.get("capabilities")
    need(type(purposes) is list and len(purposes) == 9 and all(type(row) is dict and text(row.get("purpose"))
         and row.get("new_execution_authorized") is False and row.get("disposition") in
         {"retained_scope_only", "implementation_unbound", "unavailable"} and strings(row.get("blockers"))
         and strings(row.get("permitted_input_roles")) for row in purposes),
         "all nine negative or retained capability dispositions required")
    capabilities = {row["purpose"]: row for row in purposes}
    need(set(capabilities) == {"source_custody", "control_metadata_analysis", "metadata_validation", "training",
         "inference_8D_384D_768D_4096D", "lean_kernel_and_library_build", "semantic_review",
         "runtime_filesystem_observation", "task_manual_acceptance"}
         and capabilities["semantic_review"]["disposition"] == "unavailable"
         and report.get("unavailable_capabilities_remain_explicit_blockers") is True
         and report.get("all_capabilities_required_runnable") is False, "capability coverage must retain unavailable scopes")
    need(type(proposals) is list and len(proposals) <= 64 and all(type(row) is dict for row in proposals), "bounded packet proposals required")
    selected = {}
    for proposal in proposals:
        alias = proposal.get("task_alias")
        need(type(alias) is str and alias in by_alias and alias not in selected, "unique existing packet task required")
        row = by_alias[alias]
        need(row["status"] == "blocked" and proposal.get("task_cid") == row["task_cid"]
             and type(proposal.get("revision")) is int and proposal["revision"] == row["revision"], "stale, started or completed packet target")
        need(all(proposal.get(flag, False) is False for flag in
             ("admitted", "dispatch_authorized", "native_admission", "rearm_authorized", "completion_authority", "training_authorized",
              "workers_started", "worker_launch_authorized", "execution_authorized_by_this_file", "task_completion_authority",
              "goal_completion_authority", "formalized", "semantic_review_verified"))
             and proposal.get("supervision_masks", {"training": 0, "evaluation_gold": 0}) == {"training": 0, "evaluation_gold": 0},
             "packet proposal cannot request execution or completion authority")
        selected[alias] = proposal
    entries = []
    budget_keys = {"cpu_threads", "memory_mib", "storage_bytes", "max_children", "max_tokens", "deadline_seconds", "max_attempts"}
    for row in tasks:
        alias = row["task_alias"]
        dep_rows = [{"task_cid": cid, "revision": by_cid[cid]["revision"], "status": by_cid[cid]["status"]}
                    for cid in dependencies[row["task_cid"]]]
        proposal = selected.get(alias)
        missing = []

        def require(condition: bool, reason: str) -> None:
            if not condition:
                missing.append(reason)

        capability = None
        if proposal is not None:
            capability = capabilities.get(proposal.get("purpose")) if type(proposal.get("purpose")) is str else None
            require(capability is not None, "purpose_not_in_accepted_inventory")
            require(proposal.get("purpose") in {"control_metadata_analysis", "metadata_validation"}, "productive_purpose_contract_not_selected")
            require(proposal.get("dependencies") == dep_rows, "exact_dependency_revisions_and_states_required")
            require(proposal.get("execution_kind") == "control_metadata_only", "model_execution_contract_not_selected")
            for key in ("argv", "validation_argv"):
                require(argv(proposal.get(key)), "exact_" + key + "_required")
            require(path(proposal.get("cwd"), absolute=True), "absolute_cwd_required")
            sources = proposal.get("source_descriptors")
            require(type(sources) is list and bool(sources) and all(descriptor(pin) for pin in sources), "exact_source_descriptors_required")
            for key, command_key in (("entrypoint_source", "argv"), ("validation_source", "validation_argv")):
                pin = proposal.get(key)
                require(descriptor(pin) and type(sources) is list and pin in sources
                        and argv(proposal.get(command_key)) and pin["path"] in proposal[command_key], "source_bound_" + command_key + "_required")
            inputs = proposal.get("inputs")
            roles = capability.get("permitted_input_roles", []) if capability else []
            require(type(inputs) is list and bool(inputs) and all(type(item) is dict and item.get("role") in roles
                and item.get("use") in ("verification", "provenance") and descriptor(item.get("descriptor"))
                and "profile" not in item for item in inputs), "purpose_role_bound_metadata_inputs_required")
            declared = [output.get("path") for output in row.get("outputs", []) if type(output) is dict]
            require(strings(proposal.get("outputs")) and all(path(value) for value in proposal["outputs"])
                    and proposal["outputs"] == declared, "exact_native_output_paths_required")
            body = row.get("body", {})
            require(strings(proposal.get("exclusive_keys")) and proposal["exclusive_keys"] == body.get("exclusive_keys"), "exact_native_exclusive_keys_required")
            for key in ("code_allowlist", "test_allowlist"):
                require(strings(proposal.get(key), empty=True) and all(path(value) for value in proposal[key]), "explicit_" + key + "_required")
            require(proposal.get("code_allowlist") == body.get("code_edit_allowlist", []) == [], "model_free_metadata_cannot_grant_code_edits")
            budgets = proposal.get("budgets")
            require(type(budgets) is dict and set(budgets) == budget_keys
                    and all(positive(value) for key, value in budgets.items() if key != "max_tokens")
                    and type(budgets["max_tokens"]) is int and budgets["max_tokens"] == 0, "finite_model_free_resource_retry_and_deadline_bounds_required")
            for key in ("retry_key", "invalidation_key"):
                require(text(proposal.get(key)), "explicit_" + key + "_required")
            worker, verifier = proposal.get("worker"), proposal.get("verifier")
            require(type(worker) is dict and text(worker.get("principal")) and text(worker.get("role")), "worker_role_and_principal_required")
            require(type(verifier) is dict and verifier.get("role") == "independent_acceptance" and text(verifier.get("principal"))
                and type(worker) is dict and verifier.get("principal") != worker.get("principal") and argv(verifier.get("argv")), "distinct_independent_verifier_required")
            require(type(verifier) is dict and descriptor(verifier.get("source_descriptor")) and type(sources) is list
                    and verifier["source_descriptor"] in sources and argv(verifier.get("argv"))
                    and verifier["source_descriptor"]["path"] in verifier["argv"], "source_bound_independent_verifier_required")
        elif row["status"] != "completed":
            missing.append("job_packet_not_supplied")
        complete = proposal is not None and not missing
        execution_blockers = ["original_owner_current_scope_and_admission_required", "independent_packet_acceptance_required"]
        execution_blockers.extend("dependency_not_completed:" + item["task_cid"] for item in dep_rows if item["status"] != "completed")
        if capability is not None:
            execution_blockers.extend(capability["blockers"])
        disposition = ("completed_scope_retained" if row["status"] == "completed" else
                       "packet_missing" if proposal is None else "metadata_bound_pending_review" if complete else "packet_metadata_incomplete")
        entries.append({"task_alias": alias, "task_cid": row["task_cid"], "revision": row["revision"], "status": row["status"],
            "task_record_sha256": commitment(row), "dependencies": dep_rows, "disposition": disposition,
            "metadata_complete": complete, "metadata_blockers": missing, "execution_blockers": execution_blockers,
            "capability_disposition": capability["disposition"] if capability else "not_selected",
            "packet_proposal": proposal, "independently_reviewed": False, "runnable": False, "dispatch_authorized": False})
    counts = {key: sum(entry["disposition"] == key for entry in entries) for key in
        ("completed_scope_retained", "packet_missing", "metadata_bound_pending_review", "packet_metadata_incomplete")}
    return {"schema": "legal-ir-current-job-packet-index/v1", "producer_principal": producer_principal,
        "task_scope": {key: task[key] for key in ("task_alias", "task_cid", "goal_cid", "plan_cid", "revision")},
        "dependency_scope": {key: dependency[key] for key in ("task_alias", "task_cid", "revision", "status")},
        "input_commitments": {key: commitment(value) for key, value in supplied.items()}, "entries": entries,
        "capability_dispositions": purposes,
        "counts": {"tasks": 64, "goals": 34, "goal_edges": 33, "dependencies": 115, **counts},
        "full_index_coverage": True, "productive_runnable_coverage_complete": False, "task_acceptance_satisfied": False,
        "prior_provider_outcome": "UNKNOWN", "old_provider_outcome_resolved": False,
        "descriptor_files_authenticated": False, "native_status_verified": False, "principals_authenticated": False,
        "task_or_goal_status_changed": False, "completion_authority": False, "dispatch_authorized": False,
        "native_admission": False, "training_authorized": False, "semantic_review_verified": False,
        "formalized": False, "supervision_masks": {"training": 0, "evaluation_gold": 0}}


def verify_current_job_packet_index_v1(
    report: Mapping[str, Any], *, producer_freeze: Mapping[str, Any], verifier_principal: str,
    **independent_inputs: Any,
) -> dict[str, Any]:
    """Reconstruct the factual9003 inventory; executable acceptance stays open."""
    expected = prepare_current_job_packet_index_v1(**independent_inputs)
    if (type(verifier_principal) is not str or not 0 < len(verifier_principal) <= 4096
            or any(ord(c) < 32 for c in verifier_principal) or verifier_principal == expected["producer_principal"]):
        raise ValueError("distinct bounded packet-index verifier principal required")
    raw = _handoff_reconciliation_bytes_v2(report)
    if json.loads(raw) != expected:
        raise ValueError("frozen job packet index does not reproduce")
    digest = hashlib.sha256(raw).hexdigest()
    freeze = {"schema": "legal-ir-job-packet-index-producer-freeze/v1", "report_sha256": digest,
        "report_bytes": len(raw), "producer_principal": expected["producer_principal"], "frozen_before_verification": True}
    if not isinstance(producer_freeze, Mapping) or dict(producer_freeze) != freeze:
        raise ValueError("job packet index producer freeze differs")
    return {"schema": "legal-ir-current-job-packet-index-verification/v1", "valid": True,
        "checked_scope": "factual_job_packet_inventory_only", "task_scope": expected["task_scope"],
        "report_sha256": digest, "report_bytes": len(raw), "producer_principal": expected["producer_principal"],
        "verifier_principal": verifier_principal, "input_commitments": expected["input_commitments"],
        "full_index_coverage": True, "productive_runnable_coverage_complete": False, "task_acceptance_satisfied": False,
        "native_status_verified": False, "descriptor_files_authenticated": False, "principals_authenticated": False,
        "freeze_chronology_authenticated": False, "task_or_goal_status_changed": False,
        "old_provider_outcome_resolved": False, "completion_authority": False, "dispatch_authorized": False,
        "native_admission": False, "training_authorized": False, "semantic_review_verified": False,
        "formalized": False, "supervision_masks": {"training": 0, "evaluation_gold": 0}}


def progress_log_path(board_path: Any) -> Path | None:
    if board_path is None:
        return None
    return Path(board_path).with_name(Path(board_path).stem + ".progress.log")


def census_snapshot_path(board_path: Any) -> Path | None:
    if board_path is None:
        return None
    return Path(board_path).with_name(Path(board_path).stem + ".census.json")


def _emit_progress(message: str, *, log: Callable[[str], None] | None, board_path: Any) -> None:
    text = str(message).rstrip()
    if log is not None:
        log(text)
    progress = progress_log_path(board_path)
    if progress is None:
        return
    progress.parent.mkdir(parents=True, exist_ok=True)
    with progress.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def _span_id(task: Mapping[str, Any]) -> str:
    return str(task.get("source_span_id") or task.get("id") or "")


def census_span_records(agreement: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One operator-facing census row per agreement row. Not an admit."""

    records: list[dict[str, Any]] = []
    for row in agreement.get("rows") or []:
        if not isinstance(row, Mapping) or row.get("skipped"):
            continue
        records.append(
            {
                "agrees": row.get("agrees") is True,
                "decompiled": str(row.get("decompiled") or "")[:240],
                "fields": [str(item) for item in row.get("dropped") or row.get("unsupported_fields") or [] if str(item)],
                "id": str(row.get("source_span_id") or row.get("id") or ""),
                "legal_id": str(row.get("legal_id") or ""),
                "reason": str(row.get("reason") or ""),
                "status": "agreed" if row.get("agrees") is True else "gap",
                "text": str(row.get("text") or "")[:240],
            }
        )
    return records


def _emit_census_stage(
    agreement: Mapping[str, Any],
    *,
    index: int,
    log: Callable[[str], None] | None,
    board_path: Any,
    lake_probe: Callable[..., Mapping[str, Any]] | None,
) -> dict[str, Any]:
    records = census_span_records(agreement)
    for record in records[:24]:
        _emit_progress(
            f"CENSUS span id={record['id']} status={record['status']} "
            f"reason={record['reason'] or 'none'} fields={','.join(record['fields']) or 'none'} "
            f"decompiled={record['decompiled'] or ''} text={record['text']}",
            log=log,
            board_path=board_path,
        )
    rules = [
        dict(row["rule"])
        for row in agreement.get("rows") or []
        if isinstance(row, Mapping) and row.get("agrees") is True and isinstance(row.get("rule"), Mapping) and row.get("rule")
    ]
    lake: dict[str, Any] = {
        "admitted": False,
        "error": "lake_not_run",
        "formalized": False,
        "lake_ok": False,
        "log": "",
        "target": "Legal",
        "theorem_count": 0,
    }
    if lake_probe is not None:
        probed = dict(lake_probe(rules) or {})
        lake.update(probed)
        lake["admitted"] = False
        lake["formalized"] = False
        error = str(lake.get("error") or "")
        _emit_progress(
            f"LAKE round={index} target=Legal theorems={int(lake.get('theorem_count') or 0)} "
            f"lake_ok={str(bool(lake.get('lake_ok'))).lower()} error={error or 'none'}",
            log=log,
            board_path=board_path,
        )
        if error and error not in {"lake_not_run", "no_renderable_norms", "lake_not_on_path"}:
            for line in error.splitlines()[:12]:
                _emit_progress(f"LAKE error {line}", log=log, board_path=board_path)
    elif not records:
        pass
    else:
        _emit_progress(
            f"LAKE round={index} target=Legal theorems=0 lake_ok=false error=lake_not_run",
            log=log,
            board_path=board_path,
        )
    return {"spans": records, "lake": lake}


def _mode(failure: str) -> str:
    key = str(failure or "compiler_disagreement").split(":", 1)[0]
    if key.startswith("CanonicalErrorCode."):
        return "compiler_abstain"
    return key or "compiler_disagreement"


def agreement_from_run(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize an autoformal receipt into census rows. Not an admit."""

    if not isinstance(receipt, Mapping):
        raise SupervisorLoopError("autoformal receipt must be an object")
    nested = receipt.get("agreement")
    if isinstance(nested, Mapping) and nested.get("rows") is not None:
        return dict(nested)
    if receipt.get("rows") is not None:
        rows = [dict(row) for row in receipt.get("rows") or [] if isinstance(row, Mapping)]
        operative = [row for row in rows if not row.get("skipped")]
        agreed = sum(1 for row in operative if row.get("agrees"))
        return {
            "admitted": False,
            "agreed": agreed,
            "agrees": bool(operative) and agreed == len(operative),
            "formalized": False,
            "operative": len(operative),
            "reason": "" if operative and agreed == len(operative) else "compiler_disagreement",
            "rows": rows,
        }
    ledger = receipt.get("ledger") if isinstance(receipt.get("ledger"), Mapping) else {}
    if "spans" in receipt or "spans" in ledger:
        spans = list(receipt.get("spans") or ledger.get("spans") or [])
        if any(span.get("strict_status") for span in spans if isinstance(span, Mapping)):
            return agreement_from_strict_spans(spans)
        return agreement_from_spans(spans)
    raise SupervisorLoopError("autoformal receipt has no spans or agreement rows")


def proofs_from_agreement(agreement: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Engineering round-trip receipts. Not legal proofs and not admits."""

    proofs = []
    for row in agreement.get("rows") or []:
        if row.get("skipped") or not row.get("agrees"):
            continue
        proofs.append(
            {
                "admitted": False,
                "formalized": False,
                "id": str(row.get("id") or ""),
                "kind": "strict_roundtrip",
                "proof_authoritative": False,
                "source_span_id": str(row.get("source_span_id") or row.get("id") or ""),
            }
        )
    return proofs


def agreement_from_exception(exc: BaseException, *, round_index: int) -> dict[str, Any]:
    """A loop failure is a review todo, not a compiler patch."""

    return {
        "admitted": False,
        "agreed": 0,
        "agrees": False,
        "formalized": False,
        "operative": 1,
        "reason": "loop_error",
        "rows": [
            {
                "agrees": False,
                "id": f"loop-error-{round_index}",
                "reason": "loop_error",
                "skipped": False,
                "source_span_id": f"loop-error-{round_index}",
                "text": str(exc),
            }
        ],
    }


def synthesize_goals(
    tasks: Sequence[Mapping[str, Any]],
    *,
    min_cluster: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group related todos into goals that can close several outstanding items."""

    labeled = [dict(task) for task in tasks]
    if not labeled:
        return [], []
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for task in labeled:
        mode = _mode(str(task.get("failure_mode") or ""))
        legal_id = str(task.get("legal_id") or "")
        if mode in ARCHITECTURE_MODES:
            buckets[("architecture-decision", mode)].append(task)
        elif legal_id:
            buckets[("cluster", legal_id)].append(task)
        else:
            buckets[("cluster", mode)].append(task)
    goals: list[dict[str, Any]] = []
    assigned: dict[str, str] = {}
    next_index = 20
    for (kind, key), members in sorted(buckets.items(), key=lambda item: item[0]):
        if len(members) < min_cluster:
            continue
        goal_id = f"{GOAL_PREFIX}{next_index:03d}"
        next_index += 10
        title = (
            f"Architecture: {key} coverage"
            if kind == "architecture-decision"
            else f"Cluster: {key}"
        )
        goals.append(
            {
                "admitted": False,
                "estimated_tokens": sum(int(item.get("estimated_tokens") or 0) for item in members),
                "estimated_validation_seconds": sum(
                    int(item.get("estimated_validation_seconds") or 0) for item in members
                ),
                "failure_mode": key if kind == "architecture-decision" else str(members[0].get("failure_mode") or key),
                "formalized": False,
                "goal_id": goal_id,
                "kind": kind,
                "priority": "P0" if kind == "architecture-decision" else "P1",
                "resolves": [str(item["task_id"]) for item in members],
                "status": "todo",
                "title": title,
            }
        )
        for item in members:
            assigned[str(item["task_id"])] = goal_id
    default = f"{GOAL_PREFIX}010"
    for task in labeled:
        task["goal_id"] = assigned.get(str(task["task_id"]), default)
    for goal in goals:
        members = [item for item in labeled if item.get("goal_id") == goal["goal_id"]]
        goal["source_span_ids"] = [str(item.get("source_span_id") or "") for item in members]
    return labeled, goals


def _cid(kind: str, *parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"{kind}:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def spawn_goal_tree(
    tasks: Sequence[Mapping[str, Any]],
    *,
    release_id: str = "",
    min_cluster: int = 2,
    campaign_title: str = "U.S. Code autoformal campaign",
    dispatch: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Campaign goal, architecture/cluster goals, optional citation subgoals, todos."""

    labeled, clusters = synthesize_goals(tasks, min_cluster=min_cluster)
    campaign_cid = _cid("goal", CAMPAIGN_GOAL_ID, release_id)
    plan_cid = _cid("plan", CAMPAIGN_GOAL_ID, release_id or "loop")
    campaign = {
        "admitted": False,
        "estimated_tokens": 0,
        "estimated_validation_seconds": 0,
        "failure_mode": "",
        "formalized": False,
        "goal_alias": CAMPAIGN_GOAL_ID,
        "goal_cid": campaign_cid,
        "goal_id": CAMPAIGN_GOAL_ID,
        "kind": "campaign",
        "objective_id": OBJECTIVE_ID,
        "ordinal": 1,
        "parent_goal_cid": "",
        "priority": "P0",
        "resolves": [],
        "source_span_ids": [],
        "status": "open",
        "title": campaign_title,
    }
    goals = [campaign]
    edges: list[dict[str, str]] = []
    next_sub = 21
    for ordinal, cluster in enumerate(clusters, start=2):
        cluster = dict(cluster)
        cluster["goal_alias"] = cluster["goal_id"]
        cluster["goal_cid"] = _cid("goal", cluster["goal_id"], cluster["kind"], cluster.get("failure_mode"))
        cluster["objective_id"] = OBJECTIVE_ID
        cluster["ordinal"] = ordinal
        cluster["parent_goal_cid"] = campaign_cid
        cluster["status"] = "open"
        members = [item for item in labeled if item.get("goal_id") == cluster["goal_id"]]
        citations = sorted({str(item.get("legal_id") or "") for item in members if item.get("legal_id")})
        goals.append(cluster)
        edges.append(
            {
                "parent": campaign_cid,
                "child": cluster["goal_cid"],
                "parent_goal_cid": campaign_cid,
                "child_goal_cid": cluster["goal_cid"],
                "edge_kind": "goal_decomposition",
            }
        )
        if cluster.get("kind") == "architecture-decision" and len(citations) > 1:
            for citation in citations:
                sub_id = f"{GOAL_PREFIX}{next_sub:03d}"
                next_sub += 1
                sub_cid = _cid("goal", sub_id, "subgoal", citation)
                subset = [item for item in members if str(item.get("legal_id") or "") == citation]
                goals.append(
                    {
                        "admitted": False,
                        "estimated_tokens": sum(int(item.get("estimated_tokens") or 0) for item in subset),
                        "estimated_validation_seconds": sum(
                            int(item.get("estimated_validation_seconds") or 0) for item in subset
                        ),
                        "failure_mode": cluster.get("failure_mode") or "",
                        "formalized": False,
                        "goal_alias": sub_id,
                        "goal_cid": sub_cid,
                        "goal_id": sub_id,
                        "kind": "subgoal",
                        "legal_id": citation,
                        "objective_id": OBJECTIVE_ID,
                        "ordinal": len(goals) + 1,
                        "parent_goal_cid": cluster["goal_cid"],
                        "priority": "P1",
                        "resolves": [str(item["task_id"]) for item in subset],
                        "repair_targets": [
                            str(item)
                            for item in (subset[0].get("replace") or [])
                            if str(item)
                        ] if subset else [],
                        "source_span_ids": [str(item.get("source_span_id") or "") for item in subset],
                        "status": "open",
                        "title": "Subgoal: "
                        + citation
                        + (": " + str(subset[0].get("failure_mode") or "") if subset else ""),
                    }
                )
                edges.append(
                    {
                        "parent": cluster["goal_cid"],
                        "child": sub_cid,
                        "parent_goal_cid": cluster["goal_cid"],
                        "child_goal_cid": sub_cid,
                        "edge_kind": "goal_decomposition",
                    }
                )
                for item in subset:
                    item["goal_id"] = sub_id
                    item["goal_cid"] = sub_cid
                    item["parent_goal_cid"] = cluster["goal_cid"]
        else:
            span_ids: list[str] = []
            for item in members:
                span = str(item.get("source_span_id") or "")
                if span and span not in span_ids:
                    span_ids.append(span)
            if span_ids:
                for span in span_ids:
                    sub_id = f"{GOAL_PREFIX}{next_sub:03d}"
                    next_sub += 1
                    sub_cid = _cid("goal", sub_id, "subgoal", span)
                    subset = [item for item in members if str(item.get("source_span_id") or "") == span]
                    goals.append(
                        {
                            "admitted": False,
                            "estimated_tokens": sum(int(item.get("estimated_tokens") or 0) for item in subset),
                            "estimated_validation_seconds": sum(
                                int(item.get("estimated_validation_seconds") or 0) for item in subset
                            ),
                            "failure_mode": cluster.get("failure_mode") or "",
                            "formalized": False,
                            "goal_alias": sub_id,
                            "goal_cid": sub_cid,
                            "goal_id": sub_id,
                            "kind": "subgoal",
                            "objective_id": OBJECTIVE_ID,
                            "ordinal": len(goals) + 1,
                            "parent_goal_cid": cluster["goal_cid"],
                            "priority": "P1",
                            "resolves": [str(item["task_id"]) for item in subset],
                            "repair_targets": [
                                str(item)
                                for item in (subset[0].get("replace") or [])
                                if str(item)
                            ] if subset else [],
                            "source_span_ids": [span],
                            "status": "open",
                            "title": f"Subgoal: {span}"
                            + (": " + str(subset[0].get("failure_mode") or "") if subset else ""),
                        }
                    )
                    edges.append(
                        {
                            "parent": cluster["goal_cid"],
                            "child": sub_cid,
                            "parent_goal_cid": cluster["goal_cid"],
                            "child_goal_cid": sub_cid,
                            "edge_kind": "goal_decomposition",
                        }
                    )
                    for item in subset:
                        item["goal_id"] = sub_id
                        item["goal_cid"] = sub_cid
                        item["parent_goal_cid"] = cluster["goal_cid"]
            else:
                for item in members:
                    item["goal_cid"] = cluster["goal_cid"]
                    item["parent_goal_cid"] = campaign_cid
    default_goal_id = f"{GOAL_PREFIX}010"
    default_cid = _cid("goal", default_goal_id, "ungrouped")
    ungrouped = [item for item in labeled if not item.get("goal_cid")]
    if ungrouped:
        goals.append(
            {
                "admitted": False,
                "formalized": False,
                "goal_alias": default_goal_id,
                "goal_cid": default_cid,
                "goal_id": default_goal_id,
                "kind": "ungrouped",
                "objective_id": OBJECTIVE_ID,
                "ordinal": len(goals) + 1,
                "parent_goal_cid": campaign_cid,
                "priority": "P2",
                "resolves": [str(item["task_id"]) for item in ungrouped],
                "source_span_ids": [str(item.get("source_span_id") or "") for item in ungrouped],
                "status": "open",
                "title": "Ungrouped autoformal discrepancies",
            }
        )
        edges.append(
            {
                "parent": campaign_cid,
                "child": default_cid,
                "parent_goal_cid": campaign_cid,
                "child_goal_cid": default_cid,
                "edge_kind": "goal_decomposition",
            }
        )
        for item in ungrouped:
            item["goal_id"] = default_goal_id
            item["goal_cid"] = default_cid
            item["parent_goal_cid"] = campaign_cid
    for index, task in enumerate(labeled, start=1):
        task["objective_id"] = OBJECTIVE_ID
        task["plan_cid"] = plan_cid
        task["ordinal"] = index
        task["task_cid"] = _cid("task", task.get("task_id"), task.get("source_span_id"))
        task["status"] = "ready"
        task["is_schedulable"] = True
        task["review_only"] = False
        task["completion"] = "evidence"
        task["admitted"] = False
        task["formalized"] = False
        task["proof_authoritative"] = False
        task["match_is_not_admit"] = True
        task["outputs"] = [{"path": "workspace/todo-queues/uscode-autoformal-loop.todo.md"}]
        task["acceptance_criteria"] = [str(task.get("acceptance") or "Do not mark formalized.")]
        task["validation_commands"] = [
            {"argv": ["python3", "-m", "pytest", "tests/unit/logic/test_supervisor_loop.py", "-q"]}
        ]
        task["depends_on"] = list(task.get("depends_on") or [])
    campaign["resolves"] = [goal["goal_id"] for goal in goals if goal["goal_id"] != CAMPAIGN_GOAL_ID]
    campaign["source_span_ids"] = [str(item.get("source_span_id") or "") for item in labeled]
    campaign["estimated_tokens"] = sum(int(item.get("estimated_tokens") or 0) for item in labeled)
    campaign["validation_commands"] = [
        {"argv": ["python3", "-m", "pytest", "tests/unit/logic/test_supervisor_loop.py", "-q"]}
    ]
    campaign["acceptance_criteria"] = [
        "Do not mark formalized. Child goals and todos must round-trip or stay explicit."
    ]
    tree = {
        "edges": edges,
        "goal_edges": edges,
        "goals": goals,
        "objective_id": OBJECTIVE_ID,
        "plan_cid": plan_cid,
        "tasks": labeled,
    }
    from .supervisor_dispatch import attach_dispatch

    allowed = (
        "agreement",
        "packet_directory",
        "code_identity",
        "model_identity",
        "job_template",
        "accelerate_root",
        "database",
        "runtime_root",
        "release_id",
        "query",
    )
    options = {key: value for key, value in dict(dispatch or {}).items() if key in allowed}
    options.setdefault("release_id", release_id)
    attach_dispatch(tree, **options)
    return tree


def resolve_goals(
    goals: Sequence[Mapping[str, Any]],
    *,
    proved_span_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A goal resolves when every listed source span has a round-trip receipt."""

    proved = {str(item) for item in proved_span_ids if str(item)}
    resolved: list[dict[str, Any]] = []
    open_goals: list[dict[str, Any]] = []
    for goal in goals:
        item = dict(goal)
        spans = [str(span) for span in item.get("source_span_ids") or [] if str(span)]
        if not spans or all(span in proved for span in spans):
            # DuckDB closed set uses verified_complete for admitted proof.
            # A compile round-trip is only provisionally complete.
            item["status"] = "provisionally_complete"
            resolved.append(item)
        else:
            item["status"] = "open"
            open_goals.append(item)
    return open_goals, resolved


def supervisor_population(
    tree: Mapping[str, Any],
    *,
    repository_tree_id: str = "tree:uscode-autoformal",
    proofs: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """DuckDB DatabaseTaskSource.materialize payload. Not JSONL."""

    plan_cid = str(tree.get("plan_cid") or _cid("plan", CAMPAIGN_GOAL_ID))
    goals = [dict(item) for item in tree.get("goals") or []]
    campaign_cid = next((item["goal_cid"] for item in goals if item.get("kind") == "campaign"), "")
    return {
        "admitted": False,
        "formalized": False,
        "goals": goals,
        "goal_edges": [dict(item) for item in tree.get("goal_edges") or []],
        "jsonl_written": False,
        "plan_root_cid": plan_cid,
        "plans": [
            {
                "admitted": False,
                "formalized": False,
                "goal_cid": campaign_cid,
                "plan_alias": "autoformal-loop",
                "plan_cid": plan_cid,
                "proofs": list(proofs),
                "status": "active",
            }
        ],
        "repository_tree_id": repository_tree_id,
        "schema": POPULATION_SCHEMA,
        "tasks": [dict(item) for item in tree.get("tasks") or []],
        "wrote_compiler": False,
    }


def _ensure_span_subgoals(tree: dict[str, Any]) -> dict[str, Any]:
    """One open subgoal per source span, under its failure goal or the campaign.

    An ungrouped bucket is not a second copy of the default todo goal.
    """

    goals = [dict(goal) for goal in tree.get("goals") or []]
    tasks = [dict(task) for task in tree.get("tasks") or []]
    edges = [dict(edge) for edge in tree.get("goal_edges") or []]
    campaign = next((goal for goal in goals if goal.get("kind") == "campaign"), None)
    if campaign is None:
        return tree
    drop = {goal["goal_cid"] for goal in goals if goal.get("kind") == "ungrouped"}
    goals = [goal for goal in goals if goal["goal_cid"] not in drop]
    edges = [
        edge for edge in edges
        if edge.get("child_goal_cid") not in drop and edge.get("parent_goal_cid") not in drop
    ]
    spans: list[str] = []
    for task in tasks:
        span = str(task.get("source_span_id") or "")
        if span and span not in spans:
            spans.append(span)
    next_sub = 500
    for span in spans:
        subset = [task for task in tasks if str(task.get("source_span_id") or "") == span]
        if subset and all(
            any(
                goal.get("goal_cid") == task.get("goal_cid") and goal.get("kind") == "subgoal"
                for goal in goals
            )
            for task in subset
        ):
            continue
        sub_id = f"{GOAL_PREFIX}{next_sub:03d}"
        next_sub += 1
        sub_cid = _cid("goal", sub_id, "subgoal", span)
        parent = campaign["goal_cid"]
        current = str(subset[0].get("goal_cid") or "") if subset else ""
        if any(goal.get("goal_cid") == current and goal.get("kind") == "architecture-decision" for goal in goals):
            parent = current
        goals.append(
            {
                "admitted": False,
                "failure_mode": str(subset[0].get("failure_mode") or "") if subset else "",
                "formalized": False,
                "goal_alias": sub_id,
                "goal_cid": sub_cid,
                "goal_id": sub_id,
                "kind": "subgoal",
                "objective_id": OBJECTIVE_ID,
                "ordinal": len(goals) + 1,
                "parent_goal_cid": parent,
                "priority": "P1",
                "resolves": [str(task.get("task_id") or "") for task in subset],
                "repair_targets": [
                    str(item) for item in (subset[0].get("replace") or []) if str(item)
                ] if subset else [],
                "source_span_ids": [span],
                "status": "open",
                "title": f"Subgoal: {span}"
                + (": " + str(subset[0].get("failure_mode") or "") if subset else ""),
            }
        )
        edges.append(
            {
                "parent": parent,
                "child": sub_cid,
                "parent_goal_cid": parent,
                "child_goal_cid": sub_cid,
                "edge_kind": "goal_decomposition",
            }
        )
        for task in subset:
            task["goal_id"] = sub_id
            task["goal_cid"] = sub_cid
            task["parent_goal_cid"] = parent
    tree["goals"] = goals
    tree["tasks"] = tasks
    tree["goal_edges"] = edges
    tree["edges"] = edges
    return tree


def _child_goals(task_source: Any, parent_cid: str) -> list[Mapping[str, Any]]:
    with task_source._intent._connection(write=False) as connection:
        rows = connection.execute(
            "SELECT goal_cid FROM goals WHERE parent_goal_cid = ?",
            [parent_cid],
        ).fetchall()
    children = []
    for row in rows:
        goal = task_source._intent.get_goal(str(row[0]))
        if goal is not None:
            children.append(goal)
    return children


def _roll_inconclusive_parents(task_source: Any, child: Mapping[str, Any]) -> list[str]:
    """Park a parent only when every child subgoal is already inconclusive."""

    updated: list[str] = []
    parent_cid = str(child.get("parent_goal_cid") or "")
    seen: set[str] = set()
    while parent_cid and parent_cid not in seen:
        seen.add(parent_cid)
        parent = task_source._intent.get_goal(parent_cid)
        if parent is None:
            break
        children = _child_goals(task_source, parent_cid)
        if not children or any(
            str(item.get("status") or "") != "analysis_inconclusive" for item in children
        ):
            break
        keys: list[str] = []
        for item in children:
            body = item.get("body") if isinstance(item.get("body"), Mapping) else {}
            receipt = body.get("completion_receipt") if isinstance(body, Mapping) else {}
            if not isinstance(receipt, Mapping):
                continue
            for key in receipt.get("proposal_keys") or []:
                text = str(key)
                if text in {"parser", "compiler", "decompiler"} and text not in keys:
                    keys.append(text)
        keys.sort()
        if str(parent.get("status") or "") != "analysis_inconclusive":
            task_source._intent.cas_goal_status(
                goal_cid=str(parent["goal_cid"]),
                expected_revision=int(parent["revision"]),
                new_status="analysis_inconclusive",
                receipt={
                    "admitted": False,
                    "applied": False,
                    "formalized": False,
                    "imported": False,
                    "operation": "router_proposal_review",
                    "proposal_keys": keys,
                    "wrote_compiler": False,
                },
            )
            updated.append(str(parent["goal_cid"]))
        parent_cid = str(parent.get("parent_goal_cid") or "")
    return updated


def goal_status_counts(task_source: Any) -> dict[str, Any]:
    """Count goal statuses. Inconclusive is not verified-complete and not an admit."""

    counts: dict[str, int] = {}
    with task_source._intent._connection(write=False) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) FROM goals GROUP BY status"
        ).fetchall()
    for row in rows:
        counts[str(row[0] or "")] = int(row[1])
    inconclusive = inconclusive_goals(task_source)
    opened = open_goals(task_source)
    return {
        "admitted": False,
        "formalized": False,
        "goal_status_counts": counts,
        "inconclusive_goal_count": counts.get("analysis_inconclusive", 0),
        "inconclusive_goals": inconclusive,
        "open_goal_count": counts.get("open", 0),
        "open_goals": opened,
        "verified_complete_count": counts.get("verified_complete", 0),
    }


def _ready_tasks_by_goal(task_source: Any) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    with task_source._intent._connection(write=False) as connection:
        rows = connection.execute(
            "SELECT task_cid, goal_cid, status FROM tasks"
        ).fetchall()
    for row in rows:
        if str(row[2] or "") != "ready":
            continue
        grouped.setdefault(str(row[1] or ""), []).append(str(row[0]))
    for task_ids in grouped.values():
        task_ids.sort()
    return grouped


def _goals_with_status(task_source: Any, status: str) -> list[dict[str, Any]]:
    ready_by_goal = _ready_tasks_by_goal(task_source)
    with task_source._intent._connection(write=False) as connection:
        rows = connection.execute(
            "SELECT goal_cid FROM goals WHERE status = ? ORDER BY goal_cid",
            [status],
        ).fetchall()
    listed: list[dict[str, Any]] = []
    for row in rows:
        goal = task_source._intent.get_goal(str(row[0]))
        if goal is None or str(goal.get("status") or "") != status:
            continue
        body = goal.get("body") if isinstance(goal.get("body"), Mapping) else {}
        receipt = body.get("completion_receipt") if isinstance(body.get("completion_receipt"), Mapping) else {}
        keys = [
            str(key)
            for key in (receipt.get("proposal_keys") or [])
            if str(key) in {"parser", "compiler", "decompiler"}
        ]
        spans = [str(item) for item in body.get("source_span_ids") or [] if str(item)]
        targets = [str(item) for item in body.get("repair_targets") or [] if str(item)]
        listed.append({
            "admitted": False,
            "formalized": False,
            "goal_cid": str(goal.get("goal_cid") or ""),
            "kind": str(body.get("kind") or ""),
            "parent_goal_cid": str(goal.get("parent_goal_cid") or ""),
            "proposal_keys": keys,
            "ready_task_cids": list(ready_by_goal.get(str(goal.get("goal_cid") or ""), [])),
            "repair_targets": targets,
            "source_span_ids": spans,
            "status": status,
            "title": str(goal.get("title") or ""),
        })
    return listed


def ready_task_cids_under_inconclusive_goals(task_source: Any) -> set[str]:
    """Ready todos whose goal is already parked. A claim must not take these."""

    intent = getattr(task_source, "_intent", None)
    if intent is None:
        return set()
    with intent._connection(write=False) as connection:
        goal_rows = connection.execute(
            "SELECT goal_cid FROM goals WHERE status = ?",
            ["analysis_inconclusive"],
        ).fetchall()
        task_rows = connection.execute(
            "SELECT task_cid, goal_cid, status FROM tasks"
        ).fetchall()
    parked = {str(row[0]) for row in goal_rows}
    return {
        str(row[0])
        for row in task_rows
        if str(row[2] or "").lower() == "ready" and str(row[1] or "") in parked
    }


def claim_block_for_inconclusive_goals(task_source: Any) -> dict[str, Any]:
    """Explain a refused claim when ready todos sit under parked goals."""

    blocked = sorted(ready_task_cids_under_inconclusive_goals(task_source))
    blocked_set = set(blocked)
    claimable: list[str] = []
    intent = getattr(task_source, "_intent", None)
    if intent is not None:
        with intent._connection(write=False) as connection:
            rows = connection.execute("SELECT task_cid, status FROM tasks").fetchall()
        claimable = sorted(
            str(row[0])
            for row in rows
            if str(row[1] or "").lower() == "ready" and str(row[0]) not in blocked_set
        )
    return {
        "admitted": False,
        "claim_blocked_reason": "goals_inconclusive" if blocked else "",
        "claim_blocked_task_cids": blocked,
        "claimable_ready_task_cids": claimable,
        "formalized": False,
    }


def open_goals(task_source: Any) -> list[dict[str, Any]]:
    """Name goals the supervisor can still work. Parked goals are not included."""

    return _goals_with_status(task_source, "open")


def inconclusive_goals(task_source: Any) -> list[dict[str, Any]]:
    """Name parked goals. This does not reopen them or mark them complete."""

    return _goals_with_status(task_source, "analysis_inconclusive")


def mark_span_subgoal_review(
    task_source: Any,
    task_cid: str,
    proposal_sha256: str,
    proposal_keys: Sequence[str] = (),
) -> dict[str, Any]:
    """Mark one span subgoal inconclusive. Do not close the campaign or admit it."""

    keys = [str(key) for key in proposal_keys or [] if str(key) in {"parser", "compiler", "decompiler"}]
    task = task_source.get(str(task_cid or ""))
    goal_cid = str(getattr(task, "goal_cid", "") or "") if task is not None else ""
    unchanged = {
        "admitted": False,
        "formalized": False,
        "goal_cid": goal_cid,
        "goal_status": "",
        "proposal_keys": keys,
        "rolled_up": [],
        "updated": False,
        "wrote_compiler": False,
    }
    if task is None or not goal_cid:
        return unchanged
    goal = task_source._intent.get_goal(goal_cid)
    if goal is None:
        return unchanged
    body = goal.get("body") if isinstance(goal.get("body"), Mapping) else {}
    if body.get("kind") != "subgoal":
        return unchanged
    if str(goal.get("status") or "") == "analysis_inconclusive":
        unchanged["goal_status"] = "analysis_inconclusive"
        unchanged["rolled_up"] = _roll_inconclusive_parents(task_source, goal)
        return unchanged
    task_source._intent.cas_goal_status(
        goal_cid=str(goal["goal_cid"]),
        expected_revision=int(goal["revision"]),
        new_status="analysis_inconclusive",
        receipt={
            "admitted": False,
            "applied": False,
            "formalized": False,
            "imported": False,
            "operation": "router_proposal_review",
            "proposal_keys": keys,
            "proposal_sha256": str(proposal_sha256 or ""),
            "wrote_compiler": False,
        },
    )
    return {
        "admitted": False,
        "formalized": False,
        "goal_cid": str(goal["goal_cid"]),
        "goal_status": "analysis_inconclusive",
        "proposal_keys": keys,
        "rolled_up": _roll_inconclusive_parents(task_source, goal),
        "updated": True,
        "wrote_compiler": False,
    }


def attach_goal_tree(
    source: Any,
    agreement: Mapping[str, Any],
    *,
    release_id: str,
    campaign_title: str = "US Constitution autoformal campaign",
) -> dict[str, Any]:
    """Attach sealed repair todos to a campaign, failure goal, and span subgoals.

    Does not call the router or replace the sealed packet on an existing task.
    """

    tasks = discrepancy_tasks(agreement, query=campaign_title, release_id=release_id)
    if not tasks:
        return {
            "admitted": False,
            "formalized": False,
            "goal_count": 0,
            "linked_tasks": 0,
            "router_called": False,
            "subgoal_count": 0,
            "wrote_compiler": False,
        }
    tree = _ensure_span_subgoals(
        spawn_goal_tree(tasks, release_id=release_id, campaign_title=campaign_title)
    )
    population = supervisor_population(tree, repository_tree_id="tree:us-constitution")
    population["tasks"] = []
    ingest_population(source, population)
    span_goal = {
        str(item.get("source_span_id") or ""): str(item.get("goal_cid") or "")
        for item in tree["tasks"]
        if item.get("source_span_id") and item.get("goal_cid")
    }
    from .supervisor_queue import read_packet

    linked = 0
    cursor = ""
    while True:
        page = source.list_tasks(cursor=cursor, limit=100)
        for record in page.tasks:
            body = record.body if isinstance(record.body, Mapping) else {}
            path = str(body.get("packet_path") or "")
            digest = str(body.get("packet_sha256") or "")
            if not path or not digest:
                continue
            packet = read_packet(Path(path), digest)
            row = packet.get("row") if isinstance(packet, Mapping) else {}
            span = str((row or {}).get("source_span_id") or "")
            goal_cid = span_goal.get(span) or ""
            if not goal_cid:
                continue
            if record.goal_cid != goal_cid:
                source._intent.upsert_task(
                    task_cid=record.task_cid,
                    task_alias=record.task_alias,
                    goal_cid=goal_cid,
                    ordinal=int(record.ordinal),
                    status=str(record.status),
                    priority=str(record.priority or "P0"),
                    plan_cid=str(tree["plan_cid"]),
                    objective_id=OBJECTIVE_ID,
                    body=dict(body),
                    expected_revision=int(record.revision),
                    dependencies=list(record.dependencies),
                    outputs=list(record.outputs),
                    acceptance=list(record.acceptance),
                    validations=list(record.validations),
                )
            linked += 1
        cursor = str(getattr(page, "next_cursor", "") or "")
        if not cursor:
            break
    return {
        "admitted": False,
        "formalized": False,
        "goal_count": len(tree["goals"]),
        "linked_tasks": linked,
        "router_called": False,
        "subgoal_count": sum(1 for goal in tree["goals"] if goal.get("kind") == "subgoal"),
        "wrote_compiler": False,
    }


def ingest_population(source: Any, population: Mapping[str, Any]) -> dict[str, Any]:
    """Hand the goal/todo tree to DatabaseTaskSource.materialize."""

    receipt = source.materialize(population)
    if hasattr(receipt, "get"):
        payload = dict(receipt)
    else:
        payload = {"task_count": 0}
    payload["admitted"] = False
    payload["formalized"] = False
    payload["jsonl_written"] = False
    payload["wrote_compiler"] = False
    return payload


def run_supervisor_loop(
    autoformal: Callable[[], Mapping[str, Any]],
    *,
    ingest: Callable[..., dict[str, Any]] | None = None,
    max_rounds: int = 3,
    query: str = "",
    release_id: str = "",
    board_path: Any = None,
    upload: Callable[..., dict[str, Any]] | None = None,
    native: Callable[..., dict[str, Any]] | None = None,
    source: Any | None = None,
    repository_tree_id: str = "tree:uscode-autoformal",
    prior: Mapping[str, Any] | None = None,
    log: Callable[[str], None] | None = None,
    compile_one: Callable[[str], Mapping[str, Any]] | None = None,
    dispatch: Mapping[str, Any] | None = None,
    lake_probe: Callable[..., Mapping[str, Any]] | None = None,
    lean_check: Callable[..., Mapping[str, Any]] | None = None,
    span_cache: Any | None = None,
    path_hashes: Mapping[str, str] | None = None,
    code_identity: str = "",
) -> dict[str, Any]:
    """Run autoformal, ingest DuckDB-shaped goals/todos, recurse until goals resolve."""

    if max_rounds < 1 or max_rounds > MAX_ROUNDS:
        raise SupervisorLoopError(f"max_rounds must be 1..{MAX_ROUNDS}")
    seen, proved = _prior_span_state(prior)
    resumed = bool(seen or proved or prior)
    rounds: list[dict[str, Any]] = []
    stop = "max_rounds"
    last_open: list[dict[str, Any]] = []
    last_tasks: list[dict[str, Any]] = list(
        ((prior or {}).get("population") or {}).get("tasks") or []
    )
    corpus_gaps: dict[str, dict[str, Any]] = {}
    for task in last_tasks:
        span = _span_id(task)
        if span and str(task.get("work_kind") or "") != "autoencoder_training":
            corpus_gaps[span] = dict(task)
    prior_remaining = {str(item) for item in (prior or {}).get("remaining_span_ids") or [] if str(item)}
    retrieved_rounds = 0
    gap_ids: set[str] = set(corpus_gaps) | prior_remaining
    _emit_progress(
        f"PROGRESS start max_rounds={max_rounds} resumed={str(resumed).lower()} "
        f"prior_compiled={len(proved)} prior_seen_gaps={len(seen)} "
        f"prior_remaining={len(prior_remaining)}",
        log=log,
        board_path=board_path,
    )
    for index in range(1, max_rounds + 1):
        recensed = False
        try:
            recensus_tick = (
                index > 1
                and compile_one is not None
                and last_tasks
                and retrieved_rounds >= 1
                and index % 2 == 0
            )
            if recensus_tick:
                recensed = True
                _emit_progress(
                    f"PROGRESS recensus round={index}/{max_rounds} open_todos={len(last_tasks)} "
                    f"corpus_remaining={len(gap_ids - proved)}",
                    log=log,
                    board_path=board_path,
                )
                tick = recensus_open_todos(
                    {"population": {"tasks": last_tasks}, "proved_span_ids": sorted(proved)},
                    compile_one,
                    dispatch=dispatch,
                    span_cache=span_cache,
                )
                agreement = tick["agreement"]
                receipt = {"rows": agreement.get("rows") or []}
            else:
                _emit_progress(
                    f"PROGRESS retrieve round={index}/{max_rounds} "
                    f"corpus_compiled={len(proved)} corpus_remaining={len(gap_ids - proved)}",
                    log=log,
                    board_path=board_path,
                )
                receipt = autoformal()
                retrieved_rounds += 1
                agreement = agreement_from_run(receipt)
        except SupervisorLoopError:
            raise
        except Exception as exc:
            agreement = agreement_from_exception(exc, round_index=index)
            receipt = {"error": str(exc)}
        cache_receipt: dict[str, Any] = {}
        if span_cache is not None:
            cache_receipt = dict(
                span_cache.apply_census(
                    agreement,
                    code_identity=code_identity,
                    path_hashes=path_hashes,
                )
                or {}
            )
            _emit_progress(
                f"CACHE round={index} sealed={cache_receipt.get('sealed_total')} "
                f"gaps={cache_receipt.get('gap_total')} pending={cache_receipt.get('pending_total')} "
                f"unsealed={cache_receipt.get('unsealed')} "
                f"changed_paths={','.join(cache_receipt.get('changed_paths') or []) or 'none'}",
                log=log,
                board_path=board_path,
            )
            if compile_one is not None:
                drained = span_cache.process_pending(
                    compile_one,
                    code_identity=code_identity,
                    path_hashes=path_hashes,
                )
                cache_receipt["drained"] = drained
                if int(drained.get("processed") or 0) or int(drained.get("skipped_sealed") or 0):
                    _emit_progress(
                        f"CACHE drain processed={drained.get('processed')} "
                        f"skipped_sealed={drained.get('skipped_sealed')} "
                        f"sealed_total={drained.get('sealed_total')}",
                        log=log,
                        board_path=board_path,
                    )
            lean = span_cache.build_lean_units(
                check=lean_check,
                verify=lean_check is not None,
            )
            cache_receipt["lean"] = {
                "statute_count": lean.get("statute_count"),
                "term_count": lean.get("term_count"),
                "admitted": False,
                "formalized": False,
            }
            for item in (lean.get("statutes") or [])[:8]:
                _emit_progress(
                    f"STATUTE legal_id={item.get('legal_id')} clauses={item.get('clause_count')} "
                    f"lake_ok={str(bool(item.get('lake_ok'))).lower()} "
                    f"error={item.get('lake_error') or 'none'}",
                    log=log,
                    board_path=board_path,
                )
            for item in (lean.get("terms") or [])[:12]:
                _emit_progress(
                    f"TERM kind={item.get('kind')} value={item.get('value')} "
                    f"statutes={item.get('statute_count')} "
                    f"lake_ok={str(bool(item.get('lake_ok'))).lower()} "
                    f"error={item.get('lake_error') or 'none'}",
                    log=log,
                    board_path=board_path,
                )
        stage = _emit_census_stage(
            agreement,
            index=index,
            log=log,
            board_path=board_path,
            lake_probe=lake_probe,
        )
        proofs = proofs_from_agreement(agreement)
        new_compiled = {
            str(item.get("source_span_id") or "")
            for item in proofs
            if item.get("source_span_id") and str(item.get("source_span_id") or "") not in proved
        }
        proved |= {str(item.get("source_span_id") or "") for item in proofs if item.get("source_span_id")}
        batch_todos = discrepancy_tasks(agreement, query=query, release_id=release_id)
        batch_gap_ids = {_span_id(task) for task in batch_todos if _span_id(task)}
        new_ids = batch_gap_ids - seen
        for span in list(corpus_gaps):
            if span in proved:
                corpus_gaps.pop(span, None)
        for task in batch_todos:
            span = _span_id(task)
            if span and span not in proved:
                corpus_gaps[span] = dict(task)
        todos = [dict(item) for item in corpus_gaps.values()]
        dispatch_options = dict(dispatch or {})
        dispatch_options["agreement"] = agreement
        dispatch_options.setdefault("query", query)
        dispatch_options.setdefault("release_id", release_id)
        tree = spawn_goal_tree(todos, release_id=release_id, dispatch=dispatch_options)
        todos = tree["tasks"]
        open_goals, resolved_goals = resolve_goals(tree["goals"], proved_span_ids=sorted(proved))
        status_by_id = {
            str(item.get("goal_id") or ""): str(item.get("status") or "open")
            for item in list(open_goals) + list(resolved_goals)
        }
        for goal in tree["goals"]:
            goal["status"] = status_by_id.get(str(goal.get("goal_id") or ""), str(goal.get("status") or "open"))
        last_open = open_goals
        last_tasks = list(todos)
        gap_ids = {_span_id(task) for task in todos if _span_id(task)} | prior_remaining
        remaining_ids = sorted(gap_ids - proved)
        ingested: dict[str, Any] = {"jsonl_written": False, "task_count": 0, "goal_count": 0}
        population = supervisor_population(
            tree, repository_tree_id=repository_tree_id, proofs=proofs
        )
        if todos:
            submit = ingest or submit_discrepancies
            ingested = submit(
                agreement,
                board_path=board_path,
                query=query,
                release_id=release_id,
                upload=None,
                native=native,
                goals=tree["goals"],
                tasks=todos,
            )
            ingested = dict(ingested)
            ingested["goals"] = tree["goals"]
            ingested["population"] = population
            ingested["jsonl_written"] = False
            ingested["wrote_compiler"] = False
        if source is not None:
            ingested = dict(ingested)
            ingested["native_population"] = ingest_population(source, population)
            ingested["jsonl_written"] = False
            ingested["wrote_compiler"] = False
        native_population = dict(ingested.get("native_population") or {})
        compiled = len(proved)
        operative = compiled + len(remaining_ids)
        modes = sorted({str(task.get("failure_mode") or "") for task in todos if task.get("failure_mode")})
        from .supervisor_dispatch import dispatch_counts

        counts = dispatch_counts(todos)
        phase = "recensus" if recensed else "retrieve"
        _emit_progress(
            f"PROGRESS round={index}/{max_rounds} phase={phase} "
            f"compiled={compiled}/{operative} remaining={len(remaining_ids)} "
            f"new_gaps={len(new_ids)} new_compiled={len(new_compiled)} "
            f"proofs_total={len(proved)} open_goals={len(open_goals)} "
            f"provisionally_complete={len(resolved_goals)} "
            f"ingested_tasks={int(ingested.get('task_count') or 0)} "
            f"failure_modes={','.join(modes) or 'none'}",
            log=log,
            board_path=board_path,
        )
        _emit_progress(
            f"CENSUS round={index} compiled_total={compiled} remaining={len(remaining_ids)} "
            f"new_compiled={len(new_compiled)} new_gaps={len(new_ids)} phase={phase} "
            f"compiled_ids={','.join(sorted(new_compiled)) or 'none'} "
            f"remaining_ids={','.join(remaining_ids) or 'none'}",
            log=log,
            board_path=board_path,
        )
        _emit_progress(
            f"PROGRESS dispatch round={index} edit={counts['edit']} train={counts['train']} "
            f"review={counts['review']} sealed_packets={counts['sealed_packets']} "
            f"bound_training={counts['bound_training']}",
            log=log,
            board_path=board_path,
        )
        for task in todos[:12]:
            text = str(task.get("source_text") or task.get("text") or "")
            _emit_progress(
                f"PROGRESS gap id={_span_id(task)} "
                f"reason={task.get('failure_mode') or task.get('reason')} "
                f"work_kind={task.get('work_kind') or ''} "
                f"goal={task.get('goal_id')} "
                f"text={text[:160]}",
                log=log,
                board_path=board_path,
            )
        round_receipt = {
            "admitted": False,
            "formalized": False,
            "gap_count": len(remaining_ids),
            "goal_count": len(tree["goals"]),
            "goals": tree["goals"],
            "ingested_task_count": int(ingested.get("task_count") or 0),
            "native_population": native_population,
            "jsonl_written": False,
            "new_compiled_count": len(new_compiled),
            "new_error_count": len(new_ids),
            "open_goal_count": len(open_goals),
            "phase": phase,
            "population": population,
            "proof_count": len(proofs),
            "proofs": proofs,
            "resolved_goal_count": len(resolved_goals),
            "resolved_goals": resolved_goals,
            "round": index,
            "compiled_count": compiled,
            "operative_count": operative,
            "remaining_count": len(remaining_ids),
            "census_spans": stage["spans"],
            "lake": stage["lake"],
            "span_cache": cache_receipt,
            "wrote_compiler": False,
        }
        rounds.append(round_receipt)
        snapshot = census_snapshot_path(board_path)
        if snapshot is not None:
            write_census_snapshot(
                snapshot,
                {
                    "compiled_count": compiled,
                    "compiled_span_ids": sorted(proved),
                    "failure_modes": modes,
                    "open_goal_count": len(open_goals),
                    "phase": phase,
                    "remaining_count": len(remaining_ids),
                    "remaining_span_ids": remaining_ids,
                    "round": index,
                    "census_spans": stage["spans"],
                    "lake": stage["lake"],
                    "stop_reason": "",
                },
            )
        if not remaining_ids and not open_goals:
            stop = "goals_resolved"
            break
        if not remaining_ids:
            stop = "no_outstanding_todos"
            break
        if recensed and not new_ids and not new_compiled and index < max_rounds:
            _emit_progress(
                f"PROGRESS plateau round={index} remaining={len(remaining_ids)} "
                f"next=retrieve_more_uscode",
                log=log,
                board_path=board_path,
            )
            seen |= batch_gap_ids
            continue
        if (index > 1 or resumed) and not new_ids and not new_compiled:
            stop = "no_new_errors" if open_goals else "goals_resolved"
            _emit_progress(
                f"PROGRESS plateau round={index} remaining={len(remaining_ids)} "
                f"reason={'retrieval_returned_no_new_spans' if not recensed else 'recensus_unchanged'}",
                log=log,
                board_path=board_path,
            )
            break
        seen |= batch_gap_ids | gap_ids
    remaining_ids = sorted((gap_ids | prior_remaining) - proved) if rounds else sorted(prior_remaining - proved)
    compiled_ids = sorted(proved)
    remaining = len(remaining_ids)
    compiled_total = len(compiled_ids)
    note = (
        "census complete"
        if remaining == 0
        else (
            "remaining spans need compiler/parser coverage or a wider GraphRAG query; "
            "todos declare train or edit work"
        )
    )
    _emit_progress(
        f"PROGRESS stop={stop} compiled_total={compiled_total} remaining={remaining} "
        f"open_goals={len(last_open)} rounds={len(rounds)} "
        f"compiled_ids={','.join(compiled_ids) or 'none'} "
        f"remaining_ids={','.join(remaining_ids) or 'none'} "
        f"note={note}",
        log=log,
        board_path=board_path,
    )
    _emit_progress(
        f"CENSUS stop={stop} compiled_total={compiled_total} remaining={remaining} "
        f"admitted=false formalized=false",
        log=log,
        board_path=board_path,
    )
    huggingface: dict[str, Any] = {}
    last_population = (rounds[-1].get("population") if rounds else {}) or {}
    last_tasks = list(last_population.get("tasks") or [])
    if upload is not None and last_tasks:
        huggingface = dict(upload(last_tasks) or {})
        huggingface["jsonl_written"] = False
    return {
        "admitted": False,
        "formalized": False,
        "huggingface": huggingface,
        "jsonl_written": False,
        "open_goal_count": len(last_open),
        "population": last_population,
        "proof_count": sum(int(item["proof_count"]) for item in rounds),
        "round_count": len(rounds),
        "rounds": rounds,
        "schema": SCHEMA,
        "stop_reason": stop,
        "proved_span_ids": sorted(proved),
        "seen_span_ids": sorted(seen | {
            str(task.get("source_span_id") or "")
            for task in last_tasks
            if task.get("source_span_id")
        }),
        "todo_count": remaining,
        "compiled_count": compiled_total,
        "compiled_span_ids": compiled_ids,
        "remaining_count": remaining,
        "remaining_span_ids": remaining_ids,
        "census_spans": list((rounds[-1].get("census_spans") if rounds else []) or []),
        "lake": dict((rounds[-1].get("lake") if rounds else {}) or {}),
        "span_cache": dict((rounds[-1].get("span_cache") if rounds else {}) or {}),
        "wrote_compiler": False,
    }


def write_population_receipt(
    path: str | Path,
    loop_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """One JSON object the supervisor can reload. Not JSONL."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "admitted": False,
        "formalized": False,
        "jsonl_written": False,
        "open_goal_count": loop_receipt.get("open_goal_count"),
        "population": loop_receipt.get("population") or {},
        "compiled_count": loop_receipt.get("compiled_count"),
        "compiled_span_ids": list(loop_receipt.get("compiled_span_ids") or []),
        "proved_span_ids": list(loop_receipt.get("proved_span_ids") or []),
        "remaining_count": loop_receipt.get("remaining_count"),
        "remaining_span_ids": list(loop_receipt.get("remaining_span_ids") or []),
        "schema": POPULATION_SCHEMA,
        "seen_span_ids": list(loop_receipt.get("seen_span_ids") or []),
        "seen_document_ids": list(loop_receipt.get("seen_document_ids") or []),
        "stop_reason": loop_receipt.get("stop_reason"),
        "wrote_compiler": False,
    }
    destination.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"path": str(destination), "jsonl_written": False}


def loop_progress_report(loop_receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Operator-facing corpus census for CLI JSON. Not a legal admit."""

    rounds = []
    for item in loop_receipt.get("rounds") or []:
        if not isinstance(item, Mapping):
            continue
        rounds.append(
            {
                "compiled_count": int(item.get("compiled_count") or 0),
                "new_compiled_count": int(item.get("new_compiled_count") or 0),
                "new_error_count": int(item.get("new_error_count") or 0),
                "phase": str(item.get("phase") or ""),
                "remaining_count": int(item.get("remaining_count") or 0),
                "round": item.get("round"),
            }
        )
    return {
        "admitted": False,
        "compiled_count": int(loop_receipt.get("compiled_count") or 0),
        "compiled_span_ids": list(loop_receipt.get("compiled_span_ids") or []),
        "formalized": False,
        "remaining_count": int(loop_receipt.get("remaining_count") or 0),
        "remaining_span_ids": list(loop_receipt.get("remaining_span_ids") or []),
        "rounds": rounds,
        "lake": dict(loop_receipt.get("lake") or {}),
        "stop_reason": loop_receipt.get("stop_reason"),
        "wrote_compiler": False,
    }


def write_census_snapshot(path: str | Path, loop_receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Operator-facing census: compiled vs remaining. Not a legal admit."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    compiled_ids = [str(item) for item in loop_receipt.get("compiled_span_ids") or []]
    remaining_ids = [str(item) for item in loop_receipt.get("remaining_span_ids") or []]
    payload = {
        "admitted": False,
        "compiled_count": int(loop_receipt.get("compiled_count") or len(compiled_ids)),
        "compiled_span_ids": compiled_ids,
        "failure_modes": list(loop_receipt.get("failure_modes") or []),
        "formalized": False,
        "open_goal_count": loop_receipt.get("open_goal_count"),
        "phase": str(loop_receipt.get("phase") or ""),
        "remaining_count": int(loop_receipt.get("remaining_count") or len(remaining_ids)),
        "remaining_span_ids": remaining_ids,
        "round": loop_receipt.get("round"),
        "census_spans": list(loop_receipt.get("census_spans") or []),
        "lake": dict(loop_receipt.get("lake") or {}),
        "stop_reason": loop_receipt.get("stop_reason"),
        "wrote_compiler": False,
    }
    destination.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"path": str(destination), "jsonl_written": False}


def load_population_receipt(path: str | Path) -> dict[str, Any]:
    """Reload a loop population. JSONL is not accepted."""

    destination = Path(path)
    try:
        payload = json.loads(destination.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SupervisorLoopError(f"cannot read population receipt: {destination}") from exc
    if not isinstance(payload, Mapping):
        raise SupervisorLoopError("population receipt must be one JSON object")
    if payload.get("schema") != POPULATION_SCHEMA:
        raise SupervisorLoopError("population receipt schema is not the supervisor population")
    if payload.get("jsonl_written") is True:
        raise SupervisorLoopError("population receipt must not be JSONL-authored")
    population = payload.get("population")
    if not isinstance(population, Mapping):
        raise SupervisorLoopError("population receipt is missing the goal/todo tree")
    return {
        "admitted": False,
        "formalized": False,
        "jsonl_written": False,
        "open_goal_count": payload.get("open_goal_count"),
        "population": dict(population),
        "compiled_count": payload.get("compiled_count"),
        "compiled_span_ids": [str(item) for item in payload.get("compiled_span_ids") or []],
        "proved_span_ids": [str(item) for item in payload.get("proved_span_ids") or []],
        "remaining_count": payload.get("remaining_count"),
        "remaining_span_ids": [str(item) for item in payload.get("remaining_span_ids") or []],
        "schema": POPULATION_SCHEMA,
        "seen_span_ids": [str(item) for item in payload.get("seen_span_ids") or []],
        "seen_document_ids": [str(item) for item in payload.get("seen_document_ids") or []],
        "stop_reason": payload.get("stop_reason"),
        "wrote_compiler": False,
    }


def recensus_open_todos(
    prior: Mapping[str, Any],
    compile_one: Callable[[str], Mapping[str, Any]],
    *,
    dispatch: Mapping[str, Any] | None = None,
    span_cache: Any | None = None,
) -> dict[str, Any]:
    """Re-run autoformal on outstanding todo source text. Does not claim a task."""

    loaded = dict(prior)
    tasks = list((loaded.get("population") or {}).get("tasks") or [])
    if not tasks:
        raise SupervisorLoopError("no open todos to recensus")
    rows: list[dict[str, Any]] = []
    seen_spans: set[str] = set()
    for task in tasks:
        text = str(task.get("source_text") or task.get("text") or "")
        span_id = str(task.get("source_span_id") or task.get("id") or task.get("task_id") or "")
        if span_id and span_id in seen_spans:
            continue
        if span_id:
            seen_spans.add(span_id)
        legal_id = str(task.get("legal_id") or "")
        if not text:
            rows.append(
                {
                    "agrees": False,
                    "id": span_id or "missing-text",
                    "legal_id": legal_id,
                    "reason": "loop_error",
                    "skipped": False,
                    "source_span_id": span_id or "missing-text",
                    "text": "",
                }
            )
            continue
        cached = None
        if span_cache is not None:
            cached = span_cache.skip_compile(span_id, source_text=text)
        if cached is not None:
            rows.append(
                {
                    "agrees": True,
                    "canonical_citation": str(task.get("canonical_citation") or ""),
                    "decompiled": str(cached.get("decompiled") or ""),
                    "dropped": [],
                    "id": str(task.get("id") or span_id),
                    "legal_id": legal_id,
                    "reason": "",
                    "rule": dict(cached.get("rule") or {}),
                    "skipped": False,
                    "skipped_compile": True,
                    "source_span_id": span_id,
                    "text": text,
                }
            )
            continue
        result = compile_one(text)
        status = str(result.get("compiler_status") or result.get("status") or "")
        agrees = status in {"compiled", "roundtrip_ok"}
        rows.append(
            {
                "agrees": agrees,
                "canonical_citation": str(task.get("canonical_citation") or ""),
                "decompiled": str(result.get("decompiled") or ""),
                "dropped": [str(item) for item in result.get("unsupported_fields") or [] if str(item)],
                "id": str(task.get("id") or span_id),
                "legal_id": legal_id,
                "reason": "" if agrees else str(result.get("reason") or "compiler_abstain"),
                "rule": dict(result["rule"]) if isinstance(result.get("rule"), Mapping) else {},
                "skipped": False,
                "source_span_id": span_id,
                "text": text,
            }
        )
    operative = [row for row in rows if not row.get("skipped")]
    agreed = sum(1 for row in operative if row.get("agrees"))
    agreement = {
        "admitted": False,
        "agreed": agreed,
        "agrees": bool(operative) and agreed == len(operative),
        "formalized": False,
        "operative": len(operative),
        "reason": "" if operative and agreed == len(operative) else "compiler_disagreement",
        "rows": rows,
    }
    proofs = proofs_from_agreement(agreement)
    todos = discrepancy_tasks(agreement)
    dispatch_options = dict(dispatch or {})
    dispatch_options["agreement"] = agreement
    tree = spawn_goal_tree(todos, dispatch=dispatch_options)
    proved = {str(item.get("source_span_id") or "") for item in proofs if item.get("source_span_id")}
    proved |= {str(item) for item in loaded.get("proved_span_ids") or [] if str(item)}
    open_goals, resolved_goals = resolve_goals(tree["goals"], proved_span_ids=sorted(proved))
    status_by_id = {
        str(item.get("goal_id") or ""): str(item.get("status") or "open")
        for item in list(open_goals) + list(resolved_goals)
    }
    for goal in tree["goals"]:
        goal["status"] = status_by_id.get(str(goal.get("goal_id") or ""), str(goal.get("status") or "open"))
    stop = "goals_resolved" if not todos and not open_goals else (
        "goals_resolved" if not todos else "open_todos_remain"
    )
    return {
        "admitted": False,
        "agreement": agreement,
        "claimed": False,
        "formalized": False,
        "jsonl_written": False,
        "open_goals": open_goals,
        "proofs": proofs,
        "resolved_goals": resolved_goals,
        "stop_reason": stop,
        "tree": tree,
        "wrote_compiler": False,
    }


def _prior_span_state(prior: Mapping[str, Any] | None) -> tuple[set[str], set[str]]:
    seen: set[str] = set()
    proved: set[str] = set()
    if not isinstance(prior, Mapping):
        return seen, proved
    for key in prior.get("seen_span_ids") or []:
        if str(key):
            seen.add(str(key))
    for key in prior.get("proved_span_ids") or []:
        if str(key):
            proved.add(str(key))
    population = prior.get("population") or {}
    for task in population.get("tasks") or []:
        span = str(task.get("source_span_id") or "")
        if span:
            seen.add(span)
    for plan in population.get("plans") or []:
        for item in plan.get("proofs") or []:
            span = str(item.get("source_span_id") or "")
            if span:
                proved.add(span)
    return seen, proved


def prepare_representation_cell_amendment_v1(
    *,
    current_population: Mapping[str, Any],
    current_task_bindings: Mapping[str, Any],
    amendment_request: Mapping[str, Any],
) -> dict[str, Any]:
    """Prepare one detached 4096D addition and two exact specification edits.

    This finite metadata-only profile accepts the retained 64-task population
    with supplied current revisions and native specification identities. Its
    PlanDelta/PlanDeltaItem wire data is a proposal, not a decoded/admitted
    native contract. Original-owner readback, native specification computation,
    PlanRevisionStore authorization and lineage-aware observation remain gates.
    No store, file, command, provider, model or identity allocator is opened.
    """
    supplied: dict[str, Any] = {}

    def need(condition: bool, reason: str) -> None:
        if not condition:
            raise ValueError(reason)

    def text(value: Any) -> bool:
        return type(value) is str and 0 < len(value) <= 1024 and bool(value.strip()) and "\x00" not in value

    def positive(value: Any) -> bool:
        return type(value) is int and 0 < value < 2 ** 63

    def digest(value: Any) -> bool:
        return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)

    def commitment(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()

    def closed(value: Any, fields: set[str], reason: str) -> None:
        need(type(value) is dict and set(value) == fields, reason)

    def strings(value: Any, *, empty: bool = False) -> bool:
        return (type(value) is list and (empty or bool(value)) and len(value) <= 512
                and all(text(item) for item in value) and len(value) == len(set(value)))

    def descriptor(value: Any) -> bool:
        return (type(value) is dict and set(value) == {"path", "bytes", "sha256"}
                and text(value.get("path")) and type(value.get("bytes")) is int
                and 0 <= value["bytes"] <= 2 ** 40 and digest(value.get("sha256")))

    def detached(name: str, value: Any) -> dict[str, Any]:
        need(isinstance(value, Mapping), name + " must be a mapping")
        nodes = 0

        def finite(item: Any, depth: int) -> None:
            nonlocal nodes
            nodes += 1
            need(nodes <= 50000 and depth <= 24, name + " exceeds metadata bounds")
            if type(item) is dict:
                need(all(type(key) is str for key in item), name + " requires string keys")
                for child in item.values():
                    finite(child, depth + 1)
            elif type(item) is list:
                need(len(item) <= 4096, name + " exceeds list bound")
                for child in item:
                    finite(child, depth + 1)
            else:
                need(item is None or type(item) in {str, int, float, bool}, name + " contains non-JSON data")
                if type(item) is str:
                    need(len(item) <= 16384 and "\x00" not in item, name + " contains invalid metadata text")
        original = dict(value)
        finite(original, 0)
        try:
            raw = json.dumps(original, allow_nan=False, ensure_ascii=False)
            need(len(raw.encode("utf-8")) <= 2 * 1024 ** 2, name + " exceeds byte bound")
            return json.loads(raw)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError(name + " must contain bounded finite JSON") from exc

    for name, value in (("current_population", current_population),
                        ("current_task_bindings", current_task_bindings),
                        ("amendment_request", amendment_request)):
        supplied[name] = detached(name, value)
    population, bindings, request = (supplied[name] for name in
        ("current_population", "current_task_bindings", "amendment_request"))
    closed(population, {"schema", "board_namespace", "repository_tree_id", "plan_root_cid",
                        "goals", "goal_edges", "plans", "tasks"}, "population fields must be exact")
    need(population["schema"] == "legal-ir-native-task-population/v1", "unsupported population profile")
    need(population["board_namespace"] == "legal-ir-span-graph-lean-refinement-20261016", "wrong programme namespace")
    need(text(population["plan_root_cid"]) and text(population["repository_tree_id"]), "population roots required")
    need(type(population["tasks"]) is list and len(population["tasks"]) == 64, "exact 64-task predecessor required")
    need(type(population["goals"]) is list and len(population["goals"]) == 34
         and type(population["goal_edges"]) is list and len(population["goal_edges"]) == 33,
         "original goal population required")
    need(type(population["plans"]) is list and len(population["plans"]) == 1
         and type(population["plans"][0]) is dict
         and population["plans"][0].get("plan_cid") == population["plan_root_cid"]
         and positive(population["plans"][0].get("revision")), "exact current predecessor plan required")
    by_alias: dict[str, dict[str, Any]] = {}
    identities: set[str] = set()
    ordinals: set[int] = set()
    for task in population["tasks"]:
        need(type(task) is dict and text(task.get("task_alias")) and text(task.get("task_cid"))
             and positive(task.get("ordinal")) and positive(task.get("revision")), "current task metadata incomplete")
        alias, cid, ordinal = task["task_alias"], task["task_cid"], task["ordinal"]
        need(alias not in by_alias and cid not in identities and ordinal not in ordinals, "duplicate predecessor identity")
        need(task.get("plan_cid") == population["plan_root_cid"], "predecessor is not the selected single-root profile")
        by_alias[alias] = task
        identities.add(cid)
        ordinals.add(ordinal)
    need(set(bindings) == set(by_alias), "all current task bindings required")
    for alias, task in by_alias.items():
        binding = bindings[alias]
        closed(binding, {"task_cid", "revision", "spec_revision", "record_sha256"}, "closed current binding required")
        need(binding["task_cid"] == task["task_cid"] and positive(binding["revision"])
             and binding["revision"] == task["revision"]
             and text(binding["spec_revision"]) and digest(binding["record_sha256"])
             and binding["record_sha256"] == commitment(task), "stale current task/specification binding")
    need({"LIR-1901", "LIR-1902", "LIR-1903", "LIR-1904", "LIR-1905"} <= set(by_alias), "original width cells required")
    design, comparison = by_alias["LIR-1901"], by_alias["LIR-1905"]
    goal_cid = design.get("goal_cid")
    need(text(goal_cid) and all(by_alias[a].get("goal_cid") == goal_cid
         and by_alias[a].get("goal_id") == "LIR-G119" for a in
         ("LIR-1901", "LIR-1902", "LIR-1903", "LIR-1904", "LIR-1905")), "wrong representation goal")
    need(sum(g.get("goal_cid") == goal_cid and g.get("goal_alias") == "LIR-G119"
             for g in population["goals"] if type(g) is dict) == 1, "representation goal absent")
    closed(request, {"schema", "base_population_sha256", "candidate_plan_root_cid", "child_task",
                     "replacement_tasks", "replacement_spec_bindings", "profile", "review", "delta"},
           "amendment request fields must be exact")
    need(request["schema"] == "legal-ir-representation-cell-amendment-request/v1", "unsupported amendment profile")
    need(request["base_population_sha256"] == commitment(population), "stale predecessor population")
    new_root = request["candidate_plan_root_cid"]
    need(text(new_root) and new_root != population["plan_root_cid"], "distinct proposed continuation root required")
    review = request["review"]
    closed(review, {"reviewer", "scope", "evidence"}, "closed review metadata required")
    need(text(review["reviewer"]) and review["scope"] == "representation_cell_and_comparison_metadata_only"
         and descriptor(review["evidence"]), "review evidence required")
    profile = request["profile"]
    closed(profile, {"ir_family", "source_dimension", "actual_bottleneck_dimension", "schema_version",
                     "decoder_task", "producer_family", "producer_id", "producer_revision", "causal_forward", "pooling",
                     "normalization", "input_token_limit", "output_token_limit", "sidecars",
                     "raw_vector_residual_bypass", "study_kind", "comparison_widths"}, "closed representation profile required")
    need(profile["ir_family"] == "legal_ir" and type(profile["source_dimension"]) is int
         and profile["source_dimension"] == 4096 and positive(profile["actual_bottleneck_dimension"])
         and text(profile["schema_version"]) and text(profile["decoder_task"]), "4096D LegalIR profile required")
    need(profile["producer_family"] == "leanstral" and text(profile["producer_id"]) and text(profile["producer_revision"])
         and profile["causal_forward"] == "full" and profile["pooling"] == "last"
         and profile["normalization"] == "l2", "genuine Leanstral causal producer profile required")
    need(positive(profile["input_token_limit"]) and positive(profile["output_token_limit"])
         and strings(profile["sidecars"], empty=True) and type(profile["raw_vector_residual_bypass"]) is bool,
         "explicit context/bypass limits required")
    need(profile["study_kind"] == "native_producer_systems"
         and profile["comparison_widths"] == [8, 384, 768, 4096], "four-system comparison must be separate from bottleneck study")
    child = request["child_task"]
    need(type(child) is dict, "child task required")
    template = by_alias["LIR-1904"]
    # A new logical identity cannot inherit another task's execution evidence,
    # even an empty receipt/history field. This v1 profile refuses a runtime
    # donor rather than silently cleaning or zeroing its original metadata.
    # Inspect only task-runtime containers: checkpoint/source lineage inside
    # inputs is retained provenance, not proof that this new task has executed.
    runtime_fields = {
        "history", "attempt_history", "execution_history", "status_history", "completion_history",
        "provider_history", "claim_history", "lease_history", "settlement_history", "retry_history",
        "attempt", "attempt_id", "attempt_number", "attempts", "attempt_count", "attempt_budget_consumed",
        "current_attempt", "current_attempt_id", "last_attempt", "last_attempt_id",
        "result", "results", "execution_result", "execution_results", "implementation_result",
        "provider_result", "provider_results", "last_result", "last_cycle_result", "terminal_result",
        "completion_receipt", "completion_receipts", "completion_evidence", "failure_receipt",
        "failure_terminal", "success_receipt", "terminal_receipt", "recovery_receipt", "recovery_terminal",
        "original_owner_disposition", "outcome", "callback_outcome", "provider_outcome", "outcome_knowledge",
        "claim", "claims", "claim_id", "claim_cid", "claim_state", "claim_status", "claim_owner",
        "active_claim", "current_claim", "claimed_at", "claimed_by",
        "lease", "leases", "lease_id", "lease_epoch", "lease_deadline_ms", "lease_expires_at", "current_lease",
        "provider_invocation", "provider_invocations", "provider_invocation_id", "provider_attempt_id",
        "provider_dispatched", "provider_status", "invocation_id", "invocation_status",
        "settlement", "settlements", "settlement_receipt", "settlement_status", "settlement_outcome",
        "fencing_token", "fence_epoch", "owner_session_id", "process_birth", "process_instance_id",
        "worker_pid", "worker_birth", "worker_exit_code", "started_at", "finished_at", "completed_at",
        "last_started_at", "last_finished_at",
    }
    runtime_containers = {"authored_task", "body", "runtime", "runtime_state", "runtime_metadata",
                          "execution", "execution_state", "execution_metadata", "state", "metadata",
                          "task", "task_record", "record"}
    for origin, record in (("donor", template), ("child", child)):
        pending = [record]
        inspected = 0
        while pending:
            node = pending.pop()
            if type(node) is not dict:
                continue
            inspected += 1
            need(inspected <= 1024, "task runtime metadata exceeds inspection bound")
            need(not (set(node) & runtime_fields), origin + " runtime history/evidence cannot initialize a new task")
            for key in runtime_containers:
                value = node.get(key)
                if type(value) is dict:
                    pending.append(value)
                elif type(value) is list:
                    pending.extend(item for item in value if type(item) is dict)
    mutable_child = {"task_id", "task_alias", "task_cid", "ordinal", "revision", "plan_cid", "title", "objective",
                     "outputs", "owned_paths", "exclusive_keys", "inputs", "existing_owners", "authored_task", "representation_profile"}
    need(set(child) == set(template) | {"representation_profile"}, "child fields must preserve selected task profile")
    need(all(child[k] == v for k, v in template.items() if k not in mutable_child), "child changed inherited constraints/history")
    alias, cid = child.get("task_alias"), child.get("task_cid")
    need(text(alias) and len(alias) == 8 and alias.startswith("LIR-19") and alias[6:].isdigit()
         and alias not in by_alias and child.get("task_id") == alias and text(cid) and cid not in identities
         and cid != alias and not cid.startswith("LIR-") and (":" in cid or cid.startswith("b")),
         "new durable child identity required; aliases are not dependency CIDs")
    need(child.get("goal_cid") == goal_cid and child.get("goal_id") == "LIR-G119"
         and child.get("legacy_parent_task") == "LIR-19" and child.get("plan_cid") == new_root,
         "child parent/continuation mismatch")
    need(child.get("ordinal") == max(ordinals) + 1 and type(child.get("ordinal")) is int
         and child.get("revision") == 0 and type(child.get("revision")) is int
         and child.get("status") == "blocked", "new child must be appended and blocked")
    need(child.get("depends_on") == ["LIR-1901"] and child.get("dependencies") == [design["task_cid"]], "child design dependency required")
    need(text(child.get("title")) and text(child.get("objective")), "child title/objective required")
    need("existing_owners" not in child or strings(child["existing_owners"]), "declared child owners must be nonempty")
    need(child.get("representation_profile") == profile and child.get("resource_profile") == "inference"
         and child.get("resource_stage") == "inference" and child.get("validation_commands") == [], "child inference profile mismatch")
    need(child.get("execution_authorized_by_this_file") is False and child.get("execution_packet_required") is True
         and child.get("completion") == "manual" and child.get("gold_or_teacher_admission_granted") is False,
         "child cannot acquire execution or supervision authority")
    need(type(child.get("inputs")) is dict and set(child["inputs"]) == set(template.get("inputs", {}))
         and child["inputs"].get("roles") == ["source", "allowed_context", "verified_model_and_encoder", "self_generated_prefixes"]
         and child["inputs"].get("required_dependency_results") == ["LIR-1901"]
         and strings(child["inputs"].get("references")), "child source/review roles must be preserved")
    def relative_path(value: Any) -> bool:
        return text(value) and not value.startswith("/") and ".." not in value.split("/") and not any(c in value for c in "*?[]")
    need(strings(child.get("owned_paths")) and all(relative_path(p) for p in child["owned_paths"])
         and strings(child.get("exclusive_keys")), "explicit child writer scopes required")
    for previous in population["tasks"]:
        need(not set(child["exclusive_keys"]) & set(previous.get("exclusive_keys", [])), "child writer identity collides")
        for old_path in previous.get("owned_paths", []):
            for new_path in child["owned_paths"]:
                need(new_path != old_path and not new_path.startswith(old_path.rstrip("/") + "/")
                     and not old_path.startswith(new_path.rstrip("/") + "/"), "child output scope collides")
    need(type(child.get("outputs")) is list and 0 < len(child["outputs"]) <= 32
         and all(type(o) is dict and relative_path(o.get("path")) and o.get("materialized") is False
                 and any(o["path"].startswith(p.rstrip("/") + "/") for p in child["owned_paths"])
                 for o in child["outputs"]), "unmaterialized child outputs must remain in its owned scope")
    if "authored_task" in child:
        authored = child["authored_task"]
        need(type(authored) is dict and authored.get("objective") == child.get("objective")
             and authored.get("depends_on") == child["depends_on"] and authored.get("inputs") == child["inputs"],
             "child authored metadata must match its declared task")
        for field in ("task_id", "goal_id", "owned_paths", "exclusive_keys", "status", "revision", "priority",
                      "repository", "track", "resource_profile", "resource_stage", "completion", "existing_owners",
                      "execution_packet_required", "execution_authorized_by_this_file", "gold_or_teacher_admission_granted",
                      "requires_product_change_scope", "constraints", "validation"):
            need(field not in authored or (field in child and authored[field] == child[field]),
                 "child authored identity/scope/authority mismatch")
        if "outputs" in authored:
            need(authored["outputs"] == [o["path"] for o in child["outputs"]], "child authored outputs mismatch")
    replacements = request["replacement_tasks"]
    after_bindings = request["replacement_spec_bindings"]
    closed(replacements, {"LIR-1901", "LIR-1905"}, "both comparison/design edits required atomically")
    closed(after_bindings, {"LIR-1901", "LIR-1905"}, "both replacement specification bindings required")
    expected_objectives = {
        "LIR-1901": "Freeze compatible 8D/384D/768D/Leanstral4096D native-producer systems on identical reviewed source groups, complete targets, permitted context and output budgets; keep a bypass-free single-producer bottleneck study separate.",
        "LIR-1905": "Independently compare frozen complete reviewed outputs, controls and all-enrolled fidelity/coverage/cost across the four admitted native-producer cells; this is not an isolated bottleneck-width ablation.",
    }
    for name, original in (("LIR-1901", design), ("LIR-1905", comparison)):
        need(original.get("status") in {"proposed", "admitted", "ready", "todo", "blocked"}, "claimed/running/terminal specifications cannot be amended")
        expected = json.loads(json.dumps(original))
        expected["objective"] = expected_objectives[name]
        if name == "LIR-1905":
            need(original.get("depends_on") == ["LIR-1902", "LIR-1903", "LIR-1904"]
                 and original.get("dependencies") == [by_alias[a]["task_cid"] for a in original["depends_on"]], "comparison predecessor dependencies mismatch")
            expected["depends_on"].append(alias)
            expected["dependencies"].append(cid)
            expected["inputs"]["required_dependency_results"] = expected["depends_on"][:]
        if "authored_task" in expected:
            expected["authored_task"]["objective"] = expected["objective"]
            if name == "LIR-1905":
                expected["authored_task"]["depends_on"] = expected["depends_on"][:]
                expected["authored_task"]["inputs"]["required_dependency_results"] = expected["depends_on"][:]
        need(replacements[name] == expected, "replacement may change only the complete reviewed comparison specification")
        binding = after_bindings[name]
        closed(binding, {"spec_revision", "record_sha256"}, "closed replacement binding required")
        need(text(binding["spec_revision"]) and binding["spec_revision"] != bindings[name]["spec_revision"]
             and binding["record_sha256"] == commitment(expected), "replacement specification commitment mismatch")
    delta = request["delta"]
    delta_fields = {"schema", "contract_version", "base_plan_root", "base_plan_revision", "request_cid", "roots", "items",
                    "expected_effects", "deferred_item_keys", "claimed_population_digest", "accepted_population_digest",
                    "scan_receipt_cid", "evidence_bundle_cid", "admission_receipt_cid"}
    closed(delta, delta_fields, "closed PlanDelta wire contract required")
    need(delta["schema"] == "ipfs_accelerate_py/agent-supervisor/plan-delta@1"
         and delta["contract_version"] == 1 and type(delta["contract_version"]) is int
         and delta["base_plan_root"] == population["plan_root_cid"]
         and positive(delta["base_plan_revision"])
         and delta["base_plan_revision"] == population["plans"][0]["revision"]
         and text(delta["request_cid"]), "PlanDelta predecessor binding invalid")
    roots = delta["roots"]
    root_fields = {"repository_id", "repository_root_cid", "dirty_worktree_root", "task_source_id",
                   "task_source_revision", "policy_root", "intent_ir_root", "legal_ir_root", "security_ir_root",
                   "program_root", "capability_catalog_root", "provider_catalog_root", "usage_policy_root", "configuration_root"}
    closed(roots, root_fields | {"schema", "contract_version"}, "closed PlanAuthorityRoots wire contract required")
    need(roots["schema"] == "ipfs_accelerate_py/agent-supervisor/plan-authority-roots@1"
         and type(roots["contract_version"]) is int and roots["contract_version"] == 1
         and all(text(roots[key]) for key in root_fields)
         and roots["repository_root_cid"] == population["repository_tree_id"], "declared authority roots required")
    need(delta["expected_effects"] == ["add_task", "amend_unstarted_task"] and delta["deferred_item_keys"] == []
         and type(delta["items"]) is list and len(delta["items"]) == 3, "one atomic add/two-amend delta required")
    item_fields = {"schema", "contract_version", "item_key", "operation", "target_cid", "expected_target_lifecycle",
                   "expected_target_spec_revision", "before_digest", "after_record_cid", "effect_class", "rationale", "provenance",
                   "preconditions", "expected_effects", "rollback_refs", "affected_goal_cids", "affected_task_cids", "affected_paths",
                   "dependency_impact", "conflict_impact", "resource_impact"}
    seen: set[str] = set()
    amended: set[str] = set()
    additions = 0
    for item in delta["items"]:
        closed(item, item_fields, "closed PlanDeltaItem wire contract required")
        need(item["schema"] == "ipfs_accelerate_py/agent-supervisor/plan-delta-item@1"
             and item["contract_version"] == 1 and type(item["contract_version"]) is int
             and text(item["item_key"]) and item["item_key"] not in seen
             and item["effect_class"] == "materializable_now" and text(item["rationale"]), "invalid delta item")
        seen.add(item["item_key"])
        if item["operation"] == "add_task":
            additions += 1
            need(item["target_cid"] == "" and item["expected_target_lifecycle"] == "proposed"
                 and item["expected_target_spec_revision"] == "" and item["before_digest"] == ""
                 and item["after_record_cid"] == cid, "ADD_TASK requires the proposed durable child CID")
        else:
            names = [a for a in ("LIR-1901", "LIR-1905") if by_alias[a]["task_cid"] == item["target_cid"]]
            need(item["operation"] == "amend_unstarted_task" and len(names) == 1 and names[0] not in amended,
                 "only two selected specification amendments permitted")
            name = names[0]
            amended.add(name)
            lifecycle = "unstarted" if by_alias[name]["status"] == "todo" else by_alias[name]["status"]
            need(item["expected_target_lifecycle"] == lifecycle
                 and item["expected_target_spec_revision"] == bindings[name]["spec_revision"]
                 and item["before_digest"] == bindings[name]["record_sha256"]
                 and item["after_record_cid"] == after_bindings[name]["spec_revision"], "stale amendment specification CAS")
        expected_target = cid if item["operation"] == "add_task" else item["target_cid"]
        need(item["affected_goal_cids"] == [goal_cid] and item["affected_task_cids"] == [expected_target]
             and type(item["provenance"]) is dict, "exact affected identities and provenance required")
        for field in ("preconditions", "expected_effects", "rollback_refs", "affected_paths",
                      "dependency_impact", "conflict_impact", "resource_impact"):
            need(strings(item[field], empty=True), "delta item collection must be bounded unique metadata")
    for field in ("claimed_population_digest", "accepted_population_digest", "scan_receipt_cid",
                  "evidence_bundle_cid", "admission_receipt_cid"):
        need(type(delta[field]) is str and (delta[field] == "" or text(delta[field])), "delta evidence identity invalid")
    need(additions == 1 and amended == {"LIR-1901", "LIR-1905"}, "partial comparison delta refused")
    candidate_tasks = [replacements.get(t["task_alias"], t) for t in population["tasks"]] + [child]
    return {
        "schema": "legal-ir-representation-cell-amendment-preview/v1", "scope": "caller_supplied_review_metadata_only",
        "metadata_complete": True, "base_population_sha256": commitment(population),
        "candidate_plan_root_cid": new_root, "candidate_tasks": candidate_tasks,
        "unchanged_goals": population["goals"], "unchanged_goal_edges": population["goal_edges"],
        "plan_delta_wire": delta, "profile": profile, "review": review,
        "native_contract_decode_required": True, "native_specification_identity_verification_required": True,
        "native_owner_current_population_and_claim_verification_required": True,
        "native_plan_revision_store_admission_required": True, "lineage_aware_watchdog_cutover_pending": True,
        "native_application_authorized": False, "native_identity_allocated": False,
        "dispatch_authorized": False, "rearm_authorized": False, "workers_started": False,
        "completion_authority": False, "training_authorized": False, "semantic_review_verified": False,
        "supervision_masks": {"training": 0, "evaluation_gold": 0},
    }
