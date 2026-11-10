"""ipfs_datasets_py-backed case-law normalizer (JusticeDAO world_law caselaw scrapers).

Normalizes staged case-law parquet rows into the shared world_law caselaw schema:
  * standard core fields always present (string-typed, nullable) so HF `load_dataset`
    streaming never hits null-type/schema-cast failures across parts;
  * `licence`, `licence_flag`, `flag` columns; source provenance (`source_host`,
    `source_dataset`, `normalizer`), `country`, `legal_branch`;
  * `court_id` linkage (Courthouse-scraper ids where a mapping is supplied);
  * a deterministic `doc_id` (sha256 of config+source_url/number+text prefix).
Uses ipfs_datasets_py.processors.legal_data.canonical_legal_corpora (from
/workspace/ipfs_datasets_py_latest or an installed ipfs_datasets_py) to tag the legal
branch and to refuse targets that are Caselaw Access Project corpora (CAP exclusion).
No network access, no secrets.
"""
import os, sys, hashlib
import pyarrow as pa
IPFS_DATASETS_PATH = os.environ.get("IPFS_DATASETS_PY_PATH", "/workspace/ipfs_datasets_py_latest")
if os.path.isdir(IPFS_DATASETS_PATH) and IPFS_DATASETS_PATH not in sys.path:
    sys.path.insert(0, IPFS_DATASETS_PATH)
try:
    from ipfs_datasets_py.processors.legal_data import canonical_legal_corpora as _clc
except Exception:  # pragma: no cover - library optional at read time
    _clc = None

NORMALIZER_VERSION = "caselaw-normalize/1.0"
CORE = ["doc_id", "country", "jurisdiction", "config", "court", "court_id", "chamber", "date",
        "number", "ecli", "title", "text", "source_url", "source_host", "source_dataset",
        "licence", "licence_flag", "flag", "retrieved_at", "legal_branch", "normalizer"]
BOOL = {"is_archive"}

def ipfs_datasets_available():
    return _clc is not None

def assert_not_cap(dataset_id):
    """Refuse to (re)publish anything ipfs_datasets_py maps to the Caselaw Access Project."""
    if _clc is None:
        return
    try:
        c = _clc.infer_canonical_legal_corpus_for_dataset_id(dataset_id)
        if c and c.key == "caselaw_access_project":
            raise ValueError(f"{dataset_id} maps to CAP; excluded by policy")
    except KeyError:
        pass
    except ValueError as e:
        if "CAP" in str(e): raise

def legal_branch(dataset_id):
    if _clc is not None:
        try:
            return _clc.infer_canonical_legal_corpus_for_dataset_id(dataset_id).normalized_branch() or "caselaw"
        except Exception:
            pass
    return "caselaw"

def _doc_id(cfg, r):
    key = "|".join(str(r.get(k) or "") for k in ("source_url", "number", "ris_id", "date")) + "|" + str(r.get("text") or "")[:2000]
    return hashlib.sha256(f"{cfg}|{key}".encode("utf-8", "replace")).hexdigest()

def normalize_table(t, *, dataset_id, config, country, source_host, source_dataset,
                    licence=None, licence_flag=None, flags=None, court_ids=None):
    """Return a normalized pyarrow Table. `flags`: list (aligned to rows) of flag str/None.
    `court_ids`: dict court-name -> Courthouse court_id (optional linkage)."""
    assert_not_cap(dataset_id)
    branch = legal_branch(dataset_id)
    rows = t.to_pylist()
    if flags is not None and len(flags) != len(rows):
        raise ValueError("flags length mismatch")
    out = []
    for i, r in enumerate(rows):
        r = dict(r)
        r.setdefault("config", config); r["config"] = r.get("config") or config
        r["country"] = country
        r["source_host"] = r.get("source_host") or source_host
        r["source_dataset"] = r.get("source_dataset") or source_dataset
        if licence and not r.get("licence"): r["licence"] = licence
        if licence_flag and not r.get("licence_flag"): r["licence_flag"] = licence_flag
        if flags is not None: r["flag"] = flags[i]
        if court_ids and not r.get("court_id"): r["court_id"] = court_ids.get(r.get("court"))
        r["legal_branch"] = branch; r["normalizer"] = NORMALIZER_VERSION
        r["doc_id"] = _doc_id(config, r)
        out.append(r)
    cols = CORE + sorted({k for r in out for k in r} - set(CORE))
    arrs = {}
    for c in cols:
        if c in BOOL:
            arrs[c] = pa.array([r.get(c) for r in out], pa.bool_())
        else:
            arrs[c] = pa.array([None if r.get(c) is None else str(r.get(c)) for r in out], pa.string())
    return pa.table(arrs)

if __name__ == "__main__":
    import argparse, pyarrow.parquet as pq
    ap = argparse.ArgumentParser(description="Normalize one staged caselaw parquet file")
    for a in ("src", "dst", "--dataset-id", "--config", "--country", "--source-host", "--source-dataset", "--licence", "--licence-flag"):
        ap.add_argument(a)
    x = ap.parse_args()
    tb = normalize_table(pq.read_table(x.src), dataset_id=x.dataset_id, config=x.config, country=x.country,
                         source_host=x.source_host, source_dataset=x.source_dataset, licence=x.licence, licence_flag=x.licence_flag)
    pq.write_table(tb, x.dst, compression="zstd"); print(x.dst, tb.num_rows, "ipfs_datasets_py:", ipfs_datasets_available())
