import re
_LEAD_SP = re.compile(rb"([\xc2-\xdf]|[\xe0-\xef][\x80-\xbf]) ")  # NBSP (0xA0) continuation saved as space
def fix_text(t: str) -> str:
    if not t or not re.search("Ã[\x80-\xbf]|Ä[\x80-\xbf]|Å[\x80-\xbf ]|Â§", t):
        return t or ""
    try:
        b = t.encode("latin-1")
    except UnicodeEncodeError:
        return t
    b = _LEAD_SP.sub(lambda m: m.group(1) + b"\xa0", b)
    return b.decode("utf-8", errors="replace").replace("\xa0", " ")
