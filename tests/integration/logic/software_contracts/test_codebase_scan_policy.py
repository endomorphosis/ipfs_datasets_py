"""Frozen scope over real Git/AST/CAS/SQL owners, including opaque submodules."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts import codebase_scan_policy as module
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
from ipfs_datasets_py.logic.software_contracts import codebase_git_operation as operations
from ipfs_datasets_py.logic.backends import process as transport


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def repository(root):
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Scan policy fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    return root


@pytest.fixture
def current(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    duckdb = pytest.importorskip("duckdb")
    root = repository(tmp_path / "repository")
    (root / "main.py").write_bytes("def größe(n: int) -> int:\r\n    return n + 1\r\n".encode())
    (root / "broken.py").write_text("def bad(:\n")
    (root / "README.txt").write_text("captured, unindexed\n")
    (root / "binary.dat").write_bytes(b"\xff\x00")
    (root / "large.py").write_bytes(b"#" * 1024)
    (root / "link.py").symlink_to("main.py")
    (root / "vendor").mkdir()
    (root / "vendor" / "external.py").write_text("raise RuntimeError('excluded vendor')\n")
    (root / "scratch").mkdir()
    (root / "scratch" / "hidden.py").write_text("raise RuntimeError('excluded artifact')\n")
    marker = tmp_path / "executed"
    (root / "do_not_execute.py").write_text(f"open({str(marker)!r}, 'w').write('executed')\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "complete fixture")
    connection = duckdb.connect(str(tmp_path / "catalog.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    cas = ImmutableCAS(tmp_path / "cas")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=cas,
                                    catalog=CodebaseCatalog(store, cas))
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json", proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False))
    policy = module.CodebaseScanPolicy(max_file_bytes=512, exclusions=("scratch",))
    def prepare(operation="capture", expected=None, **kwargs):
        return module.prepare_policy_current(index, root, repository_id="scan:fixture",
            operation_id=operation, expected_head=expected, policy=policy, scheduler=scheduler, **kwargs)
    yield root, index, prepare, scheduler, connection
    assert scheduler.snapshot()["active_lease_count"] == 0
    assert not marker.exists()
    connection.close()


def load(current, value):
    return module.load_policy_receipt(current[1], value["receipt_cid"])


def test_frozen_scope_preserves_complete_inventory_and_independent_selections(current):
    root, index, prepare, _, _ = current
    value = prepare(training_paths=("main.py",), proof_paths=("do_not_execute.py",))
    receipt = load(current, value)
    assert value["source_observed_live"] is True
    assert receipt["source_observed_live"] is False
    assert receipt["coverage"]["inventory_entries"] == 7
    assert receipt["coverage"]["training_selected"] == receipt["coverage"]["proof_selected"] == 1
    assert receipt["coverage"]["checked_properties"] == receipt["coverage"]["formalized_properties"] == 0
    assert {r["path"] for r in receipt["inventory"]} == {
        "main.py", "broken.py", "README.txt", "binary.dat", "large.py", "link.py", "do_not_execute.py"}
    source = next(r for r in receipt["inventory"] if r["path"] == "main.py")
    assert index.artifacts.get_bytes(source["source_cid"]) == (root / "main.py").read_bytes()
    assert all(not receipt[k] for k in ("proof_authority", "execution_authority", "training_executed", "training_admitted"))
    assert receipt["source_forest"]["root_count"] == 1
    assert receipt["policy"]["capabilities"]["submodules_and_nested_repositories"]["content_capture"] is False
    before = CodebaseHead.from_dict(value["head"])
    same = prepare("same-source", before)
    repeated = load(current, same)
    assert receipt["inventory"] == repeated["inventory"]
    assert repeated["coverage"]["training_selected"] == repeated["coverage"]["proof_selected"] == 0
    assert len(repeated["inventory"]) == 7
    assert load(current, value) == receipt  # historical replay uses immutable owners


@pytest.mark.parametrize("path", ["link.py", "binary.dat", "large.py", "broken.py", "README.txt",
                                  "vendor/external.py", "scratch/hidden.py", "missing.py"])
def test_opaque_unindexed_failed_and_excluded_entries_are_not_selectable(current, path):
    with pytest.raises(module.CodebaseScanPolicyError, match="requires captured successfully parsed Python"):
        current[2](training_paths=(path,))
    assert current[1].current("scan:fixture") is not None  # native head is still complete


@pytest.mark.parametrize("mutation", ["modified", "staged", "untracked", "deleted"])
def test_unchanged_head_overlay_identity_and_historical_receipt(current, mutation):
    root, index, prepare, _, _ = current
    first = prepare()
    first_receipt = load(current, first)
    commit = git(root, "rev-parse", "HEAD")
    if mutation in {"modified", "staged"}:
        (root / "main.py").write_text("def changed(n: int) -> int:\n    return n + 9\n")
        if mutation == "staged": git(root, "add", "main.py")
    elif mutation == "untracked":
        (root / "extra.py").write_text("x = 42\n")
    else:
        (root / "main.py").unlink()
    second = prepare("overlay", CodebaseHead.from_dict(first["head"]))
    second_receipt = load(current, second)
    assert git(root, "rev-parse", "HEAD") == commit
    assert second_receipt["source_forest"]["mode"] == "git-working"
    assert second_receipt["source_forest"]["snapshot_cid"] != first_receipt["source_forest"]["snapshot_cid"]
    assert load(current, first) == first_receipt
    assert index.current("scan:fixture") == CodebaseHead.from_dict(second["head"])


def add_submodule(current, tmp_path):
    root = current[0]
    child = repository(tmp_path / "submodule-source")
    (child / "nested.py").write_text("raise RuntimeError('submodule must never execute')\n")
    git(child, "add", ".")
    git(child, "commit", "-qm", "nested source")
    git(root, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(child), "component")
    git(root, "commit", "-qam", "opaque submodule boundary")
    return root / "component"


@pytest.mark.parametrize("state", ["clean", "dirty", "new_gitlink"])
def test_real_submodule_boundary_never_becomes_captured_or_selected(current, tmp_path, state):
    root, index, prepare, _, _ = current
    nested = add_submodule(current, tmp_path)
    before = prepare()
    if state != "clean":
        (nested / "nested.py").write_text("raise RuntimeError('different nested content')\n")
        if state == "new_gitlink":
            git(nested, "-c", "user.name=Submodule fixture", "-c", "user.email=fixture@example.invalid",
                "commit", "-qam", "changed nested commit")
            git(root, "add", "component")
        value = prepare("changed-submodule", CodebaseHead.from_dict(before["head"]))
    else:
        value = before
    receipt = load(current, value)
    row = next(r for r in receipt["inventory"] if r["path"] == "component")
    assert row["analysis_disposition"] == "opaque_unanalyzed"
    assert row["captured_for_analysis"] is row["candidate_selectable"] is False
    assert row["ast_cid"] is None
    assert row["source_key"] in receipt["source_forest"]["opaque_boundaries"]
    assert all(r["path"] != "component/nested.py" for r in receipt["inventory"])
    with pytest.raises(module.CodebaseScanPolicyError, match="requires captured successfully parsed Python"):
        prepare("bad-submodule-selection", CodebaseHead.from_dict(value["head"]), proof_paths=("component",))
    if state == "new_gitlink":
        assert value["head"]["snapshot_cid"] != before["head"]["snapshot_cid"]
    assert index.load_ast_artifact(index.load(value["head"]["manifest_cid"]), "component") is None


def test_opaque_boundary_cannot_be_resealed_as_captured_or_training_eligible(current, tmp_path):
    add_submodule(current, tmp_path)
    value = current[2]()
    receipt = load(current, value)
    row = next(r for r in receipt["inventory"] if r["path"] == "component")
    row["captured_for_analysis"] = row["candidate_selectable"] = True
    with pytest.raises(module.CodebaseScanPolicyError, match="does not reconstruct"):
        module.load_policy_receipt(current[1], current[1].artifacts.put(receipt))


@pytest.mark.parametrize("field", ["capability", "denominator", "inventory", "producer", "head", "selection", "authority"])
def test_resealed_policy_receipt_tampering_is_rejected(current, field):
    value = current[2](training_paths=("main.py",))
    receipt = deepcopy(load(current, value))
    if field == "capability": receipt["policy"]["capabilities"]["proof"] = "verified"
    elif field == "denominator": receipt["coverage"]["inventory_entries"] -= 1
    elif field == "inventory": receipt["inventory"].pop()
    elif field == "producer": receipt["producer"]["forged"] = "0" * 64
    elif field == "head": receipt["head"]["generation"] += 1
    elif field == "selection": receipt["training_selection"][0]["source_cid"] = receipt["head"]["snapshot_cid"]
    else: receipt["proof_authority"] = True
    with pytest.raises(module.CodebaseScanPolicyError):
        module.load_policy_receipt(current[1], current[1].artifacts.put(receipt))


def test_durable_independent_process_receipt_replay_without_target_source(current, tmp_path):
    root, index, prepare, _, connection = current
    value = prepare(training_paths=("main.py",), proof_paths=("main.py",))
    expected = load(current, value)
    connection.close()
    # Source removal is deliberate: public replay is historical and cannot claim live source.
    (root / "main.py").unlink()
    script = """
