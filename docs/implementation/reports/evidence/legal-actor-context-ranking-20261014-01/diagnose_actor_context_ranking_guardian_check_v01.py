"""One qualified guardian --check, with private raw streams and safe public labels.

This diagnostic cannot authorize a sample, baseline, admission, census or model.
Its only child is the unchanged guardian in its read-only --check route.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

F = Path(__file__).resolve().parent
GUARDIAN = F / 'run_scope_guardian_v02.py'
POLICY = F / 'resource-observation-policy-v01.json'
FAILED = F / 'resource-collection-v01.json'
GATE = F / 'guardian-check-diagnostic-source-independent-review-v01.json'
OUTPUT = F / 'guardian-check-diagnostic-v01.json'
PRIVATE = F / 'private-resource-diagnostics' / 'guardian-check-v01'
EXPECTED = {
    str(GUARDIAN): dict(bytes=38449, sha256='b4811b7b24f584d5cb0f7c921451a234a3e0d84b2d7507e015426e258134c2db'),
    str(POLICY): dict(bytes=7532, sha256='d9056253244e653c544b4fee5ac371a3d86a538fa8c67f6330512ec2cd9a90ac'),
    str(FAILED): dict(bytes=2165, sha256='f62adf64c67c0dc7384616f979e3ec6140f42f03ebf3111b1e5b917b576aa38e'),
}
STREAM_BOUND = 1024 * 1024
SAFE_MESSAGES = frozenset({
    'fresh guardian process required',
    'resource scheduler imported from wrong tree',
    'requested envelope cannot fit existing capacities',
    'existing disk ledger schema or authorized cap differs',
    'existing disk ledger roots differ',
    '--check accepts no execution inputs',
    'bounded existing regular scheduler state required',
    'scheduler state grew beyond read bound',
    'closed existing scheduler state inventory required',
    'invalid existing scheduler containers',
    'invalid bounded historical proof refusal metadata',
    'unsupported existing scheduler schema',
    'exact complete persisted scheduler configuration required; unknown/missing keys refused',
    'bounded explicit lane reservations required',
    'exact typed lane reservation required',
    'scheduler normalization changed persisted configuration',
    'bounded JSON required',
    'duplicate JSON key',
})
SAFE_CLASSES = frozenset({
    'ValueError', 'ResourceConfigurationError', 'FileNotFoundError',
    'ModuleNotFoundError', 'ImportError', 'PermissionError', 'JSONDecodeError',
    'KeyError', 'TypeError', 'RuntimeError', 'OSError', 'TimeoutError',
})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def descriptor(path):
    path = Path(path)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), 'regular diagnostic artifact required')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            h.update(chunk)
    require(path.stat().st_size == info.st_size, 'diagnostic artifact changed during hashing')
    return dict(path=str(path), bytes=info.st_size, sha256=h.hexdigest())


def public_descriptor(path):
    path = Path(path)
    require(path.is_absolute() and path.suffix in ('.py', '.json')
            and not any(part.startswith('private-') or part in ('results', 'hf-payload-v01') for part in path.parts)
            and not any(token in path.name.lower() for token in ('checkpoint', 'ledger', 'scheduler-state', 'stderr')),
            'public source or receipt metadata only')
    return descriptor(path)


def read_public(path):
    before = public_descriptor(path)
    require(before['bytes'] <= 16 * 1024 * 1024, 'bounded public metadata required')
    content = Path(path).read_bytes()
    require(hashlib.sha256(content).hexdigest() == before['sha256'], 'public metadata changed during read')
    return json.loads(content)


def classify(stderr_tail, *, returncode, timed_out, output_bounded):
    """Never publish arbitrary stderr text, paths, keys, state values or imports."""
    if timed_out:
        return dict(exception_class='TimeoutError', message='Guardian check exceeded the fixed 15 second bound.',
                    exact_allowlisted_message=False)
    if not output_bounded:
        return dict(exception_class='Unclassified', message='Guardian streams exceeded the diagnostic size bound.',
                    exact_allowlisted_message=False)
    if returncode == 0:
        return dict(exception_class=None, message='Guardian check returned zero; diagnostic is not an admission proof.',
                    exact_allowlisted_message=False)
    text = stderr_tail.decode('utf-8', errors='replace')
    for line in reversed(text.splitlines()):
        match = re.fullmatch(r'(?:[A-Za-z_][A-Za-z_0-9]*\.)*([A-Za-z_][A-Za-z_0-9]*):(?: (.*))?', line)
        if match and match.group(1) in SAFE_CLASSES:
            name, message = match.group(1), match.group(2) or ''
            safe = message in SAFE_MESSAGES
            return dict(exception_class=name, message=message if safe else 'Details retained in private stderr.',
                        exact_allowlisted_message=safe)
    return dict(exception_class='Unclassified', message='Details retained in private stderr.',
                exact_allowlisted_message=False)


def create_private_directory():
    parent = PRIVATE.parent
    if not os.path.lexists(parent):
        parent.mkdir(mode=0o700)
    info = parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and not parent.is_symlink()
            and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            'owned physical private700 parent required')
    PRIVATE.mkdir(mode=0o700)
    require(PRIVATE.resolve(strict=True) == PRIVATE, 'physical private diagnostic directory required')


def main():
    require(sys.argv[1:] == [] and not os.path.lexists(OUTPUT) and not os.path.lexists(PRIVATE),
            'one exclusive argument-free diagnostic required')
    own = public_descriptor(Path(__file__).resolve())
    gate = read_public(GATE)
    require(gate['schema'] == 'actor-context-ranking-guardian-check-diagnostic-source-independent-review/v1'
            and gate['passed'] is True and gate['findings'] == [] and gate['producer'] == own,
            'exact independent diagnostic source gate required')
    required = {str(Path(__file__).resolve()): own}
    for path, expected in EXPECTED.items():
        actual = public_descriptor(path)
        require(actual == dict(path=path, **expected), 'pinned diagnostic input changed')
        required[path] = actual
    require(gate['guardian'] == required[str(GUARDIAN)] and gate['policy'] == required[str(POLICY)]
            and gate['prior_failed_collection'] == required[str(FAILED)], 'exact public diagnostic custody required')
    require(type(gate['artifacts']) is dict and all(gate['artifacts'].get(path) == item for path, item in required.items()),
            'complete diagnostic source artifact closure required')
    for path, item in gate['artifacts'].items():
        require(item == public_descriptor(path), 'diagnostic gate artifact changed')
    policy = read_public(POLICY)
    require(policy['guardian'] == required[str(GUARDIAN)], 'unchanged qualified guardian required')
    for path, expected in policy['resource_producer_pins'].items():
        require(public_descriptor(path) == dict(path=path, **expected), 'qualified guardian closure changed')
    failed = read_public(FAILED)
    require(failed['passed'] is False and failed['actual_pair_count'] == 1 and failed['selected_index'] is None
            and failed['selected_input_manifest'] is None and failed['attempts'][0]['check_returncode'] == 1
            and failed['attempts'][0]['check_stderr_bytes'] == 1283
            and failed['attempts'][0]['check_stderr_sha256'] == '51ca139e9007be9d130b753b8b192493ec32a75d28e6b6fe2672b9586342313e'
            and failed['attempts'][0]['sample_receipt'] is None, 'specific preserved pre-sampler refusal required')
    create_private_directory()
    stdout_path, stderr_path = PRIVATE / 'stdout.bin', PRIVATE / 'stderr.bin'
    returncode = None
    timed_out = False
    launch_error_class = None
    with os.fdopen(os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stdout:
        with os.fdopen(os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stderr:
            try:
                result = subprocess.run([sys.executable, '-B', str(GUARDIAN), '--check'], cwd=F,
                                        stdout=stdout, stderr=stderr, timeout=15, check=False)
                returncode = result.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
            except OSError as error:
                launch_error_class = type(error).__name__ if type(error).__name__ in SAFE_CLASSES else 'OSError'
            finally:
                for stream in (stdout, stderr):
                    stream.flush()
                    os.fsync(stream.fileno())
    streams = dict(stdout=descriptor(stdout_path), stderr=descriptor(stderr_path))
    bounded = all(item['bytes'] <= STREAM_BOUND for item in streams.values())
    with stderr_path.open('rb') as stream:
        stream.seek(max(0, streams['stderr']['bytes'] - 4096))
        tail = stream.read(4096)
    classification = classify(tail, returncode=returncode, timed_out=timed_out, output_bounded=bounded)
    if launch_error_class is not None:
        classification = dict(exception_class=launch_error_class, message='Guardian process launch failed; no retry.',
                              exact_allowlisted_message=False)
    for path, item in gate['artifacts'].items():
        require(item == public_descriptor(path), 'diagnostic closing source fence changed')
    value = dict(schema='actor-context-ranking-guardian-check-diagnostic/v1', diagnostic_completed=True,
                 observed_at_utc=datetime.now(timezone.utc).isoformat(), producer=own,
                 source_qualification=public_descriptor(GATE), prior_failed_collection=required[str(FAILED)],
                 guardian=required[str(GUARDIAN)], policy=required[str(POLICY)],
                 child_invocations=1, fixed_argv=[sys.executable, '-B', str(GUARDIAN), '--check'],
                 returncode=returncode, timed_out=timed_out, launch_error_class=launch_error_class,
                 output_streams_within_bound=bounded,
                 guardian_check_succeeded=returncode == 0 and not timed_out and bounded,
                 classification=classification, private_streams=streams, raw_streams_mode='0600',
                 public_endpoint_bodies=False, diagnostic_endpoint_body_parses=0,
                 previous_missing_stderr_recovered=False, sampler_calls=0, observer_calls=0,
                 admission_calls=0, resource_API_calls=0, actual_censuses=0, model_calls=0,
                 new_claims=0, global_state_writes=0, training_authorized=False,
                 usable_as_baseline_or_compatibility_receipt=False, automatic_retry=False)
    with OUTPUT.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(descriptor(OUTPUT), sort_keys=True))


if __name__ == '__main__':
    main()
