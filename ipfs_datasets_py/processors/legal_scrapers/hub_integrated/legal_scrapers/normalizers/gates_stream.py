"""gates_stream.py RELEASE_DIR RAW_DIR RAW_REV OUT.json [--hub REPO@REV] [--raw-hub REPO@REV] [--scratch DIR]

Streaming municipal IR release gates: the same 34 gates as the Verifier-derived gates.py / gates_lean.py (schema, counts, ids
vs raw, dup ids, orphans/law links, source_url, manifest pin + input hashes, body == shipped normalize(raw), body_sha256,
vectors 384-d / unit norm / non-zero / finite / cids == corpus / pointers, vector index consistency, corpus and manifest
index hashes, bm25 document count, no faiss files; plus the informational rows_with_paragraph_breaks and graph_nodes).

Memory is bounded by streaming: corpus and raw files are read one at a time (only the id/link/url/revision/hash columns
are kept, bodies are kept as sha256), vectors one file at a time (per-cluster float64 sums instead of the full matrix),
bm25/graph counts come from parquet metadata.
A gate whose inputs can't be read (for example, raw files in another layout) is recorded as failed with NOT_RUN, and
the remaining gates still run.

--hub REPO@REV: release files missing from RELEASE_DIR (corpus, bm25 documents, graph nodes, vectors) are downloaded one at a
time from that revision into --scratch and deleted after use. RELEASE_DIR needs manifest.json, indexes/ and country_laws_ir/.
--raw-hub REPO@REV: same for the raw files (data/laws*.parquet, data/articles*.parquet) when RAW_DIR does not hold them.
"""
import argparse, glob, hashlib, json, os, re, shutil, sys
import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq

ap = argparse.ArgumentParser()
ap.add_argument('release'); ap.add_argument('raw'); ap.add_argument('rev'); ap.add_argument('out')
ap.add_argument('--hub'); ap.add_argument('--raw-hub'); ap.add_argument('--scratch')
A = ap.parse_args()
R, RAW, REV, OUT = os.path.abspath(A.release), os.path.abspath(A.raw), A.rev, A.out
SCR = os.path.abspath(A.scratch or f'{R}/.gates_fetch')
sys.path.insert(0, R)  # shipped country_laws_ir
from country_laws_ir.structure import normalize_legal_text
import inspect, zlib
# text_preservation v3.4.3+: article rows are normalized with their law row's raw text as parent (the builder does the same)
PARENT_AWARE = 'parent' in inspect.signature(normalize_legal_text).parameters
sys.path.insert(0, os.environ.get('LEGAL_SCRAPERS_SCHEMA_DIR') or os.path.dirname(os.path.abspath(__file__)))  # normalizers/schema.py (validate_ir_schema)
from schema import validate_ir_schema
if A.hub or A.raw_hub:
    os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
    from huggingface_hub import HfApi, hf_hub_download
    _api = HfApi()


class Src:
    """local directory, optionally backed by a Hub dataset revision (fetch one file, use it, delete it)."""
    def __init__(self, root, hub):
        self.root = root; self.hub = hub.split('@') if hub else None
        self._hubfiles = sorted(_api.list_repo_files(self.hub[0], repo_type='dataset', revision=self.hub[1])) if self.hub else []
    def list(self, pattern):
        loc = sorted(os.path.relpath(p, self.root) for p in glob.glob(f'{self.root}/{pattern}'))
        if loc or not self.hub:
            return loc
        rx = re.compile('^' + re.escape(pattern).replace(r'\*', '[^/]*') + '$')
        return [f for f in self._hubfiles if rx.match(f)]
    def get(self, rel):
        p = f'{self.root}/{rel}'
        if os.path.exists(p):
            return p, False
        assert self.hub, f'missing {rel}'
        return hf_hub_download(self.hub[0], rel, repo_type='dataset', revision=self.hub[1], local_dir=SCR), True
    def done(self, p, fetched):
        if fetched: os.remove(p)


