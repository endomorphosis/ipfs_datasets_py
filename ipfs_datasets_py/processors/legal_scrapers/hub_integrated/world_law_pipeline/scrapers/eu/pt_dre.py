#!/usr/bin/env python3
"""Portugal: Diário da República, 2.ª série, Parte H (Autarquias locais) - municipal regulatory acts.

Static official sources only (no use of the OutSystems JS app or its internal API):
  whole-issue PDFs  https://files.diariodarepublica.pt/gratuitos/2s/<YYYY>/<MM>/2S<NNN>A0000S<SS>.pdf
                    (NNN = issue number, SS = 00 main issue, 01.. supplements). Probed with HEAD: 200 = exists,
                    301 -> /dr/error = does not exist. Parte H (autarquias locais) exists from 2007; before that municipal
                    acts were in numbered appendices (not parsed here).
  daily RSS         https://files.diariodarepublica.pt/rss/serie2&parte=h-html.xml  (only the latest issue; links go to
                    the JS app, so it is used only as a "new issue published" signal in forward mode).
robots.txt: files.diariodarepublica.pt/robots.txt and diariodarepublica.pt/robots.txt redirect to the app's error page
(no robots file) -> nothing disallowed (RFC 9309, checked per request via common/rfc9309.py).
Rights: official acts are excluded from copyright protection (Código do Direito de Autor, art. 7.º); free public access.

Parsing: pdftotext (reading order) -> acts are segmented at the 9-digit DR publication id that ends every act; the issuer
heading (MUNICÍPIO DE X / FREGUESIA DE Y / ...) and the act title (Aviso n.º ..., Regulamento n.º ...) open each act.
Only local-authority issuers are kept, and only regulatory acts (regulamentos, posturas, planos, taxas, regimentos,
consultas públicas of draft regulations, ...); HR notices (concursos, mobilidade, nomeações, ...) are skipped.
Places: MUNICÍPIO / CÂMARA / ASSEMBLEIA MUNICIPAL / SMAS -> concelho (candidate via Wikidata pt labels + DICO).
FREGUESIA / UNIÃO DAS FREGUESIAS -> staged to _unmatched with freguesia qid/DICOFRE + parent concelho (no freguesia
places in the candidate list yet).
Usage: python3 pt_dre.py fetch [--from-year Y] [--to-year Y] [--limit-issues N] | test YYYY/MM/NNN[/SS] | all | status
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse
import csv
import gc
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402

FILES = "https://files.diariodarepublica.pt/gratuitos/2s"
RSS_H = "https://files.diariodarepublica.pt/rss/serie2&parte=h-html.xml"
STATE = STAGE / "_state" / "pt"
TMP = STATE / "tmp"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
DATA = Path(__file__).resolve().parent / "data"
FIRST_YEAR = 2007
log = get_logger("pt_dre")

TITLE = re.compile(r"^(?P<kind>Aviso|Edital|Regulamento|Deliberação|Despacho(?: normativo)?|Declaração de retificação|"
                   r"Declaração|Postura|Acordo|Contrato|Anúncio|Listagem|Protocolo|Retificação|Louvor|Parecer|Decisão|"
                   r"Resolução|Alvará|Mapa|Relatório|Norma|Instrução|Extrato|Ata)(?P<ext> \(extrato\))?"
                   r"(?: n\.º (?P<num>[\w\-/.]+))?\s*$")
ISSUER = re.compile(r"^(MUNIC[IÍ]PIO|C[AÂ]MARA MUNICIPAL|ASSEMBLEIA MUNICIPAL|SERVI[CÇ]OS MUNICIPALIZADOS|"
                    r"FREGUESIA|JUNTA DE FREGUESIA|UNI[AÃ]O DAS FREGUESIAS|ASSEMBLEIA DE FREGUESIA)\b")
PUBID = re.compile(r"^\d{9}$")
NOISE = re.compile(r"^(\d+/\d+|2\.ª série|N\.º \d+|\d{2}-\d{2}-\d{4}|\d{1,6}|Diário da República, 2\.ª série.*|"
                   r"N\.º \d+ • .*|PARTE [A-L]( \|.*)?|Pág\. \d+)$")
REG = re.compile(r"regulament|postura|plano (diretor|de urbaniza|de pormenor|municipal|intermunicipal)|\bPDM\b|\btaxas?\b|"
                 r"tarif|c[oó]digo regulamentar|regimento|medidas preventivas|reabilita[cç][aã]o urbana|\bARU\b|"
                 r"estacionamento|tr[aâ]nsito|toponímia|hor[aá]rios? de funcionamento|normas? (municipa|de funcionamento|"
                 r"de utiliza|para)|estatutos?\b", re.I)
HR = re.compile(r"procedimento concursal|contrato de trabalho|mobilidade|per[ií]odo experimental|posicionamento remunerat|"
                r"nomea[cç][aã]o|lista (unit[aá]ria|de ordena)|aposenta|cessa[cç][aã]o|despedimento|delega[cç][aã]o de compet|"
                r"designa[cç][aã]o|louvor|licen[cç]a sem|recrutamento|consolida[cç][aã]o (definitiva )?da mobilidade|"
                r"exonera|j[uú]ri\b|regime de (?:teletrabalho|substitui)|disciplinar|acusa[cç][aã]o|notifica[cç][aã]o", re.I)


def fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s).split())


class Places:
    """concelho name -> candidate row (via Wikidata pt labels / DICO); freguesia name -> [(qid, dicofre, municipality)]."""

    def __init__(self):
        self.cand = {}
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] == "PT" and r["admin_level"] == "municipality":
                self.cand[r["qid"]] = r
        self.mun, self.dico = {}, {}
        for r in csv.DictReader((DATA / "wd_pt_municipios.csv").open(encoding="utf-8")):
            q = r["m"].rsplit("/", 1)[-1]
            if q in self.cand:
                self.mun.setdefault(fold(r["pt"]), set()).add(q)
                self.dico[q] = r["dico"] or None
        for q, r in self.cand.items():
            if fold(r["place_name"]) not in self.mun:
                self.mun.setdefault(fold(r["place_name"]), set()).add(q)
        self.freg = {}
        for r in csv.DictReader((DATA / "wd_pt_freguesias.csv").open(encoding="utf-8")):
            self.freg.setdefault(fold(r["pt"]), []).append(
                (r["f"].rsplit("/", 1)[-1], r["dicofre"] or None, (r["m"] or "").rsplit("/", 1)[-1] or None, bool(r["end"])))

    # same-named concelhos (Lagoa, Calheta) are told apart by the "(Açores)/(Madeira)/(Algarve)" qualifier -> DICO prefix
    QUAL = {"acores": ("4",), "madeira": ("3",), "algarve": ("08",), "sao jorge": ("45",), "faro": ("08",)}

    def mun_q(self, name):
        mm = re.search(r"\(([^)]+)\)\s*$", name)
        base = fold(re.sub(r"\s*\([^)]*\)\s*$", "", name))
        qs = self.mun.get(base, set())
        if len(qs) > 1 and mm:
            pre = self.QUAL.get(fold(mm.group(1)), ())
            qs = {q for q in qs if (self.dico.get(q) or "").startswith(pre)} if pre else qs
        return next(iter(qs)) if len(qs) == 1 else ("ambiguous" if qs else None)

    def resolve(self, issuer: str) -> dict:
        res = dict(place_id=None, qid=None, place_name=None, admin_level=None, match=None, dico=None)
        u = issuer.upper()
        m = re.match(r"^(?:MUNIC[IÍ]PIO|C[AÂ]MARA MUNICIPAL|ASSEMBLEIA MUNICIPAL|SERVI[CÇ]OS MUNICIPALIZADOS.*?)\s+(?:D[AEO]S?\s+)?(.+)$", u)
        if u.startswith(("FREGUESIA", "JUNTA DE FREGUESIA", "UNIÃO DAS FREGUESIAS", "UNIAO DAS FREGUESIAS", "ASSEMBLEIA DE FREGUESIA")):
            res["admin_level"] = "freguesia"
            name = re.sub(r"^(?:JUNTA DE |ASSEMBLEIA DE )?(?:FREGUESIA|UNI[AÃ]O DAS FREGUESIAS)\s+(?:D[AEO]S?\s+)?", "", u)
            mm = re.search(r"\(([^)]+)\)\s*$", name)            # "FREGUESIA DE X (CONCELHO)" in some issues
            base = re.sub(r"\s*\([^)]*\)\s*$", "", name)
            hits = [h for h in self.freg.get(fold(base), []) if not h[3]] or self.freg.get(fold(base), [])
            mq0 = self.mun_q(mm.group(1)) if mm else None
            if mq0 and mq0 != "ambiguous":
                hits = [h for h in hits if h[2] == mq0] or hits
            res["freguesia_name"] = base.title()
            if len({h[0] for h in hits}) == 1:
                q, dicofre, mq, _ = hits[0]
                res.update(freguesia_qid=q, dicofre=dicofre, parent_place_id=f"wd:{mq}" if mq in self.cand else None,
                           match="freguesia_name->wikidata(not_in_candidate)")
            else:
                res["match"] = "freguesia_ambiguous" if hits else "freguesia_unknown"
            return res
        if not m:
            res["match"] = "issuer_unparsed"
            return res
        q = self.mun_q(m.group(1))
        res["admin_level"] = "municipality"
        if q == "ambiguous":
            res["match"], res["place_name"] = "concelho_ambiguous", m.group(1).title()
        elif q:
            c = self.cand[q]
            res.update(place_id=c["place_id"], qid=q, place_name=c["place_name"], match="concelho_name->candidate",
                       dico=self.dico.get(q))
        else:
            res["match"] = "concelho_unknown"
            res["place_name"] = m.group(1).title()
        return res


def clean_lines(txt: str):
    for ln in txt.replace("\f", "\n").splitlines():
        s = ln.strip().replace("\u00ad", "")
        if s and not NOISE.match(s):
            yield s


def is_heading(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.85 and not TITLE.match(s)


def split_acts(txt: str):
    """Yield (issuer, title_match, body_lines, pubid) per act. Acts end at a 9-digit DR id line.
    Modern layout (c. 2021+): after an id the previous act's page footer (its title) may follow, so the act title is the
    last title line before 'Sumário:'. Older layout (no 'Sumário:'): the first title line after the issuer heading."""
    issuer, pre, title, cur = None, [], None, []

    def commit(idx):
        nonlocal issuer, title, cur, pre
        heads = [h for h in pre[:idx] if is_heading(h)]
        if heads:
            issuer = heads[-1] if ISSUER.match(heads[-1]) or len(heads) < 2 else " ".join(heads[-2:])
        title = TITLE.match(pre[idx])
        cur = pre[idx + 1:]
        pre = []

    for s in clean_lines(txt):
        if PUBID.match(s):
            if title is None and pre:
                ti = [i for i, x in enumerate(pre) if TITLE.match(x)]
                if ti:
                    commit(ti[0])
            if title:
                yield issuer, title, cur, s
            pre, title, cur = [], None, []
            continue
        if title is not None:
            if not (TITLE.match(s) and s == title.group(0)):   # running footer repeating the act title
                cur.append(s)
            continue
        pre.append(s)
        if s.startswith("Sumário:"):
            ti = [i for i, x in enumerate(pre) if TITLE.match(x)]
            if ti:
                commit(ti[-1])
            continue
        ti = [i for i, x in enumerate(pre) if TITLE.match(x)]
        if ti and len(pre) - ti[0] > 8:
            commit(ti[0])
        elif len(pre) > 40:
            pre = pre[-12:]


def doc_type(kind: str) -> str:
    if kind in ("Regulamento", "Postura"):
        return "regulation"
    if kind in ("Deliberação", "Despacho", "Despacho normativo", "Decisão", "Resolução"):
        return "decision"
    return "gazette_act"


def parse_issue(txt: str, meta: dict, pm: Places):
    """-> list of (row_or_None, key, why)"""
    out = []
    for issuer, tm, lines, pubid in split_acts(txt):
        if not issuer or not ISSUER.match(issuer):
            continue
        kind = tm.group("kind")
        body = "\n".join(lines)
        summ = body[:900]
        m = re.search(r"Sumário:\s*(.+?)(?:\n[A-ZÁÉÍÓÚ][^\n]{0,80}\n|$)", summ, re.S)
        summary = " ".join((m.group(1) if m else lines[0] if lines else "").split())[:600]
        key = f"pt_dre:{pubid}"
        probe = f"{tm.group(0)} {summary} {summ}"
        if not (kind in ("Regulamento", "Postura") or (REG.search(probe) and not HR.search(summary or summ[:300]))):
            out.append((None, key, "not_regulatory"))
            continue
        pl = pm.resolve(issuer)
        stage = "draft_public_consultation" if re.search(r"consulta p[uú]blica|projeto de regulamento|discuss[aã]o p[uú]blica",
                                                          f"{tm.group(0)} {summary}", re.I) else None
        title = f"{tm.group(0)} — {summary}" if summary else tm.group(0)
        row = {
            "place_id": pl["place_id"], "country_code": "PT", "doc_id": key, "source_platform": "pt_dre",
            "source_url": meta["url"], "doc_type": doc_type(kind), "act_kind": kind + (" (extrato)" if tm.group("ext") else ""),
            "language": "pt", "title_native": title[:1000], "number": tm.group("num") or pubid,
            "adopted_date": None, "published_date": meta["date"], "effective_date": None, "in_force": None,
            "consolidated": False, "content_format": "pdf_text", "text": f"{tm.group(0)}\n{body}",
            "retrieved_at": utcnow(), "place_name": pl["place_name"], "qid": pl["qid"], "iso_3166_2": None,
            "admin_level": pl["admin_level"], "platform": "pt_dre", "platform_place_id": pl.get("dico"),
            "issuing_body_name": issuer.title(), "level": pl["admin_level"], "place_match": pl["match"],
            "dr_publication_id": pubid, "dr_issue": meta["issue"], "dr_supplement": meta["supp"],
            "dr_series": "2", "dr_part": "H", "pdf_url": meta["url"], "regulation_stage": stage,
            "rights": "official act, excluded from copyright (CDADC art. 7.º); Diário da República (INCM), free access",
        }
        for k in ("freguesia_name", "freguesia_qid", "dicofre", "parent_place_id"):
            if pl.get(k):
                row[k] = pl[k]
        out.append((row, key, "ok"))
    return out


class DR:
    def __init__(self):
        self.sess = PoliteSession(log, min_interval=2.0)

    def exists(self, url: str) -> bool:
        if not self.sess.robots.can_fetch(url):
            raise PermissionError(f"robots.txt disallows {url}")
        host = url.split("/")[2]
        for a in range(6):
            w = self.sess.min_interval - (time.monotonic() - self.sess.last.get(host, 0))
            if w > 0:
                time.sleep(w)
            self.sess.last[host] = time.monotonic()
            try:
                r = self.sess.s.head(url, allow_redirects=False, timeout=(20, 60))
                if r.status_code == 200:
                    return True
                if r.status_code in (301, 302, 404):
                    return False
                err = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                err = str(e)[:150]
            log.warning("HEAD retry %d/6 %s %s", a + 1, err, url)
            time.sleep(min(10 * 2 ** a, 600))
        raise RuntimeError(f"HEAD failed {url}: {err}")

    def download(self, url: str, dest: Path) -> int:
        r = self.sess.get(url, stream=True)
        n = 0
        with dest.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                n += len(chunk)
        return n


def issue_text(dr: DR, url: str) -> tuple[str, int]:
    TMP.mkdir(parents=True, exist_ok=True)
    pdf = TMP / "issue.pdf"
    n = dr.download(url, pdf)
    try:
        p = subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, timeout=900)
        txt = p.stdout.decode("utf-8", "replace")
    finally:
        pdf.unlink(missing_ok=True)
    return txt, n


def date_of(txt: str, y: int, m: int) -> str:
    mm = re.search(r"(\d{1,2}) de (janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro) de (\d{4})",
                   txt[:4000], re.I)
    months = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    if mm:
        return f"{int(mm.group(3)):04d}-{months.index(mm.group(2).lower()) + 1:02d}-{int(mm.group(1)):02d}"
    return f"{y:04d}-{m:02d}-01"


def do_issue(dr, pm, stg, done, y, m, n, s):
    url = f"{FILES}/{y}/{m:02d}/2S{n:03d}A0000S{s:02d}.pdf"
    key = f"issue:{y}/{n:03d}/{s:02d}"
    t0 = time.time()
    txt, size = issue_text(dr, url)
    meta = {"url": url, "issue": n, "supp": s, "date": date_of(txt, y, m)}
    res = parse_issue(txt, meta, pm)
    del txt
    seen = set()
    for row, k, why in res:
        if k in seen or done.has(k):
            continue
        seen.add(k)
        stg.add(row, k, why)
    stg.add(None, key, "issue_done")
    kept = sum(1 for r, _, w in res if w == "ok")
    log.info("issue %s %s: %.1f MB, local acts kept=%d skipped=%d (%.0fs)", key, meta["date"], size / 1e6, kept,
             len(res) - kept, time.time() - t0)
    return kept


def fetch(a):
    dr, pm = DR(), Places()
    done = Done(STATE / "done.sqlite")
    stg = Stager("PT", "ptdre", log, max_docs=300, max_secs=900)
    stg.graceful(done)
    stp = STATE / "progress.json"
    st = json.loads(stp.read_text()) if stp.exists() else {}
    years = range(a.to_year, a.from_year - 1, -1)   # newest first
    n_issues = 0
    for y in years:
        ys = st.get(str(y), {"n": 1, "m": 1, "miss": 0, "complete": False})
        if ys.get("complete"):
            continue
        while True:
            n = ys["n"]
            found = None
            for m in range(ys["m"], min(ys["m"] + 3, 13)):
                if dr.exists(f"{FILES}/{y}/{m:02d}/2S{n:03d}A0000S00.pdf"):
                    found = m
                    break
            if found is None:
                ys["miss"] += 1
                ys["n"] += 1
                if ys["miss"] >= 4:
                    if y < int(time.strftime("%Y")) or ys["m"] == 12:
                        ys["complete"] = True
                    else:
                        ys["n"] -= ys["miss"]      # current year: caught up; resume here next time
                        ys["miss"] = 0
                    st[str(y)] = ys
                    stp.write_text(json.dumps(st))
                    break
                continue
            ys["miss"], ys["m"] = 0, found
            for s in range(0, 10):
                if s and not dr.exists(f"{FILES}/{y}/{found:02d}/2S{n:03d}A0000S{s:02d}.pdf"):
                    break
                if done.has(f"issue:{y}/{n:03d}/{s:02d}"):
                    continue
                try:
                    do_issue(dr, pm, stg, done, y, found, n, s)
                except Exception as e:  # noqa: BLE001  (not marked done -> retried on resume)
                    log.warning("issue %d/%03d/%02d FAIL: %s", y, n, s, str(e)[:200])
                if stg.due():
                    log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
                    gc.collect()
            ys["n"] += 1
            st[str(y)] = ys
            stp.write_text(json.dumps(st))
            n_issues += 1
            if a.limit_issues and n_issues >= a.limit_issues:
                if stg.keys:
                    log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
                return
        if stg.keys:
            log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
    log.info("fetch pass finished: %s places=%d", dict(stg.total), len(stg.places))


def test(spec):
    y, m, n, *s = [int(x) for x in spec.split("/")]
    dr, pm = DR(), Places()
    url = f"{FILES}/{y}/{m:02d}/2S{n:03d}A0000S{(s[0] if s else 0):02d}.pdf"
    txt, size = issue_text(dr, url)
    res = parse_issue(txt, {"url": url, "issue": n, "supp": s[0] if s else 0, "date": date_of(txt, y, m)}, pm)
    from collections import Counter
    print(url, f"{size / 1e6:.1f} MB", Counter(w for _, _, w in res), Counter(r["place_match"] for r, _, w in res if r))
    for r, k, w in res:
        if r:
            print(" ", k, r["act_kind"], "|", r["issuing_body_name"], "->", r["place_id"], r["place_match"], "|", r["title_native"][:110])
    sch = __import__("common.live", fromlist=["_schema"])._schema()
    bad = [(r["doc_id"], sch.validate_record(r)) for r, _, _ in res if r and sch.validate_record(r)]
    print("invalid:", bad[:3])


def status():
    stp = STATE / "progress.json"
    print(json.dumps(json.loads(stp.read_text()) if stp.exists() else {}, indent=0))
    d = Done(STATE / "done.sqlite")
    print("done", d.count(), "issues", d.count("issue_done"), "kept", d.count("ok"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "all", "test", "status"])
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--from-year", type=int, default=FIRST_YEAR)
    ap.add_argument("--to-year", type=int, default=int(time.strftime("%Y")))
    ap.add_argument("--limit-issues", type=int)
    a = ap.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    if a.cmd == "status":
        return status()
    if a.cmd == "test":
        return test(a.spec)
    fetch(a)


if __name__ == "__main__":
    main()
