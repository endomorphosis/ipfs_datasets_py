"""Owned offline program checks for shared targets and a canonical Lean fixture.

Called by the reserved conversion lane after immutable target preparation. This
module never trains, regenerates bridge targets, downloads, or publishes. Learned
heads emit distributions/guidance; this helper does not relabel targets as model
programs. Only an actual successful Lake build qualifies the generated theorem.
"""
from __future__ import annotations

from dataclasses import asdict
from collections import Counter
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets')
OWNED = ROOT / 'workspace/test-logs/federal-corpus-audits'
LOCK = ROOT.parent.parent / 'JevOps/jevops/statement_lock.py'
LOCK_SHA = 'dc377f8359cac300023e225d694494ea631943298c44667ec44e1352de1e6237'
TOOLCHAIN = Path('/home/barberb/.elan/toolchains/leanprover--lean4---v4.26.0')
TOOL_SHA = {
    'lake': '65e6788674aa50c98da101339ca213c5a9599414830fa74f963ad794e025efc7',
    'lean': 'e215cbe9eab0914b49761e9e486d388e2e701cf876d1079d1ba733c48edb2d7b',
}
BRIDGES = ('modal_frame_logic', 'deontic_norms', 'fol_tdfol', 'cec_dcec', 'external_prover_router')
GATES = (
    'Company A shall submit backup report within 10 days unless emergency.',
    'The agency shall not disclose records.',
    'The officer shall retain the file for at least 20 days.',
)


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def regular(path, maximum):
    path = Path(path).absolute()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.resolve() != path or info.st_size > maximum:
        raise ValueError('expected bounded canonical regular file: ' + str(path))
    return path


def write(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    if len(raw) > 2_000_000:
        raise ValueError('formal validation receipt exceeds 2 MB')
    with Path(path).open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def failure(exc):
    return {'type': type(exc).__name__, 'message': str(exc)}


def canonical_modules():
    for name, module in tuple(sys.modules.items()):
        if name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.'):
            filename = getattr(module, '__file__', None)
            if filename and not Path(filename).resolve().is_relative_to(ROOT / 'ipfs_datasets_py'):
                raise ValueError('foreign datasets module already loaded: ' + name)


def parser_checks(view, parser, validator=None, deontic_type=None, deontic_operators=None, structural_validator=None):
    records = view.payload.get('records')
    if not isinstance(records, (list, tuple)) or not 1 <= len(records) <= 128:
        raise ValueError('expected 1..128 generated formula records')
    result = []
    for index, record in enumerate(records):
        row = {'record_index': index, 'source_record': dict(record),
               'checked_field': 'proof_input', 'passed': False, 'error': None,
               'proof_executed': False, 'admitted': False}
        try:
            text = record.get('proof_input')
            if not isinstance(text, str) or not text.strip() or len(text.encode()) > 65536:
                raise ValueError('missing or oversized native proof_input; no display-formula fallback')
            parsed = parser(text)
            if parsed is None:
                raise ValueError('native parser returned no formula')
            row['parsed_class'] = type(parsed).__module__ + '.' + type(parsed).__qualname__
            row['native_rendering'] = str(parsed)
            row['proof_input_sha256'] = hashlib.sha256(text.encode()).hexdigest()
            symbol = text.lstrip()[:1]
            if deontic_type is not None and symbol in deontic_operators and text.lstrip()[1:2] == '(':
                row['expected_deontic_operator'] = symbol
                row['parsed_operator'] = str(getattr(parsed, 'operator', None))
                if not isinstance(parsed, deontic_type) or parsed.operator != deontic_operators[symbol]:
                    raise ValueError('native parse did not preserve the generated deontic operator')
            if structural_validator is not None:
                row['operator_structure'] = structural_validator(text, parsed)
                if not row['operator_structure']['passed']:
                    raise ValueError('native parse did not preserve generated operator structure')
            if validator is not None:
                valid, errors = validator(parsed)
                row['native_validation_errors'] = errors
                row['passed'] = bool(valid) and not errors
            else:
                row['passed'] = True
        except Exception as exc:
            row['error'] = failure(exc)
        result.append(row)
    return {'passed': bool(result) and all(row['passed'] for row in result),
            'record_count': len(result), 'records': result,
            'scope': 'exact generated native proof_input syntax; display formula preserved separately; no semantic equivalence or proof claim'}



def tdfol_operator_structure(text, parsed):
    """Check actual emitted operators, never invent a missing temporal target."""
    from ipfs_datasets_py.logic.TDFOL.tdfol_parser import TDFOLLexer, TokenType
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        Formula, DeonticFormula, TemporalFormula, BinaryTemporalFormula,
    )
    symbols = {'OBLIGATION': 'O', 'PERMISSION': 'P', 'PROHIBITION': 'F',
               'ALWAYS': '□', 'EVENTUALLY': '◊', 'NEXT': 'X',
               'UNTIL': 'U', 'SINCE': 'S', 'WEAK_UNTIL': 'W', 'RELEASE': 'R'}
    binary = {'UNTIL', 'SINCE', 'WEAK_UNTIL', 'RELEASE'}
    tokens = TDFOLLexer(text).tokenize()
    emitted = []
    for index, token in enumerate(tokens):
        if token.type not in symbols:
            continue
        # The grammar also permits a reserved letter as a bare atomic predicate.
        if token.type not in binary and (index + 1 == len(tokens) or tokens[index + 1].type != TokenType.LPAREN):
            continue
        emitted.append({'operator': symbols[token.type], 'source_offset': token.position})
    nodes = []
    def visit(node, path):
        if isinstance(node, (DeonticFormula, TemporalFormula, BinaryTemporalFormula)):
            nodes.append({'path': path, 'class': type(node).__name__, 'operator': node.operator.value,
                          'time_bound': getattr(node, 'time_bound', None)})
        for name in ('formula', 'left', 'right'):
            child = getattr(node, name, None)
            if isinstance(child, Formula):
                visit(child, path + '/' + name)
    visit(parsed, '$')
    rendering = parsed.to_string()
    # Bridge proof_input is the producer's canonical to_string output. Matching
    # it exactly checks grouping/placement as well as operator multiplicity.
    passed = (Counter(item['operator'] for item in emitted) == Counter(item['operator'] for item in nodes)
              and rendering == text.strip())
    return {'passed': passed, 'emitted_operators': emitted, 'parsed_operator_paths': nodes,
            'canonical_rendering': rendering, 'canonical_serialization_preserved': rendering == text.strip(),
            'temporal_operator_count': sum(item['class'] != 'DeonticFormula' for item in nodes),
            'scope': 'operator types, multiplicity and canonical placement for this serialized program; source semantics and term sorts not established'}


