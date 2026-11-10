#!/usr/bin/env python3
"""German Landesrecht densify collector (ipfs_germany_laws, append DE-<Land> rows). robots_guard fail-closed. Resumable.

Usage: collect_de_laender.py --land SN|BB|NW|NI|HB [--tag T] [--kinds law,vwv,bek[,amending]] [--existing-ids FILE]
  SN: REVOSax sitemap (law/vwv/bek, then --tag amending --kinds amending). BB: BRAVORS VwV (chronological year lists, 20 s).
  NW: --tag delta: recht.nrw.de sitemap URLs with lastmod after the tip harvest; --tag bek / --tag vwv: every
      Bekanntmachung / Verwaltungsvorschrift URL (none of those types is on the tip), whatever its lastmod.
      delta: (LANDS NW since); a page whose law id is already on the tip
      is kept as a record with tip_update=true and is NOT packed unless pack_de.py build --include-updates.
  NI: NI-VORIS alphabetical browse tree (law node -> head + article documents). HB: transparenz.bremen.de in-force lists.
  NI and HB need $DE_WORK/LICENCE_GO_NDS_HB (user decision) -> otherwise exit 5 before any request.
Work dir: $DE_WORK/<land>[_<tag>].
Every request (and every redirect hop, via robots_guard.GuardedSession) is robots-checked; an off-host or off-scope hop
stops the run. Spacing per host = max(land min_delay, robots Crawl-delay) (BB: 20 s).
Exit: 0 slice/done, 5 licence flag missing (NI/HB), 2 robots (disallow, or 3rd consecutive robots.txt network failure), 3 land disabled,
4 memory (<3 GiB for 15 s) / RSS > 1 GiB, 6 host park (401/403/429/challenge -> work/PARKED_host), 143 SIGTERM.
Output: work/<land>/records/<id>.json  ({"law": row, "articles": [...], "pii_hits": n, "bounds": [...]}); raw pages: $DE_PAGE_CACHE/<land>[_<tag>]/<rid>.html.gz
"""
import argparse, json, os, re, signal, sys, threading, time
from pathlib import Path

import requests
import urllib3

