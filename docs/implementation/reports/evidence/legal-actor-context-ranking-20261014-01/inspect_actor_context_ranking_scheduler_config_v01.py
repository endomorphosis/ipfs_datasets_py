"""Qualified copied-scheduler CONFIG inspection only; no compatibility waiver.

Private lease/waiter/metrics contents and unknown config names/values are never
published. No imported scheduler, native client, census, mutation or model.
"""
import ast
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

F = Path(__file__).resolve().parent
GATE = F / 'guardian-config-inspection-source-independent-review-v01.json'
INPUTS = F / 'guardian-config-inspection-inputs-v01.json'
OUTPUT = F / 'guardian-config-inspection-v01.json'
RECEIPT = F / 'private-runtime-snapshots/opening-v02/snapshot-receipt-v01.json'
RECEIPT_PIN = dict(path=str(RECEIPT), bytes=1437, sha256='0f25d4e0c010c46efb923d761bcf13ecb45886b95652771a09bde85385cb165b')
CURRENT = F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py'
ADOPTION = F / 'adopt_shared_scheduler_actor_ranking_v02.py'
SCHEDULER_ENDPOINT = '/tmp/ipfs-datasets-resource-scheduler-1000.json'
INPUT_KEYS = {'schema', 'policy', 'sample_receipt', 'sampler_qualification', 'prior_diagnostic',
              'current_scheduler_source', 'historical_adoption_source'}
SET_NAMES = {'INTEGER_KEYS', 'OPTIONAL_INTEGER_KEYS', 'PERCENT_KEYS', 'OPTIONAL_PERCENT_KEYS', 'BOOLEAN_KEYS', 'PERSISTED_KEYS'}
NEW_SCALARS = {'proof_recovery_enabled', 'proof_recovery_samples', 'proof_recovery_interval_seconds',
               'proof_recovery_grants', 'proof_resource_profile'}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(), 'physical absolute artifact required')
    a = path.stat()
    require(stat.S_ISREG(a.st_mode) and a.st_size <= 16 * 1024 * 1024, 'bounded regular artifact required')
    raw = path.read_bytes(); b = path.stat()
    identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    require(identity(a) == identity(b) and len(raw) == a.st_size, 'artifact changed during read')
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def public_pin(path):
    path = Path(path)
    require(path.suffix in ('.py', '.json') and not any(part.startswith('private-') or part == 'results' for part in path.parts)
            and not any(word in path.name for word in ('checkpoint', 'disk-reservations', 'stderr')),
            'public source and receipt metadata only')
    return pin(path)