S = Src(R, A.hub); RS = Src(RAW, A.raw_hub)
res = {}; fail = []; errs = []
GATES = ['schema_49_cols_valid', 'rows_eq_raw', 'manifest_counts', 'law_ids_eq_raw', 'art_ids_eq_raw', 'dup_entry_cid', 'dup_source_id',
         'corpus_index_contiguous', 'orphans', 'art_law_id_eq_raw', 'art_law_cid_link', 'law_law_cid_self', 'empty_source_url',
         'source_url_eq_raw', 'manifest_dataset_revision', 'rows_source_revision', 'input_sha256_eq_raw', 'body_eq_shipped_normalize_raw',
         'body_sha256_ok', 'no_double_blank_lines', 'vector_files_eq_index', 'vec_rows_eq_corpus', 'vec_dim_384', 'vec_unit_norm',
         'vec_nonzero', 'vec_finite', 'vec_cids_eq_corpus', 'vector_status_embedded', 'vec_pointers', 'vector_index_consistent',
         'corpus_index_hashes', 'manifest_index_hashes', 'bm25_docs_eq_corpus', 'no_faiss_files']


def gate(name, ok, val=None):
    res[name] = val if val is not None else bool(ok)
    if not ok: fail.append(name)


def step(fn):
    try:
        fn()
    except Exception as e:
        errs.append(f'{fn.__name__}: {e!r}'[:300])


H = lambda x: hashlib.sha256((x or '').encode()).hexdigest()
M = json.load(open(f'{R}/manifest.json'))
CF = S.list('data/corpus/*.parquet')
NEED = ['record_type', 'source_id', 'law_id', 'law_cid', 'entry_cid', 'corpus_index', 'source_url', 'source_revision', 'body_sha256', 'document_index']
st = {}

# corpus: one pass, one file at a time
def corpus_pass():
    parts = []; bodyh = {}; ml = 0; npb = 0; fh = {}
    for rel in CF:
        p, f = S.get(rel)
        fh[rel] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
        pf = pq.ParquetFile(p)
        if 's' not in st: st['s'] = pf.schema_arrow
        cols = [c for c in NEED if c in pf.schema_arrow.names]
        parts.append(pq.read_table(p, columns=cols))
        for bt in pf.iter_batches(batch_size=1024, columns=['source_id', 'body']):
            for sid, b in zip(bt.column(0).to_pylist(), bt.column(1).to_pylist()):
                bodyh[sid] = H(b); ml += bool(re.search(r'\n[ \t]*\n[ \t]*\n', b or '')); npb += '\n\n' in (b or '')
        del pf; S.done(p, f)
    st['C'] = pa.concat_tables(parts, promote_options='default').to_pandas(); st['bodyh'] = bodyh; st['ml'] = ml; st['npb'] = npb; st['corpus_file_sha'] = fh
step(corpus_pass)

# raw: one pass, one file at a time (id / law_id / source_url kept; text hashed through the shipped normalizer)
def raw_pass():
    rawf = {k: RS.list(f'data/{k}*.parquet') for k in ('laws', 'articles')}
    st['ish'] = {}; tabs = {'laws': [], 'articles': []}; eqn = 0; bodyh = st.get('bodyh', {})
    lawz = {}; last = [None, None]  # v3.4.3: law id -> zlib(raw law text), read in the laws pass (laws come first)
    def law_text(lid):
        if last[0] != lid:
            z = lawz.get(lid); last[0], last[1] = lid, (zlib.decompress(z).decode('utf-8') if z is not None else None)
        return last[1]
    for k in rawf:
        for rel in rawf[k]:
            p, f = RS.get(rel)
            st['ish'][os.path.basename(rel)] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
            names = pq.read_schema(p).names
            tabs[k].append(pq.read_table(p, columns=[c for c in ('id', 'law_id', 'source_url') if c in names]))
            cols = ['id', 'text'] + (['law_id'] if PARENT_AWARE and k == 'articles' and 'law_id' in names else [])
            for bt in pq.ParquetFile(p).iter_batches(batch_size=256, columns=cols):
                lids = bt.column(2).to_pylist() if len(cols) == 3 else [None] * bt.num_rows
                for i, t, lid in zip(bt.column(0).to_pylist(), bt.column(1).to_pylist(), lids):
                    if PARENT_AWARE and k == 'laws' and isinstance(t, str) and t:
                        lawz[i] = zlib.compress(t.encode('utf-8'), 6)
                    par = law_text(lid) if lid is not None else None
                    if par and t is not None:
                        eqn += bodyh.get(i) == H(normalize_legal_text(t, parent=par))
                    else:
                        eqn += bodyh.get(i) == H(normalize_legal_text(t))
            RS.done(p, f)
    st['eqn'] = eqn
    st['RL'] = pd.concat([t.to_pandas() for t in tabs['laws']], ignore_index=True)
    st['RA'] = pd.concat([t.to_pandas() for t in tabs['articles']], ignore_index=True) if rawf['articles'] else None
    st['eqn'] = eqn