def representation_limits(gate_rule, tdfol):
    texts = [str(row['source_record'].get('proof_input') or '') for row in tdfol['records']]
    joined = '\n'.join(texts).lower()
    durations = []
    for temporal in gate_rule.get('temporal_records') or ():
        quantity = temporal.get('quantity')
        present = quantity is not None and re.search(r'(?<!\w)' + re.escape(str(quantity)) + r'(?!\w)', joined) is not None
        durations.append({'canonical_record': temporal, 'quantity_literal_in_native_tdfol': present,
                          'source_duration_absent_from_native_tdfol': not present,
                          'semantic_encoding_verified': False})
    exceptions = [{'canonical_exception': value, 'literal_in_native_tdfol': str(value).lower() in joined,
                   'source_exception_absent_from_native_tdfol': str(value).lower() not in joined,
                   'semantic_encoding_verified': False} for value in gate_rule.get('exceptions') or ()]
    return {'source_semantic_equivalence_verified': False, 'duration_observations': durations,
            'exception_observations': exceptions,
            'limitations': [
                'Backend syntax and frame schema validation do not establish source semantic equivalence.',
                'Absent source duration quantities or exceptions are not repaired or inferred by this check.',
                'A lexical quantity or exception mention alone does not establish its legal scope.',
                'TDFOL serialization does not preserve the producer agent/context metadata or distinguish every Constant from Variable; term-sort equivalence is not validated.',
                'The Lake artifact checks a numeric boundary only, independently of these bridge programs.']}


