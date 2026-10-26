"""Japan tranche 1 — d1-law / Reiki-Base tenant discovery census.

Discovery routes:
  A. Wayback CDX domain sweep of d1-law.com (cloud tenants: /<slug>/d1w_reiki/)
  B. Wayback CDX domain sweep of g-reiki.net (Gyosei cloud; egress-blocked,
     recorded for the census with blocked status)
  C. Wayback CDX domain sweep of lg.jp filtered to d1w_reiki paths
     (self-hosted installs on local-government domains)
  D. Per-host CDX prefix checks for the big-city hosts the pilot probed
     (catches self-hosted installs on non-lg.jp domains, Kumamoto-class)

Verification: per candidate endpoint — robots first, then fetch the
system index page, classify the variant, and match to the MIC registry
by (a) registry-name containment in page text, (b) romaji->kana slug /
host match against registry name_kana. Enumeration counts are taken
where cheap (live tenants, capped).

Resumable: candidates already final in tenant_census.jsonl are skipped.
Outputs: tenant_census.jsonl (all candidates), tenant_registry.json
(verified municipal/prefecture tenants only).
"""
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jp_build as B  # noqa: E402

OUT = B.OUT
CENSUS_PATH = OUT / "tenant_census.jsonl"
REGISTRY_PATH = OUT / "tenant_registry.json"
CDX = "https://web.archive.org/cdx/search/cdx"
HEADERS = B.HEADERS
ENUM_CAP = 25
KNOWN = {"40130", "20201", "03201", "07201", "43100"}
REG = B.REGISTRY
NAMES = sorted(((v["name"], c) for c, v in REG.items()), key=lambda t: -len(t[0]))

ROMAJI = [
    ("kya", "キャ"), ("kyu", "キュ"), ("kyo", "キョ"),
    ("sha", "シャ"), ("shu", "シュ"), ("sho", "ショ"), ("she", "シェ"),
    ("cha", "チャ"), ("chu", "チュ"), ("cho", "チョ"), ("che", "チェ"),
    ("tsu", "ツ"), ("nya", "ニャ"), ("nyu", "ニュ"), ("nyo", "ニョ"),
    ("hya", "ヒャ"), ("hyu", "ヒュ"), ("hyo", "ヒョ"),
    ("mya", "ミャ"), ("myu", "ミュ"), ("myo", "ミョ"),
    ("rya", "リャ"), ("ryu", "リュ"), ("ryo", "リョ"),
    ("gya", "ギャ"), ("gyu", "ギュ"), ("gyo", "ギョ"),
    ("ja", "ジャ"), ("ju", "ジュ"), ("jo", "ジョ"), ("je", "ジェ"),
    ("jya", "ジャ"), ("jyu", "ジュ"), ("jyo", "ジョ"),
    ("bya", "ビャ"), ("byu", "ビュ"), ("byo", "ビョ"),
    ("pya", "ピャ"), ("pyu", "ピュ"), ("pyo", "ピョ"),
    ("ka", "カ"), ("ki", "キ"), ("ku", "ク"), ("ke", "ケ"), ("ko", "コ"),
    ("sa", "サ"), ("shi", "シ"), ("su", "ス"), ("se", "セ"), ("so", "ソ"),
    ("ta", "タ"), ("chi", "チ"), ("te", "テ"), ("to", "ト"),
    ("na", "ナ"), ("ni", "ニ"), ("nu", "ヌ"), ("ne", "ネ"), ("no", "ノ"),
    ("ha", "ハ"), ("hi", "ヒ"), ("fu", "フ"), ("he", "ヘ"), ("ho", "ホ"),
    ("ma", "マ"), ("mi", "ミ"), ("mu", "ム"), ("me", "メ"), ("mo", "モ"),
    ("ya", "ヤ"), ("yu", "ユ"), ("yo", "ヨ"),
    ("ra", "ラ"), ("ri", "リ"), ("ru", "ル"), ("re", "レ"), ("ro", "ロ"),
    ("wa", "ワ"), ("wi", "ウィ"), ("we", "ウェ"), ("wo", "ヲ"),
    ("ga", "ガ"), ("gi", "ギ"), ("gu", "グ"), ("ge", "ゲ"), ("go", "ゴ"),
    ("za", "ザ"), ("ji", "ジ"), ("zu", "ズ"), ("ze", "ゼ"), ("zo", "ゾ"),
    ("da", "ダ"), ("di", "ヂ"), ("du", "ヅ"), ("de", "デ"), ("do", "ド"),
    ("ba", "バ"), ("bi", "ビ"), ("bu", "ブ"), ("be", "ベ"), ("bo", "ボ"),
    ("pa", "パ"), ("pi", "ピ"), ("pu", "プ"), ("pe", "ペ"), ("po", "ポ"),
    ("a", "ア"), ("i", "イ"), ("u", "ウ"), ("e", "エ"), ("o", "オ"),
    ("n", "ン"),
]
ROMAJI.sort(key=lambda t: -len(t[0]))


