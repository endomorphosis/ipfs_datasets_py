"""2026-11-04: resolve "X জেলার/জেলাধীন Y পৌরসভা|সিটি কর্পোরেশন|উপজেলা|ইউনিয়ন" titles to the sub-body Y inside district X.
Uses BD candidate places (global_municipalities_candidate.csv) with Bengali Wikidata labels and P131 ancestors (bd_gazette caches).
(codes/place_codes.parquet has no BD rows / names, so it cannot be used.) rematch() returns None if the title has no
district-of pattern (caller falls back), '' if the pattern exists but no unique confident match, else the qid."""
import re, unicodedata
def U(x): return unicodedata.normalize("NFC", x) if isinstance(x, str) else x  # ড়/ঢ়/য় precomposed vs nukta forms
BODY = [("union", r"ইউনিয়ন(?:\s*পরিষদ)?"), ("municipality", r"পৌরসভা|সিটি\s*কর্পোরেশন"), ("district", r"উপজেলা")]  # most specific first
STRIP = re.compile(r"\s*(পৌরসভা|সিটি কর্পোরেশন|ইউনিয়ন পরিষদ|ইউনিয়ন|জেলা|উপজেলা|সদর|বিভাগ)\s*$")
DIST = re.compile(r"([\u0980-\u09FF]+)\s*জেলা(?:র|ধীন|াধীন)")
W = r"([\u0980-\u09FF]+(?:[\s\-][\u0980-\u09FF]+)?)\s*"
def norm(s):
    s = s.strip()
    while STRIP.search(s) and STRIP.sub("", s).strip() != s: s = STRIP.sub("", s).strip()
    return s
def rematch(title, P):
    title = U(title)
    m = DIST.search(title)
    if not m: return None
    X = m.group(1); rest = title[m.end():]
    for lvl, rx in BODY:
        ms = list(re.finditer(W + "(?:" + rx + ")", rest))
        # lists ("A, B ও C উপজেলার") name several bodies -> not one place
        if any(re.search(r"(?:^|\s)(?:ও|এবং)(?:\s|$)|,", m.group(1)) or re.search(r"(?:,|\sও|\sএবং)\s*$", rest[:m.start()]) for m in ms): return ""
        ys = [m.group(1) for m in ms]
        ys = [norm(re.sub(r"^.*?(?:জেলার|উপজেলার|ও|এবং|,)\s+", "", y)) for y in ys]
        ys = {y for y in ys if y and not re.search(r"নির্বাচন|পরিষদ|সরকার|স্থানীয়|শ্রেণি", y)}
        if not ys: continue
        if len(ys) > 1: return ""
        y = ys.pop(); words = y.split()
        cands = set(); loose = set()
        for p in P:
            if p["level"] != lvl or p["qid"] is None: continue
            if re.search(r"\bDistrict$|^Chapai Nawabganj$", str(p["name"])) and lvl == "district": continue  # the zila itself, not an upazila
            cores = []; anc = [U(x) for x in p["anc"]]; noanc = not anc
            for c in map(U, p["cores"]):  # labels like "পীরগঞ্জ পৌরসভা, ঠাকুরগাঁও" -> core + qualifier (treated as an ancestor)
                if "," in c: c, q = c.split(",", 1); anc.append(norm(q.strip(" ()"))); c = norm(c)
                cores.append(norm(c))
            if not any(c == y or (len(words) == 2 and c == words[-1]) for c in cores): continue
            if X in anc or any(a.startswith(X) for a in anc): cands.add(p["qid"])
            elif noanc: loose.add(p["qid"])
        if len(cands) > 1:  # prefer exact full-name core
            ex = {q for q in cands if y in next(p for p in P if p["qid"] == q)["cores"]}
            cands = ex if len(ex) == 1 else cands
        if not cands and len(loose) == 1: cands = loose  # place has no P131 data: accept only if its name is unique nationwide for that body type
        return next(iter(cands)) if len(cands) == 1 else ""
    return None
