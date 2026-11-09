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


# This additive metadata profile preserves the independent D/G owner prefixes.
_PROGRAMME_WORK_PACKET_SPECS_V1 = (
    ("LIRAE-LIR03-SOURCE-PACKET-01", "source_cache_lineage", "LIR-02",
     ("release_schema_compatibility", "physical_occurrence_crosswalk")),
    ("LIRAE-LIR03-IR-PACKET-01", "typed_ir_scoped_graph", "LIR-07",
     ("complete_typed_ir", "graph_dependency_closure")),
    ("LIRAE-LIR03-MODEL-PACKET-01", "model_compatibility_quality", "LIR-17",
     ("producer_head_compatibility", "reviewed_complete_targets",
      "exposure_grouped_partitions", "frozen_quality_contract")),
    ("LIRAE-LIR03-LEAN-PACKET-02", "lean_release_verification", "LIR-12",
     ("explicit_interpretation_and_assumptions", "lean_import_toolchain_closure",
      "native_preservation_and_build", "immutable_release_readback")),
)
_PROGRAMME_WORK_PACKET_GLOBAL_GATES_V1 = (
    "source_release_manifest", "source_custody", "source_span_entity_crosswalk",
    "edition_and_legal_as_of", "independent_meaning_review",
    "every_use_applicability_review", "original_owner_admission",
    "independent_acceptance",
)


def prepare_programme_work_packet_v1(
    *, task_id, parent_reference, current_parent_reference, authority_binding,
    owner_sources, evidence, remaining_gates,
):
    """Prepare one of four detached, legacy-authority metadata work packets.

    Every descriptor and role is supplied consistency metadata. This function
    opens no file, imports no owner, invokes no callback or command, and claims
    no work. The original caller must authenticate the fixed permitted source
    and evidence paths, immutable 141-card authority snapshots, current-parent
    snapshot row, and selected source epoch. Snapshot binding is not current
    native status, independent review, resource admission or legal authority.

    The original public parent and the supplied current-parent snapshot retain
    independent hashes. Later edits to a live BACKLOG/board/plan do not rewrite
    these immutable observations. Actual dispatch requires fresh admission by
    the original authority; neither this preview nor a completed engineering
    receipt admits its scientific parent. Only fixed metadata commands and two
    output paths are derived. Caller-supplied commands and effects are absent.
    """
    max_nodes, max_depth, max_text_bytes, max_metadata_bytes = 2048, 8, 1024, 262144
    max_refs, max_ref_bytes = 64, 8388608
    nodes = [0]

    def fail(reason):
        raise ValueError("programme work packet: " + reason)

    def text(value, where):
        if type(value) is not str or not value or value != value.strip():
            fail(where + " must be a nonempty plain string")
        try:
            length = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            fail(where + " must be strict UTF-8")
        if length > max_text_bytes or any(ord(c) < 32 or ord(c) == 127 for c in value):
            fail(where + " exceeds its string bound or contains control characters")
        return value

    def copy_json(value, depth=0):
        nodes[0] += 1
        if nodes[0] > max_nodes or depth > max_depth:
            fail("metadata node/depth bound exceeded")
        kind = type(value)
        if kind is dict:
            if len(value) > max_nodes or any(type(key) is not str for key in value):
                fail("metadata requires plain string dictionary keys")
            return {copy_json(key, depth + 1): copy_json(item, depth + 1)
                    for key, item in value.items()}
        if kind is list:
            if len(value) > max_nodes:
                fail("metadata list bound exceeded")
            return [copy_json(item, depth + 1) for item in value]
        if kind is str:
            return text(value, "metadata string")
        if kind is int and -(2 ** 63) <= value < 2 ** 63:
            return value
        if value is None or kind is bool:
            return value
        fail("only exact finite JSON builtin values are supported")

    supplied = copy_json({
        "task_id": task_id, "parent_reference": parent_reference,
        "current_parent_reference": current_parent_reference,
        "authority_binding": authority_binding, "owner_sources": owner_sources,
        "evidence": evidence, "remaining_gates": remaining_gates,
    })

    def json_bound(value):
        body = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(body) > max_metadata_bytes:
            fail("serialized metadata byte bound exceeded")

    json_bound(supplied)

    def keys(value, wanted, where):
        if type(value) is not dict or set(value) != set(wanted):
            fail(where + " has unknown or missing fields")

    def digest(value, size, where):
        if type(value) is not str or len(value) != size or any(c not in "0123456789abcdef" for c in value):
            fail(where + " must be lowercase hexadecimal")

    def safe_path(value, where, *, relative=False, suffix=None):
        text(value, where)
        parts = value.split("/")
        components = parts[1:] if value.startswith("/") else parts
        if ((relative and value.startswith("/")) or not components
                or any(part in {"", ".", ".."} for part in components)
                or any(c in value for c in "\\:*?[]")
                or (suffix is not None and not value.endswith(suffix))):
            fail(where + " must be a safe explicit path")

    def reference(value, where, *, relative=False, suffix=None):
        keys(value, ("path", "bytes", "sha256"), where)
        safe_path(value["path"], where + ".path", relative=relative, suffix=suffix)
        if type(value["bytes"]) is not int or not 0 <= value["bytes"] <= max_ref_bytes:
            fail(where + ".bytes exceeds its descriptor bound")
        digest(value["sha256"], 64, where + ".sha256")

    selected = next((row for row in _PROGRAMME_WORK_PACKET_SPECS_V1
                     if supplied["task_id"] == row[0]), None)
    if selected is None:
        fail("unsupported fixed preparation task")
    selected_id, role, parent_id, role_gates = selected
    origin = supplied["parent_reference"]
    keys(origin, ("repository", "revision", "path", "task_id", "task_sha256"),
         "parent_reference")
    if (origin["repository"] != "ipfs_datasets_py"
            or origin["path"] != "ipfs_datasets_py/logic/autoformal/docs/BACKLOG.json"
            or origin["task_id"] != parent_id):
        fail("original parent identity differs")
    digest(origin["revision"], 40, "parent_reference.revision")
    digest(origin["task_sha256"], 64, "parent_reference.task_sha256")
    current = supplied["current_parent_reference"]
    keys(current, ("backlog", "task_id", "task_sha256"), "current_parent_reference")
    reference(current["backlog"], "current_parent_reference.backlog", suffix=".json")
    if current["task_id"] != parent_id:
        fail("current snapshot parent identity differs")
    digest(current["task_sha256"], 64, "current_parent_reference.task_sha256")
    authority = supplied["authority_binding"]
    keys(authority, ("kind", "namespace", "board", "plan", "source_control_revision"),
         "authority_binding")
    if authority["kind"] != "legacy_markdown" or authority["namespace"] != "legal-ir-autoencoder-v1":
        fail("selected authority differs")
    reference(authority["board"], "authority_binding.board", suffix=".md")
    reference(authority["plan"], "authority_binding.plan", suffix=".json")
    digest(authority["source_control_revision"], 64, "authority_binding.source_control_revision")

    for name, source in (("owner_sources", True), ("evidence", False)):
        values = supplied[name]
        if type(values) is not list or not 1 <= len(values) <= max_refs:
            fail(name + " requires a bounded nonempty descriptor list")
        paths = []
        for index, value in enumerate(values):
            reference(value, name + ":" + str(index), relative=source,
                      suffix=".py" if source else ".json")
            paths.append(value["path"])
        if len(set(paths)) != len(paths):
            fail(name + " paths must be unique")
    gates = supplied["remaining_gates"]
    allowed = _PROGRAMME_WORK_PACKET_GLOBAL_GATES_V1 + role_gates
    if (type(gates) is not list or not 2 <= len(gates) <= len(allowed)
            or any(type(gate) is not str or gate not in allowed for gate in gates)
            or len(set(gates)) != len(gates)
            or not {"original_owner_admission", "independent_acceptance"} <= set(gates)):
        fail("remaining_gates must retain exact supported unresolved admission gates")

    script = "scripts/ops/legal_ir/legal_ir_supervisor_contract.py"
    argv = [["python3", script, "--materialize-programme-preparation", selected_id],
            ["python3", script, "--check-task", selected_id]]
    env = "IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. "
    command = env + " ".join(argv[0]) + " && " + env + " ".join(argv[1])
    directory = "docs/implementation/reports/evidence/legal_ir_autoencoder/" + selected_id.lower()
    outputs = [directory + "/packet.json", directory + "/receipt.json"]
    result = {
        "schema": "programme-work-execution-packet/v1",
        **supplied, "role": role, "parent_task_id": parent_id,
        "execution_kind": "control_metadata_only", "metadata_complete": True,
        "readiness": "original_admission_required", "snapshot_binding_only": True,
        "validation_argv": argv, "validation_commands": [command],
        "outputs": outputs, "allowed_paths": list(outputs),
        "code_allowlist": [], "test_allowlist": [],
        "exclusive_keys": ["programme-preparation:" + selected_id],
        "budgets": {"wall_seconds": 300, "cpu_slots": 1, "memory_mb": 1024,
                    "storage_bytes": 16777216, "child_process_slots": 1,
                    "max_attempts": 1},
        "descriptor_hashes_verified": False, "current_parent_row_verified": False,
        "current_source_epoch_verified": False, "native_status_verified": False,
        "capability_verified": False, "independently_verified": False,
        "dispatch_authorized": False, "mutation_authorized": False,
        "native_admission": False, "model_execution_authorized": False,
        "training_authorized": False, "parent_semantic_admission": False,
        "task_completion_authority": False, "goal_completion_authority": False,
        "completion_authority": False, "admitted": False, "formalized": False,
        "semantic_review_verified": False,
        "supervision_masks": {"training": 0, "evaluation_gold": 0},
        "verification_limits": [
            "Descriptors and principals are supplied metadata, not authenticated file bytes or independence.",
            "Snapshot binding is not current native task state, capability, scope or resource admission.",
            "The original caller must verify fixed source/evidence paths, snapshot bytes and parent rows.",
            "Owner source snapshots are data references and are never imported or executed by this API.",
            "Later dispatch requires original admission; engineering completion admits no scientific parent.",
        ],
    }
    json_bound(result)
    return result