import json,sys,duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.codebase_scan_policy import load_policy_receipt
cx=duckdb.connect(sys.argv[1], config={'threads':1,'memory_limit':'64MB'})
store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(sys.argv[2])
index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
print(json.dumps(load_policy_receipt(index,sys.argv[3]),sort_keys=True))
cx.close()
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "catalog.duckdb"),
        str(tmp_path / "cas"), value["receipt_cid"]], capture_output=True, text=True,
        env=dict(os.environ), timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == expected


def test_source_race_during_policy_sealing_withholds_live_observation(current, monkeypatch):
    root, index, prepare, _, _ = current
    original = index.artifacts.put
    def changed(value):
        cid = original(value)
        if value.get("schema") == module.RECEIPT_SCHEMA:
            (root / "main.py").write_text("def changed(n: int) -> int:\n    return n + 2\n")
        return cid
    monkeypatch.setattr(index.artifacts, "put", changed)
    with pytest.raises(StaleCodebaseError, match="differs"):
        prepare()


def test_subtree_cannot_silently_expand_to_parent_repository(current):
    root, index, _, scheduler, _ = current
    with pytest.raises(module.CodebaseScanPolicyError, match="exact committed Git root"):
        module.prepare_policy_current(index, root / "scratch", repository_id="subtree",
            operation_id="subtree", expected_head=None, scheduler=scheduler)
    assert index.current("subtree") is None


