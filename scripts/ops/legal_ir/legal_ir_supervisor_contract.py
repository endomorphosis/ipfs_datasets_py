"""Declare executable task contracts and verify retained, source-bound evidence.

This is an inventory check, never authority to admit or formalize legal text.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import importlib
import io
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import stat
import struct
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[3]
PLAN = Path('ipfs_datasets_py/logic/autoformal/legal_ir_autoencoder_supervisor_plan.json')
BOARD = Path('ipfs_datasets_py/logic/autoformal/LIRAE-TODO.md')
SCRIPT = 'scripts/ops/legal_ir/legal_ir_supervisor_contract.py'
MATERIALIZER = 'scripts/ops/legal_ir/materialize_legal_ir_inventory.py'
WIDTH_REPLAYER = 'scripts/ops/legal_ir/replay_born_alive_width.py'
LOCAL_WIDTH_TASKS = frozenset({'LIRAE-WIDTH-384', 'LIRAE-WIDTH-768'})
EVIDENCE = Path('docs/implementation/reports/evidence/legal_ir_autoencoder')
SCHEMA = 'legal-ir-supervisor-task-receipt/v1'
REVISION = '5016b86a273ce5e4ffd066c5ae9f5fe494dd417e'
PARQUET_SHA256 = '4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8'
# An explicit deployment input, independent of the validator's private HOME.
PINNED_PARQUET = Path('/home/barberb/.cache/huggingface/hub/datasets--justicedao--ipfs_uscode/snapshots') / REVISION / 'uscode_parquet/laws.parquet'
CONSTITUTION_SOURCE_ID = 'national-archives-retained-20260923'
CONSTITUTION_SHA256 = '9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b'
CONSTITUTION = EVIDENCE / 'inputs/constitution.txt'
ANCILLARY_TASK = 'LIRAE-CONST-ANCILLARY'
CONSTITUTION_UNITS = ('preamble', *('art-' + str(n) for n in range(1, 8)), *('amend-' + str(n) for n in range(1, 28)))
CONSTITUTION_TASKS = ('LIRAE-CONST-PREAMBLE', *('LIRAE-CONST-A' + str(n) for n in range(1, 8)), *('LIRAE-CONST-AM' + str(n).zfill(2) for n in range(1, 28)))
WIDTH_REPLAY_EXECUTABLE = 'legal-ir-born-alive-width-replay-v1'
SAMPLE_HASHES = sorted(['fb6eb7e04f50bdba72b954864e4cdc9dcf0a0857e6cc9a5b6e1544b234c64c2a', '6e1086c76b41205ed5caafe80a80ff240b68f6c89484b9d6b3d78f8db8c67bf2'])
TESTS = {
    'uscode': ['tests/unit/logic/test_uscode_ingest.py', 'tests/unit/logic/test_span_cache_exchange.py', 'tests/unit/logic/test_paired_span_census.py', 'tests/unit/logic/test_entity_cache.py'],
    'constitution': ['tests/unit/logic/test_constitution_inventory.py', 'tests/unit/logic/test_constitution_article_1_inventory.py', 'tests/unit/logic/test_paired_span_census.py::test_source_row_bounds_duplicates_nonfinite_and_constitution'],
    'width': ['tests/unit/logic/formalization/autoencoder/test_ir_decoder_profile_inventory.py', 'tests/unit/logic/test_paired_span_census.py'],
    'method': ['tests/unit/logic/autoformal/test_uscode_born_alive_definition_v1.py', 'tests/unit/logic/test_lean_units.py'],
}
OWNERS = {
    'uscode': ['uscode_ingest.py', 'span_cache_exchange.py', 'paired_span_census.py', 'entity_cache.py'],
    'constitution': ['constitution_inventory.py', 'constitution_shard_inventory.py', 'constitution_unit_projection.py', 'paired_span_census.py'],
    'width': [], 'method': ['lean_units.py', 'legal_source_definition_bridge_v2.py'],
}


class ContractError(ValueError):
    pass


class WidthReplayUnavailable(ContractError):
    """An unselected or unreviewed replay cannot accept asserted metrics.

    Reviewed 384D/768D routes require explicit local selection and independent
    protected replay. Pending 8D/4096D routes have not been implemented and
    reviewed. A checkpoint digest or self-reported metrics cannot authenticate
    either an unselected route or a missing route; keep those tasks pending.
    """

    reason_code = 'width_source_bound_replay_unavailable'

    def __init__(self, task_id):
        self.receipt = {
            'schema': 'legal-ir-width-replay-capability-blocker/v1',
            'task_id': task_id,
            'dimension': int(task_id.split('-')[-1]),
            'status': 'blocked_input',
            'reason_code': self.reason_code,
            'required_capability': WIDTH_REPLAY_EXECUTABLE,
            'source_hashes': list(SAMPLE_HASHES),
            'retryable': True,
            'completion_allowed': False,
            'encoder_executed': False,
            'training_executed': False,
            'admitted': False,
            'formalized': False,
        }
        if task_id in ('LIRAE-WIDTH-08', 'LIRAE-WIDTH-4096'):
            self.receipt['prerequisites'] = inspect_width_prerequisites(task_id)
        super().__init__(self.reason_code + ': no authenticated same-source replay is available')


def require(value, message):
    if not value:
        raise ContractError(message)


def inspect_width_prerequisites(task_id):
    """Describe the two pending routes without inspecting or authorizing inputs.

    These are declared requirements, not file availability observations. The
    retained subsection geometry identifies the original task inputs; this
    metadata neither authenticates supplied vectors nor issues a live native
    capability. Every call returns detached plain data and executes no replay,
    filesystem inspection, producer, model, training or resource operation.
    """
    require(type(task_id) is str and task_id in ('LIRAE-WIDTH-08', 'LIRAE-WIDTH-4096'),
            'prerequisite inspection supports only exact pending08/4096 task IDs')
    dimension = 8 if task_id == 'LIRAE-WIDTH-08' else 4096
    sources = [
        {
            'id': 'born-alive-10-1059-n',
            'legal_id': 'usc:us:10:1059',
            'parent_sha256': '6e1086c76b41205ed5caafe80a80ff240b68f6c89484b9d6b3d78f8db8c67bf2',
            'parent_bytes': 30787,
            'byte_start': 14849, 'byte_end': 16175,
            'char_start': 14806, 'char_end': 16128,
            'span_sha256': 'bfdabce62b4c822fa39aaa517ab55815501c68b6fb10ee292accb3015e7c9faf',
            'span_bytes': 1326,
            'coverage': 'complete_literal_subsection', 'full_parent_coverage': False,
            'literal_start': '(n) Dependent Child Defined',
            'literal_end': ' (Added Pub. L. 103',
        },
        {
            'id': 'born-alive-1-8-b',
            'legal_id': 'usc:us:1:8',
            'parent_sha256': 'fb6eb7e04f50bdba72b954864e4cdc9dcf0a0857e6cc9a5b6e1544b234c64c2a',
            'parent_bytes': 1584,
            'byte_start': 722, 'byte_end': 1282,
            'char_start': 721, 'char_end': 1281,
            'span_sha256': 'e9b539bd922e3196c8bef902808393b47ce74601d64353fb505625fa0e006851',
            'span_bytes': 560,
            'coverage': 'complete_literal_subsection', 'full_parent_coverage': False,
            'literal_start': '(b) As used in this section',
            'literal_end': ' (c) Nothing in this section',
        },
    ]
    constraints = {
        'new_training_permitted': False,
        'different_authored_cohort_may_complete': False,
        'source_selection_may_change': False,
    }
    if dimension == 8:
        constraints.update(role='donor', corpus_default=False,
            vector_acquisition='preserved_compatible_vectors_or_preserved_compatible_source_to8_producer')
    else:
        constraints.update(new_encoder_execution_permitted=False,
            vector_acquisition='independently_preserved_saved_vectors_only',
            development_result={'successful': 0, 'total': 12})
    producer_fields = ['profile_id', 'revision', 'config_sha256', 'core_sha256',
                       'coordinate_contract']
    if dimension == 4096:
        producer_fields += ['model_sha256', 'worker_sha256', 'library_sha256',
                            'tokenizer_policy', 'pooling', 'normalization',
                            'worker_source_sha256', 'owner_source_sha256',
                            'vocabulary_owner_source_sha256', 'token_ids_and_count']
    producer = {
        'identity_fields': producer_fields,
        'compatibility': 'matching_preserved_donor_or_decoder_context_contract',
        'authentication': 'original_producer_bytes_and_receipt_not_caller_assertion',
    }
    if dimension == 4096:
        producer['source_contract'] = {
            'model_sha256': '4668fd2a6d2764de250489852230e96238eb5c0d7495866eb3b9c6c4fac5c7da',
            'single_sequence': True, 'untruncated': True,
            'max_source_tokens_including_special': 512,
            'pooling': 'last', 'normalization': 'l2',
        }
    return {
        'schema': 'legal-ir-width-replay-prerequisites/v1',
        'task_id': task_id, 'dimension': dimension,
        'diagnostic_scope': 'declared_requirements_only',
        'input_availability': 'not_inspected',
        'input_files_checked': False, 'executable_presence_checked': False,
        'reviewed_route_available': False, 'executable_presence_sufficient': False,
        'reviewed_local_dimensions': [384, 768],
        'source_contract': {
            'repository': 'justicedao/ipfs_uscode', 'revision': REVISION,
            'parquet_sha256': PARQUET_SHA256,
            'source_text_policy': 'exact_utf8_no_normalization',
            'offset_contract': 'zero_based_half_open_utf8_bytes',
            'sources': sources,
        },
        'required_inputs': {
            'vectors': {
                'dimension': dimension,
                'ordered_source_ids': [source['id'] for source in sources],
                'coordinates': 'finite_original_native_coordinates_no_padding_truncation_or_relabelling',
                'source_binding': 'exact_parent_and_span_hashes_bytes_offsets_and_source_identity',
                'evidence': 'original_preserved_vector_bytes_and_authenticated_producer_receipt',
            },
            'producer': producer,
            'checkpoint': {
                'identity': 'exact_saved_checkpoint_bytes_and_sha256',
                'interface': 'compatible_native_input_projection_decoder_head_core_and_coordinate_contract',
            },
            'replay': {
                'owner': WIDTH_REPLAYER,
                'required_route': 'explicit_source_bound_dimension_replay_and_independent_verifier',
                'reviewed': False,
            },
        },
        'task_constraints': constraints,
        'next_actions': [
            'Supply a precise independently preserved input locator and original source/producer contracts.',
            'Review an explicit dimension-specific replay route and independent verifier in the existing owner.',
            'Qualify the exact source/input/checkpoint route through the existing source and native resource owners.',
            'Deploy only the reviewed capability; retain task fences until protected validation authenticates a run.',
        ],
        'completion_allowed': False, 'resource_admission_granted': False,
        'encoder_executed': False, 'training_executed': False,
        'admitted': False, 'formalized': False, 'proof_authority': False,
    }


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def kind(task_id):
    for prefix, name in (('USC', 'uscode'), ('CONST', 'constitution'), ('WIDTH', 'width'), ('METHOD', 'method')):
        if task_id.startswith('LIRAE-' + prefix + '-'):
            return name
    raise ContractError('unknown task family')


def directory(task_id):
    require(re.fullmatch(r'LIRAE-[A-Z0-9-]+', task_id), 'invalid task ID')
    return EVIDENCE / task_id.lower()


def selector(task_id):
    if task_id == ANCILLARY_TASK:
        return 'ancillary'
    suffix = task_id.removeprefix('LIRAE-CONST-')
    return 'preamble' if suffix == 'PREAMBLE' else 'amend-' + str(int(suffix[2:])) if suffix.startswith('AM') else 'art-' + str(int(suffix[1:]))


def constitution_spans(inventory, task_id):
    """Select retained source rows; ancillary is the original units' complement."""
    unit = selector(task_id)
    if task_id != ANCILLARY_TASK:
        return [row for row in inventory['spans'] if row['unit_id'] == unit or row['unit_id'].startswith(unit + '.')]
    selected = [row for row in inventory['spans'] if not any(
        row['unit_id'] == original or row['unit_id'].startswith(original + '.')
        for original in CONSTITUTION_UNITS)]
    require(len(inventory['spans']) == 236 and len(selected) == 83,
            'pinned ancillary source geometry differs')
    require(all(row['status'] == 'non_operative' and (row['unit_id'] == 'signature'
                or re.fullmatch(r'note-\d+', row['unit_id'])) for row in selected),
            'ancillary may retain only non-operative notes and signatures')
    return selected


