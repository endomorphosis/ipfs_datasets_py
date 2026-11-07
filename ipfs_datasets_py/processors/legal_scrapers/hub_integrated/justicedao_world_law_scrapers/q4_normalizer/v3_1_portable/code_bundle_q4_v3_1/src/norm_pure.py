"""Pure helpers extracted from norm.py for offline staging. NO Hub writes."""
from __future__ import annotations
import os, re

# Truthful scrapers pointer (publication pending). code_record sha filled by packager.
PTR = (
  "\n\n## Scrapers & normalizer\n"
  "Code bundle staged for review; publication pending. "
  "See fixpacks/code_bundle_q4_v2/code_record.json (sha256: {CODE_RECORD_SHA256}). "
  "Canonical schema: `law_id, id, title, text, source_url, document_number, article_number, "
  "record_type, metadata_json`, matching endomorphosis/ipfs_malta_laws.\n"
)

def procs(slug: str):
  """Return PIDs of other local processes whose cmdline references slug/core. Offline only."""
  core = re.sub(r'^ipfs_|_laws?(_ir)?$', '', slug)
  hit = []
  for p in os.listdir('/proc'):
    if p.isdigit() and int(p) != os.getpid():
      try:
        cm = open(f'/proc/{p}/cmdline', 'rb').read().replace(b'\0', b' ').decode(errors='ignore')
      except Exception:
        continue
      if 'norm.py' in cm or 'norm_pure.py' in cm:
        continue
      if slug in cm or (len(core) > 3 and re.search(r'\b' + re.escape(core) + r'\b', cm)):
        hit.append(p)
  return hit