@pytest.mark.parametrize("kwargs", [{"max_entries": 257}, {"max_entries": True},
                                  {"max_file_bytes": 65537}, {"exclusions": ("../other",)},
                                  {"exclusions": ("scratch", "scratch")}])
def test_policy_rejects_unbounded_or_ambiguous_scope(kwargs):
    with pytest.raises(module.CodebaseScanPolicyError): module.CodebaseScanPolicy(**kwargs)


def test_repository_ignore_rules_are_captured_and_tracked_files_remain_in_scope(current):
    root, _, prepare, _, _ = current
    (root / ".gitignore").write_text("*.temp.py\n")
    (root / "tracked.temp.py").write_text("x = 1\n")
    git(root, "add", ".gitignore")
    git(root, "add", "-f", "tracked.temp.py")
    git(root, "commit", "-qm", "pin repository ignore rules")
    (root / "ignored.temp.py").write_text("raise RuntimeError('outside Git scope')\n")
    first = prepare()
    receipt = load(current, first)
    paths = {r["path"] for r in receipt["inventory"]}
    assert {".gitignore", "tracked.temp.py"} <= paths
    assert "ignored.temp.py" not in paths
    (root / ".gitignore").write_text("# no patterns\n")
    second = prepare("ignore-change", CodebaseHead.from_dict(first["head"]))
    assert "ignored.temp.py" in {r["path"] for r in load(current, second)["inventory"]}
    assert second["head"]["snapshot_cid"] != first["head"]["snapshot_cid"]


@pytest.mark.parametrize("kind", ["configured", "default", "repository_info"])
def test_active_external_ignore_patterns_are_rejected_before_source_publication(current, tmp_path, kind):
    root, index, prepare, _, _ = current
    if kind == "configured":
        path = tmp_path / "global.ignore"
        git(root, "config", "core.excludesfile", str(path))
    elif kind == "default":
        path = tmp_path / "xdg" / "git" / "ignore"
        path.parent.mkdir(parents=True)
    else:
        path = root / ".git" / "info" / "exclude"
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("*.py\n")
    with pytest.raises(module.CodebaseScanPolicyError, match="active or oversized external"):
        prepare()
    assert index.current("scan:fixture") is None