def lake_check(gate_rows, output, timeout_seconds):
    if tuple(row['text'] for row in gate_rows) != GATES:
        raise ValueError('only the three frozen synthetic gates are supported')
    if any(row.get('synthetic') is not True or row['result'].get('compiler_status') != 'compiled'
           or row.get('admitted') is not False for row in gate_rows):
        raise ValueError('expected strict canonical compiled synthetic gate rows')
    if sha(regular(LOCK, 100000)) != LOCK_SHA:
        raise ValueError('statement-lock source changed')
    spec = importlib.util.spec_from_file_location('formal_validation_statement_lock', LOCK)
    lock = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = lock
    spec.loader.exec_module(lock)
    patterns = [lock.pattern_from_rule(row['result']['rule']) for row in gate_rows]
    if patterns != [None, None, {'kind': 'threshold', 'fail': 19, 'meet': 20}]:
        raise ValueError('deadline/non-renderable or minimum-duration gate changed')
    minimum = gate_rows[2]['result']['rule']
    if minimum.get('temporal_records') != [{'temporal_kind': 'minimum_duration', 'value': '20 days', 'quantity': 20}]:
        raise ValueError('expected canonical minimum_duration quantity 20')
    source = lock.render_lean(patterns[2])
    locked = lock.lock_statement(source, source)
    if not source or not locked.get('ok'):
        raise ValueError('closed Lean source lock rejected generated theorem')
    for name, expected in TOOL_SHA.items():
        binary = regular(TOOLCHAIN / 'bin' / name, 100_000_000)
        if sha(binary) != expected or not os.access(binary, os.X_OK):
            raise ValueError('installed Lean/Lake binary identity changed')
    package = output / 'lake-minimum-duration'
    package.mkdir()
    for name, text in {
        'lakefile.lean': 'import Lake\nopen Lake DSL\npackage formalValidation\nlean_lib Legal\n',
        'lean-toolchain': 'leanprover/lean4:v4.26.0\n', 'Legal.lean': source,
    }.items():
        with (package / name).open('x') as handle:
            handle.write(text)
    environment = os.environ.copy()
    for name in ('LEAN_PATH', 'LEAN_SRC_PATH', 'LAKE_HOME', 'ELAN_TOOLCHAIN'):
        environment.pop(name, None)
    environment.update(PATH=str(TOOLCHAIN / 'bin') + ':/usr/bin:/bin',
                       LEAN_SYSROOT=str(TOOLCHAIN), ELAN_NO_AUTO_INSTALL='1',
                       GIT_LFS_SKIP_SMUDGE='1', GIT_NO_LAZY_FETCH='1')
    command = [str(TOOLCHAIN / 'bin/lake'), 'build', 'Legal']
    started = time.monotonic()
    timed_out = False
    with (package / 'lake.log').open('xb') as log:
        process = subprocess.Popen(command, cwd=package, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait(timeout=5)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            raise
    elapsed = time.monotonic() - started
    artifact = package / '.lake/build/lib/lean/Legal.olean'
    artifacts = {}
    for path in (package / 'Legal.lean', package / 'lakefile.lean', package / 'lean-toolchain', package / 'lake.log', artifact):
        if path.is_file():
            regular(path, 10_000_000)
            artifacts[path.relative_to(output).as_posix()] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    stable = sha(LOCK) == LOCK_SHA and all(sha(TOOLCHAIN / 'bin' / name) == expected for name, expected in TOOL_SHA.items())
    passed = returncode == 0 and not timed_out and artifact.is_file() and stable
    return {'passed': passed, 'lake_executed': True, 'command': command, 'cwd': str(package),
            'returncode': returncode, 'timed_out': timed_out, 'elapsed_seconds': elapsed,
            'timeout_seconds': timeout_seconds, 'toolchain_binary_sha256': TOOL_SHA,
            'statement_lock_sha256': LOCK_SHA, 'source_and_tools_unchanged': stable,
            'artifacts': artifacts, 'source_gate_index': 2, 'source_text': GATES[2],
            'canonical_rule': minimum, 'pattern': patterns[2], 'generated_source': source,
            'non_renderable_gate_indices': [0, 1], 'mathlib_imported': False,
            'generated_theorem_admitted_by_lake': passed, 'legal_span_admitted': False,
            'proof_scope': 'Natural-number threshold boundary at 19 and 20. This omits actor, retention action, time units and the complete legal duty.',
            'producer_lineage': 'source text -> pinned typed-deontic rule -> JevOps numeric pattern -> locked Lean -> lake build Legal',
            'learned_checkpoint_program': False,
            'offline_scope': 'absolute installed toolchain, no package dependencies or installer; parent owns network isolation'}


def run_formal_validation(*, gate_rows, source_rows, training_records, training_config,
                          prepared_targets_path, output_directory, checkpoint_lineage=None,
                          lake_timeout_seconds=60):
    """Return and persist detailed actual validation results; never grant law admission.

    training_records/config accept frozen dictionaries or their worker dataclasses.
    prepared_targets_path is the parent's training/prepared-targets.json, written
    before training entry. Caller must retain its existing source/resource guards.
    """
    output = Path(output_directory).absolute()
    if (output.exists() or output.is_symlink() or output.resolve() != output
            or not output.parent.is_dir() or not output.is_relative_to(OWNED)):
        raise ValueError('formal output must be a new directory inside the owned audit attempt')
    if not 1 <= lake_timeout_seconds <= 60:
        raise ValueError('Lake timeout must be between 1 and 60 seconds')
    output.mkdir()
    receipt = {'schema': 'shared-target-formal-validation/v1', 'passed': False,
               'error': None, 'lake': None, 'samples': [], 'sample_count': 3,
               'bridge_names': list(BRIDGES), 'legal_ir_evaluate_provers': False,
               'legal_ir_parallel_workers': 1, 'metric_disk_cache': 0,
               'bridge_generation_performed': False, 'shared_target_reuse': True,
               'checkpoint_lineage': checkpoint_lineage,
               'checkpoint_lineage_scope': 'caller-supplied training identity; no checkpoint is loaded by this validator',
               'learned_heads_output_kind': 'distributions, embeddings and guidance',
               'learned_symbolic_program_validated': False,
               'heldout_canary_qualified': False, 'cold_speed_claim': False,
               'source_span_count': len(source_rows), 'source_span_admitted_count': 0,
               'admitted': False, 'formalized': False, 'constitution_formalized': False}
    started = time.monotonic()
    before_config = None
    try:
        canonical_modules()
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord, TrainingConfig
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import target_snapshot_config
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_bundle
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
        from ipfs_datasets_py.logic.CEC.native.dcec_integration import parse_dcec_string, validate_formula
        from ipfs_datasets_py.logic.CEC.native.dcec_core import DeonticFormula as DCECDeontic, DeonticOperator as DCECOperator
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula as TDFOLDeontic, DeonticOperator as TDFOLOperator
        from ipfs_datasets_py.logic.legal_ir.adapter import LegalIRFormalizationAdapter
        from ipfs_datasets_py.logic.integration.reasoning.legal_ir_view_contracts import validate_legal_ir_view
        receipt['tree_pin'] = require_workspace_logic_tree()
        canonical_modules()
        config = TrainingConfig.from_dict(training_config) if isinstance(training_config, dict) else training_config
        records = [SampleRecord.from_dict(row) if isinstance(row, dict) else row for row in training_records]
        if (tuple(row.text for row in records) != GATES or tuple(config.legal_ir_bridge_names) != BRIDGES
                or config.legal_ir_evaluate_provers is not False or config.legal_ir_parallel_workers != 1
                or config.metric_disk_cache != 0 or config.use_sample_memory is not False):
            raise ValueError('frozen sample or bridge policy differs')
        try:
            receipt['lake'] = lake_check(gate_rows, output, lake_timeout_seconds)
        except Exception as exc:
            receipt['lake'] = {'passed': False, 'error': failure(exc),
                               'legal_span_admitted': False, 'generated_theorem_admitted_by_lake': False}
        descriptor_path = regular(prepared_targets_path, 2_000_000)
        if not descriptor_path.is_relative_to(output.parent.parent / 'training'):
            raise ValueError('shared target descriptor must belong to the sibling training lane')
        descriptor_sha = sha(descriptor_path)
        prepared = json.loads(descriptor_path.read_bytes())
        reference = prepared['artifact']
        artifact_path = regular(reference['path'], 30_000_000)
        if (not artifact_path.is_relative_to(descriptor_path.parent) or artifact_path.stat().st_size != reference['bytes']
                or sha(artifact_path) != reference['sha256'] or prepared.get('all_requested_bridge_reports_received') is not True):
            raise ValueError('shared target artifact binding or complete coverage differs')
        telemetry = prepared['bridge_report_telemetry']
        if len(telemetry) != 5 or not all(row['report_received'] is True
                and set(row['attempted_bridge_names'] or ()) == set(BRIDGES)
                and set(row['implemented_bridge_names'] or ()) == set(BRIDGES)
                and not row['failures'] and not row['failed_bridge_names'] and row['outer_timeout'] is None
                for row in telemetry.values()):
            raise ValueError('all five bridges for all five frozen inputs must have completed')
        receipt['prepared_targets_descriptor'] = {'path': str(descriptor_path), 'sha256': descriptor_sha}
        receipt['target_artifact'] = reference
        receipt['target_snapshot_id'] = prepared['target_snapshot_id']
        receipt['preparation_bridge_report_telemetry'] = telemetry
        before_config = target_snapshot_config(config)
        samples = [build_us_code_sample(**asdict(row)) for row in records]
        with load_target_bundle(artifact_path, expected_sha256=reference['sha256'], config=before_config, max_bytes=30_000_000) as bundle:
            if bundle.snapshot_id != prepared['target_snapshot_id'] or bundle.sample_count != 5 or set(bundle.statuses.values()) != {'ready'}:
                raise ValueError('shared target snapshot inventory differs')
            targets = bundle.targets_for(samples, config=before_config)
            receipt['bundle_statistics'] = bundle.statistics
        for sample in samples:
            target = targets[sample.sample_id]
            row = {'sample_id': sample.sample_id, 'source_text': sample.text, 'synthetic': True,
                   'target_document_sha256': target.document.canonical_hash(), 'passed': False,
                   'program_producer': 'deterministic source-derived shared bridge target, not learned head output',
                   'admitted': False, 'error': None}
            try:
                if target.document.source_text != sample.text or tuple(target.bridge_names) != BRIDGES:
                    raise ValueError('target source text or bridge identity differs')
                views = target.document.views
                row['dcec'] = parser_checks(views['cec_dcec.dcec_formula'], parse_dcec_string, validate_formula,
                    DCECDeontic, {'O': DCECOperator.OBLIGATORY, 'P': DCECOperator.PERMISSION, 'F': DCECOperator.FORBIDDEN})
                row['tdfol'] = parser_checks(views['fol_tdfol.tdfol_formula'], parse_tdfol,
                    deontic_type=TDFOLDeontic, deontic_operators={'O': TDFOLOperator.OBLIGATION,
                        'P': TDFOLOperator.PERMISSION, 'F': TDFOLOperator.PROHIBITION},
                    structural_validator=tdfol_operator_structure)
                gate_rule = next(item['result']['rule'] for item in gate_rows if item['text'] == sample.text)
                row['representation_limits'] = representation_limits(gate_rule, row['tdfol'])
                modal = views['modal_frame_logic.modal_ir'].payload['modal_ir']
                triples = views['modal_frame_logic.frame_logic'].payload['triples']
                if not triples or modal['frame_logic']['triples'] != triples:
                    raise ValueError('shared modal/frame triple projections differ or are empty')
                data = sample.to_dict()
                data.update(modal_ir=modal, normalized_text=modal['normalized_text'])
                adapted = LegalIRFormalizationAdapter().adapt_artifact(data)
                formulas = [formula for formula in adapted.formulas if formula.view_id == 'legal-ir-view/frame-logic/v1']
                frame_rows = [{'expression': dict(formula.expression), 'opaque': formula.opaque,
                               'validation': validate_legal_ir_view(formula.view_id, formula.expression).to_dict()}
                              for formula in formulas]
                row['frame_schema'] = {'contract_id': 'legal-ir-view/frame-logic/v1',
                    'source_triples': triples, 'projection_count': len(formulas), 'records': frame_rows,
                    'passed': len(formulas) == len(triples) and bool(formulas)
                        and all(not value['opaque'] and value['validation']['valid'] for value in frame_rows),
                    'scope': 'existing LegalIR adapter projects exact shared target triples into the frame contract; schema validation, no ErgoAI execution'}
                row['passed'] = all(row[key]['passed'] for key in ('dcec', 'tdfol', 'frame_schema'))
            except Exception as exc:
                row['error'] = failure(exc)
            receipt['samples'].append(row)
        receipt['prepared_targets_unchanged'] = sha(descriptor_path) == descriptor_sha and sha(artifact_path) == reference['sha256']
        receipt['source_and_runtime_unchanged'] = target_snapshot_config(config).to_dict() == before_config.to_dict()
        canonical_modules()
        receipt['passed'] = (receipt['lake']['passed'] and len(receipt['samples']) == 3
            and all(row['passed'] for row in receipt['samples']) and receipt['prepared_targets_unchanged']
            and receipt['source_and_runtime_unchanged'])
    except Exception as exc:
        receipt['error'] = failure(exc)
    receipt['elapsed_seconds'] = time.monotonic() - started
    receipt['timing_scope'] = 'shared artifact verification, three native parser/schema checks, and one Lake fixture build; not bridge-on evaluate latency'
    write(output / 'formal-validation.json', receipt)
    return receipt