BASE_WORK = Path(os.environ.get("DE_WORK", "/workspace/de_laender/work"))
os.environ["LEGAL_CORPORA_ROOT"] = os.environ.get("DE_GUARD_ROOT", str(BASE_WORK.parent / "guard_root"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import de_lib as L  # noqa: E402
import robots_guard as RG  # noqa: E402

PAGE_CACHE = Path(os.environ.get("DE_PAGE_CACHE", str(BASE_WORK.parent / "page_cache")))
SLICE_S = int(os.environ.get("DE_SLICE_SECONDS", "1680"))
RSS_CAP_MB = 1024
MAX_ROBOTS_TLS = 3
RC_ROBOTS, RC_DISABLED, RC_MEM, RC_LICENCE, RC_HOST_PARK = 2, 3, 4, 5, 6
STOP = {"sig": False}
CHAL = re.compile(r"just a moment|cf-browser-verification|challenge-platform|captcha|checking your browser|attention required|request rejected|access denied", re.I)


SITE_MARK = {"SN": ("REVOSax",), "BB": ("Vorschriftensystem", "BRAVORS"), "NW": ("recht.nrw.de",), "NI": ("NI-VORIS",),
             "HB": ("transparenz.bremen", "KOGIS")}


class HostStop(RuntimeError):
    pass


class Transient(RuntimeError):
    pass


class RobotsTLS(RuntimeError):
    pass


def _meminfo(key):
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith(key):
                return int(line.split()[1]) // 1024
    return 0


def rss_mib():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    return 0


def lane_tree_mb(root):
    tot = 0
    for dp, _, fs in os.walk(root):
        for f in fs:
            try:
                tot += os.lstat(os.path.join(dp, f)).st_size
            except OSError:
                pass
    return tot // (1024 * 1024)


def hard_floor_mib(root, last=[0.0, None]):
    """Hard-stop floor from the gate profile (env from gate_profile.sh); re-checks the lane tree every 60 s and falls back
    to the v2 floor (3072) once the tree is over the cap (300 MB)."""
    hard = int(os.environ.get("GATE_HARD_MIB", "3072"))
    if time.time() - last[0] >= 60 or last[1] is None:
        last[0] = time.time(); last[1] = lane_tree_mb(root) > int(os.environ.get("GATE_TREE_CAP_MB", "300"))
    return max(hard, int(os.environ.get("GATE_V2_HARD_MIB", "3072"))) if last[1] else hard


def start_guard():
    def run():
        low = None
        while True:
            if rss_mib() > RSS_CAP_MB:
                print("RSS cap", file=sys.stderr, flush=True); os._exit(RC_MEM)
            floor = hard_floor_mib(BASE_WORK)
            if _meminfo("MemAvailable:") < floor:
                low = low or time.time()
                if time.time() - low >= 15:
                    print(f"MemAvailable < {floor} MiB for 15 s", file=sys.stderr, flush=True); os._exit(RC_MEM)
            else:
                low = None
            time.sleep(1)
    threading.Thread(target=run, daemon=True).start()


def on_term(signum, frame):
    STOP["sig"] = True
    print("SIGTERM: stopping after the current item", flush=True)


NI_SKIP = ("093c6024-c9fe-430f-9f30-4f955cf72518", "b9b8008a-d0bc-4fc6-83a9-e6248182ad9b", "6c5b57fb-d0b6-49c9-b3e0-89e2a4e81639",
           "WKDE-LTR-VORIS-DOCS-PHC")  # parent / systematic catalogue / case-law branches: alphabetical tree only


class Lane:
    def __init__(self, land, kinds, existing, tag=""):
        self.land, self.cfg, self.tag = land, L.LANDS[land], tag
        self.kinds, self.existing = kinds, existing
        self.work = BASE_WORK / (land.lower() + (f"_{tag}" if tag else ""))
        self.rec = self.work / "records"
        self.state_path = self.work / "state.json"
        self.parked = self.work / "PARKED_host"
        self.req_log = self.work / "requests.jsonl"
        # gz page cache (added 2026-10-17): re-parse offline after a parser fix instead of re-fetching. Kept OUTSIDE $DE_WORK so
        # it never counts toward the lane-tree gate cap (300 MB). Default /workspace/de_laender/page_cache/<land>[_<tag>].
        self.pages = PAGE_CACHE / self.work.name
        self.st = {"queue": {}, "done_ids": [], "ok": 0, "skipped_existing": 0, "bounds_rejects": 0, "pii_hits": 0, "errors": 0,
                   "text_bytes": 0, "requests": 0, "seeded": False, "done": False, "stop_reason": "", "robots_tls_run": 0,
                   "frontier": [], "seen_lists": [], "tip_updates": 0, "kind_filtered": 0}
        if self.state_path.exists():
            self.st.update(json.loads(self.state_path.read_text()))

    def save(self):
        self.work.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.st, ensure_ascii=False)); tmp.replace(self.state_path)

    def allowed(self, url):
        return L.path_allowed(self.land, url)

    def fetch(self, s, url, kind):
        if not self.allowed(url):
            raise RG.RobotsDisallowed(f"out of scope {url}", None)
        d = RG.check(url)
        if d.robots_status == "unavailable" and int(getattr(d, "robots_http_status", 0) or 0) == 0:
            raise RobotsTLS(f"{d.reason} {url}")
        if not d.allowed or d.robots_status == "unavailable":
            raise RG.RobotsDisallowed(f"{d.reason} {url} ({d.rule})", d)
        s.min_interval = max(self.cfg["min_delay"], float(d.crawl_delay or 0))
        r, last = None, None
        for attempt in range(4):
            try:
                r = s.get(url, timeout=(25, 120), allow_redirects=True, stream=True); break
            except RG.RobotsBlocked:
                raise
            except requests.RequestException as exc:
                last = exc; time.sleep(15)
        if r is None:
            raise Transient(str(last))
        try:  # a connection dropped mid-body is transient, not a crash (urllib3 ProtocolError is not a RequestException)
            body = r.raw.read(L.BOUNDS["max_page_bytes"] + 1, decode_content=True) or b""
        except (requests.RequestException, urllib3.exceptions.HTTPError, OSError) as exc:
            r.close(); raise Transient(f"body read failed {url}: {exc}")
        head = body[:6000].decode("utf-8", "replace")
        challenge = bool(CHAL.search(head) and not any(m in head for m in SITE_MARK.get(self.land, ())))
        with self.req_log.open("a") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": kind, "url": url, "final": r.url,
                                "status": r.status_code, "bytes": len(body), "challenge": challenge}) + "\n")
        if r.status_code in (401, 403, 429) or challenge:
            raise HostStop(f"{r.status_code} {url} challenge={challenge}")
        if not self.allowed(r.url):
            raise HostStop(f"redirect off scope {url} -> {r.url}")
        if len(body) > L.BOUNDS["max_page_bytes"]:
            raise Transient(f"page over bound {url}")
        if r.status_code != 200:
            raise Transient(f"http {r.status_code} {url}")
        self.st["requests"] += 1; self.st["robots_tls_run"] = 0
        return body.decode(r.encoding or "utf-8", "replace")

    def cache_page(self, rid, page):
        """Keep the raw fetched page (gzip) so a later parser fix re-parses it offline instead of re-fetching."""
        import gzip
        self.pages.mkdir(parents=True, exist_ok=True)
        tmp = self.pages / f".{rid}.html.gz.tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            f.write(page)
        tmp.replace(self.pages / f"{rid}.html.gz")

    def fetch_page(self, s, rid, url, kind="law"):
        page = self.fetch(s, url, kind)
        self.cache_page(rid, page)
        return page

    # ------------------------------------------------------------ seeding (resumable frontier of listing pages)
    def _q(self, key, url, kind, **extra):
        if kind not in self.kinds:
            self.st["kind_filtered"] += 1; return
        if L.law_id(self.land, key) in self.existing:
            self.st["skipped_existing"] += 1; return
        if key not in self.st["queue"] and key not in self.st["done_ids"]:
            self.st["queue"][key] = dict(extra, url=url, kind=kind)

    def seed(self, s, t0):
        land, cfg = self.land, self.cfg
        if land == "SN":
            sm = L.parse_sn_sitemap(self.fetch(s, cfg["seed"], "sitemap"))
            for rid, v in sorted(sm.items(), key=lambda kv: int(kv[0])):
                self._q(rid, v["url"], v["kind"])
            return self._seeded()
        if not self.st["frontier"] and not self.st["seen_lists"]:
            if land == "HB":
                self.st["frontier"] = [cfg["seed"].format(cat=c, skip=0) for c in cfg["categories"]]
            else:
                self.st["frontier"] = [cfg["seed"]]
        seen = set(self.st["seen_lists"])
        while self.st["frontier"]:
            if STOP["sig"] or time.time() - t0 > SLICE_S:
                self.save(); return self.end(143 if STOP["sig"] else 0)
            u = self.st["frontier"].pop(0)
            if u in seen:
                continue
            try:
                page = self.fetch(s, u, "list")
            except Transient as e:
                lf = self.st.setdefault("list_fail", {}); lf[u] = lf.get(u, 0) + 1; self.st["errors"] += 1
                print("transient list", e, flush=True)
                if lf[u] < 3:
                    self.st["frontier"].append(u)
                self.save(); continue
            seen.add(u); self.st["seen_lists"].append(u)
            if land == "BB":
                for y in L.parse_bb_years(page):
                    if y not in seen and y not in self.st["frontier"]:
                        self.st["frontier"].append(y)
                for key, v in L.parse_bb_vv_list(page).items():
                    self._q(key, v["url"], v["kind"])
            elif land == "NW":
                for sm in L.parse_nw_sitemap_index(page):
                    if sm not in seen and sm not in self.st["frontier"] and sm != u:
                        self.st["frontier"].append(sm)
                for url, lm, typ in L.parse_nw_sitemap(page, L.nw_since(self.tag)):
                    self._q(url.rstrip("/").rsplit("/", 1)[1][:120], url, L.NW_KIND[typ], lastmod=lm)
            elif land == "HB":
                total, docs = L.parse_hb_list(page)
                for did, mu in docs:
                    self._q(did, mu, "law")  # kind decided after the fetch (title); all kinds wanted for HB
                m = re.search(r"skip=(\d+)$", u)
                if m and m.group(1) == "0":
                    for sk in range(50, total, 50):
                        nu = u[: m.start(1)] + str(sk)
                        if nu not in seen and nu not in self.st["frontier"]:
                            self.st["frontier"].append(nu)
            elif land == "NI":
                kids, docs = L.parse_ni_browse(page)
                for ku, lab in kids:
                    if any(x in ku for x in NI_SKIP):
                        continue
                    if L.is_ni_law_node(lab):
                        key = ku.rsplit("%23", 1)[-1][:40]
                        self._q(key, ku, "law", label=lab)
                    elif re.fullmatch(r"[A-ZÄÖÜ0-9][a-zäöüß0-9]?", lab) and ku not in seen and ku not in self.st["frontier"]:
                        self.st["frontier"].append(ku)
            self.save()
        if not self.st["seen_lists"]:  # seed listing unreachable 3x -> park the sub-lane instead of a false done
            raise HostStop("seed listing unreachable after 3 attempts")
        return self._seeded()

    def _seeded(self):
        self.st["seeded"] = True; self.save()
        print(f"seeded {len(self.st['queue'])} (skipped on Hub {self.st['skipped_existing']}, other kinds {self.st['kind_filtered']})", flush=True)
        return None

    # ------------------------------------------------------------ one item -> info dict (None = interrupted)
    def item(self, s, rid, v, t0):
        land = self.land
        if land == "SN":
            info = L.parse_sn_page(self.fetch_page(s, rid, v["url"]), v["url"])
        elif land == "BB":
            info = L.parse_bb_page(self.fetch_page(s, rid, v["url"]), v["url"])
        elif land == "NW":
            info = L.parse_nw_page(self.fetch_page(s, rid, v["url"]), v["url"]); info["lastmod"] = v.get("lastmod")
        elif land == "HB":
            info = L.parse_hb_page(self.fetch_page(s, rid, v["url"]), v["url"], rid)
        elif land == "NI":
            part = self.work / "partial" / f"{rid}.json"; part.parent.mkdir(parents=True, exist_ok=True)
            pc = json.loads(part.read_text()) if part.exists() else {"docs": None, "got": {}}
            if pc["docs"] is None:
                _, docs = L.parse_ni_browse(self.fetch(s, v["url"], "law_node"))
                pc["docs"] = [u for u, _ in docs]; part.write_text(json.dumps(pc))
            if not pc["docs"]:
                raise Transient(f"no documents under {v['url']}")
            if len(pc["docs"]) > L.BOUNDS["max_sections_per_law"]:
                raise Transient(f"law node over section bound {v['url']}")
            for du in pc["docs"]:
                if du in pc["got"]:
                    continue
                if STOP["sig"] or time.time() - t0 > SLICE_S:
                    return None
                d = L.parse_ni_doc(self.fetch(s, du, "doc"))
                pc["got"][du] = d or {"uid": du.rsplit("/", 1)[1], "heading": "", "bib": {}, "text": ""}
                part.write_text(json.dumps(pc, ensure_ascii=False))
            info = L.ni_assemble(v.get("label", ""), [(u, pc["got"][u]) for u in pc["docs"]])
            info["node_url"] = v["url"]; part.unlink()
        else:
            raise Transient(f"no adapter {land}")
        info["kind"] = v["kind"] if land in ("SN", "BB", "NW") else L._kind_from_title(info.get("title"))
        return info

    def record(self, rid, v, info):
        url = info.get("node_url") or v["url"]
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        bad = L.check_bounds(info)
        law, arts, hits = L.make_rows(self.land, info, url, ts)
        tip_update = law["id"] in self.existing
        if tip_update and self.land != "NW":
            self.st["skipped_existing"] += 1; return
        if info["kind"] not in self.kinds and self.land in ("NI", "HB"):
            self.st["kind_filtered"] += 1; return
        out = {"law": law, "articles": arts, "pii_hits": len(hits), "bounds": bad, "kind": info["kind"], "tip_update": tip_update}
        for k in ("lastmod", "valid_from", "portal_label", "normtyp"):
            if info.get(k):
                out[k] = info[k]
        (self.rec / f"{law['id']}.json").write_text(json.dumps(out, ensure_ascii=False))
        if tip_update:
            self.st["tip_updates"] += 1
        elif bad:
            self.st["bounds_rejects"] += 1
        else:
            self.st["ok"] += 1; self.st["text_bytes"] += len(law["text"].encode())
        self.st["pii_hits"] += len(hits)

    def end(self, rc, reason=""):
        if reason:
            self.st["stop_reason"] = reason
        self.save()
        print("slice end", json.dumps({k: self.st[k] for k in ("ok", "skipped_existing", "bounds_rejects", "pii_hits", "errors",
                                                               "requests", "tip_updates", "done", "stop_reason")}), flush=True)
        return rc

    def run(self):
        if self.parked.exists():
            print("PARKED_host present; not fetching", flush=True); return RC_HOST_PARK
        if self.st["done"]:
            print("already done", flush=True); return 0
        self.rec.mkdir(parents=True, exist_ok=True)
        RG.set_country("de")
        s = RG.GuardedSession()
        s.headers.update({"User-Agent": RG.ROBOTS_UA, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.5"})
        t0 = time.time()
        cur = None
        try:
            if not self.st["seeded"]:
                r = self.seed(s, t0)
                if r is not None:
                    return r
            done = set(self.st["done_ids"])
            for rid in list(self.st["queue"]):
                if STOP["sig"] or time.time() - t0 > SLICE_S:
                    return self.end(143 if STOP["sig"] else 0)
                if self.st["ok"] >= L.BOUNDS["max_laws_per_slice_pack"] or self.st["text_bytes"] >= L.BOUNDS["max_text_bytes"]:
                    self.st["done"] = True; return self.end(0, "cap")
                v = self.st["queue"][rid]; cur = rid
                if rid in done:
                    self.st["queue"].pop(rid); continue
                try:
                    info = self.item(s, rid, v, t0)
                except Transient as e:
                    print("transient", e, flush=True); self.st["errors"] += 1
                    self.st["done_ids"].append(rid); self.st["queue"].pop(rid); self.save(); continue
                if info is None:  # interrupted mid-item (NI partial cache kept) -> resume next slice
                    return self.end(143 if STOP["sig"] else 0)
                self.record(rid, v, info)
                self.st["done_ids"].append(rid); self.st["queue"].pop(rid); cur = None; self.save()
            self.st["done"] = True
            return self.end(0, "complete")
        except RobotsTLS as e:
            self.st["robots_tls_run"] += 1
            print("robots.txt network failure", self.st["robots_tls_run"], e, flush=True)
            return self.end(RC_ROBOTS, "robots") if self.st["robots_tls_run"] >= MAX_ROBOTS_TLS else self.end(0)
        except RG.RobotsBlocked as e:
            return self.end(RC_ROBOTS, f"robots: {str(e)[:200]}")
        except HostStop as e:
            self.parked.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {str(e)[:300]}\n")
            return self.end(RC_HOST_PARK, "host_stop")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--land", required=True, choices=sorted(L.LANDS))
    ap.add_argument("--kinds", default="law,vwv,bek")
    ap.add_argument("--tag", default="", help="work sub-lane, e.g. amending -> $DE_WORK/sn_amending")
    ap.add_argument("--existing-ids", default=os.environ.get("DE_EXISTING_IDS", ""),
                    help="file of law ids already on the Hub tip (one per line); those are never fetched")
    a = ap.parse_args(argv)
    cfg = L.LANDS[a.land]
    if not cfg["enabled"]:
        print(f"land {a.land} disabled: {cfg.get('hold')}", flush=True); return RC_DISABLED
    if cfg.get("licence_gate") and not (BASE_WORK / L.LICENCE_FLAG).exists():
        print(f"land {a.land}: licence gate closed ({BASE_WORK / L.LICENCE_FLAG} missing); no request made", flush=True); return RC_LICENCE
    existing = set(Path(a.existing_ids).read_text().split()) if a.existing_ids else set()
    if not existing:
        print("refusing to run without --existing-ids (Hub tip id list) to avoid refetching live rows", flush=True); return RC_DISABLED
    signal.signal(signal.SIGTERM, on_term)
    start_guard()
    return Lane(a.land, set(a.kinds.split(",")), existing, a.tag).run()


if __name__ == "__main__":
    sys.exit(main())
