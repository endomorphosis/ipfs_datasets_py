"""Source-bound receipts must survive independent checks before completion."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]


def load_standalone(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load_standalone(
    "legal_ir_supervisor_contract_test_owner",
    ROOT / "scripts/ops/legal_ir/legal_ir_supervisor_contract.py",
)
inventory = load_standalone(
    "legal_ir_contract_inventory_test_owner",
    ROOT / "ipfs_datasets_py/logic/autoformal/constitution_inventory.py",
)


def raw(value):
    return json.dumps(value, sort_keys=True).encode()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw(value))


def false_row(**fields):
    return {"admitted": False, "formalized": False, **fields}


def seed_board(tmp_path):
    task_ids = ["LIRAE-CONST-A1", "LIRAE-USC-T01", "LIRAE-WIDTH-768", "LIRAE-METHOD-01"]
    plan = {"tasks": [{"task_id": task_id, "predicted_files": []} for task_id in task_ids]}
    write_json(tmp_path / contract.PLAN, plan)
    board = "# Reviewed tasks\n\n## Goal LIRAE-ROOT\n\n- title: Retained goal\n\n"
    for task_id, status in zip(task_ids, ["completed", "in_progress", "todo", "blocked"], strict=True):
        board += f"## {task_id} Retained title\n\n- status: {status}\n- acceptance: Keep original criterion\n- validation: none\n\n"
    (tmp_path / contract.BOARD).write_text(board)
    source = tmp_path / contract.CONSTITUTION
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / contract.CONSTITUTION, source)
    return task_ids


def test_enrichment_preserves_status_and_native_semicolon_commands_and_is_idempotent(tmp_path):
    task_ids = seed_board(tmp_path)
    assert contract.enrich(tmp_path) == {"task_count": 4, "enriched": True}
    plan = json.loads((tmp_path / contract.PLAN).read_text())
    board = (tmp_path / contract.BOARD).read_text()
    native = load_standalone(
        "legal_ir_contract_native_validation_commands",
        ROOT.parent.parent / "external/ipfs_accelerate/ipfs_accelerate_py/agent_supervisor/validation/validation_commands.py",
    )
    for task in plan["tasks"]:
        block = board.split("## " + task["task_id"] + " ", 1)[1].split("\n## ", 1)[0]
        declaration = next(line.removeprefix("- validation: ") for line in block.splitlines() if line.startswith("- validation: "))
        commands = native.split_validation_commands(declaration)
        assert commands == task["validation_commands"]
        assert len(commands) == 2
        assert " -m pytest " in commands[0]
        assert commands[1].endswith(" --check-task " + task["task_id"])
        assert task["outputs"] == [(contract.directory(task["task_id"]) / "receipt.json").as_posix()]
        assert (contract.directory(task["task_id"])).as_posix() in task["allowed_paths"]
        assert "." not in task["allowed_paths"]
        assert "tests/unit/logic/test_legal_ir_supervisor_contract.py" not in task["allowed_paths"]
    for status in ["completed", "in_progress", "todo", "blocked"]:
        assert "- status: " + status in board
    assert board.count("- acceptance: Keep original criterion") == len(task_ids)
    assert "## Goal LIRAE-ROOT" in board
    assert contract.check_board(tmp_path)["board_contract_valid"] is True
    before = [(tmp_path / path).read_bytes() for path in (contract.PLAN, contract.BOARD)]
    contract.enrich(tmp_path)
    assert before == [(tmp_path / path).read_bytes() for path in (contract.PLAN, contract.BOARD)]


def test_enrichment_refuses_missing_tasks_and_check_board_refuses_duplicates(tmp_path):
    seed_board(tmp_path)
    path = tmp_path / contract.BOARD
    original = path.read_text()
    path.write_text(original.split("## LIRAE-METHOD-01", 1)[0])
    with pytest.raises(contract.ContractError, match="task IDs differ"):
        contract.enrich(tmp_path)
    path.write_text(original)
    contract.enrich(tmp_path)
    path.write_text(path.read_text() + "\n## LIRAE-METHOD-01 duplicate\n")
    with pytest.raises(contract.ContractError, match="duplicate board task"):
        contract.check_board(tmp_path)


@pytest.mark.parametrize("bad", [True, 0, None, "false"], ids=['legacy-axis-0-00', 'legacy-axis-0-01', 'legacy-axis-0-02', 'legacy-axis-0-03'])
@pytest.mark.parametrize("field", ["admitted", "formalized", "roundtrip_ok"], ids=['legacy-axis-1-00', 'legacy-axis-1-01', 'legacy-axis-1-02'])
def test_flags_must_be_boolean_false_even_nested(field, bad):
    row = false_row(roundtrip_ok=False)
    contract.false_flags(row, constitution=True)
    row["nested"] = [{field: bad}]
    with pytest.raises(contract.ContractError, match="authority must stay false"):
        contract.false_flags(row, constitution=True)


def artifact_case(tmp_path, *, initial_symlink=False):
    task_id = "LIRAE-CONST-A1"
    path = tmp_path / contract.directory(task_id) / "spans.json"
    if initial_symlink:
        target = tmp_path / "unowned.json"
        write_json(target, [false_row(id="span-1")])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
    else:
        write_json(path, [false_row(id="span-1")])
    entry = {"kind": "spans", "path": path.relative_to(tmp_path).as_posix(), "sha256": contract.sha(path.read_bytes())}
    return task_id, path, {"artifacts": [entry]}


def test_artifact_digest_authenticates_actual_bytes_and_detects_tampering(tmp_path):
    task_id, path, receipt = artifact_case(tmp_path)
    assert contract.read_artifacts(tmp_path, task_id, receipt) == {"spans": path.read_bytes()}
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(contract.ContractError, match="hash/size differs"):
        contract.read_artifacts(tmp_path, task_id, receipt)


@pytest.mark.parametrize("attack", ["traversal", "absolute", "symlink", "empty", "duplicate", "receipt"], ids=['legacy-axis-0-00', 'legacy-axis-0-01', 'legacy-axis-0-02', 'legacy-axis-0-03', 'legacy-axis-0-04', 'legacy-axis-0-05'])
def test_artifacts_reject_authority_escape_and_ambiguous_references(tmp_path, attack):
    created_alias = created_target = None
    try:
        task_id, path, receipt = artifact_case(tmp_path, initial_symlink=attack == "symlink")
        entry = receipt["artifacts"][0]
        if attack == "traversal":
            entry["path"] = "../outside.json"
        elif attack == "absolute":
            entry["path"] = str(path)
        elif attack == "symlink":
            outside = tmp_path / "unowned.json"
            outside.write_bytes(path.read_bytes())
            path.unlink()
            created_alias, created_target = path, outside
            path.symlink_to(outside)
        elif attack == "empty":
            path.write_bytes(b"")
            entry["sha256"] = contract.sha(b"")
        elif attack == "duplicate":
            receipt["artifacts"].append(dict(entry))
        else:
            target = path.with_name("receipt.json")
            target.write_bytes(path.read_bytes())
            entry["path"] = target.relative_to(tmp_path).as_posix()
        with pytest.raises(contract.ContractError):
            contract.read_artifacts(tmp_path, task_id, receipt)
        if created_alias is not None:
            assert created_alias.is_symlink() and created_alias.readlink() == created_target
    finally:
        # Exact declared v2 fixture lifecycle; preserve unexpected leaves.
        if created_alias is not None and created_alias.is_symlink() and created_alias.readlink() == created_target:
            created_alias.unlink()


def constitution_case(task_id):
    text = (ROOT / contract.CONSTITUTION).read_text()
    digest = contract.sha(text.encode())
    unit = contract.selector(task_id)
    rows = [false_row(**row, source_id="national-archives-retained-20260923", source_text_sha256=digest, roundtrip_ok=False)
            for row in inventory.inventory_constitution(text)["spans"]
            if row["unit_id"] == unit or row["unit_id"].startswith(unit + ".")]
    source = {"source_id": "national-archives-retained-20260923", "text": text, "sha256": digest}
    receipt = {"source": {"source_id": source["source_id"], "sha256": digest},
               "evidence": {"unit_id": unit, "repeal_treated_as_obligation": False}}
    return receipt, {"source": raw(source), "spans": raw(rows)}


@pytest.mark.parametrize("task_id", ["LIRAE-CONST-PREAMBLE", "LIRAE-CONST-A1", "LIRAE-CONST-AM18", "LIRAE-CONST-AM21", "LIRAE-CONST-AM27"])
def test_constitution_accepts_exact_real_inventory_and_repeal(task_id):
    receipt, data = constitution_case(task_id)
    contract.validate_constitution(ROOT, task_id, receipt, data)


@pytest.mark.parametrize("attack", ["invented_source", "wrong_unit", "different_plaintext", "missing_span", "repeal_obligation"])
def test_constitution_rejects_unbound_source_partial_coverage_and_repeal_relabeling(attack):
    task_id = "LIRAE-CONST-AM21"
    receipt, data = constitution_case(task_id)
    if attack == "invented_source":
        source = json.loads(data["source"])
        source["text"] = "We the invented People."
        source["sha256"] = receipt["source"]["sha256"] = contract.sha(source["text"].encode())
        data["source"] = raw(source)
    elif attack == "wrong_unit":
        receipt["evidence"]["unit_id"] = "amend-18"
    elif attack == "repeal_obligation":
        receipt["evidence"]["repeal_treated_as_obligation"] = True
    else:
        rows = json.loads(data["spans"])
        if attack == "different_plaintext":
            rows[0]["text"] += " shall create an obligation."
        else:
            rows.pop()
        data["spans"] = raw(rows)
    with pytest.raises(contract.ContractError):
        contract.validate_constitution(ROOT, task_id, receipt, data)


def usc_case(monkeypatch):
    sources = [
        {"ipfs_cid": "not-selected", "text": "Outside shard."},
        {"ipfs_cid": "source-a", "text": "The officer shall retain the record."},
        {"ipfs_cid": "source-b", "text": "No parser-supported legal element."},
    ]
    requested = []
    monkeypatch.setattr(contract, "usc_rows", lambda title: requested.append(title) or deepcopy(sources))
    shard = {"title": "1", "start": 1, "end": 3, "count": 2}
    sections = [false_row(ipfs_cid=row["ipfs_cid"], text=row["text"],
                          source_text_sha256=contract.sha(row["text"].encode()),
                          status="spans" if index == 0 else "abstain", span_ids=["a-span"] if index == 0 else [],
                          reason="" if index == 0 else "unsupported_parser_elements")
                for index, row in enumerate(sources[1:])]
    spans = [false_row(id="a-span", source_ipfs_cid="source-a", text="retain the record",
                      source_text_sha256=sections[0]["source_text_sha256"])]
    receipt = {"source": {"repository": "justicedao/ipfs_uscode", "revision": contract.REVISION}, "evidence": dict(shard)}
    data = {"sections": raw(sections), "spans": raw(spans), "entities": raw([false_row(id="record", span_ids=["a-span"])])}
    return shard, receipt, data, requested


def test_uscode_accepts_every_exact_pinned_row_or_explicit_abstention(monkeypatch):
    shard, receipt, data, requested = usc_case(monkeypatch)
    contract.validate_uscode(shard, receipt, data)
    assert requested == ["1"]


@pytest.mark.parametrize("attack", ["revision", "count", "wrong_plaintext", "cross_source_span", "cross_source_section", "missing_reason", "unknown_entity_span", "duplicate_section"])
def test_uscode_rejects_cross_source_unaccounted_and_unbound_evidence(monkeypatch, attack):
    shard, receipt, data, _ = usc_case(monkeypatch)
    if attack == "revision":
        receipt["source"]["revision"] = "unreviewed-latest"
    else:
        label = "spans" if attack == "cross_source_span" else "entities" if attack == "unknown_entity_span" else "sections"
        rows = json.loads(data[label])
        if attack == "count":
            rows.pop()
        elif attack == "wrong_plaintext":
            rows[0]["text"] += " Added invented law."
        elif attack == "cross_source_span":
            rows[0]["source_ipfs_cid"] = "source-b"
        elif attack == "cross_source_section":
            rows[1].update(status="spans", span_ids=["a-span"])
        elif attack == "missing_reason":
            rows[1]["reason"] = " "
        elif attack == "unknown_entity_span":
            rows[0]["span_ids"] = ["not-a-real-span"]
        else:
            rows[1] = dict(rows[0])
        data[label] = raw(rows)
    with pytest.raises(contract.ContractError):
        contract.validate_uscode(shard, receipt, data)


def untitled_uscode_case(monkeypatch):
    sources = [
        {"ipfs_cid": None, "text": None, "source_row_index": 17},
        {"ipfs_cid": None, "text": None, "source_row_index": 52491},
    ]
    monkeypatch.setattr(contract, "usc_rows", lambda title: deepcopy(sources))
    shard = {"title": "NA", "start": 0, "end": 2, "count": 2}
    sections = [false_row(**source, source_text_sha256=None, status="abstain",
                          reason="pinned recovery manifest contains no plaintext", span_ids=[])
                for source in sources]
    receipt = {"source": {"repository": "justicedao/ipfs_uscode", "revision": contract.REVISION},
               "evidence": dict(shard)}
    data = {"sections": raw(sections), "spans": raw([]), "entities": raw([])}
    return shard, receipt, data


def test_untitled_null_cid_rows_remain_distinct_explicit_abstentions(monkeypatch):
    shard, receipt, data = untitled_uscode_case(monkeypatch)
    contract.validate_uscode(shard, receipt, data)
    rows = json.loads(data["sections"])
    assert [row["source_row_index"] for row in rows] == [17, 52491]
    assert all(row["text"] is row["source_text_sha256"] is None for row in rows)


@pytest.mark.parametrize("attack", ["duplicate_index", "missing_index", "invented_plaintext", "invented_empty_text", "invented_hash", "invented_span"])
def test_null_source_rows_reject_identity_collapse_and_invented_content(monkeypatch, attack):
    shard, receipt, data = untitled_uscode_case(monkeypatch)
    rows = json.loads(data["sections"])
    if attack == "duplicate_index":
        rows[1]["source_row_index"] = rows[0]["source_row_index"]
    elif attack == "missing_index":
        del rows[0]["source_row_index"]
    elif attack == "invented_plaintext":
        rows[0]["text"] = "Invented recovery statute."
    elif attack == "invented_empty_text":
        rows[0]["text"] = ""
    elif attack == "invented_hash":
        rows[0]["source_text_sha256"] = contract.sha(b"")
    else:
        rows[0]["span_ids"] = ["invented-span"]
    data["sections"] = raw(rows)
    with pytest.raises(contract.ContractError):
        contract.validate_uscode(shard, receipt, data)


def width_case(dimension):
    row = false_row(dimension=dimension, source_hashes=list(contract.SAMPLE_HASHES),
                    profile_id="asserted-profile", checkpoint_sha256=contract.sha(b"asserted-checkpoint"),
                    status="observed", training_executed=False,
                    metrics={"cosine_similarity": .5, "reconstruction_loss": .25},
                    corpus_default=dimension == 384, role="donor", token_ceiling=512,
                    encoder_executed=False, development_result={"successful": 0, "total": 12})
    return {"evidence": {"dimension": dimension}}, {"observation": raw(row)}


@pytest.mark.parametrize("dimension", [8, 384, 768, 4096])
def test_width_never_completes_from_asserted_metrics_without_actual_checkpoint(dimension):
    receipt, data = width_case(dimension)
    with pytest.raises(contract.ContractError):
        contract.validate_width("LIRAE-WIDTH-" + str(dimension), receipt, data)


@pytest.mark.parametrize("attack", ["unavailable", "training", "authority", "wrong_sources", "nan_metric"])
def test_width_rejects_unavailable_or_invalid_observations(attack):
    receipt, data = width_case(384)
    row = json.loads(data["observation"])
    if attack == "unavailable":
        row["status"] = "unavailable"
    elif attack == "training":
        row["training_executed"] = True
    elif attack == "authority":
        row["admitted"] = True
    elif attack == "wrong_sources":
        row["source_hashes"] = ["self-asserted"]
    else:
        row["metrics"]["cosine_similarity"] = float("nan")
    data.update(observation=raw(row), checkpoint=b"asserted-checkpoint")
    with pytest.raises(contract.ContractError):
        contract.validate_width("LIRAE-WIDTH-384", receipt, data)


def test_real_retained_source_pin_and_method_task_identity():
    source = ROOT / contract.CONSTITUTION
    assert source.stat().st_size == 48617
    assert contract.sha(source.read_bytes()) == "9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b"
    plan = json.loads((ROOT / contract.PLAN).read_text())
    methods = [task for task in plan["tasks"] if contract.kind(task["task_id"]) == "method"]
    assert [task["task_id"] for task in methods] == ["LIRAE-METHOD-01"]
    assert contract.REVISION == "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
    const_ids = {task["task_id"] for task in plan["tasks"] if contract.kind(task["task_id"]) == "constitution"}
    original_ids = set(contract.CONSTITUTION_TASKS)
    assert const_ids in (original_ids, original_ids | {contract.ANCILLARY_TASK})
    expected_count = 134 + int(contract.ANCILLARY_TASK in const_ids)
    assert contract.check_board(ROOT) == {"task_count": expected_count, "board_contract_valid": True}


def test_explicit_corpus_diagnostic_checks_real_pinned_bytes_without_changing_default(tmp_path, monkeypatch):
    import hashlib
    import pyarrow as pa
    import pyarrow.parquet as pq
    task_id = 'LIRAE-USC-T01'
    text = 'Retained source plaintext.'
    parquet = tmp_path / 'download.parquet'
    pq.write_table(pa.table({'ipfs_cid': ['source-cid'], 'title_number': ['1'],
                             'section_number': ['8'], 'text': [text]}), parquet)
    monkeypatch.setattr(contract, 'PARQUET_SHA256', hashlib.sha256(parquet.read_bytes()).hexdigest())
    default = tmp_path / 'unavailable-operator-cache.parquet'
    monkeypatch.setattr(contract, 'PINNED_PARQUET', default)
    shard = {'task_id': task_id, 'title': '1', 'start': 0, 'end': 1, 'count': 1}
    write_json(tmp_path / contract.PLAN, {'tasks': [{'task_id': task_id}], 'shards': [shard]})
    task_dir = contract.directory(task_id)
    artifacts = []
    for label, value in {'sections': [false_row(ipfs_cid='source-cid', text=text,
            source_text_sha256=contract.sha(text.encode()), status='abstain', reason='explicit uncompiled inventory')],
            'spans': [], 'entities': []}.items():
        path = task_dir / (label + '.json')
        write_json(tmp_path / path, value)
        artifacts.append({'kind': label, 'path': path.as_posix(), 'sha256': contract.sha((tmp_path / path).read_bytes())})
    write_json(tmp_path / task_dir / 'receipt.json', {'schema': contract.SCHEMA, 'task_id': task_id,
        'task_kind': 'uscode', 'status': 'inventory', 'authority': false_row(),
        'source': {'repository': 'justicedao/ipfs_uscode', 'revision': contract.REVISION},
        'evidence': shard, 'artifacts': artifacts})
    command = ['--root', str(tmp_path), '--check-task', task_id]
    assert contract.main(command) == 1
    assert contract.main(command + ['--corpus-parquet', str(parquet)]) == 0
    assert contract.PINNED_PARQUET == default
    assert contract.main(command) == 1
    parquet.write_bytes(parquet.read_bytes() + b'changed')
    assert contract.main(command + ['--corpus-parquet', str(parquet)]) == 1


def test_corpus_override_authenticates_digest_before_parsing(tmp_path, monkeypatch):
    source = tmp_path / 'untrusted.parquet'
    source.write_bytes(b'invented corpus')
    monkeypatch.setattr(contract, 'PARQUET_SHA256', '0' * 64)
    with pytest.raises(contract.ContractError, match='digest differs'):
        contract.usc_rows('1', source_parquet=source)


# Programme coding preparation extends the existing owner; retained inventory stays frozen.
def programme_bundle():
    return json.loads((ROOT / contract.PLAN).read_text())['programme_engineering']


def programme_case(tmp_path, monkeypatch, *, initial_symlink=False):
    task = deepcopy(programme_bundle()['prepared_tasks'][0])
    monkeypatch.setattr(contract, '_require_programme_source_alignment',
                        lambda root: dict(contract.PROGRAMME_SOURCE_BINDING))
    changes = []
    for value in (task['owner_paths'][0], task['test_paths'][0]):
        path = tmp_path / value
        path.parent.mkdir(parents=True, exist_ok=True)
        if initial_symlink and value == task['owner_paths'][0]:
            target = tmp_path / 'outside.py'
            target.write_text('independently changed owner or test\n')
            path.symlink_to(target)
        else:
            path.write_text('independently changed owner or test\n')
        changes.append({'path': value, 'sha256': contract.sha(path.read_bytes())})
    receipt = {'status': 'implemented', 'parent_reference': task['parent_reference'],
               'source_binding': contract.PROGRAMME_SOURCE_BINDING,
               'implementation_route': contract.PROGRAMME_ROUTE, 'outcome': 'implemented', 'code_changes': changes}
    preparation = {'schema': 'legal-ir-programme-engineering-preparation/v1',
        'task_id': task['task_id'], 'parent_reference': task['parent_reference'],
        'source_binding': contract.PROGRAMME_SOURCE_BINDING,
        'admitted': False, 'formalized': False, 'semantic_review_performed': False,
        'model_gain_claimed': False, 'training_executed': False,
        'result': {key: ['unresolved preparation observation'] for key in task['result_fields']}}
    return task, receipt, preparation


def test_programme_bundle_preserves_all_135_records_metadata_and_native_cids():
    bundle = contract.check_programme_engineering_plan(ROOT)
    assert bundle['legacy_preservation']['task_count'] == 135
    assert {task['home_shard'] for task in bundle['prepared_tasks']} == {0, 1, 2, 3}
    assert len({task['goal_id'] for task in bundle['prepared_tasks']}) == 4
    native = load_standalone('legal_ir_programme_native_identity', ROOT.parent.parent /
        'external/ipfs_accelerate/ipfs_accelerate_py/agent_supervisor/task_sources/task_identity.py')
    blocks = contract._programme_task_blocks((ROOT / contract.BOARD).read_text())
    for task_id, block in blocks.items():
        title = block.splitlines()[0].split(' ', 2)[2]
        metadata = dict(line[2:].split(':', 1) for line in block.splitlines()[1:]
                        if line.startswith('- ') and ':' in line)
        metadata = {key.strip().lower(): value.strip() for key, value in metadata.items()}
        assert metadata['status'] == 'completed'
        old_task = next(task for task in json.loads((ROOT / contract.PLAN).read_text())['tasks']
                        if task['task_id'] == task_id)
        assert metadata.get('provider role') == old_task.get('provider_role')
        assert metadata.get('context budget tokens') == (str(old_task['context_budget_tokens'])
                if 'context_budget_tokens' in old_task else None)
        identity = native.canonical_task_identity(dict(task_id=task_id, title=title,
            outputs=metadata['outputs'].split(', '), acceptance=metadata['acceptance'],
            metadata=metadata), board_namespace='legal-ir-autoencoder-v1')
        assert identity.canonical_task_cid == bundle['legacy_preservation']['canonical_task_cids'][task_id]


def test_programme_entries_are_native_append_compatible_without_writes(monkeypatch):
    monkeypatch.setattr(contract, '_require_programme_source_alignment',
                        lambda root: dict(contract.PROGRAMME_SOURCE_BINDING))
    before = [(ROOT / path).read_bytes() for path in (contract.PLAN, contract.BOARD)]
    result = contract.prepare_programme_engineering(ROOT)
    assert result['completion_authority'] is result['mutation_authority'] is False
    monkeypatch.syspath_prepend(str(ROOT.parent.parent / 'external/ipfs_accelerate'))
    from ipfs_accelerate_py.agent_supervisor.task_sources.taskboard_store import (
        TaskboardMaterializationEntry, preview_taskboard_materialization,
    )
    entries = [TaskboardMaterializationEntry(**entry) for entry in result['entries']]
    preview = preview_taskboard_materialization((ROOT / contract.BOARD).read_text(), entries)
    assert len(preview.entries) == 4
    assert len(contract._programme_task_blocks(preview.candidate_text)) == 139
    for task, entry in zip(result['plan_task_additions'], result['entries'], strict=True):
        assert task['provider_role'] == 'grok-implement' and task['context_budget_tokens'] == 48000
        assert '- parent goal id: ' + task['parent_task_id'] in entry['rendered_block']
        assert '- provider role: grok-implement' in entry['rendered_block']
        assert '- context budget tokens: 48000' in entry['rendered_block']
        assert task['implementation_route'] == contract.PROGRAMME_ROUTE
        assert contract.task_contract(task) == contract.programme_engineering_contract(task)
    assert before == [(ROOT / path).read_bytes() for path in (contract.PLAN, contract.BOARD)]


@pytest.mark.parametrize('attack', ['unknown_id', 'parent', 'route', 'zero', 'negative', 'boolean',
                                    'escape_owner', 'escape_allowed', 'unknown_field'], ids=['legacy-axis-0-00', 'legacy-axis-0-01', 'legacy-axis-0-02', 'legacy-axis-0-03', 'legacy-axis-0-04', 'legacy-axis-0-05', 'legacy-axis-0-06', 'legacy-axis-0-07', 'legacy-axis-0-08'])
def test_programme_coding_contract_rejects_malformed_or_broadened_authority(attack):
    task = deepcopy(programme_bundle()['prepared_tasks'][0])
    if attack == 'unknown_id': task['task_id'] = 'LIRAE-USC-T01'
    elif attack == 'parent': task['parent_reference']['task_id'] = 'LIR-16'
    elif attack == 'route': task['implementation_route']['primary_model_id'] = 'unreviewed'
    elif attack in ('zero', 'negative', 'boolean'):
        task['context_budget_tokens'] = {'zero': 0, 'negative': -1, 'boolean': True}[attack]
    elif attack == 'escape_owner': task['owner_paths'][0] = '../outside.py'
    elif attack == 'escape_allowed': task['allowed_paths'] = ['../outside.py']
    else: task['implementation command'] = 'unreviewed executable'
    with pytest.raises(contract.ContractError):
        contract.programme_engineering_contract(task)


@pytest.mark.parametrize('value', ['/tmp/out', '../out', 'owner/../out', './owner',
                                  'owner//file', 'owner/*.py', 'owner\\file', 'owner\x00file'], ids=['legacy-axis-0-00', 'legacy-axis-0-01', 'legacy-axis-0-02', 'legacy-axis-0-03', 'legacy-axis-0-04', 'legacy-axis-0-05', 'legacy-axis-0-06', 'legacy-axis-0-07'])
def test_programme_paths_reject_escape_aliases_and_globs(value):
    with pytest.raises(contract.ContractError):
        contract._programme_safe_path(value)


@pytest.mark.parametrize('attack', ['old_id', 'old_metadata', 'old_board', 'baseline', 'child_parent'], ids=['legacy-axis-0-00', 'legacy-axis-0-01', 'legacy-axis-0-02', 'legacy-axis-0-03', 'legacy-axis-0-04'])
def test_programme_preservation_rejects_changed_legacy_or_parent_binding(tmp_path, attack):
    plan = json.loads((ROOT / contract.PLAN).read_text())
    board = (ROOT / contract.BOARD).read_text()
    if attack == 'old_id': plan['tasks'][0]['task_id'] = 'LIRAE-USC-REUSED'
    elif attack == 'old_metadata': plan['tasks'][0]['provider_role'] = 'grok-implement'
    elif attack == 'old_board': board = board.replace('- status: completed', '- status: todo', 1)
    elif attack == 'baseline': plan['programme_engineering']['legacy_preservation']['task_count'] = 134
    else: plan['programme_engineering']['prepared_tasks'][0]['parent_reference']['revision'] = 'latest'
    path = tmp_path / contract.BOARD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(board)
    with pytest.raises(contract.ContractError):
        contract.check_programme_engineering_plan(tmp_path, plan)


def test_programme_old_source_snapshot_cannot_materialize_or_enrich(tmp_path, monkeypatch):
    before = [(ROOT / path).read_bytes() for path in (contract.PLAN, contract.BOARD)]
    with pytest.raises(contract.ContractError, match='public main must be integrated'):
        contract._require_programme_source_alignment(tmp_path)
    def old_snapshot(root):
        raise contract.ContractError('current public main must be integrated before programme dispatch')
    monkeypatch.setattr(contract, '_require_programme_source_alignment', old_snapshot)
    with pytest.raises(contract.ContractError, match='public main must be integrated'):
        contract.prepare_programme_engineering(ROOT)
    with pytest.raises(contract.ContractError, match='enrichment is forbidden'):
        contract.enrich(ROOT)
    assert before == [(ROOT / path).read_bytes() for path in (contract.PLAN, contract.BOARD)]


def test_programme_receipt_authenticates_actual_owner_test_changes(tmp_path, monkeypatch):
    task, receipt, preparation = programme_case(tmp_path, monkeypatch)
    assert contract.validate_programme_engineering(tmp_path, task, receipt,
                                                  {'preparation': raw(preparation)}) is True


@pytest.mark.parametrize('attack', ['training', 'review', 'gain', 'parent', 'route', 'no_tests',
                                    'escape', 'symlink', 'hash', 'empty_result', 'nonfinite', 'artifact'], ids=['legacy-axis-0-00', 'legacy-axis-0-01', 'legacy-axis-0-02', 'legacy-axis-0-03', 'legacy-axis-0-04', 'legacy-axis-0-05', 'legacy-axis-0-06', 'legacy-axis-0-07', 'legacy-axis-0-08', 'legacy-axis-0-09', 'legacy-axis-0-10', 'legacy-axis-0-11'])
def test_programme_receipt_rejects_forged_completion_or_execution_claims(tmp_path, monkeypatch, attack):
    created_alias = created_target = None
    try:
        task, receipt, preparation = programme_case(tmp_path, monkeypatch, initial_symlink=attack == 'symlink')
        if attack in ('training', 'review', 'gain'):
            preparation[{'training': 'training_executed', 'review': 'semantic_review_performed',
                         'gain': 'model_gain_claimed'}[attack]] = True
        elif attack == 'parent': receipt['parent_reference'] = {'task_id': 'LIR-16'}
        elif attack == 'route': receipt['implementation_route'] = {'primary_provider_id': 'codex'}
        elif attack == 'no_tests': receipt['code_changes'].pop()
        elif attack == 'escape': receipt['code_changes'][0]['path'] = '../outside.py'
        elif attack == 'symlink':
            path = tmp_path / receipt['code_changes'][0]['path']
            target = tmp_path / 'outside.py'
            target.write_bytes(path.read_bytes())
            path.unlink()
            created_alias, created_target = path, target
            path.symlink_to(target)
        elif attack == 'hash': receipt['code_changes'][0]['sha256'] = '0' * 64
        elif attack == 'empty_result': preparation['result'][task['result_fields'][0]] = []
        elif attack == 'nonfinite': preparation['result'][task['result_fields'][0]] = float('nan')
        data = {'preparation': raw(preparation)}
        if attack == 'artifact': data['asserted-results'] = b'{}'
        with pytest.raises((contract.ContractError, ValueError)):
            contract.validate_programme_engineering(tmp_path, task, receipt, data)
        if created_alias is not None:
            assert created_alias.is_symlink() and created_alias.readlink() == created_target
    finally:
        # Exact declared v2 fixture lifecycle; preserve unexpected leaves.
        if created_alias is not None and created_alias.is_symlink() and created_alias.readlink() == created_target:
            created_alias.unlink()



def qualified_reuse_case(tmp_path, monkeypatch):
    import ast
    import subprocess
    task, receipt, preparation = programme_case(tmp_path, monkeypatch)
    for value in task['source_file_sha256']:
        data = subprocess.run(['git', '-C', str(ROOT), 'show', contract.PROGRAMME_PUBLIC_MAIN + ':' + value],
                              capture_output=True, check=True).stdout
        path = tmp_path / value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    value = task['owner_paths'][0]
    symbol = next(node.name for node in ast.parse((tmp_path / value).read_bytes()).body
                  if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith('_'))
    receipt.update(outcome='qualified_reuse', code_changes=[], qualified_reuse={
        'schema': 'legal-ir-programme-qualified-reuse/v1',
        'api_bindings': [dict(path=value, symbol=symbol, sha256=task['source_file_sha256'][value])],
        'test_bindings': [dict(path=path, sha256=task['source_file_sha256'][path]) for path in task['test_paths']],
        'result_sha256': contract.sha(contract._programme_json(preparation['result']))})
    return task, receipt, preparation


def test_programme_qualified_reuse_accepts_existing_api_without_fabricated_code_changes(tmp_path, monkeypatch):
    task, receipt, preparation = qualified_reuse_case(tmp_path, monkeypatch)
    assert contract.validate_programme_engineering(tmp_path, task, receipt, {'preparation': raw(preparation)})


@pytest.mark.parametrize('attack', ['symbol', 'source_hash', 'result_hash', 'test_hash', 'code_change', 'changed_owner'])
def test_programme_qualified_reuse_rejects_unauthenticated_api_or_result(tmp_path, monkeypatch, attack):
    task, receipt, preparation = qualified_reuse_case(tmp_path, monkeypatch)
    reuse = receipt['qualified_reuse']
    if attack == 'symbol': reuse['api_bindings'][0]['symbol'] = 'invented_export'
    elif attack == 'source_hash': reuse['api_bindings'][0]['sha256'] = '0' * 64
    elif attack == 'result_hash': reuse['result_sha256'] = '0' * 64
    elif attack == 'test_hash': reuse['test_bindings'][0]['sha256'] = '0' * 64
    elif attack == 'code_change': receipt['code_changes'] = [{'path': task['owner_paths'][0], 'sha256': '0' * 64}]
    else: (tmp_path / task['owner_paths'][0]).write_text('invented implementation')
    with pytest.raises(contract.ContractError):
        contract.validate_programme_engineering(tmp_path, task, receipt, {'preparation': raw(preparation)})


def test_programme_profile_targets_new_numerical_wiring_and_preserves_checkpoint_owners():
    task = programme_bundle()['prepared_tasks'][3]
    assert task['owner_paths'] == ['ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_training_v1.py']
    assert all(value is None for value in task['source_file_sha256'].values())
    assert all(path not in task['owner_paths'] for path in task['read_only_source_sha256'])
    assert '650 inactive scalars' in task['objective'] and '130 active scalars' in task['objective']
    assert 'all72gold-present TRAIN rows' in task['objective'] and 'conditions row3' in task['objective']
    assert 'new frozen38-tensor seal from the F18 donor' in task['objective']
    assert 'Start from all42 authenticated F18 donor tensors, not F15' in task['objective']
    assert any(path.endswith('legal_span_modality_conditions_retention.py') for path in task['read_only_source_sha256'])
    assert any(path.endswith('conditions_fullspan_margin_v1.py') for path in task['read_only_source_sha256'])
    assert any(path.endswith('structured_span_objective.py') for path in task['read_only_source_sha256'])
    assert task['completion_scope'] == 'engineering_preparation_only'
    assert task['satisfies_parent_semantic_dependencies'] is False


def _continuation_ref_for(path, root):
    data = path.read_bytes()
    return dict(path=path.relative_to(root).as_posix(), bytes=len(data), sha256=contract.sha(data))


def _continuation_case(tmp_path, monkeypatch, *, initial_symlink=False):
    """Synthetic evidence exercises the audit checker, not model qualification."""
    def evidence(name, value):
        path = tmp_path / 'retained' / name
        if initial_symlink and name == 'input.json':
            target = path.with_name('target.json')
            write_json(target, value)
            path.symlink_to(target)
        else:
            write_json(path, value)
        return _continuation_ref_for(path, tmp_path)
    owners = [evidence('owner.json', {'source': 'owner'}), evidence('test.json', {'source': 'test'})]
    inputs = [evidence('input.json', {'fixture': 'bounded'})]
    request = evidence('request.json', {'operation': 'original-finite-qualification',
        'source_sha256': {ref['path']: ref['sha256'] for ref in [*owners, *inputs]}})
    verifier = evidence('verifier.json', {'source': 'original-independent-verifier'})
    result = evidence('result.json', {'collected_absolute_checks': ['case1', 'case2', 'case3'],
        'pytest_returncode': 0, 'all_phases_passed': True, 'closing_errors': [],
        'actual_executed_paths': [ref['path'] for ref in owners],
        'actual_compiled_source_utf8': {ref['path']: (tmp_path / ref['path']).read_text() for ref in owners},
        'opening_frozen_sources': {ref['path']: {key: ref[key] for key in ('bytes', 'sha256')} for ref in owners},
        'closing_frozen_sources': {ref['path']: {key: ref[key] for key in ('bytes', 'sha256')} for ref in owners}})
    reap = evidence('reap.json', {'completed': True, 'outer_exec_genuinely_reaped': True,
        'outer_exec_exit_code': 0, 'request': request, 'result': result})
    closeout = evidence('original-closeout.json', {'accepted': True, 'completed': True,
        'source_native_storage_closed': True, 'source_READ_closed': True,
        'actual_storage_record': {'status': 'released'}, 'auditor': verifier,
        'request': request, 'result': result, 'root_actual_outer_reap': reap})
    binding = dict(candidate_sources=owners, inputs=inputs, request=request, verifier=verifier,
        result=result, native=closeout, storage=closeout, source=closeout, reap=reap,
        candidate_qualification=closeout,
        independent_verifier_id='sha256:' + verifier['sha256'],
        assertions={name: dict(role=role,
            path=[{'cases': 'collected_absolute_checks', 'actual_executed_source_count': 'actual_compiled_source_utf8',
                   'returncode': 'outer_exec_exit_code', 'outer_reaped': 'outer_exec_genuinely_reaped',
                   'native_accepted': 'accepted', 'native_completed': 'completed',
                   'native_custody_closed': 'source_native_storage_closed',
                   'storage_closed': 'source_native_storage_closed'}.get(name, name)]
                if name != 'storage_status' else ['actual_storage_record', 'status'],
            expected=3 if name == 'cases' else 2 if name == 'actual_executed_source_count' else expected)
            for name, (role, expected) in contract.CONTINUATION_ASSERTIONS.items()},
        executed_source_correspondence=[dict(candidate_path=ref['path'], executed_path=ref['path']) for ref in owners],
        request_correspondence=dict(role='native', path=['request']))
    tasks = [dict(task_id=task_id, title='Audit already qualified ' + operation,
        engineering_continuation=contract.CONTINUATION_SCHEMA, operation_kind=operation,
        goal_id='LIR-17.continuation.' + str(index), parent_task_id='LIR-17',
        parent_reference=dict(repository='ipfs_datasets_py', revision='a' * 40,
            path='ipfs_datasets_py/logic/autoformal/docs/BACKLOG.json',
            task_id='LIR-17', task_sha256='b' * 64),
        binding=deepcopy(binding), limits=deepcopy(contract.CONTINUATION_LIMITS))
        for index, (task_id, operation) in enumerate(contract.CONTINUATION_SPECS.items())]
    retained = [dict(task_id='LIRAE-RETAINED-' + str(index)) for index in range(139)]
    board = '# Retained board\n\n' + '\n'.join('## ' + task['task_id']
        + ' Existing\n- status: completed\n' for task in retained)
    (tmp_path / contract.BOARD).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / contract.BOARD).write_text(board)
    receipts = []
    for task in retained:
        ref = evidence(task['task_id'] + '.json', {'completed': task['task_id']})
        receipts.append(dict(task_id=task['task_id'], **ref))
    baseline = dict(schema='legal-ir-supervisor-continuation-baseline/v1', task_count=139,
        board_bytes=len(board.encode()), board_sha256=contract.sha(board.encode()),
        board_revision='taskboard:sha256:' + contract.sha(b'agent-supervisor-taskboard-revision-v1\0' + board.encode()),
        plan_tasks_sha256=contract.sha(contract._programme_json(retained)), receipts=receipts)
    for name, value in (
        ('CONTINUATION_BASE_BOARD_BYTES', len(board.encode())),
        ('CONTINUATION_BASE_BOARD_SHA256', baseline['board_sha256']),
        ('CONTINUATION_BASE_TASKS_SHA256', baseline['plan_tasks_sha256']),
        ('CONTINUATION_BASELINE_SHA256', contract.sha(json.dumps(baseline, sort_keys=True, indent=2).encode() + b'\n'))):
        monkeypatch.setattr(contract, name, value)
    monkeypatch.setattr(contract, 'check_programme_engineering_plan', lambda root, plan=None: {})
    monkeypatch.setattr(contract, '_require_programme_source_alignment', lambda root: {})
    plan = dict(tasks=retained)
    write_json(tmp_path / contract.PLAN, plan)
    bundle = dict(schema=contract.CONTINUATION_SCHEMA, baseline=baseline, tasks=tasks,
        dispatch_authorized_by_this_metadata=False, completion_authority=False)
    return plan, bundle


def _refresh_continuation_shared_ref(binding, root, path):
    ref = _continuation_ref_for(path, root)
    for role in ('candidate_qualification', 'native', 'storage', 'source', 'reap'):
        if binding[role]['path'] == ref['path']:
            binding[role] = deepcopy(ref)


def _rebind_continuation_result(binding, root, path):
    binding['result'] = _continuation_ref_for(path, root)
    reap_path = root / binding['reap']['path']; reap = json.loads(reap_path.read_bytes())
    reap['result'] = binding['result']; write_json(reap_path, reap)
    _refresh_continuation_shared_ref(binding, root, reap_path)
    qualified_path = root / binding['candidate_qualification']['path']
    qualified = json.loads(qualified_path.read_bytes())
    qualified.update(result=binding['result'], root_actual_outer_reap=binding['reap'])
    write_json(qualified_path, qualified)
    _refresh_continuation_shared_ref(binding, root, qualified_path)


def _adopt_continuation_fixture(root, plan, bundle):
    updated = dict(plan, engineering_continuation=bundle,
        tasks=plan['tasks'] + [{**task, **contract.continuation_contract(task)} for task in bundle['tasks']])
    write_json(root / contract.PLAN, updated)
    original = (root / contract.BOARD).read_bytes()
    (root / contract.BOARD).write_bytes(original + b'\n' + '\n\n'.join(
        contract.render_continuation_task(task) for task in bundle['tasks']).encode() + b'\n')
    return updated


def test_continuation_prepares_two_disjoint_local_audits_without_writes(tmp_path, monkeypatch):
    plan, bundle = _continuation_case(tmp_path, monkeypatch)
    before = [(tmp_path / path).read_bytes() for path in (contract.PLAN, contract.BOARD)]
    delta = contract.prepare_continuation(tmp_path, bundle)
    assert len(delta['entries']) == len(delta['plan_task_additions']) == 2
    assert delta['dispatch_authorized_by_this_metadata'] is delta['completion_authority'] is delta['mutation_authority'] is False
    assert before == [(tmp_path / path).read_bytes() for path in (contract.PLAN, contract.BOARD)]
    first, second = delta['plan_task_additions']
    assert set(first['allowed_paths']).isdisjoint(second['allowed_paths'])
    for task in (first, second):
        assert task['provider_role'] == 'deterministic-only' and task['context_budget_tokens'] == 0
        assert len(task['validation_commands']) == 1, 'producer and consumer must share one scheduled unit'
        assert contract.kind(task['task_id']) == 'continuation_validation'
        assert len(task['outputs']) == 2 and all(path.endswith('.json') for path in task['outputs'])
        assert all(' --materialize-continuation-validation ' in command or ' --check-task ' in command
                   for command in task['validation_commands'])
        assert not any('pytest' in command or 'grok' in command for command in task['validation_commands'])
        binding = task['binding']
        assert binding['candidate_qualification'] == binding['native'] == binding['storage'] == binding['source']


def test_continuation_materializes_and_checks_exact_receipts_only(tmp_path, monkeypatch):
    plan, bundle = _continuation_case(tmp_path, monkeypatch)
    _adopt_continuation_fixture(tmp_path, plan, bundle)
    old = {ref['path']: (tmp_path / ref['path']).read_bytes() for ref in bundle['baseline']['receipts']}
    task_id = bundle['tasks'][0]['task_id']
    result = contract.materialize_continuation_validation(tmp_path, task_id)
    assert result['materialized'] is True and result['tests_rerun'] is False
    assert contract.validate(tmp_path, task_id)['validated'] is True
    audit = json.loads((tmp_path / contract.continuation_directory(task_id) / 'validation.json').read_bytes())
    assert audit['new_audit_model_call_count'] == audit['new_audit_provider_call_count'] == 0
    assert 'model_call_count' not in audit['observations'] and 'provider_call_count' not in audit['observations']
    assert old == {path: (tmp_path / path).read_bytes() for path in old}
    paths = [tmp_path / path for path in contract.continuation_contract(bundle['tasks'][0])['outputs']]
    before = [path.read_bytes() for path in paths]
    contract.materialize_continuation_validation(tmp_path, task_id)
    assert before == [path.read_bytes() for path in paths]


@pytest.mark.parametrize('attack', ['kind', 'unknown', 'parent', 'scope', 'provider', 'context',
    'boolean_context', 'shell', 'limits', 'boolean_limit', 'zero_cases', 'boolean_cases', 'false_native',
    'boolean_returncode', 'missing_assertion', 'extra_binding', 'verifier'], ids=['case-kind', 'case-unknown', 'case-parent', 'case-scope', 'case-provider', 'case-context', 'case-boolean_context', 'case-shell', 'case-limits', 'case-boolean_limit', 'case-zero_cases', 'case-boolean_cases', 'case-false_native', 'case-boolean_returncode', 'case-missing_assertion', 'case-extra_binding', 'case-verifier'])
def test_continuation_closed_contract_rejects_broadened_or_nonpositive_tasks(tmp_path, monkeypatch, attack):
    _, bundle = _continuation_case(tmp_path, monkeypatch)
    task = deepcopy(bundle['tasks'][0])
    if attack == 'kind': task['operation_kind'] = 'training'
    elif attack == 'unknown': task['task_id'] = 'LIRAE-CONT-ARBITRARY-01'
    elif attack == 'parent': task['parent_reference']['task_sha256'] = 'latest'
    elif attack == 'scope': task['allowed_paths'] = ['.']
    elif attack == 'provider': task['provider_role'] = 'grok-implement'
    elif attack == 'context': task['context_budget_tokens'] = 48000
    elif attack == 'boolean_context': task['context_budget_tokens'] = False
    elif attack == 'shell': task['validation_commands'] = ['sh -c arbitrary']
    elif attack == 'limits': task['limits']['attempts'] = 2
    elif attack == 'boolean_limit': task['limits']['attempts'] = True
    elif attack == 'zero_cases': task['binding']['assertions']['cases']['expected'] = 0
    elif attack == 'boolean_cases': task['binding']['assertions']['cases']['expected'] = True
    elif attack == 'false_native': task['binding']['assertions']['native_accepted']['expected'] = False
    elif attack == 'boolean_returncode': task['binding']['assertions']['returncode']['expected'] = False
    elif attack == 'missing_assertion': del task['binding']['assertions']['storage_closed']
    elif attack == 'extra_binding': task['binding']['arbitrary_argv'] = ['grok']
    elif attack == 'verifier': task['binding']['independent_verifier_id'] = ''
    with pytest.raises(contract.ContractError):
        contract.continuation_contract(task)


@pytest.mark.parametrize('attack', ['source_bytes', 'zero_actual_cases', 'executed_source',
    'missing_executed_source', 'request_link', 'qualifier', 'native', 'storage', 'source',
    'input_pin', 'alias', 'outside', 'symlink', 'filename_only', 'opening_source',
    'closing_source', 'duplicate_cases', 'nonpassing_phases', 'boolean_result_returncode',
    'boolean_native_returncode', 'conflicting_shared_closure', 'duplicate_candidates',
    'duplicate_inputs', 'scope_alias'], ids=['case-source_bytes', 'case-zero_actual_cases', 'case-executed_source', 'case-missing_executed_source', 'case-request_link', 'case-qualifier', 'case-native', 'case-storage', 'case-source', 'case-input_pin', 'case-alias', 'case-outside', 'case-symlink', 'case-filename_only', 'case-opening_source', 'case-closing_source', 'case-duplicate_cases', 'case-nonpassing_phases', 'case-boolean_result_returncode', 'case-boolean_native_returncode', 'case-conflicting_shared_closure', 'case-duplicate_candidates', 'case-duplicate_inputs', 'case-scope_alias'])
def test_continuation_requires_actual_pinned_correspondence_and_closed_original_custody(tmp_path, monkeypatch, attack):
    created_alias = created_target = None
    try:
        _, bundle = _continuation_case(tmp_path, monkeypatch, initial_symlink=attack == 'symlink')
        task = deepcopy(bundle['tasks'][0]); binding = task['binding']
        if attack == 'source_bytes':
            (tmp_path / binding['candidate_sources'][0]['path']).write_bytes(b'changed candidate')
        elif attack in {'zero_actual_cases', 'executed_source', 'filename_only', 'opening_source',
                        'closing_source', 'duplicate_cases', 'nonpassing_phases', 'boolean_result_returncode'}:
            path = tmp_path / binding['result']['path']; value = json.loads(path.read_bytes())
            if attack == 'zero_actual_cases': value['collected_absolute_checks'] = []
            elif attack == 'executed_source': value['actual_compiled_source_utf8'][binding['candidate_sources'][0]['path']] = 'fabricated body'
            elif attack == 'filename_only': del value['actual_compiled_source_utf8'][binding['candidate_sources'][0]['path']]
            elif attack in {'opening_source', 'closing_source'}:
                value['opening_frozen_sources' if attack == 'opening_source' else 'closing_frozen_sources'][binding['candidate_sources'][0]['path']]['sha256'] = 'f' * 64
            elif attack == 'duplicate_cases': value['collected_absolute_checks'].append(value['collected_absolute_checks'][0])
            elif attack == 'nonpassing_phases': value['all_phases_passed'] = False
            else: value['pytest_returncode'] = False
            write_json(path, value); _rebind_continuation_result(binding, tmp_path, path)
        elif attack == 'missing_executed_source': binding['executed_source_correspondence'].pop()
        elif attack == 'request_link': binding['request_correspondence']['path'] = ['accepted']
        elif attack == 'qualifier':
            path = tmp_path / binding['candidate_qualification']['path']; value = json.loads(path.read_bytes())
            value['auditor']['sha256'] = 'f' * 64; write_json(path, value)
            _refresh_continuation_shared_ref(binding, tmp_path, path)
        elif attack in {'native', 'storage', 'source', 'boolean_native_returncode'}:
            role = 'reap' if attack == 'boolean_native_returncode' else attack
            path = tmp_path / binding[role]['path']; value = json.loads(path.read_bytes())
            value['outer_exec_exit_code' if attack == 'boolean_native_returncode' else 'completed' if role == 'native' else 'source_native_storage_closed' if role == 'storage' else 'source_READ_closed'] = False
            write_json(path, value); _refresh_continuation_shared_ref(binding, tmp_path, path)
            qualified_path = tmp_path / binding['candidate_qualification']['path']
            if role == 'reap':
                qualified = json.loads(qualified_path.read_bytes()); qualified['root_actual_outer_reap'] = binding['reap']
                write_json(qualified_path, qualified); _refresh_continuation_shared_ref(binding, tmp_path, qualified_path)
        elif attack == 'input_pin': binding['inputs'][0]['sha256'] = 'f' * 64
        elif attack == 'conflicting_shared_closure':
            binding['storage'] = dict(binding['storage'], sha256='f' * 64)
        elif attack == 'duplicate_candidates': binding['candidate_sources'].append(deepcopy(binding['candidate_sources'][0]))
        elif attack == 'duplicate_inputs': binding['inputs'].append(deepcopy(binding['inputs'][0]))
        elif attack == 'scope_alias':
            binding['storage'] = dict(binding['storage'], path=str(tmp_path / binding['storage']['path']))
        elif attack == 'alias': binding['verifier'] = deepcopy(binding['request'])
        elif attack == 'outside': binding['inputs'][0]['path'] = '/etc/passwd'
        elif attack == 'symlink':
            path = tmp_path / binding['inputs'][0]['path']; content = path.read_bytes()
            target = path.with_name('target.json'); target.write_bytes(content); path.unlink()
            created_alias, created_target = path, target
            path.symlink_to(target)
        with pytest.raises((contract.ContractError, ValueError)):
            contract._continuation_observe(tmp_path, task)
        if created_alias is not None:
            assert created_alias.is_symlink() and created_alias.readlink() == created_target
    finally:
        # Exact declared v2 fixture lifecycle; preserve unexpected leaves.
        if created_alias is not None and created_alias.is_symlink() and created_alias.readlink() == created_target:
            created_alias.unlink()


@pytest.mark.parametrize('attack', ['card', 'completed_status', 'plan_record', 'receipt', 'baseline',
                                   'added_task', 'missing_task', 'authority'], ids=['case-card', 'case-completed_status', 'case-plan_record', 'case-receipt', 'case-baseline', 'case-added_task', 'case-missing_task', 'case-authority'])
def test_continuation_preserves_all139_completed_raw_cards_records_and_receipts(tmp_path, monkeypatch, attack):
    plan, bundle = _continuation_case(tmp_path, monkeypatch)
    plan = dict(plan, engineering_continuation=bundle)
    if attack in {'card', 'completed_status'}:
        path = tmp_path / contract.BOARD
        path.write_text(path.read_text().replace('Existing' if attack == 'card' else 'completed',
                                                'Changed' if attack == 'card' else 'todo', 1))
    elif attack == 'plan_record': plan['tasks'][0]['title'] = 'changed'
    elif attack == 'receipt': (tmp_path / bundle['baseline']['receipts'][0]['path']).write_bytes(b'changed')
    elif attack == 'baseline': bundle['baseline']['receipts'].pop()
    elif attack == 'added_task': bundle['tasks'].append(deepcopy(bundle['tasks'][0]))
    elif attack == 'missing_task': bundle['tasks'].pop()
    elif attack == 'authority': bundle['dispatch_authorized_by_this_metadata'] = True
    with pytest.raises(contract.ContractError):
        contract.check_continuation_plan(tmp_path, plan)


def test_continuation_refuses_changed_owned_outputs_and_never_rearms_history(tmp_path, monkeypatch):
    plan, bundle = _continuation_case(tmp_path, monkeypatch)
    _adopt_continuation_fixture(tmp_path, plan, bundle)
    task_id = bundle['tasks'][0]['task_id']
    contract.materialize_continuation_validation(tmp_path, task_id)
    path = tmp_path / contract.continuation_directory(task_id) / 'validation.json'
    path.write_bytes(b'prior attempt evidence must survive')
    before = [(tmp_path / item).read_bytes() for item in (contract.PLAN, contract.BOARD)]
    with pytest.raises(contract.ContractError, match='retained continuation output differs'):
        contract.materialize_continuation_validation(tmp_path, task_id)
    assert path.read_bytes() == b'prior attempt evidence must survive'
    assert before == [(tmp_path / item).read_bytes() for item in (contract.PLAN, contract.BOARD)]


def test_continuation_nested_worktree_uses_original_primary_source_authority(tmp_path, monkeypatch):
    primary = tmp_path / 'primary'; primary.mkdir()
    lane = tmp_path / 'deep/lane/task-worktree'; lane.mkdir(parents=True)
    evidence = primary / 'retained.json'; evidence.write_bytes(b'{"closed":true}')
    calls = []
    def original_authority(root):
        calls.append(root)
        return primary
    monkeypatch.setattr(contract, '_continuation_primary_source_root', original_authority)
    ref = dict(path=str(evidence), bytes=evidence.stat().st_size,
               sha256=contract.sha(evidence.read_bytes()))
    assert contract._continuation_ref(lane, ref) == evidence.read_bytes()
    assert calls == [lane]
    other = tmp_path / 'unrelated.json'; other.write_bytes(evidence.read_bytes())
    ref['path'] = str(other)
    with pytest.raises(contract.ContractError, match='outside original shared source authority'):
        contract._continuation_ref(lane, ref)


def _continuation_peer_case(root, monkeypatch):
    _, bundle = _continuation_case(root, monkeypatch)
    task = deepcopy(bundle['tasks'][0]); old = task['binding']
    def evidence(name, value):
        path = root / 'retained' / ('peer-' + name + '.json')
        write_json(path, value)
        return _continuation_ref_for(path, root)
    candidates = old['candidate_sources']
    names = [str(root / ref['path']) for ref in candidates]
    nodes = ['retained/test.json::case1', 'retained/test.json::case2']
    request = evidence('request', dict(schema='owned-validation-request/v1', cwd=str(root / 'canonical'),
        selected_checks=nodes, source_sha256={**{ref['path']: ref['sha256'] for ref in old['inputs']},
            **{name: ref['sha256'] for name, ref in zip(names, candidates)}}))
    capture = evidence('capture', dict(schema='legal-ir-occurrence-inference-focused-source-capture/v1',
        completed=True, source_READ_closed=True))
    prepared = evidence('plan', dict(schema='legal-ir-occurrence-inference-fixture-original-plan/v1',
        request=request, source_capture=capture, candidate_root=str(root), canonical_root=str(root / 'canonical')))
    verifier = evidence('independent-review', dict(schema='legal-ir-occurrence-inference-focused-independent-request-review/v1',
        accepted_for_original_owned_occurrence_inference_fixture_launch=True, source_READ_closed=True,
        request=request, source_capture=capture))
    buffers = [{**ref, 'path': name} for ref, name in zip(candidates, names)]
    observation = evidence('observation', dict(schema='legal-ir-occurrence-inference-focused-torch-observation/v1',
        completed=True, pytest_returncode=0, cases_passed=2, phase_events_passed=6,
        selected_node_ids=nodes, audit=dict(selected_compile_events=buffers, denied_operations=[]),
        import_origins={'fixture.owner': buffers[0]},
        compiled_source_buffers=[dict(buffers[0], code_filename=names[0], compilation='actual_selected_bytes')]))
    terminal = evidence('terminal', dict(schema='legal-ir-occurrence-inference-focused-torch-terminal/v1',
        actual_test_cases=2, actual_phase_events=6, output_endpoint_guards_closed=True,
        project_import_origin_guards_closed=True, selected_sources_unchanged=True,
        source_buffer_compilation_guards_closed=True, original_resource_closeout_not_claimed_by_worker=True))
    complete = evidence('complete', dict(schema='legal-ir-occurrence-inference-fixture-original-controller-complete/v1',
        completed=True, worker_succeeded=True, source_READ_closed_after_verified_original_cleanup=True,
        returncode=0, request_sha256=request['sha256'], selected_cases=2, selected_phase_events=6))
    worker = evidence('worker', dict(schema='owned-validation-result/v1', completed=True,
        returncode=0, request_sha256=request['sha256'], executed_checks=nodes))
    collection = evidence('collection', dict(nodes=nodes))
    phases = evidence('phases', dict(phase_events=[dict(nodeid=node, when=phase,
        outcome='passed', wasxfail=False) for node in nodes for phase in ('setup', 'call', 'teardown')]))
    proof = evidence('closeout', dict(schema='legal-ir-occurrence-inference-fixture-independent-result-review/v1',
        accepted_actual_occurrence_inference_fixture_qualification=True, metadata_source_READ_closed=True,
        source_native_storage_custody_closed=True, original_owned_pipeline_succeeded=True,
        genuine_fixture_worker_succeeded=True, actual_worker_returncode=0, original_owner_returncode=0,
        request=request, independent_request_review=verifier, worker_observation=observation,
        terminal_custody=terminal, controller_complete=complete, worker_result=worker,
        worker_phases=phases, worker_collection=collection, source_capture=capture, prepared_plan=prepared,
        resource_closeout=dict(cleanup_proven=True, current_selected_storage_record_matches_terminal=True,
            native_lease_absent_from_current_active_scheduler=True, native_released=True,
            original_owner_and_child_PIDs_absent=True, source_READ_closed=True,
            live_processes=0, rss_bytes=0, storage_status='released', recovery_needed=False)))
    task['binding'] = dict(evidence_profile=contract.CONTINUATION_PEER_PROFILE,
        candidate_sources=candidates, inputs=old['inputs'], candidate_qualification=proof,
        request=request, verifier=verifier, result=observation, native=proof, storage=proof,
        source=proof, independent_verifier_id='sha256:' + verifier['sha256'], terminal=terminal,
        controller_complete=complete, worker_result=worker, phases=phases, collection=collection,
        source_capture=capture, prepared_plan=prepared, expected_cases=2,
        executed_source_correspondence=[dict(candidate_path=candidates[0]['path'], executed_path=names[0],
            source_kind='module', module='fixture.owner'), dict(candidate_path=candidates[1]['path'],
            executed_path=names[1], source_kind='test', module=None)])
    return task


def _rebind_peer_document(root, binding, role, body):
    path = root / binding[role]['path']; write_json(path, body)
    fresh = _continuation_ref_for(path, root)
    if role == 'candidate_qualification':
        for name in ('candidate_qualification', 'native', 'storage', 'source'):
            binding[name] = deepcopy(fresh)
        return
    binding[role] = fresh
    if role == 'verifier':
        binding['independent_verifier_id'] = 'sha256:' + fresh['sha256']
    field = {'result': 'worker_observation', 'verifier': 'independent_request_review',
        'phases': 'worker_phases', 'collection': 'worker_collection', 'terminal': 'terminal_custody'}.get(role, role)
    path = root / binding['candidate_qualification']['path']; proof = json.loads(path.read_bytes())
    proof[field] = fresh; write_json(path, proof)
    for name in ('candidate_qualification', 'native', 'storage', 'source'):
        binding[name] = _continuation_ref_for(path, root)


def test_continuation_original_peer_dialect_preserves_its_actual_measurement_scope(tmp_path, monkeypatch):
    task = _continuation_peer_case(tmp_path, monkeypatch)
    observation = contract._continuation_observe(tmp_path, task)
    assert observation['cases'] == 2 and observation['phase_reports'] == 6
    assert observation['observed_compiled_source_count'] == 2
    assert 'actual_executed_source_count' not in observation
    assert observation['actual_exec_event_buffers_attested'] is False
    assert observation['outer_tool_reap_observed'] is False
    assert observation['auditor_executable_attested'] is False
    assert observation['independent_verifier_kind'] == 'original_pinned_independent_review_metadata'


@pytest.mark.parametrize('attack', ['boolean_cases', 'zero_cases', 'compile_hash', 'module_origin',
    'failed_phase', 'xfail', 'duplicate_phase', 'native_open', 'storage_open', 'live_child',
    'controller_open', 'boolean_worker_return', 'wrong_request_review', 'wrong_candidate_root'],
    ids=['peer-boolean-cases', 'peer-zero-cases', 'peer-compile-hash', 'peer-module-origin',
         'peer-failed-phase', 'peer-xfail', 'peer-duplicate-phase', 'peer-native-open',
         'peer-storage-open', 'peer-live-child', 'peer-controller-open', 'peer-boolean-worker-return',
         'peer-wrong-request-review', 'peer-wrong-candidate-root'])
def test_continuation_original_peer_dialect_rejects_forged_counts_sources_and_custody(tmp_path, monkeypatch, attack):
    task = _continuation_peer_case(tmp_path, monkeypatch); binding = task['binding']
    if attack == 'boolean_cases': binding['expected_cases'] = True
    elif attack == 'zero_cases': binding['expected_cases'] = 0
    else:
        role = 'result' if attack in {'compile_hash', 'module_origin'} else 'phases' if attack in {
            'failed_phase', 'xfail', 'duplicate_phase'} else 'candidate_qualification' if attack in {
            'native_open', 'storage_open', 'live_child'} else 'controller_complete' if attack == 'controller_open' \
            else 'worker_result' if attack == 'boolean_worker_return' else 'verifier' if attack == 'wrong_request_review' else 'prepared_plan'
        body = json.loads((tmp_path / binding[role]['path']).read_bytes())
        if attack == 'compile_hash': body['audit']['selected_compile_events'][0]['sha256'] = 'f' * 64
        elif attack == 'module_origin': body['import_origins']['fixture.owner']['sha256'] = 'f' * 64
        elif attack == 'failed_phase': body['phase_events'][0]['outcome'] = 'failed'
        elif attack == 'xfail': body['phase_events'][0]['wasxfail'] = True
        elif attack == 'duplicate_phase': body['phase_events'][1] = deepcopy(body['phase_events'][0])
        elif attack == 'native_open': body['resource_closeout']['native_released'] = False
        elif attack == 'storage_open': body['resource_closeout']['storage_status'] = 'reserved'
        elif attack == 'live_child': body['resource_closeout']['live_processes'] = 1
        elif attack == 'controller_open': body['source_READ_closed_after_verified_original_cleanup'] = False
        elif attack == 'boolean_worker_return': body['returncode'] = False
        elif attack == 'wrong_request_review': body['request']['sha256'] = 'f' * 64
        else: body['candidate_root'] = str(tmp_path / 'wrong-frozen-root')
        _rebind_peer_document(tmp_path, binding, role, body)
    with pytest.raises(contract.ContractError):
        contract._continuation_observe(tmp_path, task)


def test_continuation_producer_and_consumer_are_one_closed_ordered_validation_unit(tmp_path, monkeypatch):
    """Same-stage declared commands run concurrently; one && unit orders the dependency."""
    import shlex
    _plan, bundle = _continuation_case(tmp_path, monkeypatch)
    for task in bundle['tasks']:
        commands = contract.continuation_contract(task)['validation_commands']
        assert len(commands) == 1
        lexer = shlex.shlex(commands[0], posix=True, punctuation_chars=';&|')
        lexer.whitespace_split = True
        tokens = list(lexer)
        assert tokens.count('&&') == 1 and not any(token in (';', '&', '|', '||') for token in tokens)
        boundary = tokens.index('&&')
        prefix = ['IPFS_DATASETS_PY_MINIMAL_IMPORTS=1', 'PYTHONPATH=.', 'python3', contract.SCRIPT]
        assert tokens[:boundary] == prefix + ['--materialize-continuation-validation', task['task_id']]
        assert tokens[boundary + 1:] == prefix + ['--check-task', task['task_id']]
        assert contract.continuation_contract(task)['context_budget_tokens'] == 0


def _preparation_ref(path, root):
    value = path.read_bytes()
    return dict(path=path.relative_to(root).as_posix(), bytes=len(value), sha256=contract.sha(value))


def _preparation_fixture(tmp_path, monkeypatch, *, retained_count=3):
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import prepare_programme_work_packet_v1
    retained = [dict(task_id='LIRAE-RETAINED-' + str(i).zfill(3), title='Retained ' + str(i))
                for i in range(retained_count)]
    board = '# Retained fixture\n\n' + ''.join('## ' + row['task_id'] + ' Old task\n\n- status: completed\n\n'
                                             for row in retained)
    (tmp_path / contract.BOARD).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / contract.BOARD).write_text(board)
    plan = dict(tasks=retained)
    write_json(tmp_path / contract.PLAN, plan)
    snapshot = tmp_path / 'workspace/snapshots'
    original = dict(tasks=[dict(id='LIR-' + str(i).zfill(2), snapshot='original') for i in range(1, 25)])
    current = dict(tasks=[dict(id='LIR-' + str(i).zfill(2), snapshot='current') for i in range(1, 25)])
    for name, body in [('original-backlog.json', original), ('current-backlog.json', current),
                       ('retained-plan.json', plan)]:
        write_json(snapshot / name, body)
    (snapshot / 'retained-board.md').write_text(board)
    receipts = []
    for row in retained:
        path = tmp_path / 'retained' / (row['task_id'].lower() + '.json')
        write_json(path, dict(task_id=row['task_id'], retained=True))
        receipts.append(dict(task_id=row['task_id'], **_preparation_ref(path, tmp_path)))
    base_sha = contract.sha(contract._programme_json(retained))
    monkeypatch.setattr(contract, 'PROGRAMME_PREPARATION_BASE_COUNT', retained_count)
    monkeypatch.setattr(contract, 'PROGRAMME_PREPARATION_BASE_TASKS_SHA256', base_sha)
    monkeypatch.setattr(contract, 'PROGRAMME_PREPARATION_BASE_BOARD_BYTES', len(board.encode()))
    monkeypatch.setattr(contract, 'PROGRAMME_PREPARATION_BASE_BOARD_SHA256', contract.sha(board.encode()))
    baseline = dict(schema='legal-ir-supervisor-programme-preparation-baseline/v1', task_count=retained_count,
        board_bytes=len(board.encode()), board_sha256=contract.sha(board.encode()),
        board_revision='taskboard:sha256:' + contract.sha(b'agent-supervisor-taskboard-revision-v1\0' + board.encode()),
        plan_tasks_sha256=base_sha, receipts=receipts)
    write_json(snapshot / 'baseline.json', baseline)
    baseline_ref = _preparation_ref(snapshot / 'baseline.json', tmp_path)
    monkeypatch.setattr(contract, 'PROGRAMME_PREPARATION_BASELINE_SHA256', baseline_ref['sha256'])
    monkeypatch.setattr(contract, '_continuation_primary_source_root', lambda root: tmp_path)
    # This synthetic fixture substitutes only the loader. Its actual packet
    # builder remains the normally imported genuine pure public owner function.
    monkeypatch.setattr(contract, '_programme_preparation_owner', lambda root, ref: prepare_programme_work_packet_v1)
    owner = tmp_path / contract.PROGRAMME_PREPARATION_OWNER
    owner.parent.mkdir(parents=True, exist_ok=True)
    owner.write_bytes((ROOT / contract.PROGRAMME_PREPARATION_OWNER).read_bytes())
    oldrows = {row['id']: row for row in original['tasks']}
    currentrows = {row['id']: row for row in current['tasks']}
    tasks = []
    for task_id, (role, parent, operation, parents) in contract.PROGRAMME_PREPARATION_SPECS.items():
        sources = []
        for logical in contract.PROGRAMME_PREPARATION_OWNER_PATHS[role]:
            path = snapshot / 'owner-sources' / logical
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('snapshot_only = True\n')  # Data, never imported.
            sources.append(_preparation_ref(path, tmp_path))
        evidence_path = snapshot / 'evidence' / (role + '.json')
        write_json(evidence_path, dict(kind='closed_metadata_fixture', role=role, qualified=True,
                                      admitted=False, formalized=False))
        evidence = [_preparation_ref(evidence_path, tmp_path)]
        authority = dict(kind='legacy_markdown', namespace='legal-ir-autoencoder-v1',
            board=_preparation_ref(snapshot / 'retained-board.md', tmp_path),
            plan=_preparation_ref(snapshot / 'retained-plan.json', tmp_path),
            source_control_revision=baseline_ref['sha256'])
        gates = ['original_owner_admission', 'independent_acceptance']
        scope = dict(schema='legal-ir-programme-admission-scope/v1', task_id=task_id, role=role,
            parent_task_id=parent, future_operation=operation,
            supporting_parents=[dict(task_id=key, task_sha256=contract.sha(contract._programme_json(currentrows[key])))
                                for key in parents],
            logical_owner_paths=list(contract.PROGRAMME_PREPARATION_OWNER_PATHS[role]),
            dependencies=dict(owner_sources=sources, evidence=evidence),
            principals=dict(worker='fixture-worker:' + task_id, independent_verifier='fixture-verifier:' + task_id,
                            identity_verified=False),
            exclusive_keys=['programme-preparation:' + task_id],
            proposed_limits=dict(contract.PROGRAMME_PREPARATION_LIMITS),
            native_binding=dict(task_cid=None, control_revision=None, status='original_admission_required'),
            remaining_gates=gates, grants={key: False for key in
                ('dispatch', 'native_execution', 'model_execution', 'training', 'meaning_review', 'parent_completion')})
        scope_path = snapshot / 'scopes' / (task_id.lower() + '.json')
        write_json(scope_path, scope)
        tasks.append(dict(task_id=task_id, title='Prepare concrete ' + role + ' control packet',
            programme_preparation='legal-ir-programme-preparation/v1', operation_kind=role,
            goal_id='LIR-03.next-work-packets-v1', parent_task_id=parent,
            parent_reference=dict(repository='ipfs_datasets_py', revision='a' * 40,
                path='ipfs_datasets_py/logic/autoformal/docs/BACKLOG.json', task_id=parent,
                task_sha256=contract.sha(contract._programme_json(oldrows[parent]))),
            current_parent_reference=dict(backlog=_preparation_ref(snapshot / 'current-backlog.json', tmp_path),
                task_id=parent, task_sha256=contract.sha(contract._programme_json(currentrows[parent]))),
            binding=dict(original_backlog=_preparation_ref(snapshot / 'original-backlog.json', tmp_path),
                current_backlog=_preparation_ref(snapshot / 'current-backlog.json', tmp_path),
                base_plan=authority['plan'], base_board=authority['board'], packet_owner=_preparation_ref(owner, tmp_path),
                owner_sources=sources, evidence=evidence, authority_binding=authority, remaining_gates=gates,
                admission_scope=_preparation_ref(scope_path, tmp_path)),
            limits=dict(contract.PROGRAMME_PREPARATION_LIMITS)))
    monkeypatch.setattr(contract, 'PROGRAMME_PREPARATION_TASKS_SHA256', contract.sha(contract._programme_json(tasks)))
    bundle = dict(schema='legal-ir-programme-preparation-bundle/v1', baseline=baseline_ref, tasks=tasks,
                  dispatch_authorized_by_this_metadata=False, completion_authority=False)
    return plan, bundle


def _adopt_preparation_fixture(root, plan, bundle):
    updated = dict(plan, programme_preparation=bundle,
        tasks=plan['tasks'] + [{**task, **contract.programme_preparation_contract(task)} for task in bundle['tasks']])
    write_json(root / contract.PLAN, updated)
    with (root / contract.BOARD).open('ab') as stream:
        stream.write(('\n' + '\n'.join(contract.render_programme_preparation_task(task)
                                     for task in bundle['tasks']) + '\n').encode())
    return updated


@pytest.mark.parametrize('task_id,role,parent', [
    ('LIRAE-LIR03-SOURCE-PACKET-01', 'source_cache_lineage', 'LIR-02'),
    ('LIRAE-LIR03-IR-PACKET-01', 'typed_ir_scoped_graph', 'LIR-07'),
    ('LIRAE-LIR03-MODEL-PACKET-01', 'model_compatibility_quality', 'LIR-17'),
    ('LIRAE-LIR03-LEAN-PACKET-02', 'lean_release_verification', 'LIR-12'),
], ids=['source', 'ir', 'model', 'lean'])
def test_programme_preparation_materializes_concrete_bound_packet_without_dispatch(tmp_path, monkeypatch, task_id, role, parent):
    plan, bundle = _preparation_fixture(tmp_path, monkeypatch, retained_count=141)
    assert len(plan['tasks']) == 141
    before_plan = (tmp_path / contract.PLAN).read_bytes()
    before_board = (tmp_path / contract.BOARD).read_bytes()
    preview = contract.prepare_programme_preparation(tmp_path, bundle)
    assert len(preview['entries']) == 4 and preview['completion_authority'] is False
    assert (tmp_path / contract.PLAN).read_bytes() == before_plan
    assert (tmp_path / contract.BOARD).read_bytes() == before_board
    _adopt_preparation_fixture(tmp_path, plan, bundle)
    task = next(row for row in bundle['tasks'] if row['task_id'] == task_id)
    commands = contract.programme_preparation_contract(task)['validation_commands']
    import shlex
    tokens = shlex.split(commands[0])
    assert len(commands) == 1 and tokens.count('&&') == 1
    boundary = tokens.index('&&')
    prefix = ['IPFS_DATASETS_PY_MINIMAL_IMPORTS=1', 'PYTHONPATH=.', 'python3', contract.SCRIPT]
    assert tokens[:boundary] == prefix + ['--materialize-programme-preparation', task_id]
    assert tokens[boundary + 1:] == prefix + ['--check-task', task_id]
    assert contract.kind(task_id) == 'programme_preparation'
    result = contract.materialize_programme_preparation(tmp_path, task_id)
    assert result['readiness'] == 'original_admission_required' and result['scientific_parent_satisfied'] is False
    packet_path = tmp_path / contract.programme_preparation_directory(task_id) / 'packet.json'
    packet = json.loads(packet_path.read_bytes())
    assert packet['task_id'] == task_id and packet['role'] == role
    assert packet['packet']['parent_task_id'] == parent
    assert packet['packet']['metadata_complete'] is True
    assert packet['packet']['current_parent_reference']['task_sha256'] != packet['packet']['parent_reference']['task_sha256']
    assert packet['admission_scope']['native_binding']['task_cid'] is None
    assert packet['admission_scope']['principals']['identity_verified'] is False
    assert all(packet['packet'][name] is False for name in contract.PROGRAMME_PREPARATION_FALSE_FLAGS)
    assert packet['packet']['supervision_masks'] == {'training': 0, 'evaluation_gold': 0}
    assert contract.validate(tmp_path, task_id)['validated'] is True
    before = {path.name: (path.read_bytes(), path.stat().st_ino) for path in packet_path.parent.iterdir()}
    contract.materialize_programme_preparation(tmp_path, task_id)
    assert {path.name: (path.read_bytes(), path.stat().st_ino) for path in packet_path.parent.iterdir()} == before
    assert (tmp_path / contract.BOARD).read_bytes().startswith(before_board)
    assert json.loads((tmp_path / contract.PLAN).read_bytes())['tasks'][:141] == plan['tasks']


@pytest.mark.parametrize('attack', ['unknown_id', 'wrong_role', 'wrong_parent', 'unknown_field',
    'context_bool', 'budget_bool', 'arbitrary_command', 'output_escape'],
    ids=['unknown-id', 'wrong-role', 'wrong-parent', 'unknown-field', 'context-bool',
         'budget-bool', 'arbitrary-command', 'output-escape'])
def test_programme_preparation_rejects_broadened_executable_contract(tmp_path, monkeypatch, attack):
    _, bundle = _preparation_fixture(tmp_path, monkeypatch)
    task = deepcopy(bundle['tasks'][0])
    if attack == 'unknown_id': task['task_id'] = 'LIRAE-LIR03-SOURCE-PACKET-99'
    elif attack == 'wrong_role': task['operation_kind'] = 'model_compatibility_quality'
    elif attack == 'wrong_parent': task['parent_task_id'] = 'LIR-17'
    elif attack == 'unknown_field': task['callback'] = 'run_anything'
    elif attack == 'context_bool': task['context_budget_tokens'] = False
    elif attack == 'budget_bool': task['limits']['cpu_slots'] = True
    elif attack == 'arbitrary_command': task['validation_commands'] = ['python3 -c arbitrary']
    else: task['outputs'] = ['../receipt.json']
    with pytest.raises(contract.ContractError):
        contract.programme_preparation_contract(task)


@pytest.mark.parametrize('attack', ['meaning_grant', 'same_principal', 'invented_native', 'future_command',
    'supporting_parent', 'owner_role', 'dependencies', 'unknown_gate'],
    ids=['meaning-grant', 'same-principal', 'invented-native', 'future-command',
         'supporting-parent', 'owner-role', 'dependencies', 'unknown-gate'])
def test_programme_preparation_rejects_forged_admission_scope(tmp_path, monkeypatch, attack):
    plan, bundle = _preparation_fixture(tmp_path, monkeypatch)
    task = bundle['tasks'][0]
    path = tmp_path / task['binding']['admission_scope']['path']
    scope = json.loads(path.read_bytes())
    if attack == 'meaning_grant': scope['grants']['meaning_review'] = True
    elif attack == 'same_principal': scope['principals']['independent_verifier'] = scope['principals']['worker']
    elif attack == 'invented_native': scope['native_binding']['task_cid'] = 'invented'
    elif attack == 'future_command': scope['future_operation'] = 'python3 -c arbitrary'
    elif attack == 'supporting_parent': scope['supporting_parents'][0]['task_sha256'] = '0' * 64
    elif attack == 'owner_role': scope['logical_owner_paths'][0] = 'ipfs_datasets_py/logic/autoformal/other.py'
    elif attack == 'dependencies': scope['dependencies']['evidence'] = []
    else: scope['remaining_gates'].append('all_legal_meaning_reviewed')
    write_json(path, scope)
    task['binding']['admission_scope'] = _preparation_ref(path, tmp_path)
    monkeypatch.setattr(contract, 'PROGRAMME_PREPARATION_TASKS_SHA256', contract.sha(contract._programme_json(bundle['tasks'])))
    with pytest.raises((contract.ContractError, ValueError)):
        contract.prepare_programme_preparation(tmp_path, bundle)
    assert not (tmp_path / contract.programme_preparation_directory(task['task_id'])).exists()


@pytest.mark.parametrize('attack', ['source', 'evidence', 'current_parent', 'original_parent', 'plan', 'board', 'receipt'],
    ids=['source', 'evidence', 'current-parent', 'original-parent', 'plan', 'board', 'receipt'])
def test_programme_preparation_requires_physical_snapshot_and_retained_history_integrity(tmp_path, monkeypatch, attack):
    _, bundle = _preparation_fixture(tmp_path, monkeypatch)
    task = bundle['tasks'][0]
    if attack in ('source', 'evidence'):
        path = tmp_path / task['binding']['owner_sources' if attack == 'source' else 'evidence'][0]['path']
    elif attack in ('current_parent', 'original_parent'):
        path = tmp_path / task['binding']['current_backlog' if attack == 'current_parent' else 'original_backlog']['path']
    elif attack == 'plan': path = tmp_path / contract.PLAN
    elif attack == 'board': path = tmp_path / contract.BOARD
    else: path = tmp_path / 'retained/lirae-retained-000.json'
    path.write_bytes(path.read_bytes() + b' ')
    if attack == 'plan':
        body = json.loads(path.read_bytes());body['tasks'][0]['title'] = 'Changed';write_json(path, body)
    with pytest.raises(contract.ContractError):
        contract.prepare_programme_preparation(tmp_path, bundle)


@pytest.mark.parametrize('body', [b'{"schema":"a","schema":"b"}', b'{"value":NaN}'],
                         ids=['duplicate-key', 'nonfinite'])
def test_programme_preparation_refuses_unsafe_snapshot_json(tmp_path, monkeypatch, body):
    _, bundle = _preparation_fixture(tmp_path, monkeypatch)
    task = bundle['tasks'][0];path = tmp_path / task['binding']['admission_scope']['path'];path.write_bytes(body)
    task['binding']['admission_scope'] = _preparation_ref(path, tmp_path)
    monkeypatch.setattr(contract, 'PROGRAMME_PREPARATION_TASKS_SHA256', contract.sha(contract._programme_json(bundle['tasks'])))
    with pytest.raises(contract.ContractError):
        contract.prepare_programme_preparation(tmp_path, bundle)


@pytest.mark.parametrize('path', ['../escape.json', 'workspace/../escape.json', 'workspace/*.json',
    'workspace/a\x00.json', 'workspace/a\\b.json', 'workspace/a[1].json'],
    ids=['parent-escape', 'nested-parent', 'glob', 'nul', 'backslash', 'brackets'])
def test_programme_preparation_rejects_unsafe_reference_paths(path):
    with pytest.raises(contract.ContractError):
        contract._programme_preparation_ref_contract(dict(path=path, bytes=1, sha256='a' * 64))


def test_programme_preparation_retained_outputs_are_immutable(tmp_path, monkeypatch):
    plan, bundle = _preparation_fixture(tmp_path, monkeypatch)
    _adopt_preparation_fixture(tmp_path, plan, bundle)
    task_id = bundle['tasks'][0]['task_id']
    contract.materialize_programme_preparation(tmp_path, task_id)
    path = tmp_path / contract.programme_preparation_directory(task_id) / 'packet.json'
    path.write_bytes(path.read_bytes() + b' ')
    before = path.read_bytes()
    with pytest.raises(contract.ContractError, match='retained programme preparation output differs'):
        contract.materialize_programme_preparation(tmp_path, task_id)
    assert path.read_bytes() == before


def test_programme_preparation_uses_only_the_normal_local_public_owner():
    path = ROOT / contract.PROGRAMME_PREPARATION_OWNER
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import prepare_programme_work_packet_v1
    assert contract._programme_preparation_owner(ROOT, _preparation_ref(path, ROOT)) is prepare_programme_work_packet_v1


def test_programme_preparation_absent_bundle_preserves_existing_plan():
    plan = json.loads((ROOT / contract.PLAN).read_bytes())
    assert 'programme_preparation' not in plan
    assert contract.check_programme_preparation_plan(ROOT, plan) is None