def owner(root, name):
    if name == 'lean_units':
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return importlib.import_module('ipfs_datasets_py.logic.autoformal.lean_units')
    spec = importlib.util.spec_from_file_location('receipt_' + name, root / 'ipfs_datasets_py/logic/autoformal' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def width_replay_owner(root):
    spec = importlib.util.spec_from_file_location('legal_ir_protected_width_replay', Path(root) / WIDTH_REPLAYER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def width_required_file_pins(dimension):
    pins = width_replay_owner(ROOT).required_input_file_pins(dimension)
    require(isinstance(pins, list) and pins, 'reviewed width input pins required')
    return pins


def task_contract(task):
    task_id = task['task_id']
    family = kind(task_id)
    task_dir = directory(task_id).as_posix()
    tests = list(TESTS[family])
    owners = ['ipfs_datasets_py/logic/autoformal/' + name for name in OWNERS[family]]
    if family == 'width':
        suffix = '4096' if task_id.endswith('-4096') else 'dimensions'
        owners += ['ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_' + suffix + '.py', 'ipfs_datasets_py/logic/formalization/autoencoder/ir_decoder_profile_inventory.py']
        tests.append('tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_' + suffix + '.py')
    allowed = sorted(set([task_dir, *owners, *task.get('predicted_files', []), *[test.split('::')[0] for test in tests]]))
    commands = ['IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 -m pytest ' + ' '.join(tests) + ' -q --tb=line', 'IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 ' + SCRIPT + ' --check-task ' + task_id]
    instructions = ('Write ' + task_dir + '/receipt.json schema=' + SCHEMA + ' task_id=' + task_id + ' task_kind=' + family + ' status=inventory|implemented authority={admitted:false,formalized:false' + (',roundtrip_ok:false' if family == 'constitution' else '') + '}; artifacts=[{kind,path,sha256}] authenticate actual nonempty files inside this task directory. Read validator family function for exact fields. Preserve plaintext/source IDs/SHA256. Missing assets stay unavailable, never fabricate observations. Inventory/abstention does not assert full-corpus formalization. ')
    instructions += {
        'uscode': 'source={repository:justicedao/ipfs_uscode,revision:' + REVISION + '}; evidence repeats shard title/start/end/count from plan.shards. JSON artifact kinds sections/spans/entities are arrays. Sections carry ipfs_cid,text,source_text_sha256,status=spans|abstain,span_ids or reason and false flags. For missing CID use source_row_index (zero-based absolute Parquet row); missing plaintext remains text=null,source_text_sha256=null,status=abstain with explicit reason, never invented legal text. Spans carry id,text,source_ipfs_cid,source_text_sha256 and false flags; entities cite span_ids. Source is pinned Hugging Face uscode_parquet/laws.parquet (download exact revision if container cache absent); validation uses authenticated operator cache.',
        'constitution': 'Use exact retained plaintext ' + CONSTITUTION.as_posix() + ', sha256=' + CONSTITUTION_SHA256 + '; JSON source artifact={source_id,text,sha256}; receipt.source repeats source_id/sha256. JSON spans artifact carries exact selected constitution_inventory rows plus source_id,source_text_sha256,admitted=false,formalized=false,roundtrip_ok=false. evidence.unit_id=' + (selector(task_id) if family == 'constitution' else '') + '; Amendment21 requires repeal_treated_as_obligation=false.',
        'width': 'JSON observation artifact carries dimension,source_hashes for both born-alive inputs,profile_id,checkpoint_sha256,status=observed,training_executed=false,admitted=false,formalized=false,metrics={cosine_similarity,reconstruction_loss}. Retain actual checkpoint artifact kind checkpoint and replay evidence; hashes/metrics alone are insufficient. The required source-bound replay capability is currently unavailable: retain a blocked-input diagnostic, never claim this task completed from unavailable inventory or a different authored cohort. evidence.dimension matches. 8d role=donor corpus_default=false;384d corpus_default=true;768d token_ceiling=512;4096d encoder_executed=false development_result={successful:0,total:12}.',
        'method': 'lean_source artifact holds actual Lean source. evidence includes both pinned source_hashes; host sealed validator supplies lake_ok by running real lake build Legal with the trusted deployed toolchain. Do not invent a provider-side compiler observation. Skipped pinned-source tests supply no completion evidence.',
    }[family]
    result = {'outputs': [task_dir + '/receipt.json'], 'allowed_paths': allowed, 'validation_commands': commands, 'receipt_instructions': instructions, 'required_validation_executables': ['lake', 'lean'] if family == 'method' else [WIDTH_REPLAY_EXECUTABLE] if family == 'width' else []}
    if task.get('local_inventory') is True:
        require(family == 'uscode', 'local inventory route requires a US Code shard')
        labels = ['sections', 'spans', 'entities']
        archives = [task_dir + '/' + label + '.zip' for label in labels]
        result.update(
            outputs=[task_dir + '/receipt.json', *archives],
            allowed_paths=[task_dir],
            validation_commands=[commands[0], 'IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 ' + MATERIALIZER + ' --task ' + task_id + ' && ' + commands[1]],
            provider_role='deterministic-only', context_budget_tokens=0,
            proposal_artifact_envelope={
                'schema': 'ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3',
                'binary_paths': archives, 'max_file_bytes': 8_000_000,
                'max_patch_bytes': 16_000_000, 'max_output_bytes': 24_000_000,
            },
            receipt_instructions=instructions + ' Reviewed local inventory retains the complete source plaintext in deterministic single-member JSON ZIP artifacts. USC inventory uses one full-section span per nonempty source row; it claims no sentence-level formalization. Each ZIP contains only <kind>.json. Independent family tests and the protected checker remain mandatory; the native proposal gate exclusively decides completion.',
        )
    if task.get('local_constitution_inventory') is True:
        require(task_id == ANCILLARY_TASK, 'local Constitution route requires the ancillary task')
        result.update(
            outputs=[task_dir + '/' + name for name in ('receipt.json', 'source.json', 'spans.json')],
            allowed_paths=[task_dir], provider_role='deterministic-only', context_budget_tokens=0,
            validation_commands=[commands[0], 'IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 ' + MATERIALIZER + ' --task ' + task_id + ' && ' + commands[1]],
            receipt_instructions=instructions + ' Retain exactly the 83 source-derived non-operative note/signature rows omitted by the original 35 unit tasks. Preserve their actual status and reason. Independent tests and the protected checker remain mandatory; only native proposal/merge admission decides completion.',
        )
    if task.get('local_width_replay') is True:
        require(task_id in LOCAL_WIDTH_TASKS, 'local width replay requires reviewed384/768 task')
        dimension = int(task_id.rsplit('-', 1)[1])
        archive = task_dir + '/checkpoint.zip'
        instructions = instructions.replace('The required source-bound replay capability is currently unavailable: retain a blocked-input diagnostic, never claim this task completed from unavailable inventory or a different authored cohort.',
            'Use the reviewed dimension-specific frozen selected-followup replay; retain exact raw checkpoint bytes in checkpoint.zip and compare against an independent protected rerun.')
        result.update(outputs=[task_dir + '/' + name for name in ('receipt.json', 'observation.json', 'checkpoint.zip')],
            allowed_paths=[task_dir], provider_role='deterministic-only', context_budget_tokens=0,
            validation_commands=[commands[0], 'IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=. python3 ' + WIDTH_REPLAYER + ' --root . --task-id ' + task_id + ' --output-directory ' + task_dir + ' && ' + commands[1]],
            required_validation_executables=['python3'],
            required_validation_file_pins=width_required_file_pins(dimension),
            proposal_artifact_envelope={'schema': 'ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3',
                'binary_paths': [archive], 'max_file_bytes': 8_000_000,
                'max_patch_bytes': 16_000_000, 'max_output_bytes': 24_000_000},
            receipt_instructions=instructions + ' Both exact born-alive parent sources and complete selected subsection byte ranges must be authenticated, with actual512 token checks/no truncation. No training. measurement_scope=identity_by_construction_not_learned_reconstruction; quality, semantic and statutory fidelity flags remain false. Preserve actual raw decoder predictions and complete producer evidence. Identity projection diagnostics are not learned reconstruction quality.',
        )
    return result


def enrich(root, *, enable_local_inventory=False, enable_local_width_replay=False):
    root = Path(root)
    plan = json.loads((root / PLAN).read_text())
    chunks = re.split(r'(?=^## )', (root / BOARD).read_text(), flags=re.MULTILINE)
    pending = set()
    routing_update = enable_local_inventory or enable_local_width_replay
    if routing_update:
        for chunk in chunks:
            match = re.match(r'## (LIRAE-[A-Z0-9-]+)\b', chunk)
            statuses = re.findall(r'^- status:\s*([^\n]+)', chunk, flags=re.MULTILINE | re.IGNORECASE)
            if match and statuses and statuses[-1].strip().lower() in {'todo', 'ready'} and ((enable_local_inventory and kind(match[1]) == 'uscode') or (enable_local_width_replay and match[1] in LOCAL_WIDTH_TASKS)):
                pending.add(match[1])
    contracts = {}
    for task in plan['tasks']:
        if task['task_id'] in pending:
            task['local_inventory' if kind(task['task_id']) == 'uscode' else 'local_width_replay'] = True
        contracts[task['task_id']] = task_contract(task)
        if not routing_update or task['task_id'] in pending:
            task.update(contracts[task['task_id']])
    seen = set()
    for index, chunk in enumerate(chunks):
        match = re.match(r'## (LIRAE-[A-Z0-9-]+)\b', chunk)
        if not match or match[1] not in contracts:
            continue
        task_id = match[1]
        seen.add(task_id)
        if routing_update and task_id not in pending:
            continue
        contract = contracts[task_id]
        chunk = re.sub(r'^- (?:outputs|allowed paths|predicted files|receipt instructions|validation|required validation executables|required validation file pins|provider role|context budget tokens|proposal artifact envelope):[^\n]*\n?', '', chunk, flags=re.MULTILINE)
        lines = ['- outputs: ' + ', '.join(contract['outputs']), '- allowed paths: ' + ', '.join(contract['allowed_paths']), '- receipt instructions: ' + contract['receipt_instructions'], '- validation: ' + '; '.join(contract['validation_commands'])]
        if contract['required_validation_executables']:
            lines.append('- required validation executables: ' + ', '.join(contract['required_validation_executables']))
        if 'required_validation_file_pins' in contract:
            lines.append('- required validation file pins: ' + json.dumps(contract['required_validation_file_pins'], separators=(',', ':'), sort_keys=True))
        for label, key in [('provider role', 'provider_role'), ('context budget tokens', 'context_budget_tokens')]:
            if key in contract:
                lines.append('- ' + label + ': ' + str(contract[key]))
        if 'proposal_artifact_envelope' in contract:
            lines.append('- proposal artifact envelope: ' + json.dumps(contract['proposal_artifact_envelope'], separators=(',', ':'), sort_keys=True))
        chunks[index] = chunk.rstrip() + '\n' + '\n'.join(lines) + '\n\n'
    require(seen == set(contracts), 'board/plan task IDs differ')
    (root / PLAN).write_text(json.dumps(plan, indent=2) + '\n')
    (root / BOARD).write_text(''.join(chunks).rstrip() + '\n')
    return {'task_count': len(contracts), 'enriched': True, **({'local_inventory_enabled_count' if enable_local_inventory else 'local_width_replay_enabled_count': len(pending)} if routing_update else {})}


def check_board(root):
    root = Path(root)
    plan = json.loads((root / PLAN).read_text())
    found = {}
    for chunk in re.split(r'(?=^## )', (root / BOARD).read_text(), flags=re.MULTILINE):
        match = re.match(r'## (LIRAE-[A-Z0-9-]+)\b', chunk)
        if match:
            require(match[1] not in found, 'duplicate board task')
            found[match[1]] = chunk
    require(set(found) == {task['task_id'] for task in plan['tasks']}, 'board/plan task IDs differ')
    for task in plan['tasks']:
        task_id = task['task_id']
        chunk = found[task_id]
        contract = task_contract(task)
        for label, value in (('outputs', ', '.join(contract['outputs'])), ('allowed paths', ', '.join(contract['allowed_paths'])), ('validation', '; '.join(contract['validation_commands']))):
            require('- ' + label + ': ' + value in chunk, 'stale board ' + label + ' for ' + task_id)
        if contract['required_validation_executables']:
            require('- required validation executables: ' + ', '.join(contract['required_validation_executables']) in chunk, 'stale required executables for ' + task_id)
        if 'required_validation_file_pins' in contract:
            require('- required validation file pins: ' + json.dumps(contract['required_validation_file_pins'], separators=(',', ':'), sort_keys=True) in chunk, 'stale required file pins for ' + task_id)
        for label, key in [('provider role', 'provider_role'), ('context budget tokens', 'context_budget_tokens')]:
            if key in contract:
                require('- ' + label + ': ' + str(contract[key]) in chunk, 'stale local execution metadata for ' + task_id)
        if 'proposal_artifact_envelope' in contract:
            require('- proposal artifact envelope: ' + json.dumps(contract['proposal_artifact_envelope'], separators=(',', ':'), sort_keys=True) in chunk, 'stale artifact envelope for ' + task_id)
        require(all(task.get(key) == value for key, value in contract.items()), 'stale plan contract ' + task_id)
    require(sha((root / CONSTITUTION).read_bytes()) == CONSTITUTION_SHA256, 'retained Constitution input differs')
    return {'task_count': len(plan['tasks']), 'board_contract_valid': True}


def false_flags(value, constitution=False):
    require(isinstance(value, dict) and value.get('admitted') is False and value.get('formalized') is False, 'admitted/formalized must be exactly false')
    if constitution:
        require(value.get('roundtrip_ok') is False, 'Constitution roundtrip_ok must be false')
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {'admitted', 'formalized', 'roundtrip_ok'}:
                    require(child is False, 'artifact authority must stay false')
                pending.append(child)
        elif isinstance(item, list):
            pending.extend(item)


def read_artifacts(root, task_id, receipt):
    result = {}
    entries = receipt.get('artifacts')
    task_dir = (root / directory(task_id)).resolve()
    require(isinstance(entries, list) and entries, 'artifact references required')
    for entry in entries:
        relative = Path(str(entry.get('path', '')))
        path = root / relative
        require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe artifact path')
        require(path.is_file() and path.resolve().is_relative_to(task_dir) and path.name != 'receipt.json', 'artifact must exist inside task directory')
        raw = path.read_bytes()
        label = entry.get('kind')
        require(0 < len(raw) <= 128 * 1024 * 1024 and entry.get('sha256') == sha(raw), 'artifact hash/size differs')
        require(isinstance(label, str) and label and label not in result, 'unique artifact kinds required')
        result[label] = raw
    return result


def payload(data, label):
    require(label in data, 'missing ' + label + ' artifact')
    raw = data[label]
    if not raw.startswith(b'PK\x03\x04'):
        return json.loads(raw)
    require(label in {'sections', 'spans', 'entities'}, 'ZIP is only supported for USC inventory arrays')
    maximum = 128 * 1024 * 1024
    require(30 <= len(raw) <= maximum, 'bounded JSON ZIP required')
    # Reject multi-member/ZIP64/multi-disk/comment archives before ZipFile
    # constructs its directory objects. No filesystem extraction is performed.
    end = struct.unpack('<4s4H2LH', raw[-22:])
    require(end[0] == b'PK\x05\x06' and end[1:5] == (0, 0, 1, 1)
            and end[7] == 0 and end[6] + end[5] == len(raw) - 22,
            'one ordinary JSON ZIP member without archive comment required')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            require(len(members) == 1 and archive.comment == b'', 'one JSON ZIP member required')
            member = members[0]
            require(member.filename == label + '.json' and member.header_offset == 0
                    and not member.is_dir() and stat.S_ISREG(member.external_attr >> 16),
                    'ordinary exact JSON ZIP member required')
            require(member.flag_bits & ~0x800 == 0 and member.extra == member.comment == b''
                    and member.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED},
                    'encrypted, extra-field or unsupported JSON ZIP refused')
            require(0 < member.file_size <= maximum and 0 < member.compress_size <= maximum,
                    'JSON ZIP uncompressed size exceeds bound')
            header = struct.unpack('<4s5H3L2H', raw[:30])
            name_end = 30 + header[9]
            require(header[0] == b'PK\x03\x04' and header[10] == 0
                    and raw[30:name_end] == (label + '.json').encode()
                    and header[2] == member.flag_bits and header[3] == member.compress_type
                    and header[6:9] == (member.CRC, member.compress_size, member.file_size)
                    and name_end + member.compress_size == end[6],
                    'JSON ZIP local member/header differs')
            compressed = raw[name_end:end[6]]
            if member.compress_type == zipfile.ZIP_DEFLATED:
                decoder = zlib.decompressobj(-15)
                content = decoder.decompress(compressed, maximum + 1)
                require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
                        'JSON ZIP stream is incomplete, trailing or exceeds bound')
            else:
                content = compressed
            require(len(content) == member.file_size <= maximum
                    and zlib.crc32(content) & 0xffffffff == member.CRC,
                    'JSON ZIP size/CRC differs')
    except (zipfile.BadZipFile, RuntimeError, OSError, struct.error, zlib.error) as error:
        raise ContractError('invalid bounded JSON ZIP artifact') from error
    result = json.loads(content)
    require(isinstance(result, list), 'USC JSON ZIP must retain an array payload')
    return result


