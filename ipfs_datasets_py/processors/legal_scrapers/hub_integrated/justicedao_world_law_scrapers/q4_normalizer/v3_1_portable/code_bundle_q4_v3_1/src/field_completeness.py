"""Field completeness for q4 packs (CoS 2026-11-05): stream parquet, count null/empty/whitespace-only
per column; write manifest.v2.json + README Field completeness section. Never rewrites parquet.
empty = '' after strip of nothing — exact empty string ''; whitespace_only = non-empty and strip()==''.
Hub: read-only tip check only when called from build; this module itself is offline."""
from __future__ import annotations
import os, json, hashlib, glob, datetime, re, yaml
import pyarrow.parquet as pq
import manifest_sanitize as MS

W = os.environ.get('Q4_WORK_ROOT') or os.path.abspath(os.path.join(os.getcwd()))
FP = os.environ.get('Q4_FIXPACKS') or os.path.join(W, 'fixpacks')

def sha(p):
  h = hashlib.sha256()
  with open(p, 'rb') as f:
    for b in iter(lambda: f.read(1 << 20), b''):
      h.update(b)
  return h.hexdigest()

def scan_kind(pack_dir, kind, batch=500):
  """Return {col: {null, empty, whitespace_only, rows}} across all shards. Streams batches."""
  paths = sorted(glob.glob(f'{pack_dir}/files/canonical/{kind}*.parquet'))
  if not paths:
    return {}, 0
  # init from first schema
  cols = list(pq.read_schema(paths[0]).names)
  st = {c: {'null': 0, 'empty': 0, 'whitespace_only': 0} for c in cols}
  rows = 0
  for p in paths:
    pf = pq.ParquetFile(p)
    for b in pf.iter_batches(batch_size=batch):
      n = b.num_rows
      rows += n
      d = b.to_pydict()
      for c in cols:
        if c not in d:
          continue
        for v in d[c]:
          if v is None:
            st[c]['null'] += 1
          elif not isinstance(v, str):
            # all-string schema; treat non-str via str()
            s = str(v)
            if s == '':
              st[c]['empty'] += 1
            elif s.strip() == '':
              st[c]['whitespace_only'] += 1
          else:
            if v == '':
              st[c]['empty'] += 1
            elif v.strip() == '':
              st[c]['whitespace_only'] += 1
  for c in st:
    st[c]['rows'] = rows
  return st, rows

def non_zero_table(st):
  """Only columns with any null/empty/whitespace_only."""
  out = {}
  for c, v in st.items():
    if v['null'] or v['empty'] or v['whitespace_only']:
      out[c] = dict(v)
  return out

def count_upstream_redaction_markers(pack_dir):
  """Count [محجوب/REDACTED] and [REDACTED-*] occurrences in articles+laws (streaming)."""
  pat = re.compile(r'\[محجوب/REDACTED\]|\[REDACTED-[A-Z]+\]')
  totals = {'marker_occurrences': 0, 'by_kind_column': {}}
  for kind in ('articles', 'laws'):
    for p in sorted(glob.glob(f'{pack_dir}/files/canonical/{kind}*.parquet')):
      pf = pq.ParquetFile(p)
      for b in pf.iter_batches(batch_size=500):
        d = b.to_pydict()
        for c, vals in d.items():
          for v in vals:
            if isinstance(v, str):
              n = len(pat.findall(v))
              if n:
                totals['marker_occurrences'] += n
                key = f'{kind}.{c}'
                totals['by_kind_column'][key] = totals['by_kind_column'].get(key, 0) + n
  return totals