# Opt-in LIR-0101 documentary inventory. Existing 9001–9004 owners are unchanged.
ASSET_INVENTORY_0101_CRITERIA_V1 = (
    "Every selected asset has immutable identity, owner, task, producer and evidence scope.",
    "F15/F17/F18 registrations and the five-variant replay are reused; published or binding counts are not model/accuracy counts.",
    "Reuse historical 16-shard/62,931-row inventory, frozen source partitions and 103-file package; original 5016 release provenance survives current 91 manifest equality. Fresh package verification is separately evidenced, not inferred from metadata or a historical receipt.",
)
ASSET_INVENTORY_0101_EVIDENCE_V1 = frozenset((
    "registration_inventory", "checkpoint_survey", "embedding_survey", "component_plan",
    "component_audit", "replay_adoption", "replay_native_audit", "source_provenance",
    "source_verification", "source_native_audit", "asset_guide", "decoder_guide", "source_guide",
))
ASSET_INVENTORY_0101_DOCUMENTS_V1 = ASSET_INVENTORY_0101_EVIDENCE_V1 | frozenset((
    "current_snapshot", "candidate", "publication_cutoff", "attribution_review",
    "public_main_receipt", "publication_receipts", "accepted_dependencies",
))


def _asset_inventory_document_v1(frame: Any, *, markdown: bool = False) -> tuple[Any, dict]:
    """Check supplied exact metadata bytes and aliases, without filesystem access.

    The original source/durable-copy owner authenticates the physical files.
    A nested checkpoint/package path is documentary data and is never opened.
    """
    def need(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)
    need(type(frame) is dict and set(frame) == {"original_descriptor", "descriptor", "utf8"},
         "0101 metadata frame has unexpected fields")
    for name in ("original_descriptor", "descriptor"):
        pin = frame[name]
        need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}, "0101 descriptor required")
        need(type(pin["path"]) is str and Path(pin["path"]).is_absolute()
             and ".." not in Path(pin["path"]).parts, "0101 exact absolute descriptor path required")
        need(type(pin["bytes"]) is int and 0 < pin["bytes"] <= 4 * 1024**2,
             "0101 descriptor byte count must be a positive bounded integer")
        need(type(pin["sha256"]) is str and len(pin["sha256"]) == 64
             and all(c in "0123456789abcdef" for c in pin["sha256"]), "0101 SHA256 required")
    need(type(frame["utf8"]) is str, "0101 exact UTF8 metadata required")
    raw = frame["utf8"].encode("utf-8")
    for pin in (frame["original_descriptor"], frame["descriptor"]):
        need(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
             "0101 metadata bytes or durable alias differ")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "duplicate 0101 metadata key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("nonfinite 0101 metadata")
    value = frame["utf8"] if markdown else json.loads(frame["utf8"], object_pairs_hook=unique,
                                                       parse_constant=constant)
    need(markdown or type(value) is dict, "0101 metadata root must be an object")
    if not markdown:
        _handoff_reconciliation_bytes_v2(value)  # Also rejects overflowed JSON floats.
    return value, {k: dict(frame[k]) for k in ("original_descriptor", "descriptor")}