def usc_rows(title, *, source_parquet=None):
    parquet = Path(source_parquet) if source_parquet is not None else PINNED_PARQUET
    require(parquet.is_file(), 'exact pinned US Code input missing; container diagnostics may pass --corpus-parquet PATH to the exact downloaded snapshot (keep downloads in /tmp)')
    with parquet.open('rb') as stream:
        require(hashlib.file_digest(stream, 'sha256').hexdigest() == PARQUET_SHA256, 'US Code Parquet input digest differs')
    import pyarrow.parquet as pq
    result = []
    source_row_index = 0
    for batch in pq.ParquetFile(parquet).iter_batches(batch_size=4000, columns=['ipfs_cid', 'title_number', 'section_number', 'text']):
        for row in batch.to_pylist():
            row['source_row_index'] = source_row_index
            source_row_index += 1
            if ('NA' if row['title_number'] is None else str(row['title_number'])) == title:
                result.append(row)
    return sorted(result, key=lambda row: (str(row['section_number'] or ''), str(row['ipfs_cid'])))


def validate_uscode(shard, receipt, data, *, source_parquet=None):
    source = receipt.get('source', {})
    require(source.get('repository') == 'justicedao/ipfs_uscode' and source.get('revision') == REVISION, 'US Code pin differs')
    require(all(receipt.get('evidence', {}).get(key) == shard[key] for key in ('title', 'start', 'end', 'count')), 'shard identity differs')
    rows = usc_rows(str(shard['title'])) if source_parquet is None else usc_rows(str(shard['title']), source_parquet=source_parquet)
    expected = rows[shard['start']:shard['end']]
    sections, spans, entities = [payload(data, label) for label in ('sections', 'spans', 'entities')]
    require(all(isinstance(rows, list) for rows in (sections, spans, entities)), 'section/span/entity arrays required')
    require(len(expected) == shard['count'] == len(sections), 'all pinned sections need rows')
    def row_key(row):
        cid = row.get('ipfs_cid')
        return cid if isinstance(cid, str) and cid else ('parquet-row', row.get('source_row_index'))
    sources = {row_key(row): row for row in expected}
    actual = {row_key(row): row for row in sections}
    span_map = {}
    require(len(actual) == len(sections) and set(actual) == set(sources), 'section identities differ')
    for row in spans:
        false_flags(row)
        cid, text, sid = row.get('source_ipfs_cid'), row.get('text'), row.get('id')
        require(cid in sources and isinstance(text, str) and text.strip() and text in sources[cid]['text'], 'span plaintext absent from pinned source')
        require(row.get('source_text_sha256') == sha(sources[cid]['text'].encode()), 'span source hash differs')
        require(isinstance(sid, str) and sid and sid not in span_map, 'unique span IDs required')
        span_map[sid] = row
    for cid, source in sources.items():
        row = actual[cid]
        false_flags(row)
        if source['text'] is None:
            require(row.get('text') is None and row.get('source_text_sha256') is None and row.get('ipfs_cid') == source['ipfs_cid'] and row.get('status') == 'abstain' and isinstance(row.get('reason'), str) and row['reason'].strip() and not row.get('span_ids'), 'missing source plaintext requires explicit abstention')
            continue
        require(row.get('text') == source['text'] and row.get('source_text_sha256') == sha(source['text'].encode()), 'section plaintext/hash differs')
        if row.get('status') == 'abstain':
            require(isinstance(row.get('reason'), str) and row['reason'].strip(), 'abstention reason required')
        else:
            refs = row.get('span_ids')
            require(row.get('status') == 'spans' and isinstance(refs, list) and refs and all(sid in span_map and span_map[sid]['source_ipfs_cid'] == cid for sid in refs), 'section must cite its actual spans')
    for row in entities:
        false_flags(row)
        refs = row.get('span_ids')
        require(isinstance(row.get('id'), str) and row['id'] and isinstance(refs, list) and refs and all(sid in span_map for sid in refs), 'entity must cite actual spans')


