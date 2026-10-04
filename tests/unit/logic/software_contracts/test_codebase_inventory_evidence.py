"""Pure receiving protocol and controlled lifecycle checks, not native qualification.

The native fixture separately exercises real owners/admission/CAS and workers.
These tests intentionally replace ownership and costly runtime boundaries.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_inventory_evidence as join
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_scan as scanner
from ipfs_datasets_py.logic.software_contracts import codebase_verification as verifier
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import SnapshotEntry
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseUnit
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import (
    CodebaseVerificationProjection, PROJECTION_SCHEMA,
)
from ipfs_datasets_py.duckdb_control.codebase_verification_queries import (
    CodebaseVerificationSelector as Selector, CodebaseVerificationQueryCursor as Cursor,
    CodebaseVerificationQueryEntry as Entry, CodebaseVerificationQueryPage as Page,
)
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec


def cid(name):
    return cid_for_structured({"pure_protocol": name})


def fixture():
    raw = b"def step(n: int) -> int:\n    return n + 1\n"
    snapshot = cid("snapshot")
    head = CodebaseHead("pure-owner", 1, cid("manifest"), snapshot,
        "rev:pure-owner:snapshot:" + snapshot, cid("receipt"))
    entry = SnapshotEntry("unit.py", "source", len(raw), cid_for_bytes(raw))
    unit = CodebaseUnit(entry.source_key, entry.entry_cid, cid("ast"), "ok")
    row = {"path": entry.path, "source_key": entry.source_key, "raw_path_hex": entry.raw_path_hex,
        "source_size_bytes": entry.size_bytes, "source_sha256": hashlib.sha256(raw).hexdigest(),
        "captured_source_available": True, "entry_cid": entry.entry_cid, "source_cid": entry.source_cid,
        "ast_cid": unit.ast_cid, "parse_status": unit.parse_status, "disposition": "deferred_budget",
        "frontiers": [{"reason": "explicit_inferred_row_budget"}], "cohort_membership": "not_in_registered_cohort",
        "authored_contracts_origin": "none_declared", "target_sha256": "2" * 64,
        "source_digest": "3" * 64, "coverage": [], "shard_index": None, "inference": None}
    ordered = [{"source_key": entry.source_key, "entry_cid": entry.entry_cid}]
    model = {"version_id": "sha256:" + "1" * 64, "variant_id": "pure-variant",
        "artifact": {"bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()},
        "artifact_cid": cid_for_bytes(b"x"), "contract_sha256": "4" * 64,
        "state_sha256": "5" * 64, "feature_space_sha256": "6" * 64,
        "runtime_version": join.training.runtimes.CODEBASE_SOURCE_FEATURE_VERSION,
        "optimized": True, "basis_policy": "unchanged_registered_vocabulary", "dtype": "float64", "device": "cpu"}
    scan = {"schema": scanner.SCHEMA, "profile": scanner.PROFILE, "codec": join.CODEC,
        "head": head.to_dict(), "model": model, "membership": {"cid": cid_for_structured(ordered), "ordered": ordered},
        "entries": [row], "shards": [], "worker_receipt": None, "counters": {}, "timings": {},
        "limits": scanner.CodebaseInventoryScanLimits().to_dict(), "implementation": {}, "authority": dict(scanner._FALSE)}
    contract = ContractSpec("contract:step", "step", ("n >= 0",), ("result >= 1",)).to_dict()
    binding = {"head": head.to_dict(), "path": entry.path, "entry": entry.to_dict(), "ast_cid": unit.ast_cid,
        "content_sha256": row["source_sha256"], "source_revision": "snapshot:" + head.snapshot_cid}
    return head, entry, unit, raw, scan, contract, binding


def projection(number=0):
    head, entry, unit, raw, scan, requested, binding = fixture()
    parent = {"schema": verifier.CODEBASE_VERIFICATION_SCHEMA, "source_binding": binding,
        "authority": dict(verifier._AUTHORITY), "requested_contracts": [requested], "salt": number,
        "pipeline_result": {"status": "success", "obligation_results": [{
            "vc_obligation": {"parent_contract_id": requested["contract_id"]}, "verdict_classification": "agree_proved"}]}}
    parent_record = verifier.CodebaseVerificationRecord(cid_for_structured(parent), join._wire(parent))
    contract = {"contract_id": requested["contract_id"], "requested_contract": requested,
        "contract_cid": cid_for_structured(requested), "lowered_contract_cid": cid("lowered"),
        "domain_id": None, "domain_cid": None, "canonical_keys": [], "applicability_keys": []}
    deps = {"head_cid": cid_for_structured(head.to_dict()), "manifest_cid": head.manifest_cid,
        "snapshot_cid": head.snapshot_cid, "ast_revision_id": head.ast_revision_id,
        "source_cid": entry.source_cid, "ast_cid": unit.ast_cid, "content_sha256": binding["content_sha256"],
        "source_revision": binding["source_revision"], "verification_cid": parent_record.artifact_cid}
    body = {"schema": PROJECTION_SCHEMA, "head": head.to_dict(), "path": entry.path,
        "source_binding": binding, "verification_cid": parent_record.artifact_cid,
        "applicability_cid": None, "contracts": [contract], "dependencies": deps,
        "authority": {"historical_conditional_evidence": True, **join._EVIDENCE_FALSE}}
    record = CodebaseVerificationProjection(cid_for_structured(body), join._wire(body), parent_record)
    identity = cid_for_structured({"projection_cid": record.projection_cid, "contract_id": requested["contract_id"]})
    return Entry(identity, requested["contract_id"], record)


def applicable_projection(classes):
    from ipfs_datasets_py.logic.software_contracts import codebase_applicability as app
    native = projection()
    value = native.projection.to_dict()
    contract = value["contracts"][0]
    contract["domain_id"], contract["domain_cid"] = "domain:pure", cid("domain")
    binding = {"parent_contract_id": contract["contract_id"], "contract_cid": contract["lowered_contract_cid"],
        "function_name": contract["requested_contract"]["function_name"],
        "domain_id": contract["domain_id"], "domain_cid": contract["domain_cid"]}
    summary = app._summaries([{**binding, "differential": {"classification": item}} for item in classes])[0]
    payload = {"schema": app.CODEBASE_APPLICABILITY_SCHEMA, "verification_cid": value["verification_cid"],
        "source_binding": value["source_binding"], "authority": dict(app._AUTHORITY),
        "status": "not_established", "contract_results": [summary]}
    artifact = app.CodebaseApplicabilityRecord(cid_for_structured(payload), join._wire(payload))
    value["applicability_cid"] = artifact.artifact_cid
    projected = CodebaseVerificationProjection(cid_for_structured(value), join._wire(value), native.projection.verification, artifact)
    identity = cid_for_structured({"projection_cid": projected.projection_cid, "contract_id": contract["contract_id"]})
    return Entry(identity, contract["contract_id"], projected)


def page(entries=(), *, complete=True, cursor=None, epoch=1, inventory=None, selector=None):
    head = fixture()[0]
    selected = Selector() if selector is None else selector
    inventory = cid("evidence-inventory") if inventory is None else inventory
    entries = tuple(sorted(entries, key=lambda row: row.entry_id))
    continuation = None if complete else Cursor(cid_for_structured(head.to_dict()), inventory, epoch, selected.cid, entries[-1].entry_id)
    return Page(selected, head, inventory, epoch, entries, continuation, start_cursor=cursor)


def implementation():
    return {"files": {}, "sha256": join.training.features.digest({}),
            "scope": "listed_local_files_only_not_execution_attestation"}


def body(pages=None):
    head, _, _, _, scan, _, _ = fixture()
    pages = [page()] if pages is None else pages
    evidence = []
    rows = {row["source_key"]: row for row in scan["entries"]}
    for item in pages:
        evidence.extend(join._summary(entry, head, item.selector, rows) for entry in item.entries)
    last = pages[-1]
    return {"schema": join.SCHEMA, "profile": join.PROFILE, "codec": join.CODEC,
        "head": head.to_dict(), "head_cid": cid_for_structured(head.to_dict()),
        "scan": {"artifact_cid": cid_for_bytes(join._wire(scan)), "record": scan},
        "selector": last.selector.to_dict(), "query": {"selector_cid": last.selector.cid,
            "inventory_cid": last.inventory_cid, "epoch": last.epoch,
            "pages": [{"page_size": max(1, len(p.entries)), "page": p.to_dict()} for p in pages],
            "complete": last.complete, "next_cursor": None if last.next_cursor is None else last.next_cursor.to_dict(),
            "closing_page_cid": page(last.entries[:1], epoch=last.epoch, inventory=last.inventory_cid).page_cid},
        "evidence": evidence, "entries": join._ledger(scan["entries"], evidence, last.complete),
        "limits": join.CodebaseInventoryEvidenceLimits().to_dict(), "implementation": implementation(),
        "authority": dict(join._FALSE)}


def record(value):
    raw = join._wire(value)
    return join.CodebaseInventoryEvidenceRecord(cid_for_bytes(raw), raw)


def rehash_scan(value):
    value["scan"]["artifact_cid"] = cid_for_bytes(join._wire(value["scan"]["record"]))


def rehash_page(value, number=0):
    item = value["query"]["pages"][number]["page"]
    item["page_cid"] = cid_for_structured({k: v for k, v in item.items() if k != "page_cid"})


@pytest.mark.parametrize("name", tuple(join.CodebaseInventoryEvidenceLimits.__dataclass_fields__))
@pytest.mark.parametrize("value", [0, -1, True, 1.0])
def test_limits_require_positive_exact_integers(name, value):
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="integer"):
        replace(join.CodebaseInventoryEvidenceLimits(), **{name: value})


@pytest.mark.parametrize("name", tuple(join.CodebaseInventoryEvidenceLimits.__dataclass_fields__))
def test_limits_do_not_widen_receiving_profile(name):
    limits = join.CodebaseInventoryEvidenceLimits()
    with pytest.raises(join.CodebaseInventoryEvidenceError):
        replace(limits, **{name: (64 if name == "page_size" else getattr(limits, name)) + 1})


@pytest.mark.parametrize("name", tuple(join._FALSE))
@pytest.mark.parametrize("flag", [0, 1, True, "false", None])
def test_rehashed_authority_aliases_remain_refused(name, flag):
    value = body()
    value["authority"][name] = flag
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="False"):
        record(value)


def test_complete_empty_query_has_explicit_scoped_absence():
    observed = record(body())
    refs = observed.advisory_refs()
    assert refs["coverage"] == {"inventory_entries": 1, "inferred_rows": 0,
        "evidence_entries": 0, "evidence_matched_members": 0,
        "evidence_complete_absent_members": 1, "evidence_unknown_members": 0}
    assert refs["entry_evidence"][0]["evidence_disposition"] == "no_exact_indexed_conditional_evidence"
    assert all(value is False for value in refs["authority"].values())
    refs["model"]["version_id"] = "changed"
    refs["entry_evidence"].clear()
    assert observed.advisory_refs()["coverage"]["inventory_entries"] == 1
    assert observed.advisory_refs()["model"]["version_id"] != "changed"


def test_deferred_structural_member_can_have_exact_conditional_evidence():
    observed = record(body([page([projection()])]))
    value = observed.to_dict()
    assert value["scan"]["record"]["entries"][0]["disposition"] == "deferred_budget"
    assert value["entries"][0]["evidence_disposition"] == "matched_complete"
    assert value["evidence"][0]["verification_status"] == "recorded_conditional_proved"
    assert not value["authority"]["proof_authority"]


@pytest.mark.parametrize("classes,status", [
    (["agree_satisfiable", "agree_unsatisfiable", "agree_proved", "agree_proved"], "empty_domain"),
    (["agree_unsatisfiable", "agree_satisfiable", "agree_proved", "agree_proved"], "inconsistent_premises"),
    (["agree_satisfiable", "agree_satisfiable", "agree_disproved", "agree_proved"], "domain_not_covered"),
    (["agree_satisfiable", "agree_satisfiable", "agree_proved", "disagree"], "disagreement_quarantined"),
])
def test_selected_applicability_preserves_vacuity_or_other_domain_frontiers(classes, status):
    observed = record(body([page([applicable_projection(classes)])]))
    summary = observed.to_dict()["evidence"][0]
    assert summary["verification_status"] == "recorded_conditional_proved"
    assert summary["applicability_status"] == status
    assert summary["applicability_summary"]["classifications"] == classes
    if status in {"empty_domain", "inconsistent_premises", "domain_not_covered"}:
        assert summary["applicability_summary"]["conditional_proved"] is False


@pytest.mark.parametrize("flag", [0, 1, "false", None])
def test_rehashed_applicability_flags_cannot_change_typed_native_summary(flag):
    native = applicable_projection(["agree_satisfiable", "agree_unsatisfiable", "agree_proved", "agree_proved"])
    value = body([page([native])])
    value["evidence"][0]["applicability_summary"]["conditional_proved"] = flag
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="typed conditional flags"):
        record(value)


def test_partial_queries_have_no_absence_and_retain_continuation():
    observed = record(body([page([projection()], complete=False)]))
    assert observed.to_dict()["entries"][0]["evidence_disposition"] == "matched_partial"
    assert observed.advisory_refs()["query"]["next_cursor"] is not None
    value = body()
    value["query"]["pages"] = []
    value["query"]["complete"] = False
    value["entries"] = join._ledger(value["scan"]["record"]["entries"], [], False)
    observed = record(value)
    assert observed.advisory_refs()["coverage"]["evidence_unknown_members"] == 1
    assert not observed.advisory_refs()["query"]["complete"]


def test_two_page_traversal_preserves_exact_source_evidence_multiplicity():
    first, second = sorted([projection(1), projection(2)], key=lambda row: row.entry_id)
    p1 = page([first], complete=False)
    p2 = page([second], cursor=p1.next_cursor)
    observed = record(body([p1, p2]))
    assert observed.advisory_refs()["coverage"]["evidence_entries"] == 2
    assert observed.advisory_refs()["coverage"]["evidence_matched_members"] == 1


@pytest.mark.parametrize("has_entries", [False, True])
def test_query_cannot_continue_after_terminal_page_even_with_valid_content_ids(has_entries):
    terminal = page([projection()] if has_entries else [])
    value = body([terminal, terminal])
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="terminal"):
        record(value)


def test_checkpoint_cid_and_sha_cannot_be_independently_rehashed():
    value = body()
    value["scan"]["record"]["model"]["artifact"]["sha256"] = "8" * 64
    rehash_scan(value)
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="checkpoint CID"):
        record(value)


@pytest.mark.parametrize("mutation", ["epoch", "inventory", "head", "start", "empty_complete", "authority"])
def test_rehashed_pages_cannot_change_root_chain_or_completeness(mutation):
    value = body([page([projection()], complete=False)])
    item = value["query"]["pages"][0]["page"]
    if mutation == "epoch":
        item["epoch"] = 2
    elif mutation == "inventory":
        item["inventory_cid"] = cid("wrong-inventory")
    elif mutation == "head":
        item["head"]["receipt_cid"] = cid("wrong-receipt")
    elif mutation == "start":
        item["start_cursor"] = item["next_cursor"]
    elif mutation == "empty_complete":
        value["query"]["complete"] = True
    else:
        item["authority"]["kernel_checked"] = 0
    rehash_page(value)
    with pytest.raises(join.CodebaseInventoryEvidenceError):
        record(value)


@pytest.mark.parametrize("name", ["path", "entry_cid", "source_cid", "source_sha256", "ast_cid", "source_size_bytes"])
def test_rehashed_scan_cannot_rebind_existing_conditional_evidence(name):
    value = body([page([projection()])])
    row = value["scan"]["record"]["entries"][0]
    row[name] = {"path": "different.py", "entry_cid": cid("other-entry"), "source_cid": cid_for_bytes(b"different"),
        "source_sha256": "9" * 64, "ast_cid": cid("other-ast"), "source_size_bytes": 0}[name]
    if name == "entry_cid":
        ordered = [{"source_key": row["source_key"], "entry_cid": row["entry_cid"]}]
        value["scan"]["record"]["membership"] = {"cid": cid_for_structured(ordered), "ordered": ordered}
    rehash_scan(value)
    with pytest.raises(join.CodebaseInventoryEvidenceError):
        record(value)


@pytest.mark.parametrize("name", ["source_cid", "ast_cid", "manifest_cid", "snapshot_cid", "head_cid", "content_sha256"])
def test_conditional_dependency_rebinding_is_refused(name):
    value = body([page([projection()])])
    value["evidence"][0]["dependencies"][name] = "0" * 64 if name == "content_sha256" else cid("other-dependency")
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="dependency"):
        record(value)


@pytest.mark.parametrize("mutation", ["missing_member", "unknown_to_absent", "duplicate_evidence", "not_finite", "model_bool", "scan_head"])
def test_record_closed_ledger_model_and_numerics(mutation):
    value = body([page([projection()], complete=False)])
    if mutation == "missing_member":
        value["entries"].clear()
    elif mutation == "unknown_to_absent":
        value["entries"][0]["evidence_disposition"] = "no_exact_indexed_conditional_evidence"
    elif mutation == "duplicate_evidence":
        value["evidence"].append(deepcopy(value["evidence"][0]))
    elif mutation == "not_finite":
        value["scan"]["record"]["model"]["optimized"] = float("nan")
    elif mutation == "model_bool":
        value["scan"]["record"]["model"]["optimized"] = 0
        rehash_scan(value)
    else:
        value["scan"]["record"]["head"]["generation"] = True
        rehash_scan(value)
    with pytest.raises(join.CodebaseInventoryEvidenceError):
        record(value)


def test_dependency_selector_explicitly_refused_before_any_query():
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="dependency"):
        join._selector(Selector(dependency_kind="source", dependency_value=cid_for_bytes(b"source")))


def test_member_fence_rejects_rehashed_omission_without_inference():
    head, entry, unit, raw, scan, _, _ = fixture()
    seal = SimpleNamespace(members=(SimpleNamespace(entry=entry, unit=unit, raw=raw, disposition="captured_python"),))
    join._match_scan_members(scan, seal)
    scan["entries"] = []
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="omits"):
        join._match_scan_members(scan, seal)


@pytest.fixture
def controlled_lifecycle(monkeypatch):
    """Owner/resource replacements deliberately make this a pure control test."""
    head, entry, unit, raw, scan, _, _ = fixture()
    seal = SimpleNamespace(members=(SimpleNamespace(entry=entry, unit=unit, raw=raw, disposition="captured_python"),))
    @contextmanager
    def scope(*args, **kwargs):
        yield object(), object(), lambda: 100.0
    monkeypatch.setattr(join, "_scope", scope)
    monkeypatch.setattr(join, "_owners", lambda *args: None)
    monkeypatch.setattr(join, "_implementation", implementation)
    monkeypatch.setattr(join, "_observe", lambda *args, **kwargs: seal)
    monkeypatch.setattr(join, "_replay_model", lambda *args, **kwargs: ([], ()))
    monkeypatch.setattr(scanner, "_history_fence", lambda *args, **kwargs: b"stable-history")
    monkeypatch.setattr(scanner, "_registry_inventory", lambda *args, **kwargs: b"stable-owner")
    monkeypatch.setattr(scanner, "_model_fence", lambda *args, **kwargs: None)
    def forbidden(*args, **kwargs):
        pytest.fail("retained validation reached inference")
    monkeypatch.setattr(scanner, "scan_current_codebase_features", forbidden)
    return head


def test_retained_live_validator_compares_native_status_summary_not_just_epoch(controlled_lifecycle, monkeypatch):
    native = page([projection()])
    old = body([native])
    monkeypatch.setattr(join, "_page", lambda *args, **kwargs: native)
    original = record(old)
    assert join.validate_current_inventory_evidence(original, object(), "pure", registry=object(),
        verification_catalog=object(), expected_head=controlled_lifecycle).artifact_cid == original.artifact_cid
    old["evidence"][0]["verification_status"] = "recorded_conditional_refuted"
    changed = record(old)
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="summary changed"):
        join.validate_current_inventory_evidence(changed, object(), "pure", registry=object(),
            verification_catalog=object(), expected_head=controlled_lifecycle)


def test_retained_live_validator_rejects_same_head_epoch_change(controlled_lifecycle, monkeypatch):
    old = record(body())
    monkeypatch.setattr(join, "_page", lambda *args, **kwargs: page(epoch=2))
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="query page changed"):
        join.validate_current_inventory_evidence(old, object(), "pure", registry=object(), verification_catalog=object())


def test_retained_live_validator_rejects_closing_only_evidence_drift(controlled_lifecycle, monkeypatch):
    old = record(body())
    calls = iter([page(), page(epoch=2)])
    monkeypatch.setattr(join, "_page", lambda *args, **kwargs: next(calls))
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="inventory changed"):
        join.validate_current_inventory_evidence(old, object(), "pure", registry=object(), verification_catalog=object())


def test_retained_live_validator_rejects_source_mutation_after_query(controlled_lifecycle, monkeypatch):
    old = record(body())
    monkeypatch.setattr(join, "_page", lambda *args, **kwargs: page())
    normal_observe = join._observe
    calls = []
    def observed(*args, **kwargs):
        result = normal_observe(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            result.members[0].raw = b"different"
        return result
    monkeypatch.setattr(join, "_observe", observed)
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="source member differs"):
        join.validate_current_inventory_evidence(old, object(), "pure", registry=object(), verification_catalog=object())


def test_retained_generation_guard_precedes_native_query(controlled_lifecycle, monkeypatch):
    value = body()
    value["implementation"]["files"]["other-generation"] = "1" * 64
    value["implementation"]["sha256"] = join.training.features.digest(value["implementation"]["files"])
    def forbidden(*args, **kwargs):
        pytest.fail("different generation reached native query")
    monkeypatch.setattr(join, "_page", forbidden)
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="generation"):
        join.validate_current_inventory_evidence(record(value), object(), "pure", registry=object(), verification_catalog=object())


@pytest.mark.parametrize("bound", ["pages", "entries", "bytes"])
def test_fresh_builder_budget_keeps_complete_membership_with_explicit_unknowns(controlled_lifecycle, monkeypatch, bound):
    head, _, _, _, scan, _, _ = fixture()
    native_scan = scanner.CodebaseInventoryScanRecord(cid_for_bytes(join._wire(scan)), join._wire(scan))
    forwarded = []
    def fresh(*args, **kwargs):
        forwarded.append(kwargs)
        return native_scan
    monkeypatch.setattr(scanner, "scan_current_codebase_features", fresh)
    first = page([projection()], complete=False)
    monkeypatch.setattr(join, "_page", lambda *args, **kwargs: first)
    options = {"max_pages": 1} if bound == "pages" else {"max_evidence_entries": 1} if bound == "entries" else {"max_query_bytes": 1}
    narrow_scan = replace(scanner.CodebaseInventoryScanLimits(), max_inferred_rows=4)
    result = join.scan_current_codebase_evidence(object(), "pure", expected_head=head, registry=object(),
        version_id=scan["model"]["version_id"], verification_catalog=SimpleNamespace(limits=SimpleNamespace(max_query_page_size=64)),
        scan_limits=narrow_scan, limits=join.CodebaseInventoryEvidenceLimits(**options))
    value = result.to_dict()
    assert len(value["entries"]) == 1
    assert not value["query"]["complete"]
    assert forwarded[0]["optimized"] is True and forwarded[0]["limits"] is narrow_scan
    if bound == "bytes":
        assert not value["query"]["pages"] and not value["evidence"]
        assert value["query"]["next_cursor"] is None
        assert value["entries"][0]["evidence_disposition"] == "unknown_budget"
    else:
        assert value["entries"][0]["evidence_disposition"] == "matched_partial"
        assert value["query"]["next_cursor"] is not None


def test_retained_cancellation_at_native_query_returns_no_record(controlled_lifecycle, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError
    def cancelled(*args, **kwargs):
        raise LeaseCancelledError("controlled query cancellation")
    monkeypatch.setattr(join, "_page", cancelled)
    with pytest.raises(LeaseCancelledError, match="controlled"):
        join.validate_current_inventory_evidence(record(body()), object(), "pure", registry=object(), verification_catalog=object())


def test_final_model_owner_fence_is_not_replaced_by_evidence_epoch(controlled_lifecycle, monkeypatch):
    monkeypatch.setattr(join, "_page", lambda *args, **kwargs: page())
    owner_reads = iter([b"entry-owner", b"changed-owner"])
    monkeypatch.setattr(scanner, "_registry_inventory", lambda *args, **kwargs: next(owner_reads))
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="model owner changed"):
        join.validate_current_inventory_evidence(record(body()), object(), "pure", registry=object(), verification_catalog=object())


def test_same_head_evidence_rebuild_during_late_model_fence_rejects(controlled_lifecycle, monkeypatch):
    state = {"epoch": 1}
    monkeypatch.setattr(join, "_page", lambda *args, **kwargs: page(epoch=state["epoch"]))
    monkeypatch.setattr(scanner, "_model_fence", lambda *args, **kwargs: state.update(epoch=2))
    with pytest.raises(join.CodebaseInventoryEvidenceError, match="during final fences"):
        join.validate_current_inventory_evidence(record(body()), object(), "pure", registry=object(), verification_catalog=object())
