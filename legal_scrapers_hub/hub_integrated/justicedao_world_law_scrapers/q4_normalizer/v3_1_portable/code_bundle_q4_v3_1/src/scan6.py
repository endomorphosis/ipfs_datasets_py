"""Bundled CoS scan6 patterns. Credential regex loaded from vendor/ relative to bundle root."""
from __future__ import annotations
import os, re
import pyarrow as pa, pyarrow.parquet as pq

def _bundle_root():
  return os.environ.get('Q4_BUNDLE_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def _load_sec():
  p = os.path.join(_bundle_root(), 'vendor', 'credential_shapes_regex.txt')
  return open(p, encoding='utf-8').read().strip()

SEC = None  # lazy
DOM = r"(?:g\s*m\s*a\s*i\s*l|gmial|gmai|gamil|gnail|gmaill|googlemail|yahoo|yaho|yahooo|ymail|rocketmail|outlook|hotmail|hotmial|hotmal|live|msn|aol|proton(?:mail)?|pm\.me|icloud|me\.com|mail\.ru|inbox\.ru|list\.ru|bk\.ru|yandex|ya\.ru|rambler|gmx|web\.de|qq|163|126|sina|rediffmail|zoho|mail\.com|tutanota|libero|laposte|orange\.fr|wanadoo|terra|uol|bol\.com\.br|seznam|wp\.pl|o2\.pl|interia|abv\.bg|ukr\.net|naver|daum|hanmail)"

def _pat():
  global SEC
  if SEC is None:
    SEC = _load_sec()
  return {
    "secret": re.compile(SEC),
    "webmail": re.compile(r"(?i)[A-Za-z0-9._%+-]+\s*(?:@|\(at\)|\[at\]|\{at\}|＠|\sat\s)\s*" + DOM + r"\b"),
    "any_email": re.compile(r"(?i)[A-Za-z0-9._%+-]+\s?@\s?[A-Za-z0-9-]+(?:\s?\.\s?[A-Za-z0-9-]+)+"),
    "path": re.compile(r"(?i)(?:/home/[\w.-]+|/Users/[\w.-]+|/workspace/|/root/|[A-Z]:\\\\?Users\\\\?)"),
    "natid_CI": re.compile(r"(?:\b[Cc]\s?\.\s?[IiLl|]\s?\.?|\b(?:CI|Ci|ci|cI|C\s[Il])(?![A-Za-zñÑáéíóú])|\b[Cc][IiLl|](?=\d{5})|(?i:\bc[eé]d(?:ula)?\.?(?:\s+de\s+identidad)?(?:\s+de)?|\bcarnet(?:\s+de\s+identidad)?|\bdocumento\s+de\s+identidad))\s*(?:[Nn][°ºo.]*\s*|#|:|[Nn]ro\.?\s*)?\s*\d[\d.,'\s-]{3,}\d"),
    "natid_dotted": re.compile(r"(?<![\d.])\d{1,2}\.\d{3}\.\d{3}(?![\d.])"),
    "natid_DNI": re.compile(r"(?i)\bDNI\s*(?:n[°ºo.]*)?\s*:?\s*\d{7,8}[A-Z]?\b"),
    "natid_CPF": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    "natid_CURP": re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b"),
    "natid_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "natid_NIE": re.compile(r"\b[XYZ]-?\d{7}-?[A-Z]\b"),
    "natid_AT_SVNR": re.compile(r"(?i)(?:sozialversicherungsnummer|SVNR|VSNR)\s*:?\s*\d{4}\s?\d{6}"),
  }

# module-level for scanlib compatibility
FAILK = {"secret", "webmail", "path"}

class _PatProxy(dict):
  def __getitem__(self, k):
    return _pat()[k]
  def items(self):
    return _pat().items()
  def keys(self):
    return _pat().keys()

PAT = _PatProxy()

def scan(path, skip_marker=True):
  f = pq.ParquetFile(path)
  PAT_ = _pat()
  h = {k: 0 for k in PAT_}
  samp = {k: [] for k in PAT_}
  base = 0
  h["path_jsonpath_allowed"] = 0
  for b in f.iter_batches(batch_size=2000):
    for name in b.schema.names:
      c = b.column(name)
      if not (pa.types.is_string(c.type) or pa.types.is_large_string(c.type)):
        continue
      for i, v in enumerate(c.to_pylist()):
        if not v:
          continue
        for k, r in PAT_.items():
          for mo in r.finditer(v):
            if k == "path" and name == "json_path" and mo.group(0) == "/workspace/" and v.startswith("/workspace/legal-corpora/"):
              h["path_jsonpath_allowed"] += 1
              continue
            h[k] += 1
            if len(samp[k]) < 40:
              s = max(0, mo.start() - 150)
              samp[k].append({"row": base + i, "col": name, "match": mo.group(0), "ctx": v[s:mo.end() + 150]})
    base += b.num_rows
  return h, samp