@pytest.mark.parametrize("change", ["config", "inactive_bytes", "active_bytes"])
def test_external_ignore_scope_drift_during_sealing_withholds_observation(current, tmp_path, monkeypatch, change):
    root, index, prepare, _, _ = current
    path = tmp_path / "declared.ignore"
    path.write_text("# frozen inactive file\n")
    git(root, "config", "core.excludesfile", str(path))
    original = index.artifacts.put
    def mutate(value):
        cid = original(value)
        if value.get("schema") == module.RECEIPT_SCHEMA:
            if change == "config":
                git(root, "config", "core.excludesfile", str(tmp_path / "different.ignore"))
            else:
                path.write_text("*.py\n" if change == "active_bytes" else "# changed inactive file\n")
        return cid
    monkeypatch.setattr(index.artifacts, "put", mutate)
    with pytest.raises(module.CodebaseScanPolicyError, match="external ignore"):
        prepare()


def test_external_scope_replay_requires_exact_captured_bytes(current, tmp_path):
    root, index, prepare, _, _ = current
    path = tmp_path / "declared.ignore"
    path.write_text("# pinned inactive file\n")
    git(root, "config", "core.excludesfile", str(path))
    value = prepare()
    receipt = load(current, value)
    global_record = receipt["external_ignores"]["files"][1]
    assert global_record["present"] is True
    assert index.artifacts.get_bytes(global_record["source_cid"]) == path.read_bytes()
    path.write_text("*.py\n")
    assert load(current, value) == receipt  # immutable history is independent of today's environment
    index.artifacts.path_for(global_record["source_cid"], source=True).unlink()
    with pytest.raises(FileNotFoundError): load(current, value)


def test_nonregular_external_ignore_file_never_blocks_or_reads_target(current, tmp_path):
    root, index, prepare, _, _ = current
    path = tmp_path / "ignore.fifo"
    os.mkfifo(path)
    git(root, "config", "core.excludesfile", str(path))
    with pytest.raises(module.CodebaseScanPolicyError, match="must be regular"):
        prepare()
    assert index.current("scan:fixture") is None


def test_untracked_self_ignored_rule_file_cannot_define_unbound_scope(current):
    root, _, prepare, _, _ = current
    (root / ".gitignore").write_text("*\n")
    (root / "hidden.py").write_text("raise RuntimeError('not part of an admitted inventory')\n")
    with pytest.raises(module.CodebaseScanPolicyError, match="ignore rules must be included"):
        prepare()


def test_custom_exclusion_cannot_hide_a_repository_rule_file(current):
    root, index, _, scheduler, _ = current
    (root / ".gitignore").write_text("*.tmp\n")
    git(root, "add", ".gitignore")
    git(root, "commit", "-qm", "scope definition")
    with pytest.raises(module.CodebaseScanPolicyError, match="ignore rules must be included"):
        module.prepare_policy_current(index, root, repository_id="hidden-rule",
            operation_id="hidden-rule", expected_head=None,
            policy=module.CodebaseScanPolicy(exclusions=(".gitignore",)), scheduler=scheduler)


def test_oversized_git_ignore_inventory_is_process_bounded_before_source_capture(current):
    root, index, prepare, _, _ = current
    for number in range(350):
        directory = root / (f"nested_{number:04d}_" + "x" * 200)
        directory.mkdir()
        (directory / ".gitignore").write_text("# no patterns\n")
    with pytest.raises(module.CodebaseScanPolicyError, match="bounded process profile"):
        prepare()
    assert index.current("scan:fixture") is None


@pytest.mark.parametrize("raw", [b"#" * 513 + b"\n*.py\n", b"\xff\n*.py\n"])
def test_opaque_repository_ignore_rule_cannot_define_admitted_scope(current, raw):
    root, index, prepare, _, _ = current
    (root / ".gitignore").write_bytes(raw)
    git(root, "add", ".gitignore")
    git(root, "commit", "-qm", "opaque scope definition")
    with pytest.raises(module.CodebaseScanPolicyError, match="exact captured bytes"):
        prepare()
    # Native structural history may exist, but the policy cannot certify it.
    assert index.current("scan:fixture") is not None


