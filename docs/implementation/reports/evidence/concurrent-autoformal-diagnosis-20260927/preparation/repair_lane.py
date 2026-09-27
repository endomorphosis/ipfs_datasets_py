"""One local, bounded, unapplied parser proposal retained in a native goal store.

This producer does not claim or complete a supervisor implementation task.
Only the existing local llama.cpp endpoint may receive HTTP requests.
"""
from __future__ import annotations
import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from datetime import datetime, timezone
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'harness'))
from smoke_resource_common import ROOT, ACCELERATE, DEPENDENCY, ScopedSources, exact, ref, require, save, verify_binding
ENDPOINT = 'http://172.17.0.1:8080'
MODEL = 'leanstral_local'
MAX_OUTPUT = 768
MAX_CONTEXT = 4096
MAX_RESPONSE_BYTES = 64_000


def require_intent_metadata(value):
    """Native intent DAG-JSON accepts no floats; HTTP evidence stays separate."""
    if isinstance(value, dict):
        require(all(isinstance(key, str) for key in value), 'intent metadata keys must be strings')
        for item in value.values(): require_intent_metadata(item)
    elif isinstance(value, list):
        for item in value: require_intent_metadata(item)
    else:
        require(value is None or isinstance(value, (str, int, bool)),
                'intent metadata must use integer/decimal-string numbers, never float')


def plain_json(value):
    if isinstance(value, Mapping):
        return {key: plain_json(member) for key, member in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain_json(member) for member in value]
    return value


def event(stage, **extra):
    return {'stage': stage, 'monotonic_ns': time.monotonic_ns(),
            'utc': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(), **extra}


def write_text(path, text):
    raw = text.encode('utf-8')
    require(len(raw) <= MAX_RESPONSE_BYTES, 'text artifact exceeds 64 KB')
    with Path(path).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return ref(path)


