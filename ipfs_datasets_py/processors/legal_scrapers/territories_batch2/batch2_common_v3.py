"""Shared helpers for Batch2 v3 sequential workers. 3.2 GiB MemAvailable floor.
Does NOT overwrite batch2_common.py (which hardcodes a 4.2 GiB startup gate meant
only for heavy persistent multi-collector daemons).
Zero deletes/overwrites; exclusive-create writes; TLS on; declared UA.
"""
from __future__ import annotations
import hashlib, json, pathlib, re, resource, sys, time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import requests

ROOT = pathlib.Path("/workspace/staging/territories_batch2_20261105")
UA = (
    "GrokBot-CountryLawCollector/1.0 "
    "(keyless official legislation; provenance archive; not model training)"
)
STOP_FLOOR_GIB = 3.2
RSS_CAP_MB = 250.0


def mem_available_gib() -> float:
    for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024 / 1024
    return 0.0


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def guard(label: str = "") -> None:
    m = mem_available_gib()
    rss = peak_rss_mb()
    if m < STOP_FLOOR_GIB:
        raise SystemExit(f"MEMORY_STOP_HOLD mem={m:.3f}GiB label={label}")
    if rss > RSS_CAP_MB:
        raise SystemExit(f"RSS_HOLD rss={rss:.1f}MB label={label}")


def install_guard() -> None:
    def no_delete(event, args):
        if event in ("os.remove", "os.rmdir", "os.unlink", "os.rename"):
            raise RuntimeError("ZERO_DELETE_REPLACE_GUARD")

    sys.addaudithook(no_delete)


def write_json_x(path, value) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.write("\n")


def write_text_x(path, text: str) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        f.write(text)


def copy_bytes_x(src: pathlib.Path, dest: pathlib.Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("xb") as f:
        f.write(src.read_bytes())


def sanitize_script(text: str) -> str:
    text = re.sub(r"\bhf_[A-Za-z0-9]{16,}\b", "REDACTED_HF_TOKEN", text)
    text = re.sub(
        r"/home/box/agent-data/connector-secrets/[^\s\"')\]]+",
        "CREDENTIAL_PATH_REMOVED",
        text,
    )
    return text


def copy_sanitized_script(src: pathlib.Path, dest: pathlib.Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("x", encoding="utf-8") as f:
        f.write(sanitize_script(src.read_text(encoding="utf-8", errors="replace")))


class Polite:
    def __init__(self, hosts, min_delay: float = 2.5):
        self.hosts = set(hosts)
        self.last = {}
        self.delay = {}
        self.min_delay = min_delay
        self.policies = {}
        self.hold = set()
        self.strikes = {}
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA

    def request(self, url: str, robots: bool = False):
        guard("request")
        host = urlparse(url).netloc
        if urlparse(url).scheme != "https" or host not in self.hosts or host in self.hold:
            raise ValueError("TLS_HOST_OR_ACCESS_HOLD")
        if not robots:
            if host not in self.policies:
                self.setup(f"https://{host}/")
            if not self.policies[host].can_fetch(UA, url):
                raise ValueError("ROBOTS_HOLD")
        delay = max(self.min_delay, self.delay.get(host, self.min_delay))
        time.sleep(max(0.0, delay - (time.monotonic() - self.last.get(host, 0.0))))
        self.last[host] = time.monotonic()
        r = self.session.get(url, timeout=(12, 45), verify=True, allow_redirects=False, stream=True)
        body = bytearray()
        for chunk in r.iter_content(65536):
            body.extend(chunk)
            if len(body) > 16 * 1024**2:
                r.close()
                raise ValueError("SIZE_HOLD")
        r.close()
        body = bytes(body)
        challenge = bool(
            re.search(
                rb"<title[^>]*>[^<]*(just a moment|access denied|captcha|attention required)"
                rb"|cf-chl-|g-recaptcha|hcaptcha|verify you are human",
                body[:120000],
                re.I,
            )
        )
        record = {
            "requested_url": url,
            "status": r.status_code,
            "content_type": r.headers.get("Content-Type"),
            "location": r.headers.get("Location"),
            "sha256": hashlib.sha256(body).hexdigest(),
            "observed_local": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "challenge": challenge,
        }
        raw = ROOT / "evidence" / f'{record["sha256"]}.raw'
        raw.parent.mkdir(parents=True, exist_ok=True)
        if not raw.exists():
            with raw.open("xb") as f:
                f.write(body)
        record["raw_path"] = str(raw)
        log = ROOT / "evidence" / "requests_v3.jsonl"
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        if r.status_code in (403, 429, 503) or challenge:
            self.strikes[host] = self.strikes.get(host, 0) + 1
            if self.strikes[host] >= 3 or challenge:
                self.hold.add(host)
        return body, record

    def get(self, url: str, robots: bool = False):
        for _ in range(4):
            body, record = self.request(url, robots)
            if 300 <= record["status"] < 400 and record.get("location"):
                nxt = urljoin(url, record["location"])
                if urlparse(nxt).scheme != "https" or urlparse(nxt).netloc not in self.hosts:
                    return body, record
                url = nxt
                continue
            return body, record
        raise ValueError("REDIRECT_LIMIT_HOLD")

    def setup(self, url: str):
        host = urlparse(url).netloc
        body, record = self.get(f"https://{host}/robots.txt", True)
        rp = RobotFileParser()
        if record["status"] == 200:
            rp.parse(body.decode(errors="replace").splitlines())
        elif record["status"] == 404:
            rp.parse([])
        else:
            self.hold.add(host)
            raise ValueError(f"ROBOTS_UNAVAILABLE_{record['status']}")
        self.policies[host] = rp
        crawl = rp.crawl_delay(UA) or rp.crawl_delay("*") or 0
        self.delay[host] = max(self.min_delay, float(crawl or 0))
        return record