def validate_constitution(root, task_id, receipt, data):
    source, rows = payload(data, 'source'), payload(data, 'spans')
    require(isinstance(source, dict) and isinstance(source.get('text'), str) and source.get('source_id'), 'full source plaintext/identity required')
    digest = sha(source['text'].encode())
    require(digest == CONSTITUTION_SHA256 == sha((root / CONSTITUTION).read_bytes()), 'Constitution retained input differs')
    require(source.get('sha256') == digest and receipt.get('source', {}).get('sha256') == digest and receipt['source'].get('source_id') == source['source_id'], 'Constitution source binding differs')
    if task_id == ANCILLARY_TASK:
        require(source['source_id'] == CONSTITUTION_SOURCE_ID, 'ancillary source identity differs')
    unit = selector(task_id)
    require(receipt.get('evidence', {}).get('unit_id') == unit, 'unit selector differs')
    inventory = owner(root, 'constitution_inventory').inventory_constitution(source['text'])
    expected = constitution_spans(inventory, task_id)
    require(expected and isinstance(rows, list) and len(rows) == len(expected), 'Constitution span coverage differs')
    actual = {row.get('id'): row for row in rows}
    require(len(actual) == len(rows) and set(actual) == {row['id'] for row in expected}, 'Constitution span IDs differ')
    for row in expected:
        item = actual[row['id']]
        false_flags(item, True)
        require(all(item.get(key) == row[key] for key in ('unit_id', 'text', 'status', 'reason')) and item.get('source_id') == source['source_id'] and item.get('source_text_sha256') == digest, 'span differs from actual inventory/source binding')
    if unit == 'amend-21':
        require(any(edge.get('kind') == 'repeal' and edge.get('target') == 'amend-18' for edge in inventory['edges']) and receipt['evidence'].get('repeal_treated_as_obligation') is False, 'retain text-backed repeal fixture')