step(raw_pass)

C = st.get('C'); RL = st.get('RL'); RA = st.get('RA')
def g_schema():
    s = st['s']; gate('schema_49_cols_valid', len(s.names) == 49 and not validate_ir_schema(s), {'n_cols': len(s.names), 'errors': validate_ir_schema(s)[:5]})
step(g_schema)
def g_rows():
    n_exp = len(RL) + (0 if RA is None else len(RA))
    gate('rows_eq_raw', len(C) == n_exp, {'corpus': len(C), 'raw_laws': len(RL), 'raw_articles': 0 if RA is None else len(RA)})
step(g_rows)
def g_mcounts(): gate('manifest_counts', M['counts'].get('corpus_rows', len(C)) == len(C), M['counts'])
step(g_mcounts)
def g_split():
    st['law'] = C[C.record_type == 'law']; st['art'] = C[C.record_type != 'law']
step(g_split)
law = st.get('law'); art = st.get('art')
def g_lawids(): gate('law_ids_eq_raw', set(law.source_id) == set(RL.id))
step(g_lawids)
def g_artids(): gate('art_ids_eq_raw', RA is None or set(art.source_id) == set(RA.id))
step(g_artids)
def g_dupcid(): gate('dup_entry_cid', C.entry_cid.duplicated().sum() == 0, int(C.entry_cid.duplicated().sum()))
step(g_dupcid)
def g_dupsid(): gate('dup_source_id', C.source_id.duplicated().sum() == 0, int(C.source_id.duplicated().sum()))
step(g_dupsid)
def g_contig(): gate('corpus_index_contiguous', sorted(C.corpus_index) == list(range(len(C))))
step(g_contig)
def g_lawcid(): st['lawcid'] = law.set_index('source_id').law_cid
step(g_lawcid)
lawcid = st.get('lawcid')
def g_art_links():
    if RA is None and 'RL' in st: st['no_articles'] = True  # as in gates_lean.py: the three article gates are not evaluated
    if RA is not None:
        ra = RA.set_index('id'); st['ra'] = ra
        orph = int((~art.law_id.isin(set(law.source_id))).sum())
        gate('orphans', orph == 0, orph)
        gate('art_law_id_eq_raw', (art.law_id.values == ra.loc[art.source_id, 'law_id'].values).all())
        gate('art_law_cid_link', (art.law_cid.values == lawcid.reindex(art.law_id).values).all())
step(g_art_links)
def g_lawself(): gate('law_law_cid_self', (law.law_cid.values == lawcid.loc[law.source_id].values).all())
step(g_lawself)
def g_empty():
    emp = int((C.source_url.fillna('').str.strip() == '').sum()); gate('empty_source_url', emp == 0, emp)
step(g_empty)
def g_url():
    rl = RL.set_index('id'); url_raw = rl.source_url.copy()
    if RA is not None:
        ra = st['ra']; url_raw = pd.concat([url_raw, ra.source_url.where(ra.source_url.fillna('') != '', ra.law_id.map(rl.source_url))])
    n = int((C.source_url.values == url_raw.loc[C.source_id].values).sum()); gate('source_url_eq_raw', n == len(C), n)
step(g_url)
def g_rev(): gate('manifest_dataset_revision', M['dataset_revision'] == REV, M['dataset_revision'])
step(g_rev)
def g_rowrev(): gate('rows_source_revision', set(C.source_revision) == {REV}, sorted(set(C.source_revision))[:3])
step(g_rowrev)
def g_ish():
    ish = st['ish']; gate('input_sha256_eq_raw', all(ish.get(k) == v for k, v in M['input_sha256'].items()) and len(M['input_sha256']) == len(ish), M['input_sha256'])
