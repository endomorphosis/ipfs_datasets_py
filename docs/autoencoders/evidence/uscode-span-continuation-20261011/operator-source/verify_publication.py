"""Verify immutable GitHub file bytes and published root gitlinks."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--manifest', type=Path, required=True)
parser.add_argument('--receipt', type=Path, required=True)
args = parser.parse_args()
manifest = json.loads(args.manifest.read_bytes())
def verify(entry):
    url = 'https://raw.githubusercontent.com/' + entry['repository'] + '/' + entry['commit'] + '/' + urllib.parse.quote(entry['path'], safe='/')
    request = urllib.request.Request(url, headers={'User-Agent': 'uscode-source-reconciliation-verifier/1'})
    with urllib.request.urlopen(request, timeout=40) as response:
        assert response.status == 200
        body = response.read(entry['bytes'] + 1)
    actual = hashlib.sha256(body).hexdigest()
    assert len(body) == entry['bytes'] and actual == entry['sha256'], entry['path']
    return dict(entry, url=url, verified=True)
with ThreadPoolExecutor(max_workers=6) as pool:
    verified = list(pool.map(verify, manifest['files']))
for expected in manifest['gitlinks']:
    line = subprocess.check_output(['git', '-C', expected['worktree'], 'ls-tree', expected['root_commit'], expected['path']], text=True).strip()
    fields = line.split()
    assert fields[:3] == ['160000', 'commit', expected['target_commit']], line
    remote = subprocess.check_output(['git', '-C', expected['worktree'], 'ls-remote', 'origin', 'refs/heads/main'], text=True).split()[0]
    assert remote == expected['root_commit'], 'root main moved; recheck ancestry before final publication claim'
    expected['verified'] = True
receipt = dict(schema='uscode-span-continuation-publication-verification/v1', passed=True,
               file_count=len(verified), files=verified, gitlinks=manifest['gitlinks'],
               scope='Exact file bytes from immutable GitHub commits and exact root datasets/accelerate gitlinks; no model publication')
args.receipt.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
print(json.dumps({'passed': True, 'file_count': len(verified), 'gitlink_count': len(manifest['gitlinks'])}))
