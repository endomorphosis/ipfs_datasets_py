"""Wave 8 shared helpers: repo map, fresh remote parquet download, dedupe files."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import io, json, os, re, sys, unicodedata, urllib.request, urllib.error

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

WAVE8 = os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/wave8")
HOST = "huggingface.co"
CONNECTOR = "custom.huggingface"

# cc: (repo, display_name, ecolex_country_name, jurisdiction, default_lang)
TARGETS = {
    'vu': ('ipfs_vanuatu_laws', 'Vanuatu', 'Vanuatu', 'Vanuatu', 'en'),
    'bi': ('ipfs_burundi_laws', 'Burundi', 'Burundi', 'Burundi', 'fr'),
    'af': ('ipfs_afghanistan_laws', 'Afghanistan', 'Afghanistan', 'Afghanistan', 'en'),
    'gm': ('ipfs_gambia_laws', 'Gambia', 'Gambia', 'Gambia', 'en'),
    'gq': ('ipfs_equatorialguinea_laws', 'Equatorial Guinea', 'Equatorial Guinea', 'Equatorial Guinea', 'es'),
    'so': ('ipfs_somalia_laws', 'Somalia', 'Somalia', 'Somalia', 'en'),
    'ss': ('ipfs_southsudan_laws', 'South Sudan', 'South Sudan', 'South Sudan', 'en'),
    'sr': ('ipfs_suriname_laws', 'Suriname', 'Suriname', 'Suriname', 'nl'),
    'nu': ('ipfs_niue_laws', 'Niue', 'Niue', 'Niue', 'en'),
    'er': ('ipfs_eritrea_laws', 'Eritrea', 'Eritrea', 'Eritrea', 'en'),
    'sd': ('ipfs_sudan_laws', 'Sudan', 'Sudan', 'Sudan', 'en'),
    'ls': ('ipfs_lesotho_laws', 'Lesotho', 'Lesotho', 'Lesotho', 'en'),
    'pg': ('ipfs_papua_new_guinea_laws', 'Papua New Guinea', 'Papua New Guinea', 'Papua New Guinea', 'en'),
    'xk': ('ipfs_kosovo_laws', 'Kosovo', 'Kosovo', 'Kosovo', 'sq'),
}

def norm(t):
    t = unicodedata.normalize('NFKD', str(t or '')).lower()
    t = re.sub(r'[^a-z0-9\u0600-\u06FF\u0400-\u04FF\u4E00-\u9FFF]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def download_remote_parquet(repo):
    """Fresh download of remote data/laws.parquet (surrogate-authenticated). Returns (table, raw_bytes)."""
    import pyarrow.parquet as pq
    from dynamic_credentials import add_surrogate_to_request
    url = f"https://{HOST}/datasets/endomorphosis/{repo}/resolve/main/data/laws.parquet"
    req = urllib.request.Request(url)
    add_surrogate_to_request(req, CONNECTOR, allowed_hosts=[HOST])
    with urllib.request.urlopen(req, timeout=300) as resp:
        blob = resp.read()
    return pq.read_table(io.BytesIO(blob)), blob

def build_dedupe(cc):
    repo = TARGETS[cc][0]
    table, _ = download_remote_parquet(repo)
    df = table.to_pandas()
    recs = [{'id': str(r.id), 'norm_title': norm(r.title)} for r in df.itertuples()]
    out = os.path.join(WAVE8, 'dedupe', f'{cc}_dedupe.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(recs, open(out, 'w'))
    # also save fresh remote parquet snapshot for staging merge
    snap = os.path.join(WAVE8, 'dedupe', f'{cc}_remote.parquet')
    with open(snap, 'wb') as f:
        import pyarrow.parquet as pq
        pq.write_table(table, f, compression='zstd')
    return {'cc': cc, 'repo': repo, 'remote_rows': int(table.num_rows),
            'dedupe_path': out, 'snapshot': snap}

if __name__ == '__main__':
    for cc in sys.argv[1:]:
        try:
            print(json.dumps(build_dedupe(cc)))
        except Exception as e:
            print(json.dumps({'cc': cc, 'error': f'{type(e).__name__}: {e}'}))
