"""Read only the permitted original-image population; never scan outside it."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import unicodedata
import warnings

D = Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002')
A = Path('/home/barberb/lift_coding/.worktrees/ir-release-accelerate-20261002')
sys.path.insert(0, str(D))
from ipfs_datasets_py.logic.formalization.autoencoder import source_function_units as units
from ipfs_datasets_py.logic.software_contracts.semantic_index import snapshot

BASE = Path('/home/barberb/lift_coding/artifacts/terminal_bench_supervisor/full-integration-20260929/terminal-full-preflight-host-01')
ROOT = BASE / 'app'
ORIGINAL = BASE / 'state/original-image.json'
OUTPUT = Path(__file__).with_name('public-inventory-static-audit.json')
sha = lambda raw: hashlib.sha256(raw).hexdigest()
wire = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
original_bytes = ORIGINAL.read_bytes()
original = json.loads(original_bytes)
exclusions = snapshot._exclusion_raw(['.runtime'])
files, python_rows, selected, extractions = [], [], [], []
for name, expected in sorted(original['sources'].items()):
    rel = PurePosixPath(name)
    assert not rel.is_absolute() and '..' not in rel.parts and rel.as_posix() == name
    path = ROOT / name
    row = dict(path=name, expected_sha256=expected['sha256'])
    files.append(row)
    try:
        st = path.lstat()
    except FileNotFoundError:
        row['missing'] = True
        continue
    row.update(regular=stat.S_ISREG(st.st_mode), symlink=stat.S_ISLNK(st.st_mode),
               links=st.st_nlink, bytes=st.st_size, executable=bool(st.st_mode & 0o111),
               executable_matches_original=bool(st.st_mode & 0o111) == expected['executable'])
    parents = [ROOT.joinpath(*rel.parts[:i]) for i in range(1, len(rel.parts))]
    row['symlink_parent'] = any(p.is_symlink() for p in parents)
    if not row['regular'] or row['symlink_parent']:
        continue
    raw = path.read_bytes()
    row.update(sha256=sha(raw), sha256_matches_original=sha(raw) == expected['sha256'],
               over_1MiB=len(raw) > 1024**2, zero_bytes=len(raw) == 0,
               native_kind=snapshot._kind(name),
               native_excluded=snapshot._ignored_raw(name.encode(), exclusions),
               native_safe_path=snapshot._safe_raw_path(name.encode()) == name,
               source_map_safe_path=('\\' not in name and unicodedata.normalize('NFC', name) == name
                                     and len(name.encode()) <= 1024))
    try:
        text = raw.decode('utf-8', 'strict')
        row['utf8'] = True
    except UnicodeDecodeError:
        row['utf8'] = False
        continue
    if not name.endswith('.py'):
        continue
    python_rows.append(row)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', SyntaxWarning)
        tree = ast.parse(text, filename=name, type_comments=True)
    extracted = units.extract_function_units(source_bytes=raw, source_sha256=sha(raw),
                                             source_path=name, max_functions=1024)
    extractions.append(extracted)
    row.update(ast_parse_ok=True, ast_nodes=sum(1 for _ in ast.walk(tree)),
        functions=sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)),
        newlines=raw.count(b'\n'), line_controls_present=any(c in raw for c in (b'\r', b'\v', b'\f', b'\x00')),
        extracted_functions=len(extracted['units']), extraction_frontier=extracted['frontier'],
        normalization=dict(Counter(u['status'] for u in extracted['units'])),
        mapped_bytes=sum(len(u['normalized_source_text'].encode()) for u in extracted['units']),
        mapped_lines=sum(len(u['source_binding']['line_byte_map']) for u in extracted['units']),
        over_character_cap=sum(len(u['normalized_source_text']) > 32768 for u in extracted['units']),
        extraction_sha256=sha(wire(extracted)), extraction_serialized_bytes=len(wire(extracted)))
    for unit in extracted['units']:
        if (not row['native_excluded'] and unit['status'] == 'eligible'
                and len(unit['normalized_source_text']) <= 32768 and len(selected) < 128):
            selected.append(dict(path=name, unit_id=unit['unit_id'], qualified_name=unit['qualified_name'],
                                 normalized_body_sha256=unit['normalized_body_sha256']))

summary = dict(files=len(files), bytes=sum(r.get('bytes', 0) for r in files),
    max_bytes=max(r.get('bytes', 0) for r in files), python_files=len(python_rows),
    python_bytes=sum(r['bytes'] for r in python_rows),
    ast_nodes=sum(r['ast_nodes'] for r in python_rows), ast_functions=sum(r['functions'] for r in python_rows),
    extracted_functions=sum(r['extracted_functions'] for r in python_rows),
    mapped_bytes=sum(r['mapped_bytes'] for r in python_rows),
    normalization=dict(sum((Counter(r['normalization']) for r in python_rows), Counter())),
    missing=[r['path'] for r in files if r.get('missing')],
    nonregular=[r['path'] for r in files if not r.get('regular')],
    symlink_parents=[r['path'] for r in files if r.get('symlink_parent')],
    shared_hardlinks=[r['path'] for r in files if r.get('links', 0) != 1],
    hash_mismatches=[r['path'] for r in files if not r.get('sha256_matches_original')],
    executable_mismatches=[r['path'] for r in files if not r.get('executable_matches_original')],
    non_utf8=[r['path'] for r in files if not r.get('utf8')],
    over_1MiB=[r['path'] for r in files if r.get('over_1MiB')],
    native_exclusions=[r['path'] for r in files if r.get('native_excluded')],
    native_kinds=dict(Counter(r['native_kind'] for r in files)),
    unsafe_paths=[r['path'] for r in files if not r.get('native_safe_path') or not r.get('source_map_safe_path')],
    original_image_sha256=sha(original_bytes), python_rows=python_rows,
    selected_pre_token_check=len(selected), selected_pre_token_check_files=sorted({r['path'] for r in selected}),
    selection='canonical path / source byte order; no embedding or tokenizer called')
checks = dict(signed_source_population_256=len(files) <= 256,
    per_file_1MiB=not summary['over_1MiB'], source_unit_python_paths_128=len(python_rows) <= 128,
    source_unit_total_python_4MiB=summary['python_bytes'] <= 4*1024**2,
    source_unit_total_functions_1024=summary['extracted_functions'] <= 1024,
    source_unit_total_normalized_4MiB=summary['mapped_bytes'] <= 4*1024**2,
    source_unit_per_file_AST_nodes_65536=all(r['ast_nodes'] <= 65536 for r in python_rows),
    source_unit_per_file_newlines_16384=all(r['newlines'] <= 16384 for r in python_rows),
    source_unit_per_file_mapped_lines_65536=all(r['mapped_lines'] <= 65536 for r in python_rows),
    catalog_total_source_16MiB=summary['bytes'] <= 16*1024**2,
    cooperative_scan_memory_envelope_4096MiB=len(files)*1024**2 <= 4096*1024**2//16,
    UTF8_exact_regular_hash_bound=not any(summary[k] for k in ('missing','nonregular','symlink_parents',
        'shared_hardlinks','hash_mismatches','executable_mismatches','non_utf8','unsafe_paths')))
sources = [D/'ipfs_datasets_py/logic/software_contracts/semantic_index/snapshot.py',
    D/'ipfs_datasets_py/logic/software_contracts/codebase_source_units_384.py',
    D/'ipfs_datasets_py/logic/software_contracts/codebase_ir.py',
    D/'ipfs_datasets_py/duckdb_control/codebase_catalog.py',
    A/'ipfs_accelerate_py/agent_supervisor/runtime/source384_repository_context.py']
report = dict(schema='retained-public-inventory-static-audit@1', root=str(ROOT), original_image=str(ORIGINAL),
    no_index_mutation=True, no_inference=True, no_source_execution=True, no_hidden_verifier_inputs=True,
    scope='Only the 218 original-image.json public source paths; generated supervisor files are outside this audit.',
    method='Independent exact byte/hash/UTF8 checks, stdlib AST parse, and shared pure function-unit extraction. No snapshot, catalog, semantic graph, numerical worker or model run.',
    producer=dict(files={str(p):sha(p.read_bytes()) for p in sources}, extraction=units.pins(),
                  script_sha256=sha(Path(__file__).read_bytes())),
    bounds_checked=checks, exclusions=[e.decode() for e in exclusions], summary=summary, files=files,
    selected_pre_token_check=selected,
    unknowns=['Whole semantic manifest 16MiB and AST catalog 64MiB serialized sizes have not been constructed or measured.',
       'The full semantic edge working set and its fit in the 8192-entry CID memo are not measured by this AST-only audit.',
       'Native full-repository preparation/observation deadlines, resource admission, tokenizer coverage and inference are unqualified here.',
       '128 eligible functions are selected before token screening; the remaining eligible units stay explicitly deferred. This does not certify formalization quality.'])
OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
print(json.dumps(dict(output=str(OUTPUT),sha256=sha(OUTPUT.read_bytes()),bounds_checked=checks,
    summary={k:v for k,v in summary.items() if k!='python_rows'}),indent=2))