def prepare_current_asset_contribution_inventory_v1(
    *, documents: Mapping[str, Any], producer_principal: str, expected_task_revision: int,
) -> dict[str, Any]:
    """Adjudicate LIR-0101 documentary evidence only; never execute or admit work.

    All inputs are supplied metadata. The original signed-packet, source,
    resource, native evidence and CAS owners retain their separate authority.
    """
    def need(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)
    def same(a: Any, b: Any) -> bool:
        return _handoff_reconciliation_bytes_v2(a) == _handoff_reconciliation_bytes_v2(b)
    def text(value: Any) -> bool:
        return type(value) is str and 0 < len(value) <= 4096 and not any(ord(c) < 32 for c in value)
    def integer(value: Any, expected: int) -> bool:
        return type(value) is int and value == expected
    need(text(producer_principal), "0101 producer principal required")
    need(type(expected_task_revision) is int and expected_task_revision > 0, "0101 exact task revision required")
    need(type(documents) is dict and set(documents) == ASSET_INVENTORY_0101_DOCUMENTS_V1,
         "0101 requires exactly the declared twenty metadata documents")
    values, aliases = {}, {}
    for role, frame in documents.items():
        values[role], aliases[role] = _asset_inventory_document_v1(
            frame, markdown=role in {"asset_guide", "decoder_guide", "source_guide"})
    need(sum(pair["descriptor"]["bytes"] for pair in aliases.values()) <= 4 * 1024**2,
         "0101 metadata closure exceeds byte bound")
    candidate, cutoff, review, snapshot = (values[k] for k in
        ("candidate", "publication_cutoff", "attribution_review", "current_snapshot"))
    need(candidate.get("schema") == "legal-ir-0101-asset-and-contribution-inventory-candidate/v1"
         and candidate.get("candidate_only") is True, "0101 historical candidate schema differs")
    need(cutoff.get("schema") == "legal-ir-0101-selected-contribution-cutoff-addendum/v1"
         and review.get("schema") == "legal-ir-0101-candidate-criterion-gaps/v2", "0101 cutoff or corrected scope differs")
    for ref in (cutoff.get("candidate_inventory"), review.get("candidate")):
        need(same(ref, aliases["candidate"]["original_descriptor"]), "0101 candidate commitment differs")
    need(same(review.get("selected_contribution_cutoff_addendum"), aliases["publication_cutoff"]["original_descriptor"]),
         "0101 corrected scope cutoff differs")
    registry = candidate.get("evidence_registry")
    need(type(registry) is list and len(registry) == 13
         and {r.get("evidence_id") for r in registry if type(r) is dict} == ASSET_INVENTORY_0101_EVIDENCE_V1,
         "0101 exact evidence registry required")
    for row in registry:
        need(same(row.get("descriptor"), aliases[row["evidence_id"]]["original_descriptor"]),
             "0101 evidence registry commitment differs")
    need(same(cutoff.get("exact_public_main_ref_receipt"), aliases["public_main_receipt"]["original_descriptor"])
         and same(cutoff.get("publication_receipts"), aliases["publication_receipts"]["original_descriptor"]),
         "0101 selected publication receipt commitment differs")

    # Bind the real task and its accepted dependency; placeholder evidence text
    # in the old candidate is never substituted for the native completion receipt.
    need(snapshot.get("schema") == "ipfs_accelerate_py/agent-supervisor/intent-plan-projection@1",
         "0101 native observation schema differs")
    tasks = snapshot.get("tasks")
    need(type(tasks) is list and len(tasks) == 64, "0101 saved native task population differs")
    task_rows = [t for t in tasks if t.get("task_alias") == "LIR-0101"]
    dep_rows = [t for t in tasks if t.get("task_alias") == "LIR-9004"]
    need(len(task_rows) == len(dep_rows) == 1, "0101 task or dependency is not unique")
    task, dependency = task_rows[0], dep_rows[0]
    scope = candidate.get("task_scope", {})
    for key in ("task_alias", "task_cid", "goal_cid", "plan_cid"):
        need(text(task.get(key)) and same(task[key], scope.get(key)), "0101 immutable task scope differs")
    need(task["task_cid"] == "baguqeeraty5cz3vfxxx5hxcvvg4o6rivtl746eoq3remdluqc3o4gqnob2ua"
         and task["goal_cid"] == "baguqeerawdzrk72ymyossnu2qifinzljp6s6yqinfgpsfhxm4oehlf5iiizq"
         and task["plan_cid"] == "baguqeeraiddmy4khowkyv37gwstmexmmku3lecsjtnaekhpqnlwx4vuwrhza",
         "0101 original task identity differs")
    need(type(task.get("revision")) is int and task["revision"] == expected_task_revision
         and task.get("status") == "blocked", "0101 current task revision/status differs")
    criteria = task.get("acceptance")
    need(type(criteria) is list and len(criteria) == 3
         and all(integer(c.get("ordinal"), i) and c.get("criterion") == expected
                 for i, (c, expected) in enumerate(zip(criteria, ASSET_INVENTORY_0101_CRITERIA_V1))),
         "0101 original native criteria differ")
    body = task.get("body", {})
    objective = "Inventory main, relevant published branches/worktrees, retained model lineages and exact tasks/codecs; adopt the completed source inventory, frozen partitions and portable package under original release provenance before proposing another run."
    for authored in (body, body.get("authored_task", {})):
        need(same(authored.get("acceptance_criteria"), list(ASSET_INVENTORY_0101_CRITERIA_V1)),
             "0101 authored criteria differ")
        need(authored.get("objective") == objective and authored.get("completion") == "manual"
             and authored.get("requires_product_change_scope") is False,
             "0101 original documentary/manual task scope differs")
    output = "data/legal_ir_span_graph_lean_20261016/LIR-0101/asset-and-contribution-inventory.json"
    need(body.get("authored_task", {}).get("outputs") == [output], "0101 original authored output differs")
    binding = body.get("asset_inventory_0101_v1", {}).get("runtime_output_binding")
    need(type(binding) is dict and set(binding) == {"schema", "original_output", "cwd", "task_root", "outputs"}
         and binding["schema"] == "legal-ir-0101-runtime-output-binding/v1"
         and binding["original_output"] == output, "0101 explicit original-to-runtime output binding required")
    cwd = binding["cwd"]
    need(text(cwd) and str(Path(cwd)) == cwd and Path(cwd).is_absolute() and ".." not in Path(cwd).parts
         and cwd == body.get("constraints", {}).get("canonical_logic_root"), "0101 bound canonical cwd differs")
    task_root = binding["task_root"]
    need(text(task_root) and str(Path(task_root)) == task_root and Path(task_root).is_absolute()
         and ".." not in Path(task_root).parts and Path(task_root).name == "LIR-0101"
         and Path(task_root).is_relative_to(Path(cwd) / "workspace/test-logs"), "0101 task-owned workspace root differs")
    outputs = binding["outputs"]
    roles = ("report", "producer_freeze", "verification")
    need(type(outputs) is dict and set(outputs) == set(roles), "0101 exact runtime output roles required")
    suffixes = ("asset-and-contribution-inventory.json", "asset-and-contribution-inventory.freeze.json",
                "asset-and-contribution-inventory.verification.json")
    relative_outputs = []
    for role, basename in zip(roles, suffixes):
        path = outputs[role]
        need(text(path) and str(Path(path)) == path and Path(path).is_absolute() and ".." not in Path(path).parts
             and Path(path).is_relative_to(task_root)
             and Path(path).parent.name == "exports" and Path(path).name == basename,
             "0101 runtime output is outside the declared task metadata workspace")
        relative_outputs.append(str(Path(path).relative_to(cwd)))
    producer_attempt = Path(outputs["report"]).parent.parent
    verifier_attempt = Path(outputs["verification"]).parent.parent
    need(Path(outputs["report"]).parent == Path(outputs["producer_freeze"]).parent
         and producer_attempt != Path(task_root) and verifier_attempt != Path(task_root)
         and not producer_attempt.is_relative_to(verifier_attempt)
         and not verifier_attempt.is_relative_to(producer_attempt),
         "0101 producer and verifier must own distinct nonnested output attempts")
    need(body.get("owned_paths") == [str(Path(task_root).relative_to(cwd))]
         and [r.get("path") for r in task.get("outputs", [])] == relative_outputs,
         "0101 runtime outputs/owned paths differ from the current native projection")
    for i, row in enumerate(task["outputs"]):
        need(integer(row.get("ordinal"), i) and row.get("effect", {}).get("path") == relative_outputs[i],
             "0101 runtime output ordinal/effect differs")
    accepted = candidate.get("accepted_dependency", {})
    receipt = dependency.get("body", {}).get("completion_receipt", {})
    need(dependency.get("status") == "completed" and integer(dependency.get("revision"), 5)
         and dependency.get("task_cid") == accepted.get("task_cid")
         and receipt.get("task_cid") == dependency.get("task_cid")
         and receipt.get("operation") == accepted.get("completion_operation")
         == "independent_native_handoff_metadata_completion_v1"
         and receipt.get("evidence_digest") == accepted.get("completion_evidence_digest"),
         "0101 accepted 9004 completion differs")
    need(task.get("dependencies") == [{"dependency_task_cid": dependency["task_cid"], "kind": "depends_on"}],
         "0101 native dependency edge differs")
    accepted_dependencies = values["accepted_dependencies"]
    need(set(accepted_dependencies) == {"schema", "task_cid", "task_revision", "dependencies"}
         and accepted_dependencies["schema"] == "legal-ir-0101-native-accepted-dependencies/v1"
         and accepted_dependencies["task_cid"] == task["task_cid"]
         and integer(accepted_dependencies["task_revision"], expected_task_revision),
         "0101 accepted dependency export task/revision differs")
    accepted_rows = accepted_dependencies["dependencies"]
    need(type(accepted_rows) is list and len(accepted_rows) == 1 and type(accepted_rows[0]) is dict
         and set(accepted_rows[0]) == {"task_cid", "revision", "status", "authority_spec_cid", "completion_receipt_cid"},
         "0101 exact original accepted dependency row required")
    accepted_row = accepted_rows[0]
    need(accepted_row["task_cid"] == dependency["task_cid"] and integer(accepted_row["revision"], 5)
         and accepted_row["status"] == "completed", "0101 accepted dependency current revision differs")
    for field in ("authority_spec_cid", "completion_receipt_cid"):
        cid = accepted_row[field]
        need(type(cid) is str and 32 <= len(cid) <= 256 and cid.startswith("b")
             and all(c in "abcdefghijklmnopqrstuvwxyz234567" for c in cid),
             "0101 actual accepted dependency CID is missing or malformed")
    need(accepted_row["completion_receipt_cid"] != receipt.get("evidence_digest"),
         "0101 evidence digest cannot substitute for actual accepted completion receipt CID")

    # Resolve only declared metadata JSON pointers. Never dereference a payload
    # path, historical Git locator, model release, or package descriptor.
    pointer_count = 0
    def pointer(ref: Any) -> Any:
        nonlocal pointer_count
        need(type(ref) is dict and set(ref) == {"evidence_id", "json_pointer"}
             and ref["evidence_id"] in ASSET_INVENTORY_0101_EVIDENCE_V1
             and type(ref["json_pointer"]) is str, "0101 documentary reference differs")
        value, path = values[ref["evidence_id"]], ref["json_pointer"]
        need(path == "" or path.startswith("/"), "0101 JSON pointer must be exact")
        for component in path.split("/")[1:]:
            for i, char in enumerate(component):
                need(char != "~" or (i + 1 < len(component) and component[i+1] in "01"),
                     "0101 invalid JSON pointer escape")
            component = component.replace("~1", "/").replace("~0", "~")
            if type(value) is list:
                need(component and all(c in "0123456789" for c in component)
                     and (component == "0" or not component.startswith("0"))
                     and int(component) < len(value), "0101 JSON pointer array bound differs")
                value = value[int(component)]
            else:
                need(type(value) is dict and component in value, "0101 documentary pointer is absent")
                value = value[component]
        pointer_count += 1
        return value
    def inspect_refs(value: Any) -> None:
        if type(value) is dict:
            if "evidence_id" in value and "json_pointer" in value:
                pointer(value)
            else:
                for child in value.values():
                    inspect_refs(child)
        elif type(value) is list:
            for child in value:
                inspect_refs(child)
    inspect_refs(candidate)
    candidate_pointer_count = pointer_count
    assets, registered = candidate.get("assets"), values["registration_inventory"].get("selected_assets")
    need(type(assets) is list and len(assets) == 19 and integer(candidate.get("selected_asset_count"), 19)
         and type(registered) is list and len(registered) == 19, "0101 selected asset population differs")
    need(len({a.get("inventory_key") for a in assets}) == 19
         and len({a.get("inventory_key") for a in registered}) == 19, "0101 duplicate selected asset")
    checkpoint_rows = values["checkpoint_survey"].get("selected_assets")
    need(type(checkpoint_rows) is list and len(checkpoint_rows) == 16, "0101 checkpoint survey scope differs")
    for i, (asset, recorded) in enumerate(zip(assets, registered)):
        identity, owner, producer = (asset.get(k, {}) for k in ("immutable_identity", "owner", "producer"))
        need(asset.get("inventory_key") == recorded.get("inventory_key") and text(asset.get("task"))
             and asset["task"] == recorded.get("task") == producer.get("reported_task"), "0101 asset task/key join differs")
        for field, original in (("path_reported", "path"), ("recorded_bytes", "recorded_bytes"),
                                ("recorded_sha256", "recorded_sha256")):
            need(same(identity.get(field), recorded.get(original)), "0101 asset immutable documentary identity differs")
        need(type(identity.get("recorded_bytes")) is int and identity["recorded_bytes"] > 0
             and type(identity.get("recorded_sha256")) is str and len(identity["recorded_sha256"]) == 64,
             "0101 asset recorded size/hash required")
        need(identity.get("payload_bytes_authenticated_by_candidate") is False
             and producer.get("execution_authenticated_by_candidate") is False
             and asset.get("criterion1_satisfied_by_candidate") is False,
             "0101 historical candidate authority was rewritten")
        need(owner.get("repository") == "ipfs_datasets_py"
             and same(owner.get("inventory_metadata_owner"), {"evidence_id": "asset_guide", "json_pointer": ""})
             and text(asset.get("evidence_scope")), "0101 documentary owner/evidence scope is absent")
        expected_ref = {"evidence_id": "registration_inventory", "json_pointer": f"/selected_assets/{i}"}
        need(expected_ref in asset.get("evidence_refs", []), "0101 selected registration reference differs")
        provenance = producer.get("metadata_provenance")
        need(type(provenance) is list and len(provenance) > 0, "0101 immutable producer/source provenance required")
        if i < 16:
            original = checkpoint_rows[i]
            need(asset["inventory_key"] == original.get("inventory_key")
                 and asset["task"] == original.get("task")
                 and identity["path_reported"] == original.get("path")
                 and same(identity["recorded_bytes"], original.get("recorded_bytes"))
                 and identity["recorded_sha256"] == original.get("recorded_checkpoint_sha256"),
                 "0101 checkpoint survey identity differs")
            need({"evidence_id": "checkpoint_survey", "json_pointer": f"/selected_assets/{i}"}
                 in asset.get("evidence_refs", []), "0101 checkpoint attribution reference differs")
            if i < 13:
                need(same(provenance, original.get("metadata_provenance")),
                     "0101 immutable producer metadata differs from retained survey")
            else:
                expected_provenance = {"evidence_id": "component_plan",
                    "json_pointer": f"/models/{i-13}/model_metadata/huggingface_config/metadata_provenance"}
                need(same(provenance, [expected_provenance]), "0101 component producer pointer differs")
                producer_metadata = pointer(expected_provenance)
                need(type(producer_metadata) is dict and bool(producer_metadata),
                     "0101 component producer metadata is absent")
        else:
            expected_provenance = {"evidence_id": "embedding_survey", "json_pointer": f"/highest_value_reuse/{i-11}"}
            need(same(provenance, [expected_provenance]) and expected_provenance in asset.get("evidence_refs", []),
                 "0101 embedding producer reference differs")
            pointer(expected_provenance)
    coverage = review.get("static_documentary_attribution_review", {})
    need(integer(coverage.get("selected_assets"), 19)
         and integer(coverage.get("demonstrated_missing_task_required_attribution_asset_count"), 0)
         and coverage.get("demonstrated_missing_task_required_attribution_fields") == [],
         "0101 corrected documentary attribution review differs")
    need(all(integer(count, 19) for count in coverage.get("field_coverage", {}).values())
         and len(coverage.get("field_coverage", {})) == 5,
         "0101 documentary field coverage differs")
    optional = review.get("optional_or_presentation_limitations", {})
    need(optional.get("historical_PID_or_DID_recovery_required") is False
         and optional.get("complete_numerical_runtime_closure_or_payload_authentication_required_for_this_metadata_inventory") is False,
         "0101 optional historical execution attribution was made mandatory")

    adoption, audit = candidate.get("F15_F17_F18_adoption", {}), values["component_audit"]
    population, imported = audit.get("population", {}), audit.get("import", {})
    ids = adoption.get("source_record_ids")
    need(type(ids) is list and len(ids) == len(set(ids)) == 3
         and set(ids) == set(population.get("exact_added_source_record_ids", [])), "0101 three registered source IDs differ")
    need(audit.get("status") == "pass" and integer(population.get("before_count"), 684)
         and integer(population.get("after_count"), 687) and integer(population.get("baseline_unique_ids"), 684)
         and integer(population.get("baseline_records_changed"), 0) and integer(population.get("baseline_ids_removed"), 0)
         and population.get("all_33_stored_fields_equal_for_each_of_684_baseline_records") is True
         and integer(imported.get("registered_count"), 3) and integer(imported.get("persisted_metadata_matched_count"), 3)
         and imported.get("all_outcomes_registered_verified") is True, "0101 registration/baseline preservation differs")
    components = audit.get("catalog", {}).get("components", [])
    need(len(components) == 3 and {c.get("label") for c in components} == {"F15", "F17", "F18"}
         and {c.get("source_record_id") for c in components} == set(ids)
         and all(c.get("dimension_role") == "source_tokens" and c.get("latent_conditioning_enabled") is False
                 and c.get("runtime_ready") is False and c.get("teacher_qualified") is False for c in components)
         and adoption.get("source_tokens_only") is True and adoption.get("latent_conditioning_enabled") is False
         and adoption.get("active384D_lane_inferred") is False
         and adoption.get("native_runtime_or_teacher_qualified") is False, "0101 source-token components gained runtime/latent authority")
    models = values["component_plan"].get("models")
    need(type(models) is list and len(models) == 3, "0101 retained component plan differs")
    planned_ids = set()
    for model in models:
        component_binding = model.get("model_metadata", {}).get("huggingface_config", {}).get("ir_checkpoint", {})
        matching = [component for component in components if component.get("source_record_id") == component_binding.get("record_id")]
        need(len(matching) == 1 and component_binding.get("record_id") not in planned_ids
             and component_binding.get("dimension_role") == "source_tokens" and component_binding.get("latent_conditioning_enabled") is False
             and same(model.get("checkpoint_pin", {}).get("bytes"), matching[0].get("checkpoint_bytes"))
             and model.get("checkpoint_pin", {}).get("sha256") == matching[0].get("checkpoint_sha256"),
             "0101 retained component plan/registration join differs")
        planned_ids.add(component_binding["record_id"])
    aliases_replay = {"original768_initialization": "original_768_initialization",
                      "aligned768_initialization": "aligned_768_initialization"}
    replay = candidate.get("five_variant_replay_adoption", {})
    retained_results = values["replay_adoption"].get("attributed_completed_results", {})
    expected_variants = {"original_donors", "original_768_initialization", "aligned_768_initialization",
                         "original_start_trained_interfaces", "aligned_start_trained_interfaces"}
    variants = replay.get("variants")
    need(type(variants) is list and len(variants) == 5
         and {aliases_replay.get(v, v) for v in variants} == expected_variants
         and same(replay.get("attributed_results"), retained_results)
         and set(retained_results.get("correct_source_primary_exact_stored_reference_by_variant", {})) == expected_variants,
         "0101 five-variant retained replay join differs")
    need(replay.get("published_or_binding_counts_are_accuracy") is False and replay.get("replay_reexecuted") is False
         and retained_results.get("statutory_gold_or_holdout_claimed") is False
         and retained_results.get("primary_references_exposed") is True
         and values["replay_native_audit"].get("status") == "PASS", "0101 replay acquired a new accuracy or holdout claim")
    need(all(integer(retained_results.get(field), count) for field, count in (
        ("first_pass_sequences", 60), ("first_pass_eos_complete", 60), ("first_pass_native_grammar_valid", 60),
        ("fresh_load_sequences", 60), ("forward_steps", 3240), ("native_tests", 173)))
         and all(type(result) is dict and integer(result.get("matched"), 0) and integer(result.get("selected"), 2)
                 for result in retained_results["correct_source_primary_exact_stored_reference_by_variant"].values()),
         "0101 retained replay accounting was relabelled")

    source, verification, native = (values[k] for k in ("source_provenance", "source_verification", "source_native_audit"))
    commitments = candidate.get("source_adoption", {}).get("retained_commitments", {})
    manifest, summary, package, retained = (source.get("manifest_equivalence", {}), verification.get("inventory_summary", {}),
                                           verification.get("package", {}), native.get("retained_source", {}))
    need(manifest.get("original_release_commit") == commitments.get("release") == "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
         and manifest.get("current_observed_release_commit") == commitments.get("selected_manifest_revision")
         == "91ca1838853ac82d7a12dd4ab47d9686f47667f9"
         and manifest.get("manifest_sha256") == commitments.get("selected_manifest_sha256")
         and manifest.get("current_metadata_snapshot_equals_original_manifest_bytes") is True,
         "0101 original release versus selected manifest provenance differs")
    need(verification.get("status") == "pass" and verification.get("all_checks_complete") is True
         and integer(summary.get("declared_corpus_shards"), 16) and integer(summary.get("rows_scanned"), 62931)
         and integer(summary.get("declared_row_count"), 62931) and summary.get("complete") is True
         and summary.get("inventory_sha256") == commitments.get("inventory_sha256") == verification.get("inventory", {}).get("sha256")
         and verification.get("partitions", {}).get("sha256") == commitments.get("partitions_sha256")
         and integer(package.get("expected_file_count"), 103) and integer(package.get("verified_file_count"), 103)
         and integer(package.get("expected_total_bytes"), 263671066) and integer(package.get("verified_total_bytes"), 263671066)
         and package.get("manifest", {}).get("sha256") == commitments.get("package_manifest_sha256")
         and package.get("row_digest") == commitments.get("ordered_row_digest"), "0101 retained inventory/partition/package commitments differ")
    need(native.get("audit_status") == "pass" and native.get("qualification_passed") is True
         and native.get("six_named_artifact_checks_passed") is True
         and same(native.get("worker_report"), {k: aliases["source_verification"]["original_descriptor"][k] for k in ("bytes", "sha256")})
         and retained.get("original_repository_revision") == commitments["release"]
         and integer(retained.get("physical_rows"), 62931) and integer(retained.get("declared_corpus_shards"), 16)
         and integer(retained.get("verified_package_files"), 103)
         and retained.get("ordered_row_digest") == commitments["ordered_row_digest"],
         "0101 separate original package verification evidence differs")
    closeout, custody = native.get("native_closeout", {}), native.get("source_custody", {})
    need(closeout.get("completed") is True and closeout.get("artifacts_durable_asserted") is True
         and closeout.get("native_lease_released") is True and closeout.get("reservation_status") == "released"
         and integer(closeout.get("returncode"), 0) and closeout.get("cleanup_error") is None
         and custody.get("all_current_hashes_match_frozen_request") is True
         and custody.get("input_and_package_custody_fences_passed") is True
         and custody.get("public_copied_exports_equal_native_original_bytes") is True,
         "0101 actual separate package verification custody is not closed")
    source_adoption = candidate.get("source_adoption", {})
    need(source_adoption.get("fresh_package_bytes_revalidated_by_candidate") is False
         and source_adoption.get("source_meaning_or_training_gold_admitted") is False
         and source_adoption.get("whole_release_equivalence_inferred_from_selected_manifest") is False
         and commitments.get("payloads_rehashed_by_this_proposal") is False
         and summary.get("source_authority_authenticated") is False and summary.get("training_eligible") is False,
         "0101 historical source verification scope was broadened")

    mains = values["public_main_receipt"]
    need(mains.get("schema") == "legal-ir-selected-public-main-refs/v1"
         and mains.get("observed_at_utc") == cutoff.get("selected_verified_public_cutoff_observed_at_utc"),
         "0101 selected publication cutoff timestamp differs")
    observed_mains = {}
    for row in mains.get("results", []):
        result = json.loads(row.get("result", {}).get("content", "null"))
        need(type(result) is dict and result.get("ref") == "refs/heads/main"
             and result.get("object", {}).get("type") == "commit"
             and row.get("repository") not in observed_mains, "0101 selected public-main receipt differs")
        observed_mains[row["repository"]] = result["object"]["sha"]
    selected_mains = cutoff.get("selected_public_main", [])
    need(len(selected_mains) == 2 and len(observed_mains) == 2
         and {r.get("repository"): r.get("commit") for r in selected_mains} == observed_mains,
         "0101 selected public-main join differs")
    receipts = values["publication_receipts"].get("receipts")
    need(type(receipts) is list, "0101 publication receipts required")
    for selected in cutoff.get("selected_public_contributions", []):
        matched = [p for p in receipts if p.get("head_repo_full_name") == selected.get("repository")
                   and same(p.get("number"), selected.get("pr"))]
        need(len(matched) == 1 and selected.get("merged") is True and matched[0].get("merged") is True
             and matched[0].get("head_sha") == selected.get("head_sha")
             and matched[0].get("merge_commit_sha") == selected.get("merge_commit_sha"),
             "0101 selected merged contribution differs")
    unmerged = cutoff.get("unmerged_selected_A_contribution", {})
    matched = [p for p in receipts if p.get("head_repo_full_name") == unmerged.get("repository")
               and same(p.get("number"), unmerged.get("pr"))]
    need(len(matched) == 1 and unmerged.get("merged") is False and matched[0].get("merged") is False
         and unmerged.get("head_sha") == matched[0].get("head_sha")
         and unmerged.get("runtime_activation_inferred") is False, "0101 unmerged contribution was promoted to main/runtime")
    for flag in ("broader_branch_coverage_claimed", "scientific_or_legal_acceptance_claimed",
                 "new_model_or_checkpoint_claimed", "task_completion_claimed"):
        need(cutoff.get(flag) is False, "0101 selected cutoff acquired broader authority")
    authority = candidate.get("authority", {})
    need(authority.get("supervision_masks") == {"evaluation_gold": 0, "training": 0}
         and all(type(v) is int for v in authority["supervision_masks"].values())
         and all(value is False for key, value in authority.items() if key != "supervision_masks"),
         "0101 candidate acquired semantic/native/model authority")
    widths = candidate.get("four_width_roles")
    need(type(widths) is list and len(widths) == 4
         and all(type(row.get("width")) is int for row in widths)
         and {row["width"] for row in widths} == {8, 384, 768, 4096}, "0101 width roles differ")
    leanstral = next(row for row in widths if row["width"] == 4096)
    need(leanstral.get("selected_keys") == [] and leanstral.get("new_asset_fabricated") is False
         and leanstral.get("attribution_status") == "not_covered_by_selected_retained_evidence",
         "0101 4096D coverage was fabricated from other widths")
    frames_commitment = hashlib.sha256(_handoff_reconciliation_bytes_v2(documents)).hexdigest()
    report = {
        "schema": "legal-ir-current-asset-contribution-inventory/v1",
        "checked_scope": "LIR-0101_documentary_asset_and_selected_contribution_inventory_only",
        "producer_principal": producer_principal,
        "task_scope": {k: task[k] for k in ("task_alias", "task_cid", "goal_cid", "plan_cid", "revision", "status")},
        "original_output": output, "runtime_output_binding": binding,
        "input_commitment_sha256": frames_commitment,
        "metadata_document_aliases": aliases, "metadata_documents": 20,
        "documentary_references_resolved": candidate_pointer_count,
        "evidence_registry_documents_verified": 13,
        "selected_asset_count": 19, "assets": assets,
        "historical_candidate_assessment": candidate["criterion_assessment"],
        "documentary_attribution_adjudication": {
            "selected_assets_with_required_documentary_fields_verified": 19, "historical_PID_or_DID_recovery_required": False,
            "candidate_draft_false_flags_preserved": True,
            "reason": "Recorded owner and immutable producer/source provenance satisfy the documentary inventory criterion; original execution, codec and payload authentication remain unclaimed.",
        },
        "accepted_dependency": {"task_alias": "LIR-9004", "task_cid": dependency["task_cid"],
            "revision": dependency["revision"], "status": dependency["status"],
            "completion_receipt_cid": accepted_row["completion_receipt_cid"],
            "authority_spec_cid": accepted_row["authority_spec_cid"],
            "completion_receipt_sha256": hashlib.sha256(_handoff_reconciliation_bytes_v2(receipt)).hexdigest()},
        "F15_F17_F18_adoption": adoption,
        "five_variant_replay_adoption": {**replay, "canonical_variants": sorted(expected_variants),
                                         "documented_variant_aliases": aliases_replay},
        "source_adoption": source_adoption,
        "source_package_verification": {"separate_native_audit_joined": True,
            "original_verification_descriptor": aliases["source_verification"]["original_descriptor"],
            "original_native_audit_descriptor": aliases["source_native_audit"]["original_descriptor"],
            "payloads_revalidated_by_this_operation": False},
        "source_and_publication_cutoff": cutoff,
        "four_width_roles": candidate.get("four_width_roles"),
        "criterion_assessment": [{"ordinal": i, "criterion": criterion,
            "status": "satisfied_for_documentary_inventory_scope"}
            for i, criterion in enumerate(ASSET_INVENTORY_0101_CRITERIA_V1)],
        "documentary_inventory_criteria_satisfied": True,
        "authority": {"native_admission": False, "task_completion_authority": False,
            "dispatch_authorized": False, "training_authorized": False, "model_runtime_admitted": False,
            "teacher_qualified": False, "semantic_review_verified": False, "formalized": False,
            "Lean_admitted": False, "supervision_masks": {"evaluation_gold": 0, "training": 0}},
        "operations": {"payloads_read": 0, "models_run": 0, "replays_run": 0,
            "provider_calls": 0, "native_status_writes": 0},
    }
    # Return a detached finite JSON tree; callers cannot mutate input frames
    # through a shared nested object in the report.
    return json.loads(_handoff_reconciliation_bytes_v2(report))


