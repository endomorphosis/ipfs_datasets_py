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


def accelerator_checkout():
    """Locate the existing accelerator dependency; never copy its implementation."""
    candidates = [ROOT / "ipfs_accelerate_py", ROOT.parent.parent / "external/ipfs_accelerate"]
    spec = importlib.util.find_spec("ipfs_accelerate_py")
    if spec is not None and spec.origin:
        candidates.append(Path(spec.origin).resolve().parent.parent)
    for candidate in candidates:
        if (candidate / "ipfs_accelerate_py/agent_supervisor/task_sources/task_identity.py").is_file():
            return candidate
    pytest.skip("native identity/CAS integration requires the existing ipfs_accelerate_py dependency")


def pending_programme_snapshot(tmp_path):
    """Exercise append preparation against a detached copy of the retained135."""
    import re
    plan = json.loads((ROOT / contract.PLAN).read_text())
    prepared_ids = {task['task_id'] for task in plan['programme_engineering']['prepared_tasks']}
    plan['tasks'] = [task for task in plan['tasks'] if task['task_id'] not in prepared_ids]
    board = ''.join(chunk for chunk in re.split(r'(?=^## )', (ROOT / contract.BOARD).read_text(),
                    flags=re.MULTILINE) if not any(chunk.startswith('## ' + task_id + ' ')
                                                  for task_id in prepared_ids)).rstrip() + '\n'
    write_json(tmp_path / contract.PLAN, plan)
    (tmp_path / contract.BOARD).write_text(board)
    return tmp_path


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
        accelerator_checkout() / "ipfs_accelerate_py/agent_supervisor/validation/validation_commands.py",
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


@pytest.mark.parametrize("bad", [True, 0, None, "false"])
@pytest.mark.parametrize("field", ["admitted", "formalized", "roundtrip_ok"])
def test_flags_must_be_boolean_false_even_nested(field, bad):
    row = false_row(roundtrip_ok=False)
    contract.false_flags(row, constitution=True)
    row["nested"] = [{field: bad}]
    with pytest.raises(contract.ContractError, match="authority must stay false"):
        contract.false_flags(row, constitution=True)


def artifact_case(tmp_path):
    task_id = "LIRAE-CONST-A1"
    path = tmp_path / contract.directory(task_id) / "spans.json"
    write_json(path, [false_row(id="span-1")])
    entry = {"kind": "spans", "path": path.relative_to(tmp_path).as_posix(), "sha256": contract.sha(path.read_bytes())}
    return task_id, path, {"artifacts": [entry]}


def test_artifact_digest_authenticates_actual_bytes_and_detects_tampering(tmp_path):
    task_id, path, receipt = artifact_case(tmp_path)
    assert contract.read_artifacts(tmp_path, task_id, receipt) == {"spans": path.read_bytes()}
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(contract.ContractError, match="hash/size differs"):
        contract.read_artifacts(tmp_path, task_id, receipt)


@pytest.mark.parametrize("attack", ["traversal", "absolute", "symlink", "empty", "duplicate", "receipt"])
def test_artifacts_reject_authority_escape_and_ambiguous_references(tmp_path, attack):
    task_id, path, receipt = artifact_case(tmp_path)
    entry = receipt["artifacts"][0]
    if attack == "traversal":
        entry["path"] = "../outside.json"
    elif attack == "absolute":
        entry["path"] = str(path)
    elif attack == "symlink":
        outside = tmp_path / "unowned.json"
        outside.write_bytes(path.read_bytes())
        path.unlink()
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
    expected_count = 134 + int(contract.ANCILLARY_TASK in const_ids) + sum(
        task.get("programme_engineering") is not None for task in plan["tasks"])
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


def programme_case(tmp_path, monkeypatch):
    task = deepcopy(programme_bundle()['prepared_tasks'][0])
    monkeypatch.setattr(contract, '_require_programme_source_alignment',
                        lambda root: dict(contract.PROGRAMME_SOURCE_BINDING))
    changes = []
    for value in (task['owner_paths'][0], task['test_paths'][0]):
        path = tmp_path / value
        path.parent.mkdir(parents=True, exist_ok=True)
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
    native = load_standalone('legal_ir_programme_native_identity', accelerator_checkout() /
        'ipfs_accelerate_py/agent_supervisor/task_sources/task_identity.py')
    blocks = contract._programme_task_blocks((ROOT / contract.BOARD).read_text())
    for task_id in bundle['legacy_preservation']['task_ids']:
        block = blocks[task_id]
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


def test_programme_entries_are_native_append_compatible_without_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(contract, '_require_programme_source_alignment',
                        lambda root: dict(contract.PROGRAMME_SOURCE_BINDING))
    before = [(ROOT / path).read_bytes() for path in (contract.PLAN, contract.BOARD)]
    pending = pending_programme_snapshot(tmp_path)
    result = contract.prepare_programme_engineering(pending)
    assert result['completion_authority'] is result['mutation_authority'] is False
    monkeypatch.syspath_prepend(str(accelerator_checkout()))
    from ipfs_accelerate_py.agent_supervisor.task_sources.taskboard_store import (
        TaskboardMaterializationEntry, preview_taskboard_materialization,
    )
    entries = [TaskboardMaterializationEntry(**entry) for entry in result['entries']]
    preview = preview_taskboard_materialization((pending / contract.BOARD).read_text(), entries)
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
                                    'escape_owner', 'escape_allowed', 'unknown_field'])
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
                                  'owner//file', 'owner/*.py', 'owner\\file', 'owner\x00file'])
def test_programme_paths_reject_escape_aliases_and_globs(value):
    with pytest.raises(contract.ContractError):
        contract._programme_safe_path(value)


@pytest.mark.parametrize('attack', ['old_id', 'old_metadata', 'old_board', 'baseline', 'child_parent'])
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
                                    'escape', 'symlink', 'hash', 'empty_result', 'nonfinite', 'artifact'])
def test_programme_receipt_rejects_forged_completion_or_execution_claims(tmp_path, monkeypatch, attack):
    task, receipt, preparation = programme_case(tmp_path, monkeypatch)
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
        path.unlink(); path.symlink_to(target)
    elif attack == 'hash': receipt['code_changes'][0]['sha256'] = '0' * 64
    elif attack == 'empty_result': preparation['result'][task['result_fields'][0]] = []
    elif attack == 'nonfinite': preparation['result'][task['result_fields'][0]] = float('nan')
    data = {'preparation': raw(preparation)}
    if attack == 'artifact': data['asserted-results'] = b'{}'
    with pytest.raises((contract.ContractError, ValueError)):
        contract.validate_programme_engineering(tmp_path, task, receipt, data)



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



def test_adopted_programme_cannot_prepare_a_second_task_population(monkeypatch):
    plan = json.loads((ROOT / contract.PLAN).read_text())
    if not any(task.get('programme_engineering') for task in plan['tasks']):
        pytest.skip('this checkout retains the pre-adoption135 snapshot')
    monkeypatch.setattr(contract, '_require_programme_source_alignment',
                        lambda root: dict(contract.PROGRAMME_SOURCE_BINDING))
    with pytest.raises(contract.ContractError, match='already adopted'):
        contract.prepare_programme_engineering(ROOT)
