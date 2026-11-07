"""Section splitter for ZA by-law texts. split(text) -> list of (start, end, label, record_type) covering text exactly
(no gaps, no overlaps), so ''.join(text[s:e]) == text. Headings: numbered sections '12.' / '12 Title' at line start that
form the longest +1 chain from 1 (table-of-contents chains are short in characters and lose to the body chain),
plus CHAPTER/PART/HOOFSTUK/DEEL and SCHEDULE/ANNEXURE/BYLAE/AANHANGSEL headings after the last section."""
import re

SEC = re.compile(r"(?m)^[ \t]*(?:(?:section|artikel)\s+)?(\d{1,3})\s*[\.\)]?[ \t]+(?=[A-Z\"“(‘'A-Za-z])([^\n]{0,160})$|^[ \t]*(\d{1,3})\.[ \t]*$", re.I)
SCHED = re.compile(r"(?m)^[ \t]*(SCHEDULE|ANNEXURE|ANNEX|APPENDIX|BYLAE|AANHANGSEL|ADDENDUM)\b[^\n]{0,80}$")


def _chains(cands):
    chains = []
    for pos, n in cands:
        placed = False
        for ch in chains:
            if n == ch[-1][1] + 1 and pos > ch[-1][0]:
                ch.append((pos, n)); placed = True; break
        if not placed and n == 1:
            chains.append([(pos, n)])
    return chains


def split(text, min_sections=2):
    L = len(text)
    cands = []
    for m in SEC.finditer(text):
        n = int(m.group(1) or m.group(3))
        line = m.group(0)
        if len(line.strip()) > 170: continue
        cands.append((m.start(), n))
    best = None
    for ch in _chains(cands):
        if len(ch) < min_sections: continue
        # span of a chain: from its first heading to the next chain's start / text end; prefer long spans, many sections
        span = (ch[-1][0] - ch[0][0]) + 1
        avg = span / len(ch)
        key = (len(ch) >= 3 and avg > 120, span, len(ch))
        if best is None or key > best[0]: best = (key, ch)
    if best is None:
        return [(0, L, "document", "document")]
    ch = best[1]
    if ch[-1][0] - ch[0][0] < 80 * len(ch):  # looks like a table of contents only
        return [(0, L, "document", "document")]
    out = []
    if ch[0][0] > 0:
        out.append((0, ch[0][0], "preamble", "preamble"))
    starts = [p for p, _ in ch] + [L]
    # schedules after the last section heading
    tail_scheds = [m.start() for m in SCHED.finditer(text, ch[-1][0] + 1)]
    tail_scheds = [p for p in tail_scheds if p - ch[-1][0] > 200]
    kept = []
    for p in tail_scheds:   # a schedule part must be >= 400 chars, else it stays inside the previous part
        if not kept or p - kept[-1] >= 400: kept.append(p)
    if kept and L - kept[-1] < 400: kept.pop()
    tail_scheds = kept[:25]
    for i, (p, n) in enumerate(ch):
        end = starts[i + 1]
        if i == len(ch) - 1 and tail_scheds:
            end = tail_scheds[0]
        out.append((p, end, str(n), "article"))
    if tail_scheds:
        bounds = tail_scheds + [L]
        for k in range(len(tail_scheds)):
            out.append((bounds[k], bounds[k + 1], f"schedule-{k + 1}", "schedule"))
    # sanity: exact cover
    assert out[0][0] == 0 and out[-1][1] == L and all(out[i][1] == out[i + 1][0] for i in range(len(out) - 1)), "split cover"
    return [o for o in out if o[1] > o[0]]