def format_readme_section(arts_nz, laws_nz, arts_rows, laws_rows, egypt_note=None):
  lines = [
    '',
    '## Field completeness',
    '',
    'Definition: `null` = SQL/Arrow null; `empty` = the empty string `""` (no characters); '
    '`whitespace_only` = a non-empty string whose `strip()` is empty. '
    'Any column of `canonical/articles*.parquet` or `canonical/laws*.parquet` not listed below '
    'has zero nulls, zero empties, and zero whitespace-only values.',
    '',
    f'Articles rows scanned: {arts_rows}. Laws rows scanned: {laws_rows}.',
    '',
  ]
  if arts_nz:
    lines.append('### Articles columns with nulls or empties')
    lines.append('')
    lines.append('| column | null | empty | whitespace_only |')
    lines.append('| --- | ---: | ---: | ---: |')
    for c, v in sorted(arts_nz.items()):
      lines.append(f"| {c} | {v['null']} | {v['empty']} | {v['whitespace_only']} |")
    lines.append('')
  else:
    lines.append('Articles: all columns have zero nulls, zero empties, and zero whitespace-only values.')
    lines.append('')
  if laws_nz:
    lines.append('### Laws columns with nulls or empties')
    lines.append('')
    lines.append('| column | null | empty | whitespace_only |')
    lines.append('| --- | ---: | ---: | ---: |')
    for c, v in sorted(laws_nz.items()):
      lines.append(f"| {c} | {v['null']} | {v['empty']} | {v['whitespace_only']} |")
    lines.append('')
  else:
    lines.append('Laws: all columns have zero nulls, zero empties, and zero whitespace-only values.')
    lines.append('')
  if egypt_note:
    lines.append('### Upstream redaction markers (Egypt)')
    lines.append('')
    lines.append(egypt_note)
    lines.append('')
  return '\n'.join(lines)