def validate_width(task_id, receipt, data, *, root=None, replay_enabled=False):
    row = payload(data, 'observation')
    false_flags(row)
    dimension = int(task_id.split('-')[-1])
    require(row.get('dimension') == dimension and receipt.get('evidence', {}).get('dimension') == dimension, 'width differs')
    require(sorted(row.get('source_hashes', [])) == SAMPLE_HASHES, 'both pinned sample sources required')
    require(row.get('training_executed') is False and row.get('status') == 'observed', 'unavailable assets cannot complete')
    reviewed_replay = root is not None and replay_enabled and task_id in LOCAL_WIDTH_TASKS
    require(isinstance(row.get('profile_id'), str) and row['profile_id'] and 'checkpoint' in data, 'actual profile/checkpoint identity required')
    if not reviewed_replay:
        require(sha(data['checkpoint']) == row.get('checkpoint_sha256'), 'actual profile/checkpoint identity required')
    metrics = row.get('metrics', {})
    require(all(type(metrics.get(key)) in (int, float) and math.isfinite(metrics[key]) for key in ('cosine_similarity', 'reconstruction_loss')), 'finite measured metrics required')
    require(-1 <= metrics['cosine_similarity'] <= 1 and metrics['reconstruction_loss'] >= 0, 'metrics out of range')
    if dimension == 8:
        require(row.get('role') == 'donor' and row.get('corpus_default') is False, '8d remains donor')
    elif dimension == 384:
        require(row.get('corpus_default') is True, '384d remains corpus default')
    elif dimension == 768:
        require(row.get('token_ceiling') == 512, 'retain selected profile 512-token ceiling')
    else:
        require(row.get('encoder_executed') is False and row.get('development_result') == {'successful': 0, 'total': 12}, 'reuse saved vectors and retain 0/12')
    if reviewed_replay:
        require(row.get('measurement_scope') == 'identity_by_construction_not_learned_reconstruction', 'explicit projection measurement scope required')
        require(all(row.get(key) is False for key in ('quality_qualified', 'source_semantics_verified', 'statutory_fidelity_qualified', 'learned_reconstruction_demonstrated')), 'projection diagnostics cannot assert quality or fidelity')
        module = width_replay_owner(root)
        with tempfile.TemporaryDirectory(prefix='legal-ir-width-verify-') as scratch:
            result = module.verify_observation(Path(root), task_id, row, data['checkpoint'], output_directory=Path(scratch))
        require(isinstance(result, dict) and result.get('verified') is True, 'independent width replay verification failed')
        return
    # A file digest and plausible numbers are insufficient evidence of a run.
    # This fail-closed gate must be replaced by a reviewed owner replay that
    # authenticates the exact sample inputs, selected checkpoint and metrics.
    # An executable with the declared name alone cannot authorize completion.
    raise WidthReplayUnavailable(task_id)