def romaji_to_kana(s):
    s = s.lower()
    out, i = [], 0
    while i < len(s):
        if i + 1 < len(s) and s[i] == s[i + 1] and s[i] not in "aiueon":
            out.append("ッ")
            i += 1
            continue
        for r, k in ROMAJI:
            if s.startswith(r, i):
                out.append(k)
                i += len(r)
                break
        else:
            return None
    return "".join(out)


def hw_to_fw(s):
    return unicodedata.normalize("NFKC", s or "")


KANA_INDEX = {}
for c, v in REG.items():
    k = hw_to_fw(v.get("name_kana", ""))
    if k:
        KANA_INDEX.setdefault(k, []).append(c)
        KANA_INDEX.setdefault(k.replace("ー", "ウ"), []).append(c)


def romaji_morae(s):
    """Split romaji into (romaji, kana) morae; None if unparseable."""
    s = s.lower()
    out, i = [], 0
    while i < len(s):
        gem = i + 1 < len(s) and s[i] == s[i + 1] and s[i] not in "aiueon"
        for r, k in ROMAJI:
            if s.startswith(r, i + (1 if gem else 0)):
                if gem:
                    out.append(("tsu", "ッ"))
                out.append((r, k))
                i += len(r) + (1 if gem else 0)
                break
        else:
            return None
    return out


def kana_variants(morae):
    """Long-vowel spellings: romaji 'kyoto' may be キョト / キョウト."""
    if morae is None:
        return []
    base = "".join(k for _, k in morae)
    variants = {base, base.replace("オウ", "オー").replace("エイ", "エー")}
    tail = {}
    for j, (r, _) in enumerate(morae):
        v = r[-1] if r else ""
        if v in "ou" and len(r) > 0:
            tail[j] = "ウ"
        elif v in "ei":
            tail[j] = "イ"
        elif v == "a":
            tail[j] = "ア"

    def build(extra):
        parts = []
        for j, (r, k) in enumerate(morae):
            parts.append(k)
            if j in extra:
                parts.append(tail[j])
        return "".join(parts)

    if tail:
        import itertools
        pos = list(tail)
        subsets = [set(pos)] if len(pos) > 3 else []
        for r in range(0, min(3, len(pos)) + 1):
            subsets += [set(c) for c in itertools.combinations(pos, r)]
        for s in subsets:
            variants.add(build(s))
    out = set()
    for v in variants:
        out.add(v)
        out.add(v.replace("オウ", "オー").replace("エイ", "エー"))
        out.add(v.replace("オウ", "オオ"))
    return list(out)


SUFFIXES = ["-city", "-town", "-village", "-shi", "-machi", "-cho", "-son",
            "-mura", "-ku", "-ken", "-pref", "-city-office"]


def slug_kana_match(slug):
    """Return (hits, prefer_kind): JIS codes whose name_kana matches the
    slug reading, plus the body kind implied by the slug suffix."""
    base = slug.lower()
    prefer = None
    for suf in SUFFIXES:
        if base.endswith(suf):
            prefer = ("prefecture" if suf in ("-ken", "-pref")
                      else "municipality")
            base = base[: -len(suf)]
            break
    base = base.replace("-", "")
    morae = romaji_morae(base)
    hits = []
    for v in kana_variants(morae):
        for cand in (v, v + "シ", v + "マチ", v + "チョウ", v + "ムラ",
                     v + "ソン", v + "ク", v + "ケン", v + "ト", v + "フ"):
            hits += KANA_INDEX.get(cand, [])
    return sorted(set(hits)), prefer


def name_in_text(text):
    for name, code in NAMES:
        if len(name) >= 3 and name in text:
            return code, name
    return None


# ---------- CDX discovery ----------
def cdx_stream(params, extractor, cap_lines=3_000_000, label=""):
    found = {}
    n = 0
    truncated = False
    try:
        with requests.get(CDX, params=params, headers=HEADERS, stream=True,
                          timeout=180) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                n += 1
                if n > cap_lines:
                    truncated = True
                    break
                hit = extractor(line.strip())
                if hit:
                    found.setdefault(hit[0], hit[1])
    except Exception as e:  # noqa: BLE001
        print(f"CDX {label} error after {n} lines: {type(e).__name__}: {e}",
              flush=True)
    print(f"CDX {label}: {n} lines -> {len(found)} candidates"
          f"{' (TRUNCATED)' if truncated else ''}", flush=True)
    return found