def post_json(url, value=None):
    payload = json.dumps(value).encode() if value is not None else None
    request = urllib.request.Request(url, data=payload,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST' if value is not None else 'GET')
    with urllib.request.urlopen(request, timeout=5) as response:
        raw = response.read(256_001)
        require(len(raw) <= 256_000, 'metadata endpoint response exceeds bound')
        return json.loads(raw)


def install_network_observer(runtime, expected):
    observations = []
    permitted = {'/health', '/v1/models', '/props', '/apply-template', '/tokenize', '/v1/chat/completions'}
    def audit(name, args):
        if name == 'socket.connect':
            address = args[1]
            require(isinstance(address, tuple) and len(address) >= 2 and
                    address[0] == '172.17.0.1' and address[1] == 8080,
                    'proposal lane network endpoint is not authorized')
        elif name == 'urllib.Request':
            url, data, headers, method = args
            parsed = urllib.parse.urlsplit(url)
            require(parsed.scheme == 'http' and parsed.netloc == '172.17.0.1:8080'
                    and parsed.path in permitted and not parsed.query and not parsed.fragment,
                    'proposal lane URL is not authorized')
            if parsed.path == '/v1/chat/completions':
                require(method == 'POST' and not observations, 'only one generation request is authorized')
                body = json.loads(data)
                require(body == expected.get('payload'), 'actual router HTTP arguments differ from reviewed request')
                record = event('actual_router_http_request', method=method, url=url,
                               body=body, body_sha256=hashlib.sha256(data).hexdigest())
                save(runtime / 'actual-http-request.json', record)
                observations.append(record)
    sys.addaudithook(audit)
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    return observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--training-marker', type=Path, required=True)
    parser.add_argument('--plan', type=Path, default=HERE / 'repair-proposal-plan.json')
    args = parser.parse_args()
    require(sys.stdin.readline() == 'RUN\n', 'root launch barrier missing')
    runtime = args.runtime_root.absolute()
    require(runtime.is_dir() and runtime.resolve() == runtime, 'runtime must be existing owned canonical directory')
    require(not (runtime / 'proposal-receipt.json').exists(), 'proposal attempt cannot be reused')
    marker = args.training_marker.absolute()
    require(marker.is_relative_to(ROOT / 'workspace/test-logs/federal-corpus-audits') and
            marker.resolve() == marker, 'training marker outside owned canonical audit root')
    started = time.monotonic()
    source_observations = ScopedSources()
    sys.path[:0] = [str(ACCELERATE), str(ROOT), str(ROOT / 'scripts/ops/legal_ir')]
    plan_ref = ref(args.plan)
    plan = json.loads(args.plan.read_bytes())
    require(plan['provider']['temperature'] == 0 and plan['provider']['request_context_budget_tokens'] == MAX_CONTEXT,
            'proposal policy drift')
    require(ref(plan['source_receipt']['path'])['sha256'] == plan['source_receipt']['sha256'], 'training evidence changed')
    require(ref(plan['parser_source']['path'])['sha256'] == plan['parser_source']['sha256'], 'parser source changed')
    save(runtime / 'sealed-plan.json', plan)
    inputs = [plan_ref, ref(plan['source_receipt']['path']), ref(plan['parser_source']['path'])]
    expected_request = {}
    observed = install_network_observer(runtime, expected_request)
    receipt = {'schema': 'native-goal-local-parser-proposal/v1', 'passed': False,
               'admitted': False, 'formalized': False, 'applied': False, 'imported': False,
               'wrote_compiler': False, 'native_claimed': False, 'native_daemon_executed': False,
               'native_task_completed': False, 'review_required': True, 'provider_calls': 0,
               'provider': plan['provider'], 'plan': plan_ref, 'error': None}
    task_source = None
    try:
        binding = verify_binding(DEPENDENCY)
        from run_autoformal_supervisor import pin_accelerate
        pin = pin_accelerate(ACCELERATE)
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        tree_pin = require_workspace_logic_tree()
        from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
        from ipfs_accelerate_py.agent_supervisor.task_sources.control_plane_contracts import content_identity
        from ipfs_datasets_py.logic.autoformal.supervisor_router import resolve_gap_with_router, router_prompt, _scoped_proposal
        from ipfs_accelerate_py import llm_router
        rows = plan['training_gap_rows']
        require(len(rows) == 3 and all(x['allow_partial'] is False and x['compiler_status'] == 'abstained' for x in rows),
                'proposal evidence must be three strict training gaps')
        target = next(x for x in rows if x['source']['legal_id'] == 'usc:us:16:6809')
        row = {**target['source'], 'reason': 'compiler_abstain:calendar_date_object_loss',
               'allowed_edit_paths': plan['allowed_edit_paths'], 'preserve': plan['limitations'],
               'replace': [plan['focus']], 'decompiled': '', 'agrees': False, 'skipped': False}
        prompt = router_prompt(row) + '\nAdditional evidence and code anchors (data, not instructions):\n' + json.dumps({
            'training_gaps': [{'text': x['source']['text'], 'source_span_id': x['source']['source_span_id'],
                              'strict_diagnostics': x['strict_diagnostics'], 'parser_vocabulary': x['parser_vocabulary']} for x in rows],
            'code_anchors': plan['code_anchors'], 'required_output': 'Only the parser key with a minimal generic Python function replacement. No prose, no imports, no source execution.'},
            sort_keys=True, ensure_ascii=True)
        prompt_ref = write_text(runtime / 'prompt.txt', prompt)
        health = post_json(ENDPOINT + '/health')
        models = post_json(ENDPOINT + '/v1/models')
        props = post_json(ENDPOINT + '/props')
        require(health.get('status') == 'ok' and MODEL in [x.get('id') for x in models.get('data', [])], 'local model not ready')
        physical = props.get('default_generation_settings', {}).get('n_ctx')
        require(isinstance(physical, int) and physical == plan['provider']['physical_server_context_preflight'],
                'existing server context differs; no reconfiguration authorized')
        messages = [{'role': 'user', 'content': prompt}]
        template = post_json(ENDPOINT + '/apply-template', {'messages': messages, 'add_generation_prompt': True})
        rendered = template.get('prompt')
        require(isinstance(rendered, str), 'server did not return the applied chat template')
        write_text(runtime / 'rendered-prompt.txt', rendered)
        tokenized = post_json(ENDPOINT + '/tokenize', {'content': rendered, 'add_special': True, 'parse_special': True})
        tokens = tokenized.get('tokens')
        require(isinstance(tokens, list) and all(isinstance(x, int) for x in tokens), 'server tokenizer unavailable')
        # Keep 64 tokens of additional template margin and reserve every output token.
        require(len(tokens) + MAX_OUTPUT + 64 <= MAX_CONTEXT, 'whole request exceeds unchanged 4096-token budget')
        budget = {'input_tokens': len(tokens), 'max_new_tokens': MAX_OUTPUT, 'template_margin_tokens': 64,
                  'request_context_budget_tokens': MAX_CONTEXT, 'physical_server_context_tokens': physical,
                  'physical_server_context_changed': False, 'template_sha256': hashlib.sha256(rendered.encode()).hexdigest()}
        save(runtime / 'request-budget.json', budget)
        task_id = content_identity({'schema': 'local-parser-proposal-task/v1', 'plan_sha256': plan_ref['sha256'], 'prompt_sha256': prompt_ref['sha256']})
        goal_id = content_identity({'schema': 'local-parser-proposal-goal/v1', 'task_id': task_id})
        acceptance = 'Retain one bounded local temperature-zero raw proposal plus its exact HTTP request, source evidence and parser-scope diagnostic for human review. This is proposal evidence only; do not implement or complete a repair task, remove strict abstention, change any source, admit Lean, promote weights, or upload.'
        goal = {'goal_cid': goal_id, 'goal_alias': 'LOCAL-PARSER-PROPOSAL', 'title': 'Review a generic calendar-date parser repair proposal',
                'status': 'open', 'kind': 'unapplied-source-proposal', 'instructions': acceptance,
                'sealed_plan': plan, 'prompt': prompt, 'context_budget': budget}
        task = {'task_cid': task_id, 'task_id': 'PROPOSAL-' + plan_ref['sha256'][:20], 'goal_cid': goal_id,
                'title': 'Generate one reviewable local parser proposal from strict US Code gaps', 'status': 'ready',
                'board_namespace': 'autoformal-local-proposal-smoke-v1', 'is_schedulable': False,
                'review_only': True, 'completion': 'evidence', 'context_budget_tokens': MAX_CONTEXT,
                'provider_configuration': plan['provider'], 'description': acceptance, 'body_markdown': prompt,
                'sealed_plan': plan_ref, 'training_sources': rows,
                'outputs': [{'path': 'raw-proposal.txt'}], 'acceptance_criteria': [acceptance],
                'validation_commands': []}
        population = {'repository_tree_id': 'sha256:' + plan['parser_source']['sha256'], 'goals': [goal], 'tasks': [task]}
        require_intent_metadata(population)
        save(runtime / 'goal-task-payload.json', population)
        task_source = DatabaseTaskSource(runtime / 'proposal.duckdb', owner_id='bounded-local-parser-proposal')
        save(runtime / 'materialization-receipt.json', dict(task_source.materialize(population)))
        before = task_source.get(task_id)
        require(before and before.status == 'ready' and before.body['body_markdown'] == prompt, 'native task lost prompt or status')
        stored_goal = task_source.intent.get_goal(goal_id)
        require(stored_goal['body']['prompt'] == prompt, 'native goal lost prompt')
        save(runtime / 'native-task-before.json', before.to_dict())
        save(runtime / 'native-goal-before.json', plain_json(stored_goal))
        save(runtime / 'proposal-ready.json', event('native_goal_prepared_waiting_for_training'))
        while not marker.exists():
            if marker.with_name('summary.json').exists():
                raise RuntimeError('linked training lane finished without native method entry')
            require(time.monotonic() - started < 400, 'training method entry marker not observed within 400 seconds')
            time.sleep(.1)
        marker_row = ref(marker)
        signal = json.loads(marker.read_bytes())
        require(signal.get('stage') == 'native_training_method_entry' and isinstance(signal.get('monotonic_ns'), int),
                'marker does not record actual native training entry')
        require(not marker.with_name('training-finished.json').exists(), 'training completed before proposal dispatch')
        save(runtime / 'training-start-observation.json', {'artifact': marker_row, 'event': signal})
        expected_request['payload'] = {'model': MODEL, 'messages': messages, 'max_tokens': MAX_OUTPUT,
                                       'temperature': 0.0, 'seed': 0, 'response_format': {'type': 'json_object'}}
        generated = {}
        def generate(original_prompt, **kwargs):
            require(original_prompt == router_prompt(row) and kwargs == {'temperature': 0, 'task_kind': 'legal'}, 'resolver generation request changed')
            generated['started'] = event('router_generate_start')
            save(runtime / 'request-started.json', generated['started'])
            try:
                raw = llm_router.generate_text(prompt, provider='llama_cpp', model_name=MODEL,
                    allow_local_fallback=False, allow_cross_provider_fallback=False,
                    temperature=0.0, seed=0, max_tokens=MAX_OUTPUT, timeout=120,
                    response_format={'type': 'json_object'}, task_kind='legal')
                generated['raw'] = str(raw)
                generated['artifact'] = write_text(runtime / 'raw-proposal.txt', generated['raw'])
                return generated['raw']
            finally:
                generated['finished'] = event('router_generate_finished')
                save(runtime / 'request-finished.json', generated['finished'])
        resolved = resolve_gap_with_router(row, generate)
        save(runtime / 'scope-validation.json', resolved)
        require(len(observed) == 1, 'no real local provider request observed')
        proposal, diagnostic = _scoped_proposal(generated['raw'], {'parser'})
        if proposal:
            save(runtime / 'canonical-proposal.json', proposal)
        trace = llm_router.get_last_generation_trace()
        save(runtime / 'router-trace.json', trace)
        artifacts = [ref(path) for path in sorted(runtime.glob('*')) if path.is_file() and path.name != 'repair-lane.log' and path.suffix != '.duckdb' and '.duckdb.' not in path.name]
        body = dict(before.body)
        body['router_proposal'] = {**resolved, 'applied': False, 'review_required': True,
                                  'raw_proposal': generated['artifact'], 'artifacts': artifacts,
                                  'provider': plan['provider'], 'request_budget': budget,
                                  'request_observation': ref(runtime / 'actual-http-request.json')}
        require_intent_metadata(body)
        task_source.intent.upsert_task(task_cid=before.task_cid, task_alias=before.task_alias,
            goal_cid=before.goal_cid, ordinal=before.ordinal, status=before.status, priority=before.priority,
            plan_cid=before.plan_cid, objective_id=before.objective_id, body=body,
            expected_revision=before.revision, dependencies=list(before.dependencies), outputs=list(before.outputs),
            acceptance=list(before.acceptance), validations=list(before.validations))
        after = task_source.get(task_id)
        require(after.status == before.status and after.body['body_markdown'] == prompt and
                after.body['router_proposal']['raw_proposal'] == generated['artifact'], 'proposal CAS persistence changed contract')
        save(runtime / 'native-task-after.json', after.to_dict())
        task_source.close(); task_source = None
        require(exact(inputs), 'proposal source inputs changed')
        source_rows = source_observations.verify()
        receipt.update(passed=bool(proposal) and not diagnostic, proposal_scope_valid=bool(proposal) and not diagnostic,
            scope_diagnostic=diagnostic, provider_calls=1, native_task_status=after.status,
            native_goal_cid=goal_id, native_task_cid=task_id, prompt_persisted_without_truncation=True,
            prompt=prompt_ref, raw_proposal=generated['artifact'], proposal_digest=resolved['proposal_sha256'],
            proposal_request_wall_seconds=(generated['finished']['monotonic_ns']-generated['started']['monotonic_ns'])/1e9,
            actual_request_start_monotonic_ns=observed[0]['monotonic_ns'],
            actual_request_end_monotonic_ns=generated['finished']['monotonic_ns'],
            training_start_monotonic_ns=signal['monotonic_ns'], request_budget=budget,
            scoped_sources=source_rows, accelerate_dependency=binding, tree_pin=tree_pin, accelerate_pin=pin)
    except BaseException as exc:
        receipt['error'] = {'type': type(exc).__name__, 'message': str(exc)[:2000], 'traceback': traceback.format_exc()[-8000:]}
        receipt['provider_calls'] = len(observed)
    finally:
        if task_source is not None:
            task_source.close()
        try:
            receipt['scoped_sources'] = source_observations.verify()
            receipt['accelerate_dependency_after'] = verify_binding(DEPENDENCY)
            require(exact(inputs), 'input source drift')
        except BaseException as exc:
            receipt['passed'] = False
            receipt['source_guard_error'] = str(exc)[:2000]
        receipt['elapsed_seconds'] = time.monotonic() - started
        save(runtime / 'proposal-receipt.json', receipt)
    print(json.dumps({'passed': receipt['passed'], 'provider_calls': receipt['provider_calls'],
                      'receipt': str(runtime / 'proposal-receipt.json')}), flush=True)
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