def apply_to_pack(pack_name, batch_articles=500, batch_laws=100):
  """Mutate pack in place: README + manifest.json hashes + new manifest.v2.json. Returns change rows."""
  pack_dir = f'{FP}/{pack_name}'
  assert os.path.isdir(pack_dir), pack_dir
  changes = []
  rd = f'{pack_dir}/files/README.md'
  mj = f'{pack_dir}/manifest.json'
  old_readme_sha = sha(rd)
  old_manifest_sha = sha(mj)

  arts_st, arts_rows = scan_kind(pack_dir, 'articles', batch=batch_articles)
  laws_st, laws_rows = scan_kind(pack_dir, 'laws', batch=batch_laws)
  arts_nz = non_zero_table(arts_st)
  laws_nz = non_zero_table(laws_st)

  egypt_note = None
  markers = None
  if 'egypt_governorate' in pack_name:
    markers = count_upstream_redaction_markers(pack_dir)
    m0 = json.load(open(mj))
    pack_red = sum((v.get('count') or 0) for v in (m0.get('redactions') or {}).values())
    art_text = markers['by_kind_column'].get('articles.text', 0)
    art_title = markers['by_kind_column'].get('articles.title', 0)
    law_text = markers['by_kind_column'].get('laws.text', 0)
    egypt_note = (
      f'This pack contains upstream redaction markers of the form `[محجوب/REDACTED]` that were already '
      f'present in the source tables (endomorphosis / prior stage). Counts by column: '
      f'articles.text={art_text}, articles.title={art_title}, laws.text={law_text} '
      f'(total marker occurrences={markers["marker_occurrences"]}). '
      f'The q4 pack applied zero new redactions (manifest `redactions` count={pack_red}). '
      f'These markers are disclosed here; values were not invented or replaced.'
    )

  # Update README: replace existing Field completeness section if present, else append
  text = open(rd, encoding='utf-8').read()
  section = format_readme_section(arts_nz, laws_nz, arts_rows, laws_rows, egypt_note)
  if '\n## Field completeness\n' in text:
    # strip old section through next ## or EOF
    text = re.sub(r'\n## Field completeness\n.*?(?=\n## |\Z)', section, text, flags=re.S)
  else:
    text = text.rstrip() + '\n' + section
  # validate yaml front matter still loads
  if text.startswith('---'):
    yaml.safe_load(text.split('---\n')[1])
  open(rd, 'w', encoding='utf-8').write(text)
  new_readme_sha = sha(rd)
  changes.append((pack_name, 'files/README.md', old_readme_sha, new_readme_sha, 'readme_field_completeness'))

  # Update manifest.json: refresh README hash; add field_completeness summary pointer
  m = json.load(open(mj))
  files = m.get('files') or []
  found = False
  for f in files:
    if f.get('path') == 'README.md':
      f['size'] = os.path.getsize(rd)
      f['sha256'] = new_readme_sha
      found = True
  if not found:
    files.append({'path': 'README.md', 'op': 'modify', 'size': os.path.getsize(rd), 'sha256': new_readme_sha, 'rows': None})
  # remove prior manifest.v2 entry if re-running
  files = [f for f in files if f.get('path') != 'manifest.v2.json']
  m['files'] = files
  m['field_completeness'] = {
    'definition': {
      'null': 'Arrow/SQL null',
      'empty': 'exact empty string ""',
      'whitespace_only': 'non-empty string with strip()==""',
      'omission_rule': 'any column not listed has zero nulls, zero empties, zero whitespace_only',
    },
    'articles_rows': arts_rows,
    'laws_rows': laws_rows,
    'articles_non_zero': arts_nz,
    'laws_non_zero': laws_nz,
  }
  if egypt_note:
    m['field_completeness']['upstream_redaction_markers'] = {
      'form': '[محجوب/REDACTED]',
      'source': 'present in upstream/source tables; pack applied zero new redactions',
      'counts': markers,
      'pack_redactions_total': pack_red,
    }
  m['manifest_version'] = 'v2-disclosure'
  m['completeness_restated_at'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')

  # Write sanitised manifest.v2.json first to compute its hash, then add to files list
  v2_path = f'{pack_dir}/manifest.v2.json'
  # provisional files list without v2 self-entry for sanitize body; then add self
  body = MS.sanitize(dict(m))
  # write temp without self hash
  json.dump(body, open(v2_path, 'w'), indent=1)
  v2_sha = sha(v2_path)
  v2_size = os.path.getsize(v2_path)
  # add self to both manifests' file lists
  self_entry = {'path': 'manifest.v2.json', 'op': 'add', 'size': v2_size, 'sha256': v2_sha, 'rows': None}
  # But path in pack root not under files/ — upload lists use path_in_repo. Existing layout has manifest.json at pack root.
  m['files'] = files + [self_entry]
  body['files'] = list(m['files'])
  # rewrite v2 with files including self (size/sha of v2 will change — compute stable approach:
  # store manifest.v2.json WITHOUT including its own file entry in the hashed body, OR include with placeholder.
  # Prefer: file list in v2 includes README+parquet+csv+manifest.v2 with correct sha after final write.
  # Two-pass: write content without self; hash; append self; rewrite — second write changes hash.
  # Solution: put manifest.v2.json hash in a sibling field, and list it in upload manifest separately.
  # CoS wants manifest.v2 in the pack. Use: files list entries for data files + README; 
  # `manifest_v2_sha256` field on the object itself; upload manifest lists the file with sha after write.

  # Simpler approach matching existing manifest.json (at pack root, listed in upload separately):
  # Keep files[] as the Hub upload payload paths under files/. manifest.v2.json sits at pack root
  # like manifest.json and is listed in q4_upload_manifest_v2.tsv explicitly.

  m['files'] = files  # without self in files[] (files[] are under files/)
  body = MS.sanitize(dict(m))
  json.dump(body, open(v2_path, 'w'), indent=1)
  v2_sha = sha(v2_path)
  body['manifest_v2_sha256'] = v2_sha
  # rewrite once with self-sha field (does change file bytes/hash) — freeze by writing final without embedding own sha in body
  # Final: body has no self-sha; upload tsv carries sha of the file on disk.
  json.dump(MS.sanitize(dict(m)), open(v2_path, 'w'), indent=1)
  v2_sha = sha(v2_path)

  json.dump(m, open(mj, 'w'), indent=1)  # raw local manifest (may have more than sanitised)
  # Also write sanitised overwrite of? Keep manifest.json as working copy (was already sanitised on build).
  # Re-sanitize manifest.json for consistency with build_q2 output
  json.dump(MS.sanitize(dict(m)), open(mj, 'w'), indent=1)
  new_manifest_sha = sha(mj)
  changes.append((pack_name, 'manifest.json', old_manifest_sha, new_manifest_sha, 'manifest_readme_hash_and_completeness'))
  changes.append((pack_name, 'manifest.v2.json', '', v2_sha, 'add_manifest_v2'))

  return {
    'pack': pack_name,
    'changes': changes,
    'arts_nz': arts_nz,
    'laws_nz': laws_nz,
    'arts_rows': arts_rows,
    'laws_rows': laws_rows,
    'readme_sha': new_readme_sha,
    'manifest_sha': new_manifest_sha,
    'manifest_v2_sha': v2_sha,
    'egypt': markers,
  }

if __name__ == '__main__':
  import sys
  for name in sys.argv[1:]:
    r = apply_to_pack(name)
    print('APPLIED', name, 'arts_nz', r['arts_nz'], 'laws_nz', r['laws_nz'], 'v2', r['manifest_v2_sha'][:12])
