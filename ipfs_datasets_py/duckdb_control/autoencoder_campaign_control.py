"""Bounded owner control of original, prepared v8 campaign jobs.

Wire submission persists intent only. The owner explicitly drains requests in
sequence; B2 owns resource admission, parallel workers, replay and completion.
Each drain has its own durable start/finish. An uncertain start never calls B2
again: B2 may otherwise dispatch an untouched remainder of the request.
Reads inspect registry history, not the journal held by an executing B2 call.
No listener, worker or network operation starts when this module is imported.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Mapping
import uuid

from .autoencoder_registry import AutoencoderRegistry, SCHEMA as REGISTRY_SCHEMA, _artifact, _token
from .contracts import canonical_json_bytes
from ..optimizers.logic_theorem_optimizer import autoencoder_campaign_owned_training as preparation
from ..optimizers.logic_theorem_optimizer import autoencoder_campaign_training_request as codec
from ..optimizers.logic_theorem_optimizer.autoencoder_daemon_operation_journal import DurableDaemonOperationJournal

SCHEMA = 'autoencoder-owned-campaign-control-v1'
MAX_ASSIGNMENTS = 64
MAX_RUNS = 64
MAX_DRAINS = 64
MAX_REPLY_BYTES = 128 * 1024
MAX_TOTAL_REQUEST_BYTES = 64 * 1024 * 1024
_SUBMIT = 'SubmitCampaignTraining'
_BIND = 'BindCampaignTrainingControl'
_START = 'StartCampaignTrainingDrain'
_FINISH = 'FinishCampaignTrainingDrain'
_AUTHORITY_FALSE = ('admitted', 'formalized', 'promotion_performed', 'publication_performed',
                    'source_authority_authenticated', 'global_holdout_verified')


class OwnedCampaignControlError(ValueError):
    """An immutable assignment or its durable control history differs."""


def _require(value, message):
    if not value:
        raise OwnedCampaignControlError(message)


def _same(left, right):
    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _copy(value, maximum=codec.MAX_REQUEST_BYTES):
    codec._ordinary(value)
    raw = canonical_json_bytes(value)
    _require(len(raw) <= maximum, 'control value exceeds byte bound')
    return json.loads(raw)


def _reply(value):
    return _copy(value, MAX_REPLY_BYTES)


def _digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _identifier(value, name):
    _require(type(value) is str, name + ' must be an exact string')
    _token(value, name)
    return value


def _content(value):
    _require(type(value) is dict and set(value) == {'sha256', 'bytes'}
             and type(value['sha256']) is str and type(value['bytes']) is int,
             'request_artifact must be an ordinary descriptor')
    ref = _artifact(value)
    _require(0 < ref['bytes'] <= codec.MAX_REQUEST_BYTES, 'request artifact exceeds bound')
    return ref


def _phase_id(control_id, ordinal, phase):
    return 'campaign-control-' + phase + ':' + _digest({'control': control_id, 'ordinal': ordinal})


def _check_finish_capacity(registry, request, ref):
    """Reject oversized future finish commands before a worker can start."""
    ids = [row['run_id'] for row in request['batches']]
    completed = [{'run_id': run_id, 'completion_receipt_sha256': 'f' * 64,
        'candidate_version_id': 'sha256:' + 'f' * 64,
        'candidate': {'sha256': 'f' * 64, 'bytes': 2**63 - 1},
        'execution_mode': 'native_training'} for run_id in ids]
    summary = {'status': 'recovery_required', 'report_sha256': 'f' * 64,
        'execution_mode': 'native_training', 'recorded_native_execution_verified': False,
        'dispatched_run_ids': ids, 'completed': completed, 'deferred_run_ids': []}
    payload = {'control_operation_id': 'campaign-control:' + 'f' * 64, 'ordinal': MAX_DRAINS,
        'execution_id': 'f' * 32, 'request_artifact': ref, 'start_sha256': 'f' * 64, 'summary': summary}
    # Candidate versions use the registry's fixed sha256 identity. Replacing a
    # completed record with its shorter deferred ID cannot enlarge this bound.
    registry._command_digest('campaign-control-finish:' + 'f' * 64, _FINISH, payload)
    return len(canonical_json_bytes({'command': _FINISH, 'payload': payload}))


def _pristine(run):
    return (run['status'] == 'queued' and type(run['attempt']) is int and run['attempt'] == 0
            and type(run['fence']) is int and run['fence'] == 0
            and run['lease'] is None and run['result'] is None)


class OwnedCampaignControl:
    """Immutable campaign assignments for one owner and submitting worker.

    ``max_new_batches`` on ``execute_pending`` is a total budget across that
    invocation, charged conservatively by each started drain's selected prefix.
    Each request receives at most one B2 call per owner drain. Only a durable
    successful finish permits the next explicit drain. ``read`` reports recorded
    verification; it does not verify current candidate files or native capability.
    """

    def __init__(self, registry: AutoencoderRegistry, *, worker_id: str,
                 prepared_campaigns: Mapping[str, Mapping[str, Any]]) -> None:
        _require(type(registry) is AutoencoderRegistry, 'control requires the actual registry owner')
        self._registry = registry
        self._owner = preparation._owner(registry)
        self._worker_id = _identifier(worker_id, 'worker_id')
        _require(type(prepared_campaigns) is dict and 1 <= len(prepared_campaigns) <= MAX_ASSIGNMENTS,
                 'control requires one to 64 prepared campaigns')
        preparation._pin()
        self._prepared, self._requests = {}, {}
        run_ids, byte_count = set(), 0
        for key, supplied in prepared_campaigns.items():
            _require(type(supplied) is dict and set(supplied) == {'request_artifact', 'journal_path', 'registration'},
                     'invalid prepared campaign handle')
            handle = _copy(supplied)
            ref = _content(handle['request_artifact'])
            _require(key == ref['sha256'], 'campaign key differs from request digest')
            byte_count += ref['bytes']
            _require(byte_count <= MAX_TOTAL_REQUEST_BYTES, 'aggregate prepared requests exceed bound')
            request = codec.decode_campaign_training_request(preparation._read(registry, ref, codec.MAX_REQUEST_BYTES))
            _require(_same(request['owner'], self._owner) and request['worker_id'] == self.worker_id,
                     'prepared campaign belongs to another owner or worker')
            _check_finish_capacity(registry, request, ref)
            expected_journal = str(Path(request['output_root']) / 'owner-operations.json')
            _require(handle['journal_path'] == expected_journal, 'prepared journal path differs')
            registration = preparation._history(registry, request, ref, required=True)
            _require(_same(handle['registration'], registration), 'prepared registration receipt differs')
            selected = {row['run_id'] for row in request['batches']}
            _require(not (selected & run_ids), 'prepared campaigns overlap original runs')
            run_ids.update(selected)
            _require(len(run_ids) <= MAX_RUNS, 'assigned original run union exceeds 64')
            self._prepared[key], self._requests[key] = handle, request
            self._check_runs(request)
        self._run_ids = frozenset(run_ids)
        self._request_sha256s = frozenset(self._prepared)
        self._pid, self._lock = os.getpid(), threading.RLock()
        self._running, self._draining, self._closed = set(), False, False

    @property
    def registry(self):
        return self._registry

    @property
    def worker_id(self):
        return self._worker_id

    @property
    def run_ids(self):
        return self._run_ids

    @property
    def request_sha256s(self):
        return self._request_sha256s

    def _ensure_open(self):
        _require(not self._closed and os.getpid() == self._pid, 'controller is closed or inherited by another process')
        self.registry._ensure_owner()
        _require(_same(self._owner, {'database_path': str(self.registry.database_path),
                                     'artifact_root': str(self.registry.artifact_root)}), 'registry owner changed')

    def _assignment(self, supplied):
        self._ensure_open()
        ref = _content(supplied)
        handle = self._prepared.get(ref['sha256'])
        _require(handle is not None and _same(handle['request_artifact'], ref), 'request is outside assigned scope')
        return handle, self._requests[ref['sha256']], ref

    def _check_runs(self, request, connection=None):
        runs = []
        for batch in request['batches']:
            run = (self.registry.get_run(batch['run_id']) if connection is None
                   else self.registry._run(connection, batch['run_id']))
            _require(run['variant_id'] == request['variant_id'] and run['base_version_id'] == batch['base_version_id']
                     and run['spec'].get('job_spec_sha256') == batch['job_spec_sha256']
                     and _same(run['spec'].get('job_spec_artifact'), batch['job_spec_artifact']),
                     'registered original job binding differs')
            runs.append(run)
        return runs

    def _check_prepared(self, handle, request, ref):
        # First submission only. Duplicate receipts/read/resolve never wait for
        # the execution journal. B2 independently validates full inputs later.
        _require(all(_pristine(run) for run in self._check_runs(request)), 'new submission requires pristine original jobs')
        current = codec.decode_campaign_training_request(preparation._read(self.registry, ref, codec.MAX_REQUEST_BYTES))
        _require(_same(current, request), 'prepared request bytes changed')
        registration = preparation._history(self.registry, request, ref, required=True)
        _require(_same(registration, handle['registration']), 'preparation history changed')
        path, _ = preparation._journal_paths(request, existing=True)
        _require(str(path) == handle['journal_path'], 'prepared journal differs')
        with DurableDaemonOperationJournal(path, preparation._journal_binding(request, ref), create=False) as journal:
            _require(_same(journal.get_metadata('prepared'), {'request_artifact': ref, 'journal_path': str(path)}),
                     'journal prepared binding differs')
            saved = journal.get_metadata('registration')
            _require(saved is None or _same(saved, registration), 'journal registration differs')
            _require(not journal.operations(), 'new submission cannot adopt execution history')

    def _submission(self, operation_id, supplied):
        handle, request, ref = self._assignment(supplied)
        _identifier(operation_id, 'operation_id')
        control_id = 'campaign-control:' + _digest({'owner': self._owner, 'worker_id': self.worker_id,
                                                   'wire_operation_id': operation_id})
        payload = {'control_schema': SCHEMA, 'owner': self._owner, 'worker_id': self.worker_id,
                   'wire_operation_id': operation_id, 'request_artifact': ref,
                   'prepared_sha256': _digest(handle), 'run_ids': [row['run_id'] for row in request['batches']]}
        return control_id, payload

    def _get_operation(self, operation_id):
        with self.registry._transaction() as connection:
            row = connection.execute('SELECT payload_digest, receipt FROM autoencoder_control.operations WHERE operation_id=?',
                                     [operation_id]).fetchone()
        return None if row is None else {'payload_digest': row[0], 'receipt': json.loads(row[1])}

    def _mutate(self, operation_id, command, payload, apply):
        try:
            return self.registry._mutate(operation_id, command, payload, apply)
        except Exception:
            try:
                resolved = self.registry.resolve_operation(operation_id, command, payload)
            except Exception:
                resolved = None
            if resolved is not None:
                return resolved
            raise

    def _binding_id(self, ref):
        return 'campaign-control-request:' + _digest({'owner': self._owner, 'request_artifact': ref})

    def _accepted(self, receipt, control_id, payload):
        expected = {'schema': REGISTRY_SCHEMA, 'operation_id': control_id, 'command': _SUBMIT,
                    'admitted': False, **payload, 'status': 'accepted'}
        _require(_same(receipt, expected), 'durable submission receipt differs')
        return _reply({'schema': SCHEMA, 'status': 'accepted', 'request_artifact': payload['request_artifact'],
                       'wire_operation_id': payload['wire_operation_id'], 'control_operation_id': control_id,
                       **{name: False for name in _AUTHORITY_FALSE}})

    def _find_submission(self, ref):
        binding_id = self._binding_id(ref)
        operation = self._get_operation(binding_id)
        if operation is None:
            return None
        receipt = operation['receipt']
        _require(type(receipt) is dict and type(receipt.get('submission_payload')) is dict,
                 'invalid durable campaign binding')
        control_id, payload = self._submission(receipt['submission_payload'].get('wire_operation_id'), ref)
        bound = {'owner': self._owner, 'request_artifact': ref, 'control_operation_id': control_id,
                 'submission_payload': payload}
        expected = {'schema': REGISTRY_SCHEMA, 'operation_id': binding_id, 'command': _BIND,
                    'admitted': False, **bound}
        _require(_same(receipt, expected) and _same(self.registry.resolve_operation(binding_id, _BIND, bound), receipt),
                 'durable campaign binding differs')
        return self._accepted(self.registry.resolve_operation(control_id, _SUBMIT, payload), control_id, payload)

    def submit(self, operation_id: str, request_artifact: Mapping[str, Any]) -> dict:
        control_id, payload = self._submission(operation_id, request_artifact)
        old = self.registry.resolve_operation(control_id, _SUBMIT, payload)
        if old is not None:
            return self._accepted(old, control_id, payload)
        handle, request, ref = self._assignment(request_artifact)
        self._check_prepared(handle, request, ref)
        def apply(connection):
            binding_id = self._binding_id(ref)
            _require(connection.execute('SELECT 1 FROM autoencoder_control.operations WHERE operation_id=?',
                                        [binding_id]).fetchone() is None, 'campaign already has a selected submission')
            _require(all(_pristine(run) for run in self._check_runs(request, connection)), 'original job is no longer pristine')
            bound = {'owner': self._owner, 'request_artifact': ref, 'control_operation_id': control_id,
                     'submission_payload': payload}
            receipt = {'schema': REGISTRY_SCHEMA, 'operation_id': binding_id, 'command': _BIND,
                       'admitted': False, **bound}
            connection.execute('INSERT INTO autoencoder_control.operations VALUES (?, ?, ?)',
                [binding_id, self.registry._command_digest(binding_id, _BIND, bound), canonical_json_bytes(receipt).decode()])
            return {**payload, 'status': 'accepted'}
        return self._accepted(self._mutate(control_id, _SUBMIT, payload, apply), control_id, payload)

    def resolve(self, operation_id: str, request_artifact: Mapping[str, Any]) -> dict:
        control_id, payload = self._submission(operation_id, request_artifact)
        old = self.registry.resolve_operation(control_id, _SUBMIT, payload)
        receipt = None if old is None else self._accepted(old, control_id, payload)
        return _reply({'schema': SCHEMA, 'wire_operation_id': operation_id, 'control_operation_id': control_id,
                      'resolution': 'missing' if old is None else 'committed', 'receipt': receipt,
                      **{name: False for name in _AUTHORITY_FALSE}})

    def _phase(self, accepted, ordinal, phase, operations=None):
        control_id = accepted['control_operation_id']
        operation_id = _phase_id(control_id, ordinal, phase)
        operation = self._get_operation(operation_id) if operations is None else operations.get(operation_id)
        if operation is None:
            return None
        receipt = operation['receipt']
        names = {'control_operation_id', 'ordinal', 'execution_id', 'request_artifact'} | (
            {'selected_run_ids', 'max_new_batches', 'max_workers'} if phase == 'start' else {'start_sha256', 'summary'})
        _require(type(receipt) is dict and set(receipt) == names | {'schema', 'operation_id', 'command', 'admitted'},
                 'invalid durable drain phase')
        payload = {name: receipt[name] for name in names}
        command = _START if phase == 'start' else _FINISH
        _require(_same(receipt, {'schema': REGISTRY_SCHEMA, 'operation_id': operation_id, 'command': command,
                                'admitted': False, **payload})
                 and payload['control_operation_id'] == control_id and type(payload['ordinal']) is int
                 and payload['ordinal'] == ordinal and _same(payload['request_artifact'], accepted['request_artifact'])
                 and type(payload['execution_id']) is str and len(payload['execution_id']) == 32
                 and all(c in '0123456789abcdef' for c in payload['execution_id'])
                 and operation['payload_digest'] == self.registry._command_digest(operation_id, command, payload),
                 'durable drain phase binding differs')
        return receipt

    def _completion(self, run_id):
        result = self.registry.get_run_completion(run_id)
        _require(result is not None, 'reported completion has no durable candidate')
        run, version = result['run'], result['candidate_version']
        mode = run['result'].get('execution_mode')
        _require(mode in ('native_training', 'injected_test'), 'candidate execution mode differs')
        return {'run_id': run_id, 'completion_receipt_sha256': _digest(result['completion_receipt']),
                'candidate_version_id': version['version_id'], 'candidate': version['artifact'], 'execution_mode': mode}

    def _verify_summary(self, summary, request, completions=None):
        names = {'status', 'report_sha256', 'execution_mode', 'recorded_native_execution_verified',
                 'dispatched_run_ids', 'completed', 'deferred_run_ids'}
        _require(type(summary) is dict and set(summary) == names, 'invalid drain summary')
        _require(summary['status'] in ('ready', 'complete', 'recovery_required')
                 and summary['execution_mode'] in ('native_training', 'injected_test')
                 and type(summary['recorded_native_execution_verified']) is bool
                 and type(summary['report_sha256']) is str and len(summary['report_sha256']) == 64
                 and all(c in '0123456789abcdef' for c in summary['report_sha256']), 'invalid drain summary identity')
        ordered = [batch['run_id'] for batch in request['batches']]
        for field in ('dispatched_run_ids', 'deferred_run_ids'):
            ids = summary[field]
            _require(type(ids) is list and all(type(value) is str for value in ids)
                     and ids == [run_id for run_id in ordered if run_id in ids], 'drain summary run membership differs')
        _require(type(summary['completed']) is list and len(summary['completed']) <= len(ordered), 'invalid completed list')
        completed_ids = []
        for record in summary['completed']:
            _require(type(record) is dict and record.get('run_id') in ordered, 'completion outside campaign')
            if completions is None:
                actual = self._completion(record['run_id'])
            else:
                if record['run_id'] not in completions:
                    completions[record['run_id']] = self._completion(record['run_id'])
                actual = completions[record['run_id']]
            _require(_same(record, actual), 'recorded candidate history differs')
            _require(record['execution_mode'] == summary['execution_mode'], 'mixed execution modes in campaign drain')
            completed_ids.append(record['run_id'])
        _require(completed_ids == [run_id for run_id in ordered if run_id in completed_ids], 'completed order/duplicates differ')
        _require(not (set(completed_ids) & set(summary['deferred_run_ids'])), 'completed/deferred overlap')
        if summary['status'] == 'complete':
            _require(completed_ids == ordered and not summary['deferred_run_ids'], 'incomplete completed campaign')
        if summary['status'] == 'ready':
            _require(summary['deferred_run_ids'] and set(completed_ids) | set(summary['deferred_run_ids']) == set(ordered),
                     'ready campaign has unexplained jobs')
        if summary['recorded_native_execution_verified']:
            _require(summary['status'] == 'complete' and summary['execution_mode'] == 'native_training',
                     'native verification conflicts with recorded mode/status')
        return summary

    def _history(self, accepted, request):
        history, gap, blocked = [], False, False
        ordered = [batch['run_id'] for batch in request['batches']]
        completed, completions = set(), {}
        # One bounded exact-key query, then one completion lookup per run for
        # this read only. There is no cross-read trust cache. The reused registry
        # completion verifier still queries its operation/event history per run.
        ids = [_phase_id(accepted['control_operation_id'], ordinal, phase)
               for ordinal in range(1, MAX_DRAINS + 1) for phase in ('start','finish')]
        with self.registry._transaction() as connection:
            self._check_runs(request, connection)
            rows = connection.execute('SELECT operation_id,payload_digest,receipt FROM autoencoder_control.operations '
                'WHERE operation_id IN (' + ','.join('?' for _ in ids) + ')', ids).fetchall()
        _require(len(rows) <= 2 * MAX_DRAINS, 'drain history row bound exceeded')
        operations = {}
        for identity, digest, raw in rows:
            _require(type(raw) is str and len(raw.encode()) <= MAX_REPLY_BYTES, 'drain history receipt exceeds bound')
            operations[identity] = {'payload_digest':digest,'receipt':json.loads(raw)}
        for ordinal in range(1, MAX_DRAINS + 1):
            start = self._phase(accepted, ordinal, 'start', operations)
            finish = self._phase(accepted, ordinal, 'finish', operations)
            if start is None:
                _require(finish is None, 'finish without drain start')
                gap = True
                continue
            _require(not gap and not blocked, 'drain history has a gap or uncertain predecessor')
            count, workers = start['max_new_batches'], start['max_workers']
            _require(type(count) is int and 1 <= count <= MAX_RUNS and type(workers) is int
                     and 1 <= workers <= request['execution_policy']['max_workers'], 'durable drain bounds differ')
            remaining = [run_id for run_id in ordered if run_id not in completed]
            _require(start['selected_run_ids'] == remaining[:count] and start['selected_run_ids'],
                     'durable selected prefix differs')
            if finish is not None:
                _require(finish['execution_id'] == start['execution_id'] and finish['start_sha256'] == _digest(start),
                         'finish differs from exact drain start')
                summary = self._verify_summary(finish['summary'], request, completions)
                current = {row['run_id'] for row in summary['completed']}
                _require(completed <= current and set(summary['dispatched_run_ids']) <= set(start['selected_run_ids']),
                         'drain lost previous completion or dispatched outside prefix')
                if summary['status'] != 'recovery_required':
                    _require(summary['dispatched_run_ids'] == start['selected_run_ids']
                             and current - completed == set(start['selected_run_ids']), 'successful drain progress differs')
                completed = current
                blocked = summary['status'] in ('complete', 'recovery_required')
            else:
                blocked = True
            history.append((start, finish))
        return history

    def read(self, request_artifact: Mapping[str, Any]) -> dict:
        _, request, ref = self._assignment(request_artifact)
        accepted = self._find_submission(ref)
        result = {'schema': SCHEMA, 'request_artifact': ref, 'status': 'not_submitted',
                  'wire_operation_id': None, 'control_operation_id': None, 'drain_count': 0,
                  'progress': None, 'current_artifact_availability_checked': False,
                  'native_runtime_qualified': False, **{name: False for name in _AUTHORITY_FALSE}}
        if accepted is None:
            return _reply(result)
        result.update({key: accepted[key] for key in ('status','wire_operation_id','control_operation_id')})
        history = self._history(accepted, request)
        result['drain_count'] = len(history)
        if history:
            start, finish = history[-1]
            if finish is not None:
                result.update(status=finish['summary']['status'], progress=_copy(finish['summary']))
            else:
                with self._lock:
                    running = (ref['sha256'], start['ordinal'], start['execution_id']) in self._running
                result['status'] = 'running' if running else 'recovery_required'
        return _reply(result)

    def _summarize(self, returned, request, ref, start):
        report = _copy(returned)
        _require(type(report) is dict and report.get('schema_version') == 'autoencoder-campaign-owned-execution-status-v1'
                 and _same(report.get('request_artifact'), ref), 'B2 report binding differs')
        _require(all(report.get(name) is False for name in _AUTHORITY_FALSE), 'B2 authority flags differ')
        _require(report.get('batch_count') == len(request['batches']) and type(report.get('batch_count')) is int
                 and type(report.get('batches')) is list and len(report['batches']) == len(request['batches']),
                 'B2 batch count differs')
        mode = report.get('execution_mode')
        _require(mode in ('native_training','injected_test') and type(report.get('native_execution_verified')) is bool,
                 'B2 execution mode differs')
        completed, deferred = [], []
        for batch, row in zip(request['batches'], report['batches'], strict=True):
            _require(type(row) is dict and all(row.get(key) == batch[key] for key in ('batch_id','run_id','job_id')),
                     'B2 batch identity differs')
            _require(type(row.get('completion_verified')) is bool and type(row.get('supervised_native_execution_verified')) is bool,
                     'B2 verification fields differ')
            run = self.registry.get_run(batch['run_id'])
            _require(run['status'] == row.get('registry_status'), 'B2 registry observation changed')
            if row['completion_verified']:
                record = self._completion(batch['run_id'])
                _require(record['execution_mode'] == row.get('execution_mode') == mode
                         and _same(record['candidate'], row.get('candidate'))
                         and record['candidate_version_id'] == row.get('candidate_version_id'), 'B2 candidate differs')
                _require(not row['supervised_native_execution_verified'] or mode == 'native_training', 'injected native claim')
                completed.append(record)
            if row.get('status') == 'queued':
                _require(_pristine(run) and not row['completion_verified'], 'B2 queued observation differs')
                deferred.append(batch['run_id'])
        _require(report.get('completed_run_ids') == [row['run_id'] for row in completed]
                 and report.get('deferred_run_ids') == deferred, 'B2 progress list differs')
        native = mode == 'native_training' and report.get('status') == 'complete' and all(
            row['supervised_native_execution_verified'] for row in report['batches'])
        _require(report['native_execution_verified'] == native, 'B2 aggregate native flag differs')
        _require(type(report.get('pending_operation_slots')) is list and type(report.get('unresolved_operation_slots')) is list,
                 'B2 pending-operation fields differ')
        if report.get('status') != 'recovery_required':
            _require(not report['pending_operation_slots'] and not report['unresolved_operation_slots'],
                     'B2 success has unresolved operations')
        summary = {'status': report.get('status'), 'report_sha256': _digest(report), 'execution_mode': mode,
                   'recorded_native_execution_verified': report['native_execution_verified'],
                   'dispatched_run_ids': report.get('dispatched_run_ids'), 'completed': completed,
                   'deferred_run_ids': deferred}
        self._verify_summary(summary, request)
        _require(set(summary['dispatched_run_ids']) <= set(start['selected_run_ids']), 'B2 dispatched outside selected prefix')
        return summary

    def _execute_one(self, accepted, maximum, workers):
        handle, request, ref = self._assignment(accepted['request_artifact'])
        history = self._history(accepted, request)
        if history and (history[-1][1] is None or history[-1][1]['summary']['status'] != 'ready'):
            return self.read(ref), 0
        _require(len(history) < MAX_DRAINS, 'campaign drain history bound reached')
        completed = set() if not history else {row['run_id'] for row in history[-1][1]['summary']['completed']}
        runs = self._check_runs(request)
        remaining = [run['run_id'] for run in runs if run['run_id'] not in completed]
        _require(remaining and all(_pristine(run) for run in runs if run['run_id'] in remaining),
                 'remaining original jobs require explicit recovery')
        _require(workers <= request['execution_policy']['max_workers'], 'worker count exceeds sealed policy')
        ordinal, count = len(history) + 1, min(maximum, len(remaining))
        payload = {'control_operation_id': accepted['control_operation_id'], 'ordinal': ordinal,
                   'execution_id': uuid.uuid4().hex, 'request_artifact': ref,
                   'selected_run_ids': remaining[:count], 'max_new_batches': count, 'max_workers': workers}
        operation_id = _phase_id(accepted['control_operation_id'], ordinal, 'start')
        def apply(connection):
            # Cross-controller compare-and-set lives in the registry transaction.
            # Every drain ordinal has one operation ID; a different nonce conflicts.
            now = self._check_runs(request, connection)
            _require(_same(now, runs), 'original jobs changed before drain start')
            return payload
        try:
            start = self._mutate(operation_id, _START, payload, apply)
        except Exception:
            if self._phase(accepted, ordinal, 'start') is not None:
                return self.read(ref), count
            raise
        expected = {'schema': REGISTRY_SCHEMA, 'operation_id': operation_id, 'command': _START,
                    'admitted': False, **payload}
        _require(_same(start, expected), 'start receipt differs')
        token = (ref['sha256'], ordinal, payload['execution_id'])
        with self._lock:
            self._running.add(token)
        try:
            returned = preparation.execute_prepared_campaign_training(self.registry, ref,
                max_new_batches=count, max_workers=workers)
            summary = self._summarize(returned, request, ref, start)
            finish_payload = {key: payload[key] for key in ('control_operation_id','ordinal','execution_id','request_artifact')}
            finish_payload.update(start_sha256=_digest(start), summary=summary)
            finish_id = _phase_id(accepted['control_operation_id'], ordinal, 'finish')
            self._mutate(finish_id, _FINISH, finish_payload, lambda connection: finish_payload)
        finally:
            with self._lock:
                self._running.discard(token)
        return self.read(ref), count

    def execute_pending(self, *, max_new_batches: int = 1, max_workers: int = 1) -> dict:
        """Owner-only sequential drain; the batch budget is global to this call.

        This method is never called by the gateway pump. At most one bounded B2
        invocation is made per submitted request. Concurrent controllers cannot
        both obtain the same durable start. Failures retain uncertain history;
        the control layer never sends FailRun or recreates a journal or lease.
        """
        self._ensure_open()
        _require(type(max_new_batches) is int and 1 <= max_new_batches <= MAX_RUNS, 'invalid total drain batch budget')
        _require(type(max_workers) is int and 1 <= max_workers <= codec.MAX_WORKERS, 'invalid worker count')
        _require(all(max_workers <= request['execution_policy']['max_workers'] for request in self._requests.values()),
                 'worker count exceeds an assigned sealed policy')
        with self._lock:
            self._ensure_open()
            _require(not self._draining, 'owner drain is already active')
            self._draining = True
        results, remaining = [], max_new_batches
        try:
            for key in sorted(self.request_sha256s):
                ref = self._prepared[key]['request_artifact']
                accepted = self._find_submission(ref)
                if accepted is None:
                    continue
                if remaining == 0:
                    results.append(self.read(ref))
                    continue
                try:
                    result, used = self._execute_one(accepted, remaining, max_workers)
                    remaining -= used
                except Exception as error:
                    # Conservatively consume the remaining budget on ambiguity.
                    # Neither an exception nor a missing reply authorizes retry.
                    remaining = 0
                    try:
                        result = self.read(ref)
                    except Exception:
                        result = {**accepted, 'status': 'recovery_required', 'progress': None,
                                  'current_artifact_availability_checked': False, 'native_runtime_qualified': False}
                    if result['status'] not in ('ready','complete'):
                        result['status'] = 'recovery_required'
                    result['control_error'] = type(error).__name__[:128]
                results.append(result)
            return _reply({'schema': SCHEMA, 'results': results, 'max_new_batches': max_new_batches,
                           'remaining_batch_budget': remaining, 'native_runtime_qualified': False,
                           **{name: False for name in _AUTHORITY_FALSE}})
        finally:
            with self._lock:
                self._draining = False

    def close(self):
        _require(os.getpid() == self._pid, 'forked process cannot close owner control')
        with self._lock:
            _require(not self._draining and not self._running, 'cannot close control during execution')
            self._closed = True

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *exc):
        self.close()


__all__ = ['OwnedCampaignControl', 'OwnedCampaignControlError', 'SCHEMA']
