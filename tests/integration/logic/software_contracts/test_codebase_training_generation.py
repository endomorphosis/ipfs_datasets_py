"""Strict cohort and immutable child generation acceptance for one scalar profile."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_training_corpus as corpus
from ipfs_datasets_py.logic.software_contracts import codebase_model_generation as generation
from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as source384


def source(operator, name="capacity", function="calculate"):
    sort = "int" if operator in ("+", "-", "*") else "bool"
    return f"def {function}({name}: int, threshold: int) -> {sort}:\n    return {name} {operator} threshold\n"


def capture(root, specifications):
    import duckdb
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources

    root.mkdir(parents=True)
    repo = root / "repo"
    repo.mkdir()
    for arguments in (("init", "-q"), ("config", "user.name", "Fixture"),
                      ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", "-C", str(repo), *arguments], check=True)
    selections = []
    for path, role, text in specifications:
        (repo / path).write_text(text)
        selections.append(dict(path=path, role=role, group_id=path))
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "operator-disjoint scalar source"], check=True)
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store, artifacts = DuckDBASTStore(connection=connection), ImmutableCAS(root / "cas")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                    catalog=CodebaseCatalog(store, artifacts))
    scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "resources.json", auto_renew_leases=False, lane_reservations={}))
    head = index.prepare_current(repo, repository_id="repository:strict384", operation_id="capture",
        expected_head=None, scheduler=scheduler).head
    return SimpleNamespace(root=root, repo=repo, connection=connection, index=index,
                           scheduler=scheduler, head=head, selections=selections)


def close(prepared):
    prepared.connection.close()
    assert prepared.scheduler.snapshot()["active_lease_count"] == 0


def write_public(prepared, name, value):
    public = prepared.root / "public"
    public.mkdir(exist_ok=True)
    (public / (name + ".json")).write_bytes(source384._raw(value))


@pytest.fixture(scope="module")
def current(tmp_path_factory):
    specifications = [(f"{role}_{i}.py", role, source(operator))
        for role, operators in (("train", ("+", "-", "*")),
                                ("validation", ("<", "<=", ">")),
                                ("holdout", (">=", "==", "!=")))
        for i, operator in enumerate(operators)]
    value = capture(tmp_path_factory.mktemp("strict384") / "owned", specifications)
    yield value
    close(value)


def freeze(current, **options):
    return corpus.freeze_corpus(current.index, expected_head=current.head,
        selections=current.selections, **options)


def test_exact_sources_three_separate_objectives_and_explicit_unknowns(current):
    handle = freeze(current, transductive_source_context=True)
    value = corpus.verify_frozen_corpus(handle, current.index, expected_head=current.head)
    assert value["schema"] == "codebase-training-corpus@1"
    assert value["denominator"] == dict(enumerated=9, fitted_representatives=9,
        deduplicated=0, missing_properties=9, unknown_properties=0, checked_properties=0)
    assert len(value["components"]) == 9 and value["transductive_source_context"]
    assert value["pretraining_exposure"]["status"] == "unknown"
    assert not value["pretraining_exposure"]["complete_parent_training_corpus_available"]
    for row in value["rows"]:
        assert row["source_sha256"] == hashlib.sha256((current.repo / row["path"]).read_bytes()).hexdigest()
        assert set(row["objectives"]) == {"syntax", "semantic", "checked_property"}
        assert row["objectives"]["syntax"]["target"]
        assert row["objectives"]["semantic"]["native_program"]
        assert not row["label_provenance"]["learned_teacher_used"]
        assert not row["label_provenance"]["desired_intent_used"]
        assert not row["label_provenance"]["unchecked_prediction_used"]
    write_public(current, "strict-corpus-missing-properties", value)


def test_parameter_rename_leakage_in_legacy_style_split_is_rejected_before_fit(tmp_path):
    prepared = capture(tmp_path / "renamed", [
        ("train.py", "train", source("+", "capacity")),
        ("validation.py", "validation", source("+", "volume")),
        ("holdout.py", "holdout", source("+", "quantity"))])
    try:
        legacy = source384.prepare_corpus(prepared.index, expected_head=prepared.head, selections=prepared.selections)
        assert len(legacy["rows"]) == 3
        with pytest.raises(ValueError, match="connected .* crosses corpus splits"):
            freeze(prepared)
    finally:
        close(prepared)


def test_within_split_alpha_duplicates_have_explicit_preserved_denominator(tmp_path):
    prepared = capture(tmp_path / "duplicates", [
        ("train_a.py", "train", source("+", "capacity")),
        ("train_b.py", "train", source("+", "volume")),
        ("validation.py", "validation", source("<")),
        ("holdout.py", "holdout", source("=="))])
    try:
        value = freeze(prepared).to_dict()
        assert value["denominator"]["enumerated"] == 4
        assert value["denominator"]["fitted_representatives"] == 3
        assert value["denominator"]["deduplicated"] == 1
        removed, = [r for r in value["rows"] if not r["fit_eligible"]]
        assert removed["path"] == "train_b.py" and removed["duplicate_of"] == "train_a.py"
        assert removed["source_text"] == source("+", "volume")
    finally:
        close(prepared)


def test_transitive_declared_lineage_is_conservative_and_cannot_cross_splits(current):
    with pytest.raises(ValueError, match="connected .* crosses corpus splits"):
        freeze(current, lineage_edges=[dict(left="train_0.py", right="train_1.py", relation="revision"),
            dict(left="train_1.py", right="validation_0.py", relation="conservative_related")])


@pytest.mark.parametrize("field", ["desired_intent", "predicted_target", "teacher_target"])
def test_caller_correctness_labels_are_not_accepted(current, field):
    selections = deepcopy(current.selections)
    selections[0][field] = {"operator": "multiply"}
    with pytest.raises(ValueError, match="closed source selection"):
        corpus.freeze_corpus(current.index, expected_head=current.head, selections=selections)


def test_saved_or_unissued_corpus_cannot_authorize_a_fit(current):
    for value in (freeze(current).to_dict(), corpus.FrozenCodebaseCorpus()):
        with pytest.raises(ValueError, match="locally issued"):
            corpus.verify_frozen_corpus(value, current.index, expected_head=current.head)


@pytest.mark.parametrize("domains", [False, []])
def test_false_or_list_is_not_an_empty_property_mapping(current, domains):
    with pytest.raises(ValueError, match="property domain mapping"):
        freeze(current, input_domains=domains)


@pytest.fixture(scope="module")
def qualified(current):
    lake = os.environ.get("CODEBASE384_LAKE")
    if not lake:
        pytest.skip("explicit native Lake required")
    domains = {path: {"capacity": {"lower": -1, "upper": 1}, "threshold": {"lower": -1, "upper": 1}}
               for path in ("train_0.py", "validation_0.py")}
    execution = corpus.check_properties(current.index, expected_head=current.head,
        selections=current.selections, input_domains=domains, lake_executable=lake,
        scheduler=current.scheduler, output_directory=current.root / "public" / "property-lake")
    frozen = freeze(current, input_domains=domains, checked_execution=execution)
    value = frozen.to_dict()
    assert value["denominator"]["checked_properties"] == 2
    assert value["denominator"]["missing_properties"] == 7
    write_public(current, "strict-corpus-checked-properties", value)
    return frozen, execution, domains


def test_actual_kernel_checked_property_is_distinct_from_syntax_or_source_equivalence(current, qualified):
    frozen, _, _ = qualified
    value = corpus.verify_frozen_corpus(frozen, current.index, expected_head=current.head)
    checked = [r["objectives"]["checked_property"] for r in value["rows"]
               if r["objectives"]["checked_property"]["status"] == "checked_within_model"]
    assert len(checked) == 2 and sum(row["target"]["case_count"] for row in checked) == 18
    assert all(row["provenance"]["finite_correspondence_kernel_checked"] for row in checked)
    assert all(not row["provenance"]["python_equivalence_proved"] for row in checked)
    assert value["property_receipt"]["backend_executed"]


@pytest.mark.parametrize("damage", ["saved_handle", "wrong_domains"])
def test_checked_label_requires_exact_live_independent_result(current, qualified, damage):
    _, execution, domains = qualified
    if damage == "saved_handle":
        execution = execution.to_dict()
    else:
        domains = deepcopy(domains)
        domains["train_0.py"]["capacity"]["upper"] = 0
    with pytest.raises(ValueError, match="live issued|identity differs"):
        freeze(current, input_domains=domains, checked_execution=execution)


def test_unavailable_property_checker_preserves_missing_and_unknown_denominators(current):
    domains = {"train_0.py": {"capacity": {"lower": 0, "upper": 0}, "threshold": {"lower": 0, "upper": 0}}}
    execution = corpus.check_properties(current.index, expected_head=current.head, selections=current.selections,
        input_domains=domains, lake_executable="/no/selected/lake", scheduler=current.scheduler)
    value = freeze(current, input_domains=domains, checked_execution=execution).to_dict()
    assert value["denominator"]["missing_properties"] == 8
    assert value["denominator"]["unknown_properties"] == 1
    assert value["denominator"]["checked_properties"] == 0
    unknown, = [r["objectives"]["checked_property"] for r in value["rows"]
                if r["objectives"]["checked_property"]["status"] == "unknown"]
    assert unknown["target"] is None and not unknown["provenance"]["finite_correspondence_kernel_checked"]


@pytest.fixture(scope="module")
def numerical(current, qualified):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    checkpoint = os.environ.get("CODEBASE384_CHECKPOINT")
    if not checkpoint:
        pytest.skip("explicit pinned shared parent required")
    policy = {}

    def validate_copy(version, evaluation):
        return bool(policy.get("qualified") and version["artifact"] == policy["artifact"]
            and evaluation == dict(candidate_version_id=version["version_id"],
                protocol_id="unchanged-qualified-parent-copy@1", baseline_sha256=policy["baseline_sha256"]))

    registry = AutoencoderRegistry(current.root / "models.duckdb", current.root / "models",
                                   promotion_validator=validate_copy)
    path = Path(checkpoint)
    parent = source384.register_shared_parent(registry, checkpoint_path=path,
        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    parent_version = registry.get_version(parent)
    registry.initialize_head("initialize-main", parent_version["variant_id"], "main", parent)
    head = registry.resolve_head(parent_version["variant_id"], "main")
    arguments = dict(expected_head=current.head, frozen_corpus=qualified[0], registry=registry,
        parent_version_id=parent, branch="main", expected_model_head=head, operation_id="strict-fit",
        embedding_snapshot=os.environ["CODEBASE384_EMBEDDING_SNAPSHOT"], scheduler=current.scheduler,
        timeout_seconds=240, memory_mb=4096)
    result = generation.adapt_current_source384(current.index, current.repo, **arguments)
    value = generation.load_generation(current.index, registry, result["version_id"])
    policy.update(artifact=parent_version["artifact"], qualified=value["evaluation"]["parent_holdout"]["exact_targets"]
        == value["evaluation"]["parent_holdout"]["count"],
        baseline_sha256=source384._sha(source384._raw(value["evaluation"]["parent_holdout"])))
    write_public(current, "strict-fit-result", result)
    write_public(current, "strict-model-generation", value)
    try:
        yield SimpleNamespace(registry=registry, parent=parent, parent_version=parent_version,
            head=head, arguments=arguments, result=result, value=value, policy=policy)
    finally:
        registry.close()


def test_actual_strict_child_has_versioned_byte_layout_environment_and_run_binding(current, numerical):
    value, result = numerical.value, numerical.result
    assert result["training_executed"] and not result["promotion_performed"]
    assert value["schema"] == "codebase-model-generation@1"
    assert value["weights"]["layout"]["head_weights"][0] == 384
    assert value["randomness"]["seed"] is None
    assert value["randomness"]["policy"] == "no_random_parameters_or_stochastic_training"
    assert value["environment"]["numerical"]["dtype"] == "float64"
    assert value["objectives"]["auxiliary_objectives_used_to_update_weights"] is False
    assert value["parent_exposure"]["complete_parent_training_corpus_available"] is False
    assert value["evaluation"]["parent_holdout"]["count"] == value["evaluation"]["child_holdout"]["count"] == 3
    assert numerical.registry.resolve_head(numerical.parent_version["variant_id"], "main") == numerical.head


def test_exact_adaptation_replay_performs_no_second_fit(current, numerical):
    result = generation.adapt_current_source384(current.index, current.repo, **numerical.arguments)
    assert result["version_id"] == numerical.result["version_id"]
    assert result["replayed"] and not result["training_executed"]
    write_public(current, "strict-fit-replay", result)


def test_overall_deadline_is_consumed_before_fit_and_checked_before_attachment(current, numerical, monkeypatch):
    from threading import Event
    expired = Event()
    captured = []

    def terminal(*args, **kwargs):
        captured.append(kwargs["timeout_seconds"])
        assert 0 < kwargs["timeout_seconds"] < numerical.arguments["timeout_seconds"]
        expired.set()
        return deepcopy(numerical.result) | {"version_id": numerical.result["numerical_child_version_id"]}

    with monkeypatch.context() as patch:
        patch.setattr(source384, "train_current_source384", terminal)
        with pytest.raises(ValueError, match="adaptation cancelled or deadline expired"):
            generation.adapt_current_source384(current.index, current.repo,
                **dict(numerical.arguments, cancel_event=expired))
    assert len(captured) == 1
    assert numerical.registry.resolve_head(numerical.parent_version["variant_id"], "main") == numerical.head


def test_changed_source_after_retained_fit_cannot_attach_generation(current, numerical, monkeypatch):
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
    path = current.repo / "train_0.py"
    original = path.read_bytes()

    def changed_source(*args, **kwargs):
        path.write_text(source("*"))
        return deepcopy(numerical.result) | {"version_id": numerical.result["numerical_child_version_id"]}

    try:
        with monkeypatch.context() as patch:
            patch.setattr(source384, "train_current_source384", changed_source)
            with pytest.raises(StaleCodebaseError):
                generation.adapt_current_source384(current.index, current.repo, **numerical.arguments)
    finally:
        path.write_bytes(original)
    assert numerical.registry.resolve_head(numerical.parent_version["variant_id"], "main") == numerical.head


@pytest.mark.parametrize("damage", ["weights", "codebook", "layout", "seed", "environment", "parent", "source", "corpus", "expected_head"])
def test_resealed_generation_tampering_cannot_detach_native_numerical_work(current, numerical, damage):
    value = deepcopy(numerical.value)
    if damage == "weights": value["weights"]["head_sha256"] = "0" * 64
    elif damage == "codebook": value["weights"]["codebook_sha256"] = "0" * 64
    elif damage == "layout": value["weights"]["layout"]["arithmetic_dtype"] = "float32"
    elif damage == "seed": value["randomness"]["seed"] = 123
    elif damage == "environment":
        value["environment"]["worker_launch"]["device"] = "cuda"
        value["request"]["environment"] = deepcopy(value["environment"])
    elif damage == "parent": value["parent"]["checkpoint_sha256"] = "0" * 64
    elif damage == "source": value["source_head"]["generation"] += 1
    elif damage == "corpus": value["corpus_sha256"] = "0" * 64
    else: value["request"]["expected_model_head"]["generation"] += 1
    value["generation_sha256"] = source384._sha(source384._raw({k: v for k, v in value.items() if k != "generation_sha256"}))
    artifact = generation._stage(numerical.registry, value)
    version = numerical.registry.register_version("tamper-" + damage, numerical.parent_version["variant_id"],
        artifact, parent_version_id=numerical.parent)["version_id"]
    with pytest.raises(ValueError):
        generation.load_generation(current.index, numerical.registry, version)


def test_stale_expected_parent_is_refused_before_fit(current, numerical, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("stale head reached numerical fitting")
    arguments = deepcopy({k: v for k, v in numerical.arguments.items()
                          if k not in ("registry", "scheduler", "frozen_corpus")})
    arguments.update(registry=numerical.registry, scheduler=current.scheduler, frozen_corpus=numerical.arguments["frozen_corpus"])
    arguments["expected_model_head"]["generation"] += 1
    with monkeypatch.context() as patch:
        patch.setattr(source384, "train_current_source384", forbidden)
        with pytest.raises(ValueError, match="expected model head changed"):
            generation.adapt_current_source384(current.index, current.repo, **arguments)


def test_retention_failure_does_not_promote_child(current, numerical):
    evaluation = numerical.value["evaluation"]
    assert evaluation["child_holdout"]["exact_targets"] < evaluation["parent_holdout"]["exact_targets"]
    with pytest.raises(ValueError, match="retention gate failed"):
        generation.promote_generation(current.index, numerical.registry, numerical.result["version_id"],
                                     operation_id="reject-regressed-child")
    assert numerical.registry.resolve_head(numerical.parent_version["variant_id"], "main") == numerical.head
    write_public(current, "retention-refusal", dict(evaluation=evaluation, promoted=False,
        expected_head=numerical.head, actual_head=numerical.registry.resolve_head(numerical.parent_version["variant_id"], "main")))


def test_native_head_cas_uses_qualified_identical_parent_copies_and_refuses_stale_result(current, numerical, monkeypatch):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import RegistryError
    registry, variant = numerical.registry, numerical.parent_version["variant_id"]
    assert numerical.policy["qualified"]
    first = registry.register_version("copy-a", variant, numerical.parent_version["artifact"],
        metadata={"qualification_control": "unchanged-good-parent-copy-a"})["version_id"]
    second = registry.register_version("copy-b", variant, numerical.parent_version["artifact"],
        metadata={"qualification_control": "unchanged-good-parent-copy-b"})["version_id"]

    def evaluation(version):
        return dict(candidate_version_id=version, protocol_id="unchanged-qualified-parent-copy@1",
                    baseline_sha256=numerical.policy["baseline_sha256"])

    # Inject only a timing event after a retained genuine numerical result.
    # This control does not claim that another numerical fit executed.
    def changed_after_fit(*args, **kwargs):
        registry.promote_head("copy-cas-a", variant, "main", first,
            expected_version_id=numerical.parent, expected_generation=numerical.head["generation"],
            evaluation=evaluation(first))
        return deepcopy(numerical.result) | {"version_id": numerical.result["numerical_child_version_id"]}

    with monkeypatch.context() as patch:
        patch.setattr(source384, "train_current_source384", changed_after_fit)
        with pytest.raises(ValueError, match="expected model head changed"):
            generation.adapt_current_source384(current.index, current.repo, **numerical.arguments)
    with pytest.raises(RegistryError, match="compare-and-swap conflict"):
        registry.promote_head("copy-cas-b-stale", variant, "main", second,
            expected_version_id=numerical.parent, expected_generation=numerical.head["generation"],
            evaluation=evaluation(second))
    head = registry.resolve_head(variant, "main")
    assert head["version_id"] == first and head["generation"] == numerical.head["generation"] + 1
    assert head["version_id"] != numerical.result["numerical_child_version_id"]
    write_public(current, "native-head-cas", dict(before=numerical.head, after=head,
        copied_baseline_artifact=numerical.parent_version["artifact"], actual_trained_child_promoted=False,
        first_unchanged_parent_copy=first, stale_second_parent_copy=second,
        stale_compare_and_swap_refused=True, post_fit_head_change_refused=True,
        timing_control="injected return of retained real numerical result; no second-fit claim"))


def test_cold_generation_replay_uses_durable_owners_without_fitting(current, numerical):
    import sys
    numerical.registry.close()
    current.connection.close()
    script = '''
import json,sys,duckdb
from pathlib import Path
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts import codebase_model_generation as generation
from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as numerical
root=Path(sys.argv[1])
def forbidden(*args,**kwargs): raise AssertionError('read path attempted training')
numerical.train_current_source384=forbidden
numerical._worker=forbidden
with duckdb.connect(str(root/'source.duckdb'),config={'threads':1,'memory_limit':'64MB'}) as connection:
    store=DuckDBASTStore(connection=connection); artifacts=ImmutableCAS(root/'cas')
    index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=artifacts,catalog=CodebaseCatalog(store,artifacts))
    with AutoencoderRegistry(root/'models.duckdb',root/'models') as registry:
        value=generation.load_generation(index,registry,sys.argv[2])
        assert value['generation_sha256']==sys.argv[3]
        assert not value['promotion_performed']
        print('COLD_GENERATION_PASSED')
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(current.root),
        numerical.result["version_id"], numerical.value["generation_sha256"]],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("COLD_GENERATION_PASSED\n")
    write_public(current, "cold-generation-replay", dict(returncode=result.returncode,
        generation_sha256=numerical.value["generation_sha256"], training_executed=False,
        fresh_native_source_and_model_owners=True))
