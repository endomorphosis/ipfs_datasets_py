"""asia_latam robots.txt policy switch (owner policy 2026-11-01 12:14 PT: legal texts are fetched even where robots.txt
disallows). Reversible: RESPECT_ROBOTS=1 in the environment, or {"respect_robots": true} in common/robots_policy.json.
Still in force regardless: per-host delays / Crawl-delay, the shared archive ratelimit, honest UA, no WAF/captcha
bypass, no proxies. Disallowed URLs that are fetched anyway are remembered here so records can carry an honest
source_policy (TAG) instead of robots_allowed_rfc9309. robots meta noarchive/noindex: tag, never skip."""
import json, os, threading
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse

TAG = "robots_ignored_owner_policy_20261101"
_CFG = Path(__file__).resolve().parent / "robots_policy.json"


def _respect():
    v = os.environ.get("RESPECT_ROBOTS")
    if v is not None:
        return v.strip().lower() in ("1", "true", "yes", "on")
    try:
        return bool(json.loads(_CFG.read_text()).get("respect_robots", False))
    except (OSError, ValueError):
        return False          # default since 2026-11-01: do not respect robots.txt disallow


RESPECT = _respect()
_lock = threading.Lock()
_urls = OrderedDict()   # url -> reason (bounded)
_hosts = {}             # host -> reason (robots unreachable / disallow-all treated as allow under the owner policy)


def note(url, reason="robots_disallow"):
    url = url.split("#", 1)[0]
    with _lock:
        _urls[url] = reason
        _urls.move_to_end(url)
        while len(_urls) > 200_000:
            _urls.popitem(last=False)


def note_host(host, reason):
    with _lock:
        _hosts[host.lower()] = reason


def ignored(url):
    """Reason string if this URL (or its host) was robots-disallowed/unreachable and fetched anyway, else None."""
    if not url:
        return None
    url = url.split("#", 1)[0]          # page-range splits (…pdf#page=7) refer to the fetched file
    r = _urls.get(url)
    if r:
        return r
    return _hosts.get(urlparse(url).netloc.lower())


def policy(url, default):
    """source_policy for a record fetched from `url`."""
    return TAG if ignored(url) else default


def fields(url, default=None):
    """Extra record fields: {} if robots allowed it; else source_policy=TAG + robots_txt_disallowed + reason."""
    r = ignored(url)
    if not r:
        return {} if default is None else {"source_policy": default}
    return {"source_policy": TAG, "robots_txt_disallowed": True, "robots_ignored_reason": r[:120]}