def verify_current_asset_contribution_inventory_v1(
    report: Mapping[str, Any], *, producer_freeze: Mapping[str, Any], verifier_principal: str,
    documents: Mapping[str, Any], producer_principal: str, expected_task_revision: int,
) -> dict[str, Any]:
    """Reconstruct all three original criteria from independently supplied metadata."""
    if (type(verifier_principal) is not str or not 0 < len(verifier_principal) <= 4096
            or any(ord(c) < 32 for c in verifier_principal) or verifier_principal == producer_principal):
        raise ValueError("0101 distinct verifier principal required")
    expected = prepare_current_asset_contribution_inventory_v1(documents=documents,
        producer_principal=producer_principal, expected_task_revision=expected_task_revision)
    raw = _handoff_reconciliation_bytes_v2(report)
    expected_freeze = {"schema": "legal-ir-0101-inventory-producer-freeze/v1",
        "report_sha256": hashlib.sha256(raw).hexdigest(), "report_bytes": len(raw),
        "producer_principal": producer_principal, "frozen_before_verification": True}
    if (_handoff_reconciliation_bytes_v2(producer_freeze) != _handoff_reconciliation_bytes_v2(expected_freeze)
            or raw != _handoff_reconciliation_bytes_v2(expected)):
        raise ValueError("0101 report, producer freeze or independent input commitment differs")
    return {"schema": "legal-ir-current-asset-contribution-inventory-verification/v1",
        "valid": True, "checked_scope": expected["checked_scope"], "verifier_principal": verifier_principal,
        "producer_principal": producer_principal, "task_scope": expected["task_scope"],
        "report_sha256": hashlib.sha256(raw).hexdigest(), "report_bytes": len(raw),
        "input_commitment_sha256": expected["input_commitment_sha256"],
        "original_criteria_verified": 3, "selected_assets_verified": 19,
        "native_admission": False, "completion_authority": False, "semantic_admission": False,
        "training_authorized": False, "supervision_masks": {"evaluation_gold": 0, "training": 0}}