@pytest.mark.parametrize("helper", ["_external_ignore_scope", "_repository_rule_paths"])
def test_source_edit_during_final_scope_query_withholds_live_success(current, monkeypatch, helper):
    root, _, prepare, _, _ = current
    original = getattr(module, helper)
    calls = []
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result)
        if len(calls) == 3:
            (root / "main.py").write_text("def changed(n: int) -> int:\n    return n + 99\n")
        return result
    monkeypatch.setattr(module, helper, mutate)
    with pytest.raises(StaleCodebaseError):
        prepare()
    assert len(calls) == 3


@pytest.mark.parametrize("target_present", [True, False])
def test_external_ignore_symlink_is_rejected_without_opening_target(current, tmp_path, monkeypatch, target_present):
    root, index, prepare, _, _ = current
    target = tmp_path / "ignore-target"
    if target_present:
        target.write_text("# inactive target\n")
    link = tmp_path / "ignore-link"
    link.symlink_to(target)
    git(root, "config", "core.excludesfile", str(link))
    original = os.open
    opened = []
    def observe(path, *args, **kwargs):
        opened.append(Path(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(os, "open", observe)
    with pytest.raises(module.CodebaseScanPolicyError, match="without a symlink"):
        prepare()
    assert link not in opened and target not in opened
    assert index.current("scan:fixture") is None


def test_working_capture_replaced_fifo_is_nonblocking_and_opaque(current, monkeypatch):
    root, _, _, _, _ = current
    path = root / "candidate.py"
    path.write_text("x = 1\n")
    original = os.open
    raced = []
    def replace_at_open(candidate, flags, *args, **kwargs):
        if Path(candidate) == path:
            assert flags & os.O_NONBLOCK
            path.unlink()
            os.mkfifo(path)
            raced.append(True)
        return original(candidate, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", replace_at_open)
    entry = module.snapshots._working_entry(root, b"candidate.py", 512)
    assert raced == [True]
    assert entry.is_opaque and entry.opaque_reason == "symlink_or_nonregular"
    assert entry.captured_bytes is None


@pytest.mark.parametrize("mode", ["filesystem", "git-unborn"])
def test_uncommitted_roots_are_outside_the_frozen_policy(current, tmp_path, mode):
    _, index, _, scheduler, _ = current
    root = tmp_path / mode
    if mode == "git-unborn":
        repository(root)
    else:
        root.mkdir()
    (root / "example.py").write_text("x = 1\n")
    with pytest.raises(module.CodebaseScanPolicyError, match="committed Git root"):
        module.prepare_policy_current(index, root, repository_id=mode,
            operation_id=mode, expected_head=None, scheduler=scheduler)
    assert index.current(mode) is None


@pytest.mark.parametrize("suffix", [".pyi", ".PY"])
def test_native_python_language_classification_remains_selectable(current, suffix):
    root, _, prepare, _, _ = current
    path = "declarations" + suffix
    (root / path).write_text("def identity(value: int) -> int:\n    return value\n")
    git(root, "add", path)
    git(root, "commit", "-qm", "Python classification fixture")
    value = prepare(training_paths=(path,), proof_paths=(path,))
    receipt = load(current, value)
    row = next(row for row in receipt["inventory"] if row["path"] == path)
    assert row["analysis_disposition"] == "python_ast_ok"
    assert row["candidate_selectable"] is True
    assert receipt["training_selection"][0]["path"] == path
    assert receipt["proof_selection"][0]["path"] == path
    assert receipt["training_admitted"] is False and receipt["proof_authority"] is False


def private_configuration(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    xdg = tmp_path / "xdg"
    (xdg / "git").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    return home, xdg


@pytest.mark.parametrize("location", ["home", "xdg"])
@pytest.mark.parametrize("active", [False, True])
def test_native_global_configuration_is_shared_by_scope_and_capture(current, tmp_path, monkeypatch, location, active):
    root, index, prepare, _, _ = current
    home, xdg = private_configuration(tmp_path, monkeypatch)
    ignore = tmp_path / "global.ignore"
    ignore.write_text("*.py\n" if active else "# no patterns\n")
    config = home / ".gitconfig" if location == "home" else xdg / "git" / "config"
    config.write_text(f"[core]\n\texcludesfile = {ignore}\n")
    (root / "untracked.py").write_text("x = 1\n")
    if active:
        with pytest.raises(module.CodebaseScanPolicyError, match="active or oversized external"):
            prepare()
        assert index.current("scan:fixture") is None
    else:
        value = prepare()
        receipt = load(current, value)
        assert receipt["external_ignores"]["files"][1]["path"] == str(ignore)
        assert "untracked.py" in {row["path"] for row in receipt["inventory"]}


def test_native_home_configuration_overrides_xdg_bait(current, tmp_path, monkeypatch):
    root, _, prepare, _, _ = current
    home, xdg = private_configuration(tmp_path, monkeypatch)
    bait, selected = tmp_path / "bait.ignore", tmp_path / "selected.ignore"
    bait.write_text("*.py\n")
    selected.write_text("# selected inactive rule\n")
    (xdg / "git" / "config").write_text(f"[core]\n\texcludesfile = {bait}\n")
    (home / ".gitconfig").write_text(f"[core]\n\texcludesfile = {selected}\n")
    (root / "untracked.py").write_text("x = 1\n")
    receipt = load(current, prepare())
    assert receipt["external_ignores"]["files"][1]["path"] == str(selected)
    assert "untracked.py" in {row["path"] for row in receipt["inventory"]}


def test_relative_include_and_ignore_paths_keep_native_origins(current, tmp_path, monkeypatch):
    root, _, prepare, _, _ = current
    home, _ = private_configuration(tmp_path, monkeypatch)
    (home / "parts").mkdir()
    (home / ".gitconfig").write_text("[include]\n\tpath = parts/selected.conf\n")
    (home / "parts" / "selected.conf").write_text("[core]\n\texcludesfile = selected.ignore\n")
    (home / "parts" / "selected.ignore").write_text("*.py\n")  # Wrong-origin bait.
    (root / "selected.ignore").write_text("# repository-relative selected file\n")
    (root / "untracked.py").write_text("x = 1\n")
    receipt = load(current, prepare())
    assert receipt["external_ignores"]["files"][1]["path"] == str(root / "selected.ignore")
    assert "untracked.py" in {row["path"] for row in receipt["inventory"]}


@pytest.mark.parametrize("matching", [False, True])
def test_conditional_include_uses_native_home_and_exact_git_root(current, tmp_path, monkeypatch, matching):
    _, index, prepare, _, _ = current
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    ignore = tmp_path / "active.ignore"
    ignore.write_text("*.py\n")
    (tmp_path / "selected.conf").write_text(f"[core]\n\texcludesfile = {ignore}\n")
    pattern = "repository" if matching else "another-root"
    (tmp_path / ".gitconfig").write_text(f'[includeIf "gitdir:~/{pattern}/"]\n\tpath = selected.conf\n')
    if matching:
        with pytest.raises(module.CodebaseScanPolicyError, match="active or oversized external"):
            prepare()
        assert index.current("scan:fixture") is None
    else:
        assert load(current, prepare())["external_ignores"]["selector"] == "XDG_CONFIG_HOME"


@pytest.mark.parametrize("relative", [False, True])
def test_explicit_global_configuration_overrides_home_and_xdg(current, tmp_path, monkeypatch, relative):
    root, _, prepare, _, _ = current
    home, xdg = private_configuration(tmp_path, monkeypatch)
    bait, selected = tmp_path / "bait.ignore", tmp_path / "selected.ignore"
    bait.write_text("*.py\n")
    selected.write_text("# selected inactive rule\n")
    for config in [home / ".gitconfig", xdg / "git" / "config"]:
        config.write_text(f"[core]\n\texcludesfile = {bait}\n")
    config = root / "selected.config" if relative else tmp_path / "selected.config"
    config.write_text(f"[core]\n\texcludesfile = {selected}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", config.name if relative else str(config))
    (root / "untracked.py").write_text("x = 1\n")
    receipt = load(current, prepare())
    assert receipt["external_ignores"]["files"][1]["path"] == str(selected)
    assert "untracked.py" in {row["path"] for row in receipt["inventory"]}


@pytest.mark.parametrize("xdg", [None, ""])
def test_default_ignore_uses_frozen_home_when_xdg_unset_or_empty(current, tmp_path, monkeypatch, xdg):
    _, index, prepare, _, _ = current
    home, _ = private_configuration(tmp_path, monkeypatch)
    if xdg is None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
    path = home / ".config" / "git" / "ignore"
    path.parent.mkdir(parents=True)
    path.write_text("*.py\n")
    with pytest.raises(module.CodebaseScanPolicyError, match="active or oversized external"):
        prepare()
    assert index.current("scan:fixture") is None


def test_absent_home_with_explicit_xdg_keeps_native_configuration(current, tmp_path, monkeypatch):
    root, _, prepare, _, _ = current
    _, xdg = private_configuration(tmp_path, monkeypatch)
    monkeypatch.delenv("HOME", raising=False)
    ignore = tmp_path / "selected.ignore"
    ignore.write_text("# no active patterns\n")
    (xdg / "git" / "config").write_text(f"[core]\n\texcludesfile = {ignore}\n")
    (root / "untracked.py").write_text("x = 1\n")
    receipt = load(current, prepare())
    assert "untracked.py" in {row["path"] for row in receipt["inventory"]}
    assert receipt["external_ignores"]["files"][1]["path"] == str(ignore)


def test_missing_home_and_xdg_never_invents_passwd_ignore_scope(current, monkeypatch):
    _, index, prepare, _, _ = current
    for key in ["HOME", "XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL"]:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(module.CodebaseScanPolicyError, match="requires HOME or XDG_CONFIG_HOME"):
        prepare()
    assert index.current("scan:fixture") is None


@pytest.mark.parametrize("key", ["HOME", "XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL"])
def test_environment_drift_after_sealing_withholds_current_result(current, tmp_path, monkeypatch, key):
    _, index, prepare, _, _ = current
    original = index.artifacts.put
    captured = []
    def mutate(value):
        cid = original(value)
        if value.get("schema") == module.RECEIPT_SCHEMA:
            captured.append(cid)
            monkeypatch.setenv(key, str(tmp_path / "changed-environment"))
        return cid
    monkeypatch.setattr(index.artifacts, "put", mutate)
    with pytest.raises(module.CodebaseScanPolicyError, match="configuration environment changed"):
        prepare()
    assert operations.current_git_operation() is None
    assert len(captured) == 1
    assert module.load_policy_receipt(index, captured[0])["source_observed_live"] is False


def test_precancelled_scan_has_no_initial_git_or_artifact_effect(current, monkeypatch):
    _, index, prepare, _, _ = current
    cancelled = threading.Event()
    cancelled.set()
    calls = []
    original = module.snapshots._git
    monkeypatch.setattr(module.snapshots, "_git", lambda *args: calls.append(args) or original(*args))
    before = sorted(path for path in index.artifacts.root.rglob("*") if path.is_file())
    with pytest.raises(LeaseCancelledError):
        prepare(cancel_event=cancelled)
    assert calls == []
    assert sorted(path for path in index.artifacts.root.rglob("*") if path.is_file()) == before
    assert operations.current_git_operation() is None


@pytest.mark.parametrize("kwargs", [{"timeout_seconds": 0}, {"timeout_seconds": True},
                                  {"timeout_seconds": float("nan")}, {"memory_mb": 0}])
def test_invalid_operation_budget_is_rejected_before_initial_git(current, monkeypatch, kwargs):
    _, _, prepare, _, _ = current
    calls = []
    monkeypatch.setattr(module.snapshots, "_git", lambda *args: calls.append(args))
    with pytest.raises(ValueError):
        prepare(**kwargs)
    assert calls == [] and operations.current_git_operation() is None


def test_deadline_accumulates_scope_and_native_publication_costs(current, monkeypatch):
    _, index, prepare, _, _ = current
    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    for name in ["_external_ignore_scope", "_repository_rule_paths"]:
        original = getattr(module, name)
        def cost(*args, _original=original, **kwargs):
            result = _original(*args, **kwargs)
            clock[0] += 7.0
            return result
        monkeypatch.setattr(module, name, cost)
    original = index.prepare_current
    timeouts = []
    def native(*args, **kwargs):
        timeouts.append(kwargs["timeout_seconds"])
        result = original(*args, **kwargs)
        clock[0] += 7.0
        return result
    monkeypatch.setattr(index, "prepare_current", native)
    with pytest.raises(LeaseTimeoutError):
        prepare(timeout_seconds=20)
    assert timeouts == [6.0]
    assert index.current("scan:fixture") is not None  # Complete history survives a refused live result.
    assert operations.current_git_operation() is None


def test_all_git_phases_share_one_envelope_and_original_environment(current, monkeypatch):
    root, _, prepare, scheduler, _ = current
    original = transport.SubprocessExecutor.execute
    observations = []
    def observe(self, invocation, cancellation=None):
        state = scheduler.snapshot()
        observations.append((state["active_root_lease_count"], state["active_lease_count"],
                             state["allocated"], dict(invocation.environment), invocation.cwd))
        return original(self, invocation, cancellation)
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", observe)
    prepare()
    assert observations and observations[0][1] == 1
    assert {row[1] for row in observations} == {1, 2}
    assert all(row[0] == 1 and row[2] == observations[0][2] and row[3] == observations[0][3]
               and row[4] == root for row in observations)
    assert observations[0][3].get("HOME") == os.environ.get("HOME")
    assert operations.current_git_operation() is None


def test_scan_child_preserves_caller_owned_parent(current):
    root, index, _, scheduler, _ = current
    with scheduler.acquire("orchestration", cpu_slots=2, memory_mb=1024,
                           child_process_slots=2, timeout=0) as parent:
        module.prepare_policy_current(index, root, repository_id="parent-scan",
            operation_id="parent-scan", expected_head=None, parent_lease=parent,
            policy=module.CodebaseScanPolicy(max_file_bytes=512, exclusions=("scratch",)))
        assert not parent.released and scheduler.snapshot()["active_lease_count"] == 1
    assert operations.current_git_operation() is None


def test_exhausted_parent_child_slots_refuse_before_git(current, monkeypatch):
    root, index, _, scheduler, _ = current
    calls = []
    monkeypatch.setattr(module.snapshots, "_git", lambda *args: calls.append(args))
    with scheduler.acquire("orchestration", cpu_slots=2, memory_mb=1024,
                           child_process_slots=1, timeout=0) as parent:
        with parent.acquire_child(cpu_slots=1, memory_mb=512, child_process_slots=1, timeout=0):
            with pytest.raises(LeaseTimeoutError):
                module.prepare_policy_current(index, root, repository_id="blocked-scan",
                    operation_id="blocked-scan", expected_head=None, parent_lease=parent,
                    timeout_seconds=0.05)
            assert not parent.released and scheduler.snapshot()["active_lease_count"] == 2
    assert calls == [] and operations.current_git_operation() is None


def test_cancellation_reaches_initial_native_executor(current, monkeypatch):
    _, _, prepare, _, _ = current
    cancelled = threading.Event()
    original = transport.SubprocessExecutor.execute
    calls = []
    def cancel(self, invocation, cancellation=None):
        cancelled.set()
        result = original(self, invocation, cancellation)
        calls.append(result.cancelled)
        return result
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", cancel)
    with pytest.raises(LeaseCancelledError):
        prepare(cancel_event=cancelled)
    assert calls == [True] and operations.current_git_operation() is None


@pytest.mark.parametrize("change", [{"timed_out": True}, {"cancelled": True},
    {"output_truncated": True}, {"resource_exhausted": True}, {"process_tree_terminated": True},
    {"error": "injected cleanup refusal"}, {"stdout": "decoded text"}, {"returncode": True}])
def test_raw_transport_refusals_never_publish_or_leave_context(current, monkeypatch, change):
    _, index, prepare, _, _ = current
    original = transport.SubprocessExecutor.execute
    def refuse(self, invocation, cancellation=None):
        return replace(original(self, invocation, cancellation), **change)
    monkeypatch.setattr(transport.SubprocessExecutor, "execute", refuse)
    with pytest.raises(module.CodebaseScanPolicyError, match="bounded process profile"):
        prepare()
    assert index.current("scan:fixture") is None and operations.current_git_operation() is None


def test_raw_git_preserves_binary_blobs_and_undecodable_paths(current):
    root, _, prepare, _, _ = current
    first = prepare()
    receipt = load(current, first)
    binary = next(row for row in receipt["inventory"] if row["path"] == "binary.dat")
    assert binary["opaque_reason"] == "undecodable" and binary["captured_for_analysis"] is False
    name = b"non-\xff.py"
    with open(os.fsencode(root) + b"/" + name, "wb") as stream:
        stream.write(b"x = 1\n")
    second = prepare("raw-path", CodebaseHead.from_dict(first["head"]))
    receipt = load(current, second)
    row = next(row for row in receipt["inventory"] if row["source_key"] == "raw:" + name.hex())
    assert row["captured_for_analysis"] is False and row["candidate_selectable"] is False
