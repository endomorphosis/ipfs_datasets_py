"""Robots meta check for archived pages (coordinator rule 2026-10-10: skip archived pages whose
<meta name="robots"/"googlebot"/... content> carries noarchive or noindex; log each skip).
PDFs/binaries -> no flags."""
import re

_META = re.compile(rb"<meta\b[^>]*>", re.I)
_NAME = re.compile(rb"""\bname\s*=\s*["']?\s*([a-z0-9_.-]+)""", re.I)
_CONTENT = re.compile(rb"""\bcontent\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
BOTS = {b"robots", b"googlebot", b"bingbot", b"ia_archiver", b"archive.org_bot", b"ccbot", b"slurp"}
FLAGS = ("noarchive", "noindex")


def robots_meta_flags(body, x_robots_tag=None, content_type=""):
    found = set()
    if x_robots_tag:
        parts = {p.strip() for p in x_robots_tag.lower().split(",")}
        found |= {f for f in FLAGS if f in parts} | ({"noindex", "noarchive"} if "none" in parts else set())
    if not body or "pdf" in (content_type or "").lower() or body[:5] == b"%PDF-":
        return sorted(found)
    for m in _META.finditer(body[:300000]):
        tag = m.group(0)
        n = _NAME.search(tag)
        if not n or n.group(1).lower() not in BOTS:
            continue
        c = _CONTENT.search(tag)
        if not c:
            continue
        val = (c.group(1) or c.group(2) or c.group(3) or b"").lower().replace(b" ", b"")
        parts = set(val.split(b","))
        if b"none" in parts:
            found |= {"noindex", "noarchive"}
        for f in FLAGS:
            if f.encode() in parts:
                found.add(f)
    return sorted(found)


def policy_for(flags):
    if "noarchive" in flags:
        return "noarchive_meta"
    if "noindex" in flags:
        return "noindex_meta"
    return None
