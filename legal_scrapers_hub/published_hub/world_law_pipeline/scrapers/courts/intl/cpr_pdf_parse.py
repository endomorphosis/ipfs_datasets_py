"""Generic parser for Commonwealth-Caribbean style CPR PDFs numbered Part.Rule (e.g. 'Rule 26.3'), via pdftotext -layout.
parse(pdf_path, junk=[regex,...]) -> list of dicts {part, part_title, rule, title, text}."""
import re, subprocess
def pdftext(pdf): return subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True).stdout
def parse(pdf, junk=(), max_gap=3, blocks=()): return parse_text(pdftext(pdf), junk, max_gap, blocks)
def parse_text(txt, junk=(), max_gap=3, blocks=()):
    J = [re.compile(j) for j in junk]
    L0 = txt.splitlines(); drop = set()
    for bs, be in blocks:  # drop running footer/header blocks: from a line matching bs up to (not incl.) the next line matching be, max 15 lines
        for i, l in enumerate(L0):
            if re.search(bs, l):
                for k in range(i, min(i + 15, len(L0))):
                    if k > i and re.search(be, L0[k]): break
                    drop.add(k)
    L = [l for i, l in enumerate(L0) if i not in drop and not any(j.search(l) for j in J)]
    # margin notes (e.g. 'S.I. 2001     58.10 The forms') -> strip the margin prefix
    L = [re.sub(r"^\S.{0,26}?\s{3,}(?=\d{1,2}\.\d{1,3}[\s–-]+\S)", "  ", l) for l in L]
    st = [i for i, l in enumerate(L) if re.fullmatch(r"\s*(Part|PART) 1\s*", l)]
    b0 = st[0] if st else 0
    parts = {}
    for i in range(b0, len(L)):
        m = re.fullmatch(r"\s*(?:Part|PART) (\d+)\s*", L[i])
        if m:
            t = [x.strip() for x in L[i + 1:i + 6] if x.strip() and not set(x.strip()) <= set("_-")][:1]
            parts.setdefault(int(m.group(1)), t[0] if t else None)
    cand, prev = [], (0, 0)
    for i in range(b0, len(L)):
        m = re.match(r"^\s{0,24}(\d{1,2})\.(\d{1,3})(?:[\s–-]+\S|\s*$)", L[i])
        if not m or re.search(r"Rule\s+\d+\.\d+\s*$", L[i]): continue
        if re.fullmatch(r"\s*\d{1,2}\.\d{1,3}\s*", L[i]): continue
        k = (int(m.group(1)), int(m.group(2)))
        if (k[0] == prev[0] and 0 < k[1] - prev[1] <= max_gap) or (0 < k[0] - prev[0] <= 2 and k[1] == 1):
            cand.append((i, k)); prev = k
    def isnum(s): return re.fullmatch(r"[0-9ivxlcA-Z]{1,5}", s) is not None
    out = []
    for j, (i, k) in enumerate(cand):
        end = cand[j + 1][0] if j + 1 < len(cand) else len(L)
        blk = []
        for x in L[i:end]:
            s = x.strip()
            if not s or isnum(s) or set(s) <= set("_-"): continue
            if re.fullmatch(r"(Part|PART) \d+", s) or re.match(r"(Appendix|Schedule|SCHEDULE|APPENDIX|FORM \d+\s*$)", s): break
            blk.append(s)
        back = [x.strip() for x in L[max(b0, i - 5):i] if x.strip() and not isnum(x.strip()) and not set(x.strip()) <= set("_-")]
        title = back[-1] if back and len(back[-1]) < 140 and not re.match(r"^\(", back[-1]) and not back[-1].endswith((";", ",", "-", ":")) and not re.search(r"Rule\s+\d+\.\d+\s*$", back[-1]) else None
        if j + 1 < len(cand) and blk:
            nb = [x.strip() for x in L[cand[j + 1][0] - 5:cand[j + 1][0]] if x.strip()]
            if nb and blk[-1] == nb[-1]: blk = blk[:-1]
        out.append({"part": k[0], "part_title": parts.get(k[0]), "rule": f"{k[0]}.{k[1]}", "title": title, "text": re.sub(r"\s+", " ", " ".join(blk)).strip()})
    return out