step(g_ish)
def g_body(): gate('body_eq_shipped_normalize_raw', st['eqn'] == len(C), st['eqn'])
step(g_body)
def g_bsh():
    bodyh = st['bodyh']; bsh = int(sum(bodyh[s_] == h for s_, h in zip(C.source_id, C.body_sha256))); gate('body_sha256_ok', bsh == len(C), bsh)
step(g_bsh)
def g_ml(): gate('no_double_blank_lines', st['ml'] == 0, st['ml'])
step(g_ml)
def g_npb(): res['rows_with_paragraph_breaks'] = int(st['npb'])
step(g_npb)
st.pop('bodyh', None)

# vectors: one file at a time
def vectors():
    idx = pd.read_parquet(f'{R}/indexes/vector_chunks.parquet'); st['vidx'] = idx
    gate('vector_files_eq_index', sorted(S.list('data/vectors/*.parquet')) == sorted(idx.relative_path))
    VS = []; dims = set(); nmin, nmax = np.inf, -np.inf; zeros = 0; finite = True; sums = {}; order = []; bad = []; perrow = []
    for r in idx.itertuples():
        p, f = S.get(r.relative_path); b = open(p, 'rb').read(); t = pq.read_table(p)
        n = t.num_rows; cid = t['entry_cid'].to_pylist()
        if hashlib.sha256(b).hexdigest() != r.sha256 or len(b) != r.size_bytes or n != r.row_count: bad.append((r.relative_path, 'hash/size/rows'))
        if cid[0] != r.first_key or cid[-1] != r.last_key: bad.append((r.relative_path, 'keys'))
        if r.dimension != 384 or r.model_name != 'thenlper/gte-small': bad.append((r.relative_path, 'dim/model'))
        E = t['embedding'].combine_chunks().flatten().to_numpy().astype(np.float64).reshape(n, -1); dims.add(E.shape[1])
        nn = np.linalg.norm(E, axis=1); nmin = min(nmin, float(nn.min())); nmax = max(nmax, float(nn.max()))
        zeros += int((np.abs(E).sum(1) == 0).sum()); finite = finite and bool(np.isfinite(E).all())
        cl = np.asarray(t['cluster_id'].to_pylist())
        for c in dict.fromkeys(cl.tolist()):
            m = cl == c; s0 = sums.get(c)
            sums[c] = (E[m].sum(0) + (s0[0] if s0 else 0), int(m.sum()) + (s0[1] if s0 else 0))
            if c not in order: order.append(c)
        m = cl == int(r.cluster_id)
        sc = E[m] @ np.asarray(r.shard_centroid)
        perrow.append((int(r.cluster_id), r.Index, int(m.sum()), float(sc.min()) if m.any() else None, bool((np.diff(sc) <= 1e-6).all())))
        VS.append(t.select([c for c in ('entry_cid', 'document_index', 'faiss_id', 'corpus_chunk_id', 'corpus_row_offset', 'law_cid', 'cluster_id') if c in t.column_names]))
        del t, E, b; S.done(p, f)
    V = pa.concat_tables(VS).to_pandas(); del VS
    gate('vec_rows_eq_corpus', len(V) == len(C), len(V))
    gate('vec_dim_384', dims == {384}, sorted(dims)[0] if len(dims) == 1 else sorted(dims))
    gate('vec_unit_norm', max(abs(nmin - 1), abs(nmax - 1)) < 1e-5, [nmin, nmax])
    gate('vec_nonzero', zeros == 0, zeros)
    gate('vec_finite', finite)
    gate('vec_cids_eq_corpus', V.entry_cid.nunique() == len(V) and set(V.entry_cid) == set(C.entry_cid))
    gate('vector_status_embedded', M['vector']['status'] == 'embedded' and M['vector']['model_name'] == 'thenlper/gte-small', M['vector']['status'])
    j = V.merge(C[['entry_cid', 'document_index', 'law_cid']], on='entry_cid', suffixes=('', '_c'))
    gate('vec_pointers', bool((j.document_index == j.document_index_c).all() and (V.faiss_id == V.document_index).all() and ((j.corpus_chunk_id == j.document_index // 4096) & (j.corpus_row_offset == j.document_index % 4096)).all() and (j.law_cid == j.law_cid_c).all()))
    # cluster checks in the same order and with the same tolerances as gates_lean.py (clusters in order of first appearance;
    # for each, the index rows naming it, in index order)
    by_cl = {}
    for (c, i, cnt, mn, ordok) in perrow: by_cl.setdefault(c, []).append((i, cnt, mn, ordok))
    for c in order:
        cen = sums[c][0] / sums[c][1]; cen = cen / np.linalg.norm(cen)
        for (i, cnt, mn, ordok) in by_cl.get(c, []):
            r = idx.loc[i]
            if cnt == 0: bad.append((int(c), r.relative_path, 'index cluster_id has no rows in its file')); continue
            # Centroid tolerance 5e-5 (was 1e-5): the builder and repack_vectors_by_cluster.py store the centroid as a float32
            # mean, this gate recomputes it as a float64 mean; on large tight clusters the two differ by up to ~1.2e-5
            # (Belgium 8fb0a87e1a, clusters 10/16/22/29 of ~3.7k rows). A precision gap, not a routing defect (on Belgium
            # any two cluster centroids differ by >= 2.2e-2). Only this tolerance changed; min_score and every other gate are as before.
            if np.abs(cen - np.asarray(r.centroid)).max() > 5e-5: bad.append((int(c), 'centroid'))
            if abs(mn - r.centroid_min_score) > 1e-5: bad.append((int(c), 'min_score'))
            if not ordok: bad.append((int(c), 'order'))
    gate('vector_index_consistent', not bad, bad[:10])
step(vectors)

def g_corpidx():
    corp_idx = pd.read_parquet(f'{R}/indexes/corpus_chunks.parquet'); fh = st['corpus_file_sha']; cb = []
    for r in corp_idx.itertuples():
        h = fh.get(r.relative_path)
        if h is None:
            p, f = S.get(r.relative_path); h = hashlib.sha256(open(p, 'rb').read()).hexdigest(); S.done(p, f)
        if h != r.sha256: cb.append(r.relative_path)
    gate('corpus_index_hashes', not cb, cb)
step(g_corpidx)
def g_midx():
    mp = []
    for k, dd in (M.get('indexes') or {}).items():
        if isinstance(dd, dict) and 'sha256' in dd:
            p = f"{R}/{dd.get('relative_path') or 'indexes/' + k + '.parquet'}"
            if not os.path.exists(p) or hashlib.sha256(open(p, 'rb').read()).hexdigest() != dd['sha256']: mp.append(k)
    gate('manifest_index_hashes', not mp, mp)
step(g_midx)
def count_rows(pattern):
    n = 0
    for rel in S.list(pattern):
        p, f = S.get(rel); n += pq.read_metadata(p).num_rows; S.done(p, f)
    return n
def g_bm25():
    bd = count_rows('data/bm25/documents/*.parquet'); gate('bm25_docs_eq_corpus', bd == len(C), bd)
step(g_bm25)
def g_graph(): res['graph_nodes'] = count_rows('data/graph/nodes/*.parquet')
step(g_graph)
def g_faiss():
    fa = glob.glob(f'{R}/**/*.faiss', recursive=True) + glob.glob(f'{R}/**/*.index', recursive=True)
    fa += [f for f in S._hubfiles if f.endswith(('.faiss', '.index'))]
    gate('no_faiss_files', not fa, fa)
step(g_faiss)
for nm in GATES:
    if st.get('no_articles') and nm in ('orphans', 'art_law_id_eq_raw', 'art_law_cid_link'): continue
    if nm not in res: gate(nm, False, 'NOT_RUN: ' + (errs[0] if errs else '?'))
res['FAILED'] = fail; res['PASS'] = not fail
if errs: res['errors'] = errs
shutil.rmtree(SCR, ignore_errors=True)
json.dump(res, open(OUT, 'w'), indent=1, default=str)
for k, v in res.items(): print(k, json.dumps(v, default=str)[:300])