def discover():
    cands = {}

    def ex_d1law(line):
        m = re.match(r"https?://([^/]+)/([^/]+)/d1w_reiki/", line)
        if m:
            host, slug = m.groups()
            ep = f"https://{host}/{slug}/d1w_reiki/"
            return (ep, {"endpoint": ep, "system": "d1law", "variant": "cloud",
                         "host": host, "slug": slug, "via": "cdx-d1law.com"})
        m = re.match(r"https?://([^/]+)/d1w_reiki/", line)
        if m:
            host = m.group(1)
            ep = f"https://{host}/d1w_reiki/"
            return (ep, {"endpoint": ep, "system": "d1law",
                         "variant": "cloud-host", "host": host, "slug": "",
                         "via": "cdx-d1law.com"})
        return None

    cands.update(cdx_stream(
        {"url": "d1-law.com", "matchType": "domain", "fl": "original",
         "filter": "original:.*d1w_reiki.*", "collapse": "urlkey",
         "output": "text", "limit": "4000000"},
        ex_d1law, label="d1-law.com"))

    def ex_greiki(line):
        m = re.match(r"https?://([^/]+)/([^/]+)/", line)
        if m:
            host, slug = m.groups()
            ep = f"https://{host}/{slug}/"
            return (ep, {"endpoint": ep, "system": "reikibase",
                         "variant": "cloud-greiki", "host": host, "slug": slug,
                         "via": "cdx-g-reiki.net"})
        return None

    cands.update(cdx_stream(
        {"url": "g-reiki.net", "matchType": "domain", "fl": "original",
         "collapse": "urlkey", "output": "text", "limit": "2000000"},
        ex_greiki, label="g-reiki.net"))

    def ex_lgjp(line):
        m = re.match(r"https?://([^/]+)/((?:[^/]+/)*?)d1w_reiki/", line)
        if m:
            host, prefix = m.groups()
            ep = f"https://{host}/{prefix}d1w_reiki/"
            return (ep, {"endpoint": ep, "system": "unknown",
                         "variant": "selfhosted", "host": host, "slug": "",
                         "via": "cdx-lg.jp"})
        return None

    cands.update(cdx_stream(
        {"url": "lg.jp", "matchType": "domain", "fl": "original",
         "filter": "original:.*d1w_reiki.*", "collapse": "urlkey",
         "output": "text", "limit": "4000000"},
        ex_lgjp, label="lg.jp"))

    import jp_probe2, jp_probe4  # noqa: E402
    hosts = {}
    for src in (jp_probe2.HOSTS, jp_probe4.HOSTS):
        for code, (name, host) in src.items():
            hosts[host] = (code, name)
    s = requests.Session()
    for host, (code, name) in sorted(hosts.items()):
        for sub in ("d1w_reiki", "html/d1w_reiki", "reiki"):
            try:
                r = s.get(CDX, params={"url": f"{host}/{sub}",
                                       "matchType": "prefix", "fl": "original",
                                       "limit": "3"},
                          headers=HEADERS, timeout=30)
                lines = [l for l in (r.text or "").splitlines() if l.strip()]
            except Exception:  # noqa: BLE001
                lines = []
            if lines:
                ep = f"https://{host}/{sub}/"
                if ep not in cands:
                    cands[ep] = {"endpoint": ep, "system": "unknown",
                                 "variant": "selfhosted", "host": host,
                                 "slug": "", "via": f"cdx-host:{host}",
                                 "hint_code": code, "hint_name": name}
                break
            time.sleep(0.2)
    print(f"discovery total: {len(cands)} candidate endpoints", flush=True)
    return cands


# ---------- verification ----------
UNION_MARKERS = ("広域連合", "消防組合", "一部事務組合", "企業団", "環境衛生組合",
                 "衛生組合", "清掃組合")


