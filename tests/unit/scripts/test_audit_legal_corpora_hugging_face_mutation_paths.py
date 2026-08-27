"""Focused tests for the LCR-084 Hugging Face mutation-path audit."""

from __future__ import annotations

from pathlib import Path

import scripts.ops.legal_data.audit_legal_corpora_hugging_face_mutation_paths as audit

PROTECTED = "justicedao/ipfs_state_laws"


def _audit_source(tmp_path: Path, source: str) -> dict[str, object]:
    scan = tmp_path / "scan"
    scan.mkdir()
    (scan / "subject.py").write_text(source, encoding="utf-8")
    return audit.inventory_mutation_paths(
        repository_root=tmp_path,
        scan_roots=(Path("scan"),),
        protected_repos=(
            PROTECTED,
            "justicedao/ipfs_federal_register",
        ),
    )


def _only_callsite(report: dict[str, object]) -> dict[str, object]:
    callsites = report["callsites"]
    assert isinstance(callsites, list)
    assert len(callsites) == 1
    return callsites[0]


def test_imported_but_unused_runtime_does_not_authorize_write(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    authorize_and_mutate_canonical,
)

def mutate():
    api = HfApi()
    api.upload_file(repo_id="{PROTECTED}", path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1
    assert report["status"] == "blocked"


def test_module_level_write_call_is_inventoried(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

api = HfApi()
api.delete_repo(repo_id="{PROTECTED}")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["function"] == "<module>"
    assert callsite["write_method"] == "delete_repo"
    assert callsite["protection"] == "unprotected"


def test_write_alias_and_rebinding_are_resolved(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

TARGET = "{PROTECTED}"

def mutate():
    api = HfApi()
    commit = api.repo_info
    commit = api.create_commit
    commit(repo_id=TARGET, operations=[])
''',
    )
    callsite = _only_callsite(report)
    assert callsite["write_method"] == "create_commit"
    assert callsite["protection"] == "unprotected"


def test_method_resolver_alias_is_a_write_not_a_read(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
class Publisher:
    def publish(self):
        writer = self._require_api_method("create_commit")
        writer(repo_id="{PROTECTED}", operations=[])
''',
    )
    callsite = _only_callsite(report)
    assert callsite["write_method"] == "create_commit"
    assert callsite["protection"] == "unprotected"


def test_partial_write_alias_with_bound_repo_is_resolved(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from functools import partial as bind
from huggingface_hub import HfApi

def mutate():
    api = HfApi()
    writer = bind(api.upload_file, repo_id="{PROTECTED}")
    writer(path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["write_method"] == "upload_file"
    assert callsite["protected_target"] is True
    assert callsite["protection"] == "unprotected"


def test_hf_api_and_repo_info_read_are_not_mutations(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

def probe():
    api = HfApi()
    return api.repo_info(repo_id="{PROTECTED}", repo_type="dataset")
''',
    )
    assert report["callsite_count"] == 0
    assert report["unprotected_count"] == 0
    assert report["status"] == "passed"


def test_guard_in_unrelated_function_does_not_protect_write(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def unused_guard():
    require_unprotected_or_runtime("{PROTECTED}", method="upload_file")

def mutate():
    api = HfApi()
    api.upload_file(repo_id="{PROTECTED}", path_or_fileobj="x", path_in_repo="x")
''',
    )
    assert _only_callsite(report)["protection"] == "unprotected"


def test_protected_literal_in_unrelated_function_does_not_taint_arbitrary_value(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

def documentation_value():
    return "{PROTECTED}"

def generic_writer(target):
    api = HfApi()
    api.upload_file(repo_id=target, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protected_target"] is False
    assert callsite["protection"] == "not_a_proven_protected_target"
    assert report["unprotected_count"] == 0


def test_uncalled_public_repo_parameter_is_potentially_protected(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi

def evil(repo_id):
    HfApi().upload_file(repo_id=repo_id, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["repo_expression"] == "repo_id"
    assert callsite["potential_protected_target"] is True
    assert callsite["protected_target"] is True
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1
    assert report["status"] == "blocked"


def test_unknown_repository_bearing_attribute_is_potentially_protected(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi

def evil(config):
    api = HfApi()
    api.create_commit(repo_id=config.repository_id, operations=[])
''',
    )
    callsite = _only_callsite(report)
    assert callsite["repo_expression"] == "config.repository_id"
    assert callsite["potential_protected_target"] is True
    assert callsite["protected_target"] is True
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1


def test_protected_repo_matching_is_case_insensitive_through_aliases(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi

TARGET = "JusticeDAO/IPFS_State_Laws"

def mutate():
    alias = TARGET
    api = HfApi()
    api.upload_file(repo_id=alias, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protected_target"] is True
    assert callsite["protected_repos"] == [PROTECTED]
    assert callsite["protection"] == "unprotected"


def test_legacy_guard_must_dominate_api_construction_and_write(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def mutate(repo_id="{PROTECTED}"):
    require_unprotected_or_runtime(repo_id, method="upload_file")
    api = HfApi()
    api.upload_file(repo_id=repo_id, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "legacy_dominating_guard"
    assert callsite["guard_lines"]
    assert report["unprotected_count"] == 0


def test_legacy_guard_accepts_dynamic_same_repository_parameter(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def mutate(repo_id):
    require_unprotected_or_runtime(repo_id, method="upload_file")
    api = HfApi()
    api.upload_file(repo_id=repo_id, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["potential_protected_target"] is True
    assert callsite["protection"] == "legacy_dominating_guard"
    assert report["unprotected_count"] == 0


def test_guard_for_different_object_attribute_does_not_authorize(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

class Writer:
    def mutate(self):
        require_unprotected_or_runtime(self.audit_repo_id, method="upload_file")
        api = HfApi()
        api.upload_file(
            repo_id=self.repository_id,
            path_or_fileobj="x",
            path_in_repo="x",
        )
''',
    )
    assert _only_callsite(report)["protection"] == "unprotected"


def test_guard_after_api_construction_is_not_dominating(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def mutate(repo_id="{PROTECTED}"):
    api = HfApi()
    require_unprotected_or_runtime(repo_id, method="upload_file")
    api.upload_file(repo_id=repo_id, path_or_fileobj="x", path_in_repo="x")
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert "construction" in str(callsite["reason"])


def test_caller_forgeable_runtime_override_is_not_a_guard(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def mutate(runtime_authorized=False):
    require_unprotected_or_runtime(
        "{PROTECTED}",
        method="upload_file",
        runtime_authorized=runtime_authorized,
    )
    api = HfApi()
    api.upload_file(repo_id="{PROTECTED}", path_or_fileobj="x", path_in_repo="x")
''',
    )
    assert _only_callsite(report)["protection"] == "unprotected"


def test_actual_canonical_lambda_callback_protects_write(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    authorize_and_mutate_canonical,
)

def mutate(request):
    api = HfApi()
    return authorize_and_mutate_canonical(
        request,
        lambda decision: api.create_commit(repo_id="{PROTECTED}", operations=[]),
    )
''',
    )
    callsite = _only_callsite(report)
    assert callsite["canonical_callback"] is True
    assert callsite["protection"] == "canonical_runtime"
    assert report["unprotected_count"] == 0


def test_same_named_fake_canonical_attribute_does_not_authorize(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi

def mutate(fake, request):
    api = HfApi()
    return fake.authorize_and_mutate_canonical(
        request,
        lambda decision: api.create_commit(repo_id="{PROTECTED}", operations=[]),
    )
''',
    )
    callsite = _only_callsite(report)
    assert callsite["canonical_callback"] is False
    assert callsite["protection"] == "unprotected"


def test_reassigned_condition_invalidates_earlier_conditional_guard(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import require_unprotected_or_runtime

def mutate(publish, repo_id="{PROTECTED}"):
    if publish:
        require_unprotected_or_runtime(repo_id, method="upload_file")
    publish = True
    if publish:
        api = HfApi()
        api.upload_file(repo_id=repo_id, path_or_fileobj="x", path_in_repo="x")
''',
    )
    assert _only_callsite(report)["protection"] == "unprotected"


def test_canonical_nested_callback_delegation_is_followed(tmp_path: Path) -> None:
    report = _audit_source(
        tmp_path,
        f'''\
from huggingface_hub import HfApi
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    authorize_and_mutate_canonical,
)

def mutate(request):
    api = HfApi()
    def commit(decision):
        return api.upload_file(repo_id="{PROTECTED}", path_or_fileobj="x", path_in_repo="x")
    return authorize_and_mutate_canonical(request, commit)
''',
    )
    callsite = _only_callsite(report)
    assert callsite["function"].endswith("<locals>.commit")
    assert callsite["protection"] == "canonical_runtime"


def test_fail_closed_probe_narrows_only_unprotected_fallback(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import is_protected_repo
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    authorize_and_mutate_canonical,
)

def publish(repo_id, protected_mode, request):
    if is_protected_repo(repo_id) and not protected_mode:
        raise PermissionError("canonical runtime required")

    def execute():
        return HfApi().create_commit(repo_id=repo_id, operations=[])

    if protected_mode:
        return authorize_and_mutate_canonical(
            request,
            lambda decision: execute(),
        )
    else:
        return execute()
''',
    )
    callsite = _only_callsite(report)
    assert callsite["analysis_context_count"] == 2
    assert callsite["protection_variants"] == ["canonical_runtime"]
    assert callsite["protection"] == "canonical_runtime"
    assert report["unprotected_count"] == 0


def test_fail_closed_probe_does_not_authorize_true_branch_without_runtime(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
from huggingface_hub import HfApi
from ipfs_datasets_py.huggingface.protected_repo_guard import is_protected_repo

def publish(repo_id, protected_mode):
    if is_protected_repo(repo_id) and not protected_mode:
        raise PermissionError("canonical runtime required")

    def execute():
        return HfApi().create_commit(repo_id=repo_id, operations=[])

    if protected_mode:
        return execute()
    else:
        return execute()
''',
    )
    callsite = _only_callsite(report)
    assert callsite["protection"] == "unprotected"
    assert report["unprotected_count"] == 1


def test_refresh_publish_and_create_selectors_hard_rejection_is_inventoryable(
    tmp_path: Path,
) -> None:
    report = _audit_source(
        tmp_path,
        '''\
async def refresh_state_laws_corpus(args):
    direct_external_mutation_requested = bool(
        getattr(args, "publish_to_hf", False)
        or getattr(args, "create_repo", False)
    )
    if direct_external_mutation_requested:
        return {"status": "failed_preflight"}
    return {"status": "ok"}
''',
    )
    assert report["hard_rejected_functions"] == [
        {
            "path": "scan/subject.py",
            "function": "refresh_state_laws_corpus",
            "line": 6,
            "selector": "direct_external_mutation_requested",
            "selector_expression": "bool(getattr(args, 'publish_to_hf', False) or getattr(args, 'create_repo', False))",
            "mechanism": "refresh_hard_rejection",
        }
    ]


def test_live_tree_has_no_unprotected_protected_repo_writer() -> None:
    report = audit.inventory_mutation_paths()
    assert report["authorizing_hub_upload"] is False
    assert report["syntax_errors"] == []
    assert report["callsite_count"] >= 1
    assert report["protected_callsite_count"] >= 1
    assert report["unprotected_count"] == 0, report["reasons"]
    assert report["status"] == "passed"
    assert any(
        item["function"] == "refresh_state_laws_corpus"
        and item["mechanism"] == "refresh_hard_rejection"
        for item in report["hard_rejected_functions"]
    )


def test_cli_check_passes_live_tree() -> None:
    assert (
        audit.main(
            [
                "--protected-repo",
                PROTECTED,
                "--protected-repo",
                "justicedao/ipfs_federal_register",
                "--require-runtime",
                "ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime",
                "--check",
            ]
        )
        == 0
    )