def read_json(path, expected, private=False):
    captured = pin(path) if private else public_pin(path)
    require(captured == expected, 'exact authenticated input descriptor required')
    raw = Path(path).read_bytes()
    require(len(raw) == captured['bytes'] and hashlib.sha256(raw).hexdigest() == captured['sha256'], 'consumed bytes changed')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate metadata key refused')
            value[key] = item
        return value
    def finite(raw):
        value = float(raw); require(math.isfinite(value), 'nonfinite metadata refused'); return value
    result = json.loads(raw, object_pairs_hook=unique, parse_float=finite,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite metadata refused')))
    require(pin(path) == captured, 'closing consumed input changed')
    return result


def source_schema(current_raw, adoption_raw):
    """Inspect source syntax; never execute a producer or its annotations."""
    tree = ast.parse(current_raw)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ResourceSchedulerConfig')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'persisted_dict')
    returns = [n for n in method.body if isinstance(n, ast.Return)]
    require(len(returns) == 1 and isinstance(returns[0].value, ast.Dict), 'literal persisted config schema required')
    fields = []
    for key, value in zip(returns[0].value.keys, returns[0].value.values, strict=True):
        require(isinstance(key, ast.Constant) and type(key.value) is str, 'literal config field names required')
        name = key.value
        require(name == 'lane_reservations' and isinstance(value, ast.DictComp)
                or isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
                and value.value.id == 'self' and value.attr == name, 'direct persisted config field source required')
        fields.append(name)
    require(len(fields) == len(set(fields)) <= 128, 'unique bounded source config schema required')
    constants = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                 and any(isinstance(t, ast.Name) and t.id == 'LOCAL_BENCHMARK_PROOF_PROFILE' for t in n.targets)]
    require(constants == ['local-benchmark@1'], 'exact reviewed public proof profile literal required')
    sets = {}
    def evaluate(node):
        if isinstance(node, ast.Set):
            value = ast.literal_eval(node)
            require(all(type(k) is str for k in value), 'literal historical source fields required'); return value
        if isinstance(node, ast.Name) and node.id in sets:
            return sets[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return evaluate(node.left) | evaluate(node.right)
        raise ValueError('closed historical set expression required')
    for node in ast.parse(adoption_raw).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in SET_NAMES:
            sets[node.targets[0].id] = evaluate(node.value)
    require(set(sets) == SET_NAMES and sets['PERSISTED_KEYS'] <= set(fields)
            and set(fields) - sets['PERSISTED_KEYS'] == NEW_SCALARS, 'exact reviewed current and historical schemas required')
    return sets, set(fields), constants[0]


def disclosed_value(name, value, sets, profile, expected):
    """Only reviewed scalar types/ranges or exact-public nested policy values."""
    integer = lambda v: type(v) is int and 0 <= v <= 10**12
    number = lambda v: type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 10**12
    if name in sets['INTEGER_KEYS']: return integer(value)
    if name in sets['OPTIONAL_INTEGER_KEYS']: return value is None or integer(value)
    if name in sets['PERCENT_KEYS']: return number(value) and value <= 100
    if name in sets['OPTIONAL_PERCENT_KEYS']: return value is None or number(value) and value <= 100
    if name in sets['BOOLEAN_KEYS'] or name == 'proof_recovery_enabled': return type(value) is bool
    if name in ('proof_backoff_seconds', 'proof_recovery_interval_seconds'): return number(value)
    if name in ('proof_recovery_samples', 'proof_recovery_grants'): return integer(value) and 1 <= value <= 1024
    if name == 'proof_resource_profile': return value is None or value == profile
    if name == 'lane_reservations': return type(value) is dict and canonical(value) == canonical(expected.get(name))
    return False


def config_summary(config, expected, sets, fields, profile):
    require(type(config) is dict and len(config) <= 256 and all(type(k) is str and len(k) <= 256 for k in config),
            'bounded config object required')
    require(set(expected) == sets['PERSISTED_KEYS'], 'policy must equal reviewed historical config schema')
    known = set(expected) | fields
    rows = {}
    for name in sorted(known):
        item = dict(present=name in config, expected_by_policy=name in expected, declared_by_current_source=name in fields)
        if name in config:
            value = config[name]
            show = disclosed_value(name, value, sets, profile, expected)
            item.update(value_type=type(value).__name__, value_sha256=digest(value), value_disclosed=show,
                        equals_policy_value=name in expected and type(value) is type(expected[name]) and value == expected[name])
            if show: item['value'] = value
        rows[name] = item
    unknown = sorted(set(config) - known)
    return dict(config_sha256=digest(config), config_key_count=len(config), expected_policy_key_count=len(expected),
                current_source_key_count=len(fields), exact_policy_config_equal=canonical(config) == canonical(expected),
                missing_expected_keys=sorted(set(expected) - set(config)),
                additional_reviewed_keys=sorted((set(config) - set(expected)) & known),
                unknown_key_count=len(unknown), unknown_key_name_sha256=[hashlib.sha256(k.encode()).hexdigest() for k in unknown],
                unknown_values_disclosed=False, known_fields=rows,
                current_source_declared_fields=sorted(fields), expected_policy_fields=sorted(expected))


def main():
    require(sys.argv[1:] == [] and not os.path.lexists(OUTPUT), 'one exclusive argument-free config inspection required')
    own = public_pin(Path(__file__).resolve()); gate_pin = public_pin(GATE)
    gate = read_json(GATE, gate_pin)
    require(gate['schema'] == 'actor-context-ranking-guardian-config-inspection-source-independent-review/v1'
            and gate['passed'] is True and gate['findings'] == [] and gate['observer'] == own,
            'exact independent config inspection source gate required before private parsing')
    require(gate['artifacts'].get(own['path']) == own, 'qualified observer raw source binding required')
    for path, item in gate['artifacts'].items(): require(public_pin(path) == item, 'qualified public artifact changed')
    inputs_pin = public_pin(INPUTS); inputs = read_json(INPUTS, inputs_pin)
    require(type(inputs) is dict and set(inputs) == INPUT_KEYS
            and inputs['schema'] == 'actor-context-ranking-guardian-config-inspection-inputs/v1', 'closed config inspection manifest required')
    paths = dict(policy=F/'resource-observation-policy-v01.json', sampler_qualification=F/'sampler-source-independent-review-v01.json',
                 prior_diagnostic=F/'guardian-check-diagnostic-v01.json', current_scheduler_source=CURRENT,
                 historical_adoption_source=ADOPTION)
    public = {}
    for key, path in paths.items():
        require(inputs[key] == public_pin(path) and gate[key] == inputs[key]
                and gate['artifacts'].get(str(path)) == inputs[key], 'exact qualified public input joins required')
        public[key] = inputs[key]
    policy = read_json(paths['policy'], inputs['policy'])
    sampler_gate = read_json(paths['sampler_qualification'], inputs['sampler_qualification'])
    require(sampler_gate['schema'] == 'actor-context-ranking-sampler-source-independent-review/v1'
            and sampler_gate['passed'] is True and sampler_gate['findings'] == [] and sampler_gate['sampler'] == policy['sampler']
            and public_pin(policy['sampler']['path']) == policy['sampler'], 'exact qualified unchanged sampler required')
    diagnostic = read_json(paths['prior_diagnostic'], inputs['prior_diagnostic'])
    require(diagnostic['guardian_check_succeeded'] is False and diagnostic['classification']['exception_class'] == 'ValueError'
            and diagnostic['classification']['message'] == 'exact complete persisted scheduler configuration required; unknown/missing keys refused',
            'specific preserved configuration refusal required')
    sets, fields, profile = source_schema(CURRENT.read_bytes(), ADOPTION.read_bytes())
    require(inputs['sample_receipt'] == RECEIPT_PIN, 'exact authenticated diagnostic opening2 receipt required')
    for directory in (RECEIPT.parent.parent, RECEIPT.parent):
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and not directory.is_symlink() and directory.resolve(strict=True) == directory
                and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, 'owned private700 sample directories required')
    require(stat.S_IMODE(RECEIPT.stat().st_mode) == 0o400, 'authenticated private receipt400 required')
    receipt = read_json(RECEIPT, inputs['sample_receipt'], private=True)
    require(receipt['schema'] == 'actor-context-ranking-private-endpoints/v1' and receipt['role'] == 'opening'
            and receipt['cell'] is None and receipt['index'] == 2 and receipt['shared_state_modified'] is False
            and receipt['resource_API_calls'] == 0, 'true unchanged qualified opening2 receipt required')
    copied = RECEIPT.parent/'scheduler.json'
    require(receipt['scheduler']['path'] == str(copied) and receipt['source_scheduler']['path'] == SCHEDULER_ENDPOINT
            and all(receipt['scheduler'][k] == receipt['source_scheduler'][k] for k in ('bytes','sha256'))
            and stat.S_IMODE(copied.stat().st_mode) == 0o400, 'exact authenticated copied scheduler400 required')
    state = read_json(copied, receipt['scheduler'], private=True)
    require(type(state) is dict and type(state.get('config')) is dict, 'copied scheduler config object required')
    summary = config_summary(state['config'], policy['scheduler_config'], sets, fields, profile)
    require(pin(RECEIPT) == inputs['sample_receipt'] and pin(copied) == receipt['scheduler'], 'private copied input closing fence changed')
    for key, path in paths.items(): require(public_pin(path) == public[key], 'public input closing fence changed')
    for path, item in gate['artifacts'].items(): require(public_pin(path) == item, 'qualified artifact closing fence changed')
    value = dict(schema='actor-context-ranking-guardian-config-inspection/v1', inspection_completed=True,
                 observed_at_utc=datetime.now(timezone.utc).isoformat(), observer=own, source_qualification=gate_pin,
                 input_manifest=inputs_pin, public_inputs=public, sample_receipt=inputs['sample_receipt'],
                 copied_scheduler=receipt['scheduler'], summary=summary, ledger_body_parses=0,
                 leases_waiters_metrics_disclosed=False, native_endpoints_opened=0, resource_API_calls=0,
                 subprocess_calls=0, actual_censuses=0, model_calls=0, global_writes=0, new_claims=0,
                 compatibility_qualified=False, training_authorized=False, config_mutation_authorized=False)
    with OUTPUT.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    OUTPUT.chmod(0o444); print(json.dumps(public_pin(OUTPUT), sort_keys=True))


if __name__ == '__main__':
    main()