def verify(fx, cand, enum_budget):
    rec = dict(cand)
    ep = cand["endpoint"]
    if cand["system"] == "unknown":
        rec["system_guess"] = "d1law-from-path"
    idx_rel = ("reiki_taikei/taikei_default.html"
               if cand["system"] == "reikibase"
               else "mokuji_bunya_index.html")
    idx_url = ep + idx_rel
    try:
        raw = fx.get(idx_url, None, timeout=45, attempts=1)
        idx_text = B.decode(raw)
        rec["live"] = True
    except PermissionError as e:
        rec.update(live=False, status="robots_blocked", error=str(e))
        return rec, enum_budget
    except Exception as e:  # noqa: BLE001
        rec.update(live=False, status="unreachable",
                   error=f"{type(e).__name__}: {e}")
        return rec, enum_budget
    text = idx_text
    if "Reiki-Base" in text or "ぎょうせい" in text:
        rec["system"] = "reikibase"
    if re.search(r"OpenResDataWin\('[^']+','[^']+'\)", text):
        rec["variant_gen"] = "two-arg (older gen)"
    hit = name_in_text(text)
    if hit:
        rec["jis"], rec["matched_name"] = hit
        rec["match"] = "page-text"
    elif cand.get("hint_code"):
        rec["jis"] = cand["hint_code"]
        rec["matched_name"] = cand.get("hint_name")
        rec["match"] = "host-hint (pilot probe list)"
    else:
        host_tok = ""
        m = re.match(r"(?:www\d?\.)?(?:city|town|village)\.([^.]+)\.", cand.get("host", ""))
        if m:
            host_tok = m.group(1)
        for tok in (cand.get("slug") or "", host_tok):
            if not tok:
                continue
            codes, prefer = slug_kana_match(tok)
            pool = codes
            if prefer:
                pref_pool = [c for c in codes
                             if REG.get(c, {}).get("kind") in
                             (prefer, "ward")]
                if pref_pool:
                    pool = pref_pool
            if len(pool) == 1:
                rec["jis"] = pool[0]
                rec["matched_name"] = REG[pool[0]]["name"]
                rec["match"] = f"kana:{tok}"
                break
            if len(codes) > 1:
                rec.setdefault("kana_candidates", codes)
        if "jis" not in rec:
            # last resort: the tenant root page (frameset/title often
            # carries the body name; d1-law roots 403, Reiki-Base don't)
            try:
                raw = fx.get(ep, None, timeout=45, attempts=1)
                root_text = B.decode(raw)
                hit = name_in_text(root_text)
                if hit:
                    rec["jis"], rec["matched_name"] = hit
                    rec["match"] = "page-text (root)"
                    text = root_text + "\n" + text
            except Exception as e:  # noqa: BLE001
                rec["root_error"] = f"{type(e).__name__}: {e}"
        if "jis" not in rec:
            slug = cand.get("slug") or ""
            if any(m in text for m in UNION_MARKERS) or any(
                    t in slug for t in ("eisei", "jimu", "suido", "kankyo",
                                        "kumiai", "rengo", "kouiki")):
                rec["status"] = "non_municipal_union"
            else:
                rec["status"] = "unmatched"
            return rec, enum_budget
    if rec.get("status") is None:
        rec["status"] = "verified"
    reg = REG.get(rec["jis"], {})
    rec["kind"] = reg.get("kind", "")
    rec["registry_name"] = reg.get("name", "")
    if rec["jis"] in KNOWN:
        rec["status"] = "known_pilot"
    if (rec.get("status") == "verified" and enum_budget > 0
            and rec.get("kind") in ("municipality", "prefecture", "ward")):
        code = rec["jis"]
        try:
            if rec["system"] == "reikibase":
                _, docs = B.enumerate_corpus(fx, code, ep)
            else:
                _, docs = B.enumerate_d1law(fx, code, ep)
            rec["corpus_docs"] = len(docs)
            enum_budget -= 1
        except Exception as e:  # noqa: BLE001
            rec["enum_error"] = f"{type(e).__name__}: {e}"
    return rec, enum_budget


def main():
    done_eps = set()
    if CENSUS_PATH.exists():
        for l in CENSUS_PATH.read_text(encoding="utf-8").splitlines():
            if l.strip():
                done_eps.add(json.loads(l)["endpoint"])
    cand_path = OUT / "tenant_candidates.json"
    if cand_path.exists():
        raw = json.loads(cand_path.read_text(encoding="utf-8"))
        cands = {c["endpoint"]: c for c in raw}
        print(f"loaded {len(cands)} cached candidates", flush=True)
    else:
        cands = discover()
        cand_path.write_text(json.dumps(list(cands.values()),
                                        ensure_ascii=False, indent=1),
                             encoding="utf-8")
    fx = B.Fetcher()
    enum_budget = ENUM_CAP
    todo = {ep: c for ep, c in cands.items() if ep not in done_eps}
    print(f"verifying {len(todo)} new candidates "
          f"({len(done_eps)} already in census)", flush=True)
    with CENSUS_PATH.open("a", encoding="utf-8") as out:
        for ep, cand in sorted(todo.items()):
            try:
                rec, enum_budget = verify(fx, cand, enum_budget)
            except Exception as e:  # noqa: BLE001
                rec = dict(cand, status="error",
                           error=f"{type(e).__name__}: {e}")
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            print(rec.get("status"), rec.get("jis", ""), ep,
                  rec.get("corpus_docs", ""), flush=True)
            time.sleep(0.3)
    reg = {}
    for l in CENSUS_PATH.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("status") in ("verified", "known_pilot") and r.get("jis"):
            prev = reg.get(r["jis"])
            if prev is None or (r.get("corpus_docs") or 0) > (prev.get("corpus_docs") or 0):
                reg[r["jis"]] = r
    REGISTRY_PATH.write_text(json.dumps(reg, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    print(f"census done: {len(reg)} verified tenants in registry")


if __name__ == "__main__":
    main()