def validate(root, task_id, *, source_parquet=None):
    root = Path(root).resolve()
    plan = json.loads((root / PLAN).read_text())
    require(any(task['task_id'] == task_id for task in plan['tasks']), 'task absent from plan')
    receipt = json.loads((root / directory(task_id) / 'receipt.json').read_text())
    family = kind(task_id)
    require(receipt.get('schema') == SCHEMA and receipt.get('task_id') == task_id and receipt.get('task_kind') == family, 'receipt identity differs')
    require(receipt.get('status') in {'inventory', 'implemented'}, 'pending/unavailable work cannot complete')
    false_flags(receipt.get('authority'), family == 'constitution')
    data = read_artifacts(root, task_id, receipt)
    if family == 'uscode':
        validate_uscode(next(row for row in plan['shards'] if row['task_id'] == task_id), receipt, data, source_parquet=source_parquet)
    elif family == 'constitution':
        validate_constitution(root, task_id, receipt, data)
    elif family == 'width':
        task = next(task for task in plan['tasks'] if task['task_id'] == task_id)
        validate_width(task_id, receipt, data, root=root, replay_enabled=task.get('local_width_replay') is True)
    else:
        require(sorted(receipt.get('evidence', {}).get('source_hashes', [])) == SAMPLE_HASHES, 'method source pins differ')
        require('lean_source' in data, 'actual Lean source required')
        source = data['lean_source'].decode()
        require(not re.search(r'\b(sorry|axiom)\b', source), 'Lean proof escape')
        lean = owner(root, 'lean_units')
        require(source == lean.render_term_lean('object', 'born alive', statute_ids=['usc:us:1:8', 'usc:us:10:1059']), 'method source differs from pinned template')
        found = {row['ipfs_cid']: sha(row['text'].encode()) for title in ('1', '10') for row in (usc_rows(title) if source_parquet is None else usc_rows(title, source_parquet=source_parquet))}
        require(found.get('bafkreig4hls5clk3wa5iec5oa575e7gcpnyn3smiicsxgucu4yl654cvnu') == SAMPLE_HASHES[1] and found.get('bafkreihd2kvpadnqo2bwhjti7sq3kunzamoicottjgy32kva6eduqkcvru') == SAMPLE_HASHES[0], 'method source plaintext pins differ')
        result = lean.probe_lean_source(source)
        require(result.get('lake_ok') is True and result.get('admitted') is False and result.get('formalized') is False, 'real lake build Legal failed')
    return {'task_id': task_id, 'validated': True, 'admitted': False, 'formalized': False, **({'lake_ok': True} if family == 'method' else {})}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--enrich', action='store_true')
    modes.add_argument('--enable-local-inventory', action='store_true', help='Enable reviewed local inventory only for currently pending US Code shards; completed contracts remain unchanged')
    modes.add_argument('--enable-local-width-replay', action='store_true', help='Enable reviewed frozen replay only for pending384/768 tasks; preserve every other contract')
    modes.add_argument('--check-board', action='store_true')
    modes.add_argument('--check-task', metavar='TASK_ID')
    modes.add_argument('--inspect-width-prerequisites',
        choices=('LIRAE-WIDTH-08', 'LIRAE-WIDTH-4096', 'all'), metavar='TASK_ID|all',
        help='Print declared pending-width requirements only; inspect no files and authorize no completion')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--corpus-parquet', type=Path, help='Exact pinned Parquet for local diagnostics; its immutable digest is always checked')
    args = parser.parse_args(argv)
    try:
        if args.inspect_width_prerequisites == 'all':
            result = {
                'schema': 'legal-ir-width-replay-prerequisite-bundle/v1',
                'diagnostic_scope': 'declared_requirements_only',
                'diagnostics': [inspect_width_prerequisites(task_id)
                    for task_id in ('LIRAE-WIDTH-08', 'LIRAE-WIDTH-4096')],
                'completion_allowed': False,
            }
        elif args.inspect_width_prerequisites is not None:
            result = inspect_width_prerequisites(args.inspect_width_prerequisites)
        else:
            result = enrich(args.root, enable_local_width_replay=True) if args.enable_local_width_replay else enrich(args.root, enable_local_inventory=True) if args.enable_local_inventory else enrich(args.root) if args.enrich else check_board(args.root) if args.check_board else validate(args.root, args.check_task, source_parquet=args.corpus_parquet)
    except WidthReplayUnavailable as exc:
        print(json.dumps(exc.receipt, sort_keys=True), file=sys.stderr)
        return 75
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as exc:
        print('LegalIR contract failed: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
