#!/usr/bin/env python3
"""Stream DILA LEGI tar.gz dumps into collection JSON records.

One record per LEGITEXT (code / law / regulation). Articles become documents[].
Only in-force article versions (VIGUEUR, VIGUEUR_DIFF) are kept to stay compact.
Resume via index.jsonl. Incrementals overlay existing records.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

LICENSE = "Licence Ouverte 2.0"
PUBLISHER = "DILA"
SOURCE_NAME = "Légifrance/LEGI open data"
DATASET_URL = "https://www.data.gouv.fr/fr/datasets/legi-codes-lois-et-reglements-consolides/"
EXCHANGE_URL = "https://echanges.dila.gouv.fr/OPENDATA/LEGI/"
JURISDICTION = "FR"
COUNTRY = "France"
LANGUAGE = "fr"
SOURCE_TYPE = "legifrance"

IN_FORCE_ETATS = frozenset({"VIGUEUR", "VIGUEUR_DIFF"})
SENTINEL_DATES = frozenset({"", "2999-01-01", "2222-02-22"})

CODE_NATURES = frozenset({"CODE"})
LOI_NATURES = frozenset({
    "LOI", "LOI_ORGANIQUE", "LOI_CONSTITUTIONNELLE", "LOI_CONSTIT",
    "DECRET_LOI", "ORDONNANCE",
})
REG_NATURES = frozenset({
    "DECRET", "ARRETE", "ARRETE_ROYAL", "DECISION", "CIRCULAIRE",
    "AVIS", "DELIBERATION", "RAPPORT", "CONVENTION",
})

NATURE_ELI = {
    "LOI": "loi",
    "LOI_ORGANIQUE": "loi",
    "LOI_CONSTITUTIONNELLE": "loi",
    "LOI_CONSTIT": "loi",
    "DECRET": "decret",
    "DECRET_LOI": "decret",
    "ORDONNANCE": "ordonnance",
    "ARRETE": "arrete",
    "ARRETE_ROYAL": "arrete",
    "DECISION": "decision",
}

CID_RE = re.compile(r"(LEGITEXT\d{12}|JORFTEXT\d{12})")
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
WS_RE = re.compile(r"[ \t\r\f\v]+")
NL_RE = re.compile(r"\n{3,}")

SOFT_LIMIT_BYTES = 20 * 1024 ** 3
HARD_LIMIT_BYTES = 24 * 1024 ** 3

log = logging.getLogger("legi")


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


KEEP_NULL = frozenset({"eli", "celex", "ecli", "date", "is_current"})


def omit_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if v is None and k not in KEEP_NULL:
                continue
            out[k] = omit_none(v)
        return out
    if isinstance(obj, list):
        return [omit_none(x) for x in obj]
    return obj


def setup_logging(logf: Path) -> None:
    logf.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(logf, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.setLevel(logging.INFO)
    log.handlers.clear()
    log.addHandler(fh)
    log.addHandler(sh)


def local_name(tag: str) -> str:
    if tag and tag[0] == "{":
        return tag.rsplit("}", 1)[-1]
    return tag or ""


def find_first(elem: ET.Element, name: str) -> Optional[ET.Element]:
    for e in elem.iter():
        if local_name(e.tag) == name:
            return e
    return None


def text_of(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    return (elem.text or "").strip()


def xml_plain(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    parts: List[str] = []

    def walk(e: ET.Element) -> None:
        tag = local_name(e.tag).lower()
        if tag in {"br"}:
            parts.append("\n")
        if e.text:
            parts.append(e.text)
        for c in e:
            ctag = local_name(c.tag).lower()
            if ctag in {"p", "div", "li", "h1", "h2", "h3", "h4", "blockquote", "tr"}:
                parts.append("\n")
            walk(c)
            if ctag in {"p", "div", "li", "br", "h1", "h2", "h3", "h4"}:
                parts.append("\n")
            if c.tail:
                parts.append(c.tail)

    walk(elem)
    s = "".join(parts)
    s = s.replace("\xa0", " ").replace("\u202f", " ")
    s = WS_RE.sub(" ", s)
    s = NL_RE.sub("\n\n", s)
    return s.strip()


def safe_id(raw: str) -> str:
    s = SAFE_RE.sub("_", (raw or "").strip())
    s = s.strip("._") or "unknown"
    return s[:180]


def instrument_id(legitext: str) -> str:
    lid = (legitext or "").strip()
    if not lid:
        return "fr-unknown"
    if lid.startswith("fr-"):
        return safe_id(lid)
    return safe_id(f"fr-{lid}")


def record_type_of(nature: str) -> str:
    n = (nature or "").upper()
    return {
        "CODE": "code",
        "LOI": "law",
        "LOI_ORGANIQUE": "law",
        "LOI_CONSTITUTIONNELLE": "constitution",
        "LOI_CONSTIT": "constitution",
        "DECRET_LOI": "decree",
        "ORDONNANCE": "ordinance",
        "DECRET": "decree",
        "ARRETE": "regulation",
        "ARRETE_ROYAL": "regulation",
        "DECISION": "instrument",
        "CIRCULAIRE": "instrument",
        "AVIS": "instrument",
        "DELIBERATION": "instrument",
        "RAPPORT": "instrument",
        "CONVENTION": "instrument",
    }.get(n, "instrument")


def document_type_of(nature: str) -> str:
    n = (nature or "").upper()
    return {
        "CODE": "code",
        "LOI": "statute",
        "LOI_ORGANIQUE": "statute",
        "LOI_CONSTITUTIONNELLE": "constitution",
        "LOI_CONSTIT": "constitution",
        "DECRET_LOI": "decree",
        "ORDONNANCE": "ordinance",
        "DECRET": "decree",
        "ARRETE": "regulation",
        "ARRETE_ROYAL": "regulation",
    }.get(n, "instrument")


def law_status_of(etat: Optional[str], en_vigueur: bool) -> str:
    e = (etat or "").upper()
    if e in IN_FORCE_ETATS or (en_vigueur and e in {"", "VIGUEUR"}):
        return "current"
    if e in {"ABROGE", "ABROGE_DIFF"}:
        return "repealed"
    if e in {"MODIFIE", "PERIME"}:
        return "superseded"
    if not en_vigueur:
        return "historical"
    return "unknown"


def classify_path(name: str) -> Tuple[str, bool]:
    n = name.replace("\\", "/")
    if "/code_en_vigueur/" in n:
        return "code", True
    if "/TNC_en_vigueur/" in n:
        return "tnc", True
    if "/code_non_vigueur/" in n:
        return "code", False
    if "/TNC_non_vigueur/" in n:
        return "tnc", False
    if "/eli/" in n:
        return "eli", True
    return "other", False


def path_cid(name: str) -> Optional[str]:
    m = re.search(r"/(LEGITEXT\d{12}|JORFTEXT\d{12})/", name)
    if m:
        return m.group(1)
    m = CID_RE.search(name)
    return m.group(1) if m else None


def nature_group(nature: str) -> str:
    n = (nature or "").upper()
    if n in CODE_NATURES:
        return "code"
    if n in LOI_NATURES:
        return "loi"
    if n in REG_NATURES:
        return "reglement"
    if n:
        return "autre"
    return "inconnu"


def build_eli(nature: str, date_issued: Optional[str], nor: Optional[str]) -> Optional[str]:
    if not nor or not date_issued or date_issued in SENTINEL_DATES:
        return None
    kind = NATURE_ELI.get((nature or "").upper())
    if not kind:
        return None
    try:
        y, m, d = date_issued.split("-")
        month = str(int(m))
        day = str(int(d))
    except Exception:
        return None
    return f"https://www.legifrance.gouv.fr/eli/{kind}/{y}/{month}/{day}/{nor}/jo/texte"


def source_url_for(rec_id: str, nature: str) -> str:
    n = (nature or "").upper()
    if n == "CODE":
        return f"https://www.legifrance.gouv.fr/codes/id/{rec_id}"
    return f"https://www.legifrance.gouv.fr/loda/id/{rec_id}"


def article_url(art_id: str, nature: str) -> str:
    if (nature or "").upper() == "CODE":
        return f"https://www.legifrance.gouv.fr/codes/article_lc/{art_id}"
    return f"https://www.legifrance.gouv.fr/loda/id/{art_id}"


def clean_date(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = v.strip()
    if v in SENTINEL_DATES:
        return None
    return v


def parse_texte_version(root: ET.Element) -> Dict[str, Any]:
    rec_id = text_of(find_first(root, "ID"))
    nature = text_of(find_first(root, "NATURE"))
    cid = text_of(find_first(root, "CID"))
    nor = text_of(find_first(root, "NOR")) or None
    titre = text_of(find_first(root, "TITREFULL")) or text_of(find_first(root, "TITRE"))
    etat = text_of(find_first(root, "ETAT"))
    date_publi = clean_date(text_of(find_first(root, "DATE_PUBLI")))
    date_texte = clean_date(text_of(find_first(root, "DATE_TEXTE")))
    date_debut = clean_date(text_of(find_first(root, "DATE_DEBUT")))
    date_fin = clean_date(text_of(find_first(root, "DATE_FIN")))
    dern = clean_date(text_of(find_first(root, "DERNIERE_MODIFICATION")))
    num = text_of(find_first(root, "NUM")) or None
    autorite = text_of(find_first(root, "AUTORITE")) or None
    ministere = text_of(find_first(root, "MINISTERE")) or None
    visas = xml_plain(find_first(root, "VISAS"))
    signataires = xml_plain(find_first(root, "SIGNATAIRES"))
    tp = xml_plain(find_first(root, "TP"))
    nota = xml_plain(find_first(root, "NOTA"))
    date_issued = date_texte or date_publi or date_debut
    return {
        "id": rec_id,
        "cid": cid or rec_id,
        "nor": nor,
        "nature": nature,
        "title": titre,
        "etat": etat,
        "date_issued": date_issued,
        "date_publi": date_publi,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "derniere_modification": dern,
        "num": num,
        "autorite": autorite,
        "ministere": ministere,
        "visas": visas,
        "signataires": signataires,
        "travaux_preparatoires": tp,
        "nota": nota,
    }


def parse_article(root: ET.Element) -> Optional[Dict[str, Any]]:
    art_id = text_of(find_first(root, "ID"))
    if not art_id:
        return None
    num = text_of(find_first(root, "NUM"))
    etat = text_of(find_first(root, "ETAT")).upper()
    date_debut = clean_date(text_of(find_first(root, "DATE_DEBUT")))
    date_fin = clean_date(text_of(find_first(root, "DATE_FIN")))
    if etat and etat not in IN_FORCE_ETATS:
        return None
    if not etat and date_fin is not None:
        return None
    contenu = None
    for e in root.iter():
        if local_name(e.tag) == "BLOC_TEXTUEL":
            contenu = find_first(e, "CONTENU")
            break
    body = xml_plain(contenu)
    nota_el = None
    for e in list(root):
        if local_name(e.tag) == "NOTA":
            nota_el = e
            break
    nota = xml_plain(nota_el)
    hierarchy: List[str] = []
    seen = set()
    for e in root.iter():
        if local_name(e.tag) == "TITRE_TM":
            t = (e.text or "").strip()
            if t and t not in seen:
                seen.add(t)
                hierarchy.append(t)
    ctx = find_first(root, "TEXTE")
    parent_cid = None
    parent_nature = None
    parent_title = None
    if ctx is not None:
        parent_cid = ctx.attrib.get("cid") or ctx.attrib.get("CID")
        parent_nature = ctx.attrib.get("nature") or ctx.attrib.get("NATURE")
        tt = find_first(ctx, "TITRE_TXT")
        if tt is not None:
            parent_title = (tt.text or "").strip() or tt.attrib.get("c_titre_court")
    title = f"Article {num}" if num else art_id
    text = body
    if nota:
        text = (text + "\n\nNota : " + nota).strip()
    hier_text = " > ".join(hierarchy) if hierarchy else None
    status = law_status_of(etat or "VIGUEUR", True)
    return {
        "id": art_id,
        "title": title,
        "text": text,
        "date_filed": date_debut,
        "document_number": num or None,
        "source_url": article_url(art_id, parent_nature or ""),
        "document_type": "article",
        "record_type": "article",
        "article_identifier": art_id,
        "article_number": num or None,
        "article_heading": title,
        "citation": f"art. {num}" if num else art_id,
        "hierarchy_path_text": hier_text,
        "law_identifier": parent_cid,
        "law_status": status,
        "is_current": status == "current",
        "valid_from": date_debut,
        "valid_to": date_fin,
        "effective_date": date_debut,
        "metadata": {
            "num": num or None,
            "etat": etat or "VIGUEUR",
            "date_debut": date_debut,
            "date_fin": date_fin,
            "hierarchy": hier_text,
            "parent_cid": parent_cid,
            "parent_nature": parent_nature,
            "parent_title": parent_title,
            "text_extraction": {"source": "legi_xml", "backend": "collect_legi"},
        },
    }


class TextBuf:
    __slots__ = ("path_cid", "bucket", "en_vigueur", "meta", "articles", "article_ids")

    def __init__(self, path_cid: str, bucket: str, en_vigueur: bool) -> None:
        self.path_cid = path_cid
        self.bucket = bucket
        self.en_vigueur = en_vigueur
        self.meta: Dict[str, Any] = {}
        self.articles: List[Dict[str, Any]] = []
        self.article_ids: Set[str] = set()

    def add_article(self, doc: Dict[str, Any]) -> None:
        aid = doc["id"]
        if aid in self.article_ids:
            self.articles = [d for d in self.articles if d["id"] != aid]
        else:
            self.article_ids.add(aid)
        self.articles.append(doc)

    def merge_from(self, other: "TextBuf") -> None:
        for k, v in other.meta.items():
            if v and not self.meta.get(k):
                self.meta[k] = v
            elif v and k in {"title", "id", "nature", "nor", "cid", "etat", "date_issued"}:
                self.meta[k] = v
        for d in other.articles:
            self.add_article(d)
        if other.bucket != "other":
            self.bucket = other.bucket
        self.en_vigueur = self.en_vigueur or other.en_vigueur


def sort_articles(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(d: Dict[str, Any]) -> Tuple:
        num = (d.get("metadata") or {}).get("num") or ""
        return (num, d.get("id") or "")
    return sorted(docs, key=key)


def compose_text(meta: Dict[str, Any], docs: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    title = meta.get("title") or ""
    if title:
        parts.append(title)
    visas = meta.get("visas") or ""
    if visas:
        parts.append(visas)
    for d in docs:
        h = f"{d.get('title') or d['id']}"
        hier = (d.get("metadata") or {}).get("hierarchy")
        if hier:
            h = f"{h} ({hier})"
        body = d.get("text") or ""
        parts.append(h + ("\n" + body if body else ""))
    sign = meta.get("signataires") or ""
    if sign:
        parts.append(sign)
    return "\n\n".join(p for p in parts if p).strip()


def build_record(buf: TextBuf, retrieved_at: str, dump_name: str, eli_map: Dict[str, str]) -> Optional[Dict[str, Any]]:
    meta = buf.meta
    rec_id = meta.get("id") or buf.path_cid
    if not rec_id:
        return None
    nature = meta.get("nature") or ("CODE" if buf.bucket == "code" else "")
    title = meta.get("title") or rec_id
    docs = sort_articles(buf.articles)
    nor = meta.get("nor")
    date_issued = meta.get("date_issued")
    cid = meta.get("cid") or buf.path_cid
    eli = build_eli(nature, date_issued, nor) or eli_map.get(rec_id) or eli_map.get(cid) or None
    official = rec_id
    src = source_url_for(rec_id, nature)
    etat = meta.get("etat") or ("VIGUEUR" if buf.en_vigueur else None)
    status = law_status_of(etat, buf.en_vigueur)
    date_publi = meta.get("date_publi")
    date_debut = meta.get("date_debut")
    date_fin = meta.get("date_fin")
    date = date_debut or date_publi or date_issued
    iid = instrument_id(rec_id)
    # rewrite article document ids to stable fr-LEGITEXT-art-LEGIARTI form
    out_docs = []
    for d in docs:
        d = dict(d)
        art = d.get("article_identifier") or d.get("id")
        d["id"] = f"{iid}-{art}" if art else iid
        d["law_identifier"] = rec_id
        d["retrieved_at"] = retrieved_at
        if not d.get("source_url"):
            d["source_url"] = article_url(art or "", nature)
        out_docs.append(d)
    body = compose_text(meta, out_docs)
    if not body:
        body = title or rec_id
    rtype = record_type_of(nature)
    record = {
        "schema_version": "collection_record.v1",
        "record_type": rtype,
        "id": iid,
        "title": title,
        "canonical_title": title,
        "text": body,
        "source_url": src,
        "source_type": SOURCE_TYPE,
        "date": date,
        "date_issued": date_issued or date,
        "jurisdiction": JURISDICTION,
        "country": COUNTRY,
        "language": LANGUAGE,
        "languages": [LANGUAGE],
        "eli": eli,
        "celex": None,
        "ecli": None,
        "license": LICENSE,
        "retrieved_at": retrieved_at,
        "identifier": rec_id,
        "official_identifier": official,
        "law_identifier": rec_id,
        "citation": (f"{title} ({nor})" if nor else title),
        "document_type": document_type_of(nature),
        "canonical_law_url": src,
        "canonical_document_url": src,
        "law_status": status,
        "is_current": status == "current",
        "valid_from": date_debut,
        "valid_to": date_fin,
        "effective_date": date_debut or date_issued,
        "publication_date": date_publi,
        "last_modified_date": meta.get("derniere_modification"),
        "status_source": "legi_etat",
        "status_confidence": "high" if etat else "medium",
        "article_count": len(out_docs),
        "article_extraction_status": "ok" if out_docs else "missing",
        "scraped_at": retrieved_at,
        "documents": out_docs,
        "plaintiff_docket": [],
        "defendant_docket": [],
        "authorities": [],
        "hierarchy": [],
        "official_metadata": {
            "cid": cid,
            "nor": nor,
            "nature": nature or None,
            "etat": etat,
            "num": meta.get("num"),
            "autorite": meta.get("autorite"),
            "ministere": meta.get("ministere"),
            "bucket": buf.bucket,
            "en_vigueur": buf.en_vigueur,
        },
        "metadata": {
            "collector": "fr-legi",
            "collector_run_id": dump_name,
            "source_path": dump_name,
            "source_host": "echanges.dila.gouv.fr",
            "content_type": "application/xml",
            "text_extraction": {"source": "legi_xml", "backend": "collect_legi"},
            "discovery": {
                "method": "dila_freemium_dump",
                "catalog_identifier": rec_id,
                "seed_url": EXCHANGE_URL,
            },
            "rights": {
                "license": LICENSE,
                "attribution": "Direction de l'information légale et administrative (DILA) / Légifrance",
                "official_reuse_url": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
                "not_legal_advice": True,
            },
            "parser": "collect_legi.py",
            "schema": "collection_record.v1",
            "license": LICENSE,
            "retrieved_at": retrieved_at,
            "official_id": official,
            "publisher": PUBLISHER,
            "source_name": SOURCE_NAME,
            "cid": cid,
            "nor": nor,
            "nature": nature or None,
            "nature_group": nature_group(nature),
            "etat": etat,
            "num": meta.get("num"),
            "date_publi": date_publi,
            "date_debut": date_debut,
            "date_fin": date_fin,
            "derniere_modification": meta.get("derniere_modification"),
            "autorite": meta.get("autorite"),
            "ministere": meta.get("ministere"),
            "bucket": buf.bucket,
            "en_vigueur": buf.en_vigueur,
            "dump": dump_name,
            "dataset_url": DATASET_URL,
            "n_articles_in_force": len(out_docs),
        },
    }
    return omit_none(record)


def load_index_ids(path: Path) -> Set[str]:
    done: Set[str] = set()
    if not path.exists():
        return done
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            i = obj.get("id")
            if i:
                done.add(i)
    return done


def merge_records(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    for k in (
        "title", "canonical_title", "source_url", "eli", "date_issued", "date",
        "license", "retrieved_at", "law_status", "is_current", "valid_from",
        "valid_to", "effective_date", "publication_date", "last_modified_date",
        "citation", "document_type", "record_type", "identifier",
        "official_identifier", "law_identifier", "canonical_law_url",
        "source_type",
    ):
        if new.get(k) not in (None, "", []):
            old[k] = new[k]
    md = old.setdefault("metadata", {})
    md.update({k: v for k, v in (new.get("metadata") or {}).items() if v is not None})
    by_id = {d["id"]: d for d in old.get("documents") or [] if d.get("id")}
    for d in new.get("documents") or []:
        if d.get("id"):
            by_id[d["id"]] = d
    old["documents"] = sort_articles(list(by_id.values()))
    old["text"] = compose_text(
        {
            "title": old.get("title"),
            "visas": (old.get("metadata") or {}).get("visas"),
            "signataires": (old.get("metadata") or {}).get("signataires"),
        },
        old["documents"],
    )
    old["jurisdiction"] = JURISDICTION
    old["country"] = COUNTRY
    old["language"] = LANGUAGE
    old["source_type"] = SOURCE_TYPE
    return old


def write_record(instr: Path, record: Dict[str, Any], merge: bool) -> Tuple[str, int]:
    sid = safe_id(record["id"])
    dest = instr / f"{sid}.json"
    if dest.exists():
        # Always merge late article batches for the same LEGITEXT (tar may
        # flush a directory then see leftover files, or overlay incrementals).
        try:
            with dest.open("r", encoding="utf-8") as f:
                prev = json.load(f)
            record = merge_records(prev, record)
        except Exception as exc:
            log.warning("merge failed for %s: %s — replacing", dest, exc)
    instr.mkdir(parents=True, exist_ok=True)
    # Compact JSON: indent=2 would blow the ~25GB France budget on large codes.
    data = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd, tmp = tempfile.mkstemp(dir=instr, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(tmp, dest)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return dest.name, dest.stat().st_size


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, dirs, files in os.walk(path):
        for fn in files:
            try:
                total += (Path(root) / fn).stat().st_size
            except OSError:
                pass
    return total


def rebuild_index(root: Path) -> int:
    instr = root / "instruments"
    index = root / "index.jsonl"
    n = 0
    with index.open("w", encoding="utf-8") as out:
        if not instr.exists():
            return 0
        for p in sorted(instr.glob("*.json")):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            md = obj.get("metadata") or {}
            entry = {
                "id": obj.get("id"),
                "title": obj.get("title"),
                "nature": md.get("nature"),
                "nature_group": md.get("nature_group"),
                "en_vigueur": md.get("en_vigueur"),
                "path": f"instruments/{p.name}",
                "n_documents": len(obj.get("documents") or []),
                "bytes": p.stat().st_size,
                "source_url": obj.get("source_url"),
                "eli": obj.get("eli"),
                "date_issued": obj.get("date_issued"),
                "dump": md.get("dump"),
            }
            out.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
            n += 1
    return n



def append_index_line(index_path: Path, record: Dict[str, Any], rel: str, nbytes: int) -> None:
    md = record.get("metadata") or {}
    entry = {
        "id": record.get("id"),
        "path": f"instruments/{rel}",
        "title": record.get("title"),
        "identifier": record.get("identifier"),
        "eli": record.get("eli"),
        "source_url": record.get("source_url"),
        "source_type": record.get("source_type"),
        "jurisdiction": record.get("jurisdiction"),
        "language": record.get("language"),
        "law_status": record.get("law_status"),
        "date": record.get("date"),
        "retrieved_at": record.get("retrieved_at"),
        "article_count": record.get("article_count") or len(record.get("documents") or []),
        "bytes": nbytes,
        "nature": md.get("nature"),
        "nature_group": md.get("nature_group"),
        "dump": md.get("dump"),
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")


class Collector:
    def __init__(
        self,
        root: Path,
        retrieved_at: str,
        resume_ids: Set[str],
        include_non_vigueur: bool,
        overlay: bool,
        max_bytes: int,
    ) -> None:
        self.root = root
        self.instr = root / "instruments"
        self.index_path = root / "index.jsonl"
        self.retrieved_at = retrieved_at
        self.resume_ids = resume_ids
        self.include_non_vigueur = include_non_vigueur
        self.overlay = overlay
        self.max_bytes = max_bytes
        self.bytes_written = 0
        self.n_xml = 0
        self.n_xml_err = 0
        self.n_articles_kept = 0
        self.n_articles_skip = 0
        self.n_records = 0
        self.n_skipped_resume = 0
        self.n_skipped_disk = 0
        self.n_merged = 0
        self.counts_nature: Dict[str, int] = {}
        self.counts_bucket: Dict[str, int] = {}
        self.open: Dict[str, TextBuf] = {}
        self.alias: Dict[str, str] = {}
        self.order: List[str] = []
        self.max_open = 8
        self.counts_status: Dict[str, int] = {}
        self.last_dir_cid: Optional[str] = None
        self.dump_name = ""
        self.stop_reglements = False
        self.stop_all = False
        self.eli_map: Dict[str, str] = {}
        self.flushed_keys: Set[str] = set()

    def canon(self, key: str) -> str:
        seen = set()
        while key in self.alias and key not in seen:
            seen.add(key)
            key = self.alias[key]
        return key

    def maybe_stop(self, nature: str, bucket: str, en_vigueur: bool) -> bool:
        if self.stop_all:
            return True
        if not en_vigueur and not self.include_non_vigueur:
            return True
        if not en_vigueur and self.bytes_written > SOFT_LIMIT_BYTES:
            return True
        ng = nature_group(nature)
        if self.stop_reglements and ng in {"reglement", "autre", "inconnu"} and bucket == "tnc":
            return True
        if self.bytes_written > SOFT_LIMIT_BYTES and ng in {"reglement", "autre"}:
            self.stop_reglements = True
            return True
        if self.bytes_written > self.max_bytes:
            self.stop_all = True
            return True
        return False

    def flush_one(self, key: str) -> None:
        key = self.canon(key)
        buf = self.open.pop(key, None)
        if buf is None:
            return
        rec = build_record(buf, self.retrieved_at, self.dump_name, self.eli_map)
        if rec is None:
            return
        rec_id = rec["id"]
        nature = (rec.get("metadata") or {}).get("nature") or ""
        if self.maybe_stop(nature, buf.bucket, buf.en_vigueur):
            self.n_skipped_disk += 1
            return
        exists = (self.instr / f"{safe_id(rec_id)}.json").exists()
        if (not self.overlay) and rec_id in self.resume_ids and exists:
            self.n_skipped_resume += 1
            return
        merge = exists  # always merge late article batches for same LEGITEXT
        rel, nbytes = write_record(self.instr, rec, merge=merge)
        self.bytes_written += nbytes
        self.n_records += 1
        if merge:
            self.n_merged += 1
        self.resume_ids.add(rec_id)
        self.flushed_keys.add(key)
        self.flushed_keys.add(rec_id)
        cid = (rec.get("metadata") or {}).get("cid")
        if cid:
            self.flushed_keys.add(cid)
        ng = (rec.get("metadata") or {}).get("nature_group") or "inconnu"
        self.counts_nature[ng] = self.counts_nature.get(ng, 0) + 1
        bk = f"{buf.bucket}_{'en_vigueur' if buf.en_vigueur else 'non_vigueur'}"
        self.counts_bucket[bk] = self.counts_bucket.get(bk, 0) + 1
        st = rec.get("law_status") or "unknown"
        self.counts_status[st] = self.counts_status.get(st, 0) + 1
        append_index_line(self.index_path, rec, rel, nbytes)
        if self.n_records % 200 == 0:
            log.info(
                "progress records=%s xml=%s articles_kept=%s bytes=%.1fMB open=%s dump=%s",
                self.n_records, self.n_xml, self.n_articles_kept,
                self.bytes_written / 1e6, len(self.open), self.dump_name,
            )
        if self.n_records % 2000 == 0:
            try:
                write_summary(self.root, self, [self.dump_name], {"remainder": ["in progress"], "blockers": []})
            except Exception:
                pass

    def flush_lru(self) -> None:
        while len(self.open) > self.max_open:
            oldest = None
            for k in list(self.order):
                ck = self.canon(k)
                if ck in self.open:
                    oldest = ck
                    break
                try:
                    self.order.remove(k)
                except ValueError:
                    pass
            if oldest is None:
                oldest = next(iter(self.open), None)
            if oldest is None:
                break
            self.flush_one(oldest)

    def touch(self, cid: str, bucket: str, en_vigueur: bool) -> TextBuf:
        key = self.canon(cid)
        if key in self.flushed_keys and key not in self.open and self.overlay:
            # reopen for overlay merge of later files in same tar
            pass
        if key not in self.open:
            self.open[key] = TextBuf(key, bucket, en_vigueur)
            self.order.append(key)
            self.flush_lru()
        buf = self.open[key]
        if bucket != "other":
            buf.bucket = bucket
        buf.en_vigueur = buf.en_vigueur or en_vigueur
        return buf

    def link_ids(self, a: str, b: str, bucket: str, en_vigueur: bool) -> TextBuf:
        """Make a and b alias to the same buffer, merging if both exist."""
        if not a:
            return self.touch(b, bucket, en_vigueur)
        if not b or a == b:
            return self.touch(a, bucket, en_vigueur)
        ca, cb = self.canon(a), self.canon(b)
        if ca == cb:
            return self.touch(ca, bucket, en_vigueur)
        buf_a = self.open.get(ca)
        buf_b = self.open.get(cb)
        if buf_a and buf_b and buf_a is not buf_b:
            buf_a.merge_from(buf_b)
            self.open.pop(cb, None)
            self.alias[cb] = ca
            self.alias[b] = ca
            return buf_a
        if buf_a:
            self.alias[cb] = ca
            self.alias[b] = ca
            return buf_a
        if buf_b:
            self.alias[ca] = cb
            self.alias[a] = cb
            return buf_b
        buf = self.touch(ca, bucket, en_vigueur)
        self.alias[cb] = ca
        self.alias[b] = ca
        return buf

    def handle_xml(self, name: str, data: bytes) -> None:
        self.n_xml += 1
        bucket, en_vigueur = classify_path(name)
        if bucket == "eli":
            self.handle_eli(name, data)
            return
        if bucket == "other":
            return
        if not en_vigueur and not self.include_non_vigueur:
            return
        if self.stop_all:
            return
        base = name.replace("\\", "/")
        if "/section_ta/" in base or "/texte/struct/" in base:
            return
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            self.n_xml_err += 1
            if self.n_xml_err < 30:
                log.warning("XML parse error %s: %s", name, exc)
            return
        tag = local_name(root.tag)
        cid = path_cid(name)
        if tag == "TEXTE_VERSION":
            meta = parse_texte_version(root)
            rec_id = meta.get("id") or cid
            if not rec_id:
                return
            if self.maybe_stop(meta.get("nature") or "", bucket, en_vigueur):
                return
            xml_cid = meta.get("cid") or cid or rec_id
            buf = self.link_ids(rec_id, xml_cid, bucket, en_vigueur)
            if cid and cid not in (rec_id, xml_cid):
                buf = self.link_ids(rec_id, cid, bucket, en_vigueur)
            buf.meta.update({k: v for k, v in meta.items() if v})
            buf.meta.setdefault("id", rec_id)
        elif tag == "ARTICLE":
            doc = parse_article(root)
            if doc is None:
                self.n_articles_skip += 1
                return
            parent = (doc.get("metadata") or {}).get("parent_cid") or cid
            if not parent:
                return
            nature = (doc.get("metadata") or {}).get("parent_nature") or ""
            if self.maybe_stop(nature, bucket, en_vigueur):
                return
            keys = [parent]
            if cid and cid != parent:
                keys.append(cid)
            buf = self.link_ids(keys[0], keys[1] if len(keys) > 1 else keys[0], bucket, en_vigueur)
            if not buf.meta.get("nature") and nature:
                buf.meta["nature"] = nature
            if not buf.meta.get("title"):
                pt = (doc.get("metadata") or {}).get("parent_title")
                if pt:
                    buf.meta["title"] = pt
            if not buf.meta.get("id") and cid and str(cid).startswith("LEGITEXT"):
                buf.meta["id"] = cid
            buf.add_article(doc)
            self.n_articles_kept += 1

    def handle_eli(self, name: str, data: bytes) -> None:
        n = name.replace("\\", "/")
        if not n.endswith("/jo/texte/versions.xml"):
            return
        m = re.search(
            r"/eli/([^/]+)/(\d{4})/(\d{1,2})/(\d{1,2})/([^/]+)/jo/texte/versions\.xml$",
            n,
        )
        if not m:
            return
        kind, y, mo, d, nor = m.groups()
        eli = f"https://www.legifrance.gouv.fr/eli/{kind}/{y}/{int(mo)}/{int(d)}/{nor}/jo/texte"
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            return
        for e in root.iter():
            if local_name(e.tag) == "VERSION":
                vid = e.attrib.get("id")
                if vid:
                    self.eli_map[vid] = eli

    def handle_suppression(self, data: bytes) -> None:
        if not self.overlay:
            return
        for raw in data.decode("utf-8", "replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            path = line.split()[0]
            m = re.search(r"(LEGIARTI\d{12})", path)
            cid = path_cid(path)
            if not (m and cid):
                continue
            art_id = m.group(1)
            for candidate in {cid, self.canon(cid)}:
                dest = self.instr / f"{safe_id(candidate)}.json"
                if not dest.exists():
                    continue
                try:
                    obj = json.loads(dest.read_text(encoding="utf-8"))
                except Exception:
                    continue
                docs = [d for d in obj.get("documents") or [] if d.get("id") != art_id]
                if len(docs) != len(obj.get("documents") or []):
                    obj["documents"] = docs
                    dest.write_text(
                        json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )

    def flush_open(self) -> None:
        for cid in list(self.open):
            self.flush_one(cid)

    def note_dir(self, name: str) -> None:
        cid = path_cid(name)
        if not cid:
            return
        if self.last_dir_cid and cid != self.last_dir_cid:
            # DILA dumps group all files for one LEGITEXT/JORFTEXT directory.
            self.flush_open()
        self.last_dir_cid = cid

    def process_tar(self, tar_path: Path, overlay: Optional[bool] = None) -> None:
        if overlay is not None:
            self.overlay = overlay
        self.dump_name = tar_path.name
        log.info("processing tar %s (%.1f MB) overlay=%s", tar_path, tar_path.stat().st_size / 1e6, self.overlay)
        t0 = time.time()
        n_members = 0
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar:
                n_members += 1
                if n_members % 100000 == 0:
                    log.info("scanned members=%s xml=%s records=%s open=%s elapsed=%.0fs",
                             n_members, self.n_xml, self.n_records, len(self.open), time.time()-t0)
                if not member.isfile():
                    continue
                name = member.name or ""
                base = name.replace("\\", "/")
                bn = os.path.basename(base)
                if bn.startswith("liste_suppression"):
                    try:
                        f = tar.extractfile(member)
                        if f is None:
                            continue
                        self.handle_suppression(f.read())
                    except Exception as exc:
                        log.warning("extract failed %s: %s", name, exc)
                    continue
                if not base.endswith(".xml"):
                    continue
                if "/section_ta/" in base or "/texte/struct/" in base:
                    continue
                if "/code_non_vigueur/" in base or "/TNC_non_vigueur/" in base:
                    if not self.include_non_vigueur:
                        continue
                if "/eli/" in base and not base.endswith("/jo/texte/versions.xml"):
                    continue
                self.note_dir(base)
                try:
                    f = tar.extractfile(member)
                    if f is None:
                        continue
                    data = f.read()
                except Exception as exc:
                    log.warning("extract failed %s: %s", name, exc)
                    continue
                # Skip historical article versions before XML parse.
                if "/article/" in base and b"<ETAT>VIGUEUR" not in data:
                    self.n_articles_skip += 1
                    continue
                self.handle_xml(name, data)
        self.flush_open()
        log.info(
            "done tar %s in %.1fs records=%s xml=%s xml_err=%s articles_kept=%s skipped_resume=%s skipped_disk=%s merged=%s bytes=%.1fMB",
            tar_path.name, time.time() - t0, self.n_records, self.n_xml, self.n_xml_err,
            self.n_articles_kept, self.n_skipped_resume, self.n_skipped_disk, self.n_merged,
            self.bytes_written / 1e6,
        )


def _pt_label(utc_iso: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        local = dt.astimezone(ZoneInfo("America/Los_Angeles"))
        return local.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return utc_iso


def write_summary(
    root: Path,
    col: Collector,
    dump_files: List[str],
    extra: Dict[str, Any],
) -> None:
    instr = root / "instruments"
    index = root / "index.jsonl"
    summary = root / "SUMMARY.md"
    inst_bytes = dir_size(instr)
    idx_bytes = index.stat().st_size if index.exists() else 0
    n_files = len(list(instr.glob("*.json"))) if instr.exists() else 0
    n_index = 0
    if index.exists():
        with index.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n_index += 1
    st = col.counts_status
    dump_bytes = extra.get("dump_bytes")
    dump_line = ", ".join(f"`{d}`" for d in dump_files) or "*(none)*"
    pt = _pt_label(col.retrieved_at)
    lines = [
        "# France legislation corpus (LEGI / Légifrance)",
        "",
        "- jurisdiction: FR",
        "- country: France",
        "- source: DILA LEGI open data (codes, lois et règlements consolidés) via Légifrance",
        f"- official_dataset: {DATASET_URL}",
        f"- dila_exchange: {EXCHANGE_URL}",
        f"- license: {LICENSE}",
        "- source_type: legifrance",
        f"- last_run_retrieved_at: {col.retrieved_at} (PT: {pt})",
        f"- dump: {dump_line}",
        f"- dump_bytes: {dump_bytes if dump_bytes is not None else 'n/a'}",
        f"- instruments_json: {n_files}",
        f"- index_jsonl_lines: {n_index}",
        f"- discovered: {n_files + col.n_skipped_disk + col.n_skipped_resume}",
        f"- fetched: {col.n_xml}",
        f"- parsed: {col.n_xml - col.n_xml_err}",
        f"- written: {col.n_records}",
        f"- skipped: {col.n_skipped_resume + col.n_skipped_disk}",
        f"- failed: {col.n_xml_err}",
        f"- law_status: current={st.get('current', 0)} historical={st.get('historical', 0)} repealed={st.get('repealed', 0)} superseded={st.get('superseded', 0)} unknown={st.get('unknown', 0)}",
        f"- in_force_articles: {col.n_articles_kept}",
        f"- historical_article_versions_omitted: {col.n_articles_skip}",
        f"- overlay_merges: {col.n_merged}",
        f"- instruments_bytes: {inst_bytes} ({inst_bytes / 1e9:.3f} GB)",
        f"- index_bytes: {idx_bytes}",
        f"- json_payload_bytes_this_run: {col.bytes_written}",
        "- coverage: shard (current consolidations from Freemium global dump; historical *_non_vigueur omitted; incrementals not applied)",
        "",
        "## Dump used",
        "",
    ]
    for d in dump_files:
        lines.append(f"- `{d}`")
    if not dump_files:
        lines.append("- *(none)*")
    lines += ["", "### By nature group", ""]
    if col.counts_nature:
        for k, v in sorted(col.counts_nature.items()):
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- *(none)*")
    lines += ["", "### By bucket", ""]
    if col.counts_bucket:
        for k, v in sorted(col.counts_bucket.items()):
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- *(none)*")
    lines += ["", "## Remainder / blockers", ""]
    remainder = extra.get("remainder") or []
    for r in remainder:
        lines.append(f"- {r}")
    if extra.get("blockers"):
        lines += ["", "### Blockers", ""]
        for b in extra["blockers"]:
            lines.append(f"- {b}")
    if extra.get("incrementals"):
        lines += ["", "## Incrementals not applied", ""]
        for x in extra["incrementals"]:
            lines.append(f"- {x}")
    lines += [
        "",
        "## Record shape",
        "",
        "One JSON collection_record per LEGITEXT (code, law, or regulation). "
        "`id` is `fr-LEGITEXT…`. `documents[]` holds in-force articles "
        "(ETAT VIGUEUR / VIGUEUR_DIFF). `text` is the concatenated consolidated body. "
        "JSON is compact (not indent=2) so the France shard stays under ~25 GB.",
        "",
        "Historical article versions (MODIFIE, ABROGE, …) and `*_non_vigueur` trees are omitted.",
        "",
        "## Notes",
        "",
        "- Dataset is not legal advice (`metadata.rights.not_legal_advice: true`).",
        "- Consolidated Légifrance texts are informative; the Journal officiel remains authentic.",
        "",
    ]
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("wrote %s files=%s bytes=%.1fMB", summary, n_files, inst_bytes / 1e6)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tars", nargs="+", type=Path)
    ap.add_argument("--root", type=Path, default=Path("/workspace/legal-corpora/fr"))
    ap.add_argument("--overlay", action="store_true", help="Merge into existing JSON (incrementals)")
    ap.add_argument("--include-non-vigueur", action="store_true")
    ap.add_argument("--max-gb", type=float, default=24.0)
    args = ap.parse_args()
    root: Path = args.root
    (root / "instruments").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    setup_logging(root / "logs" / "collector.log")
    retrieved = utcnow()
    resume = load_index_ids(root / "index.jsonl")
    log.info("start retrieved_at=%s resume_ids=%s overlay=%s root=%s", retrieved, len(resume), args.overlay, root)
    col = Collector(
        root=root,
        retrieved_at=retrieved,
        resume_ids=resume,
        include_non_vigueur=args.include_non_vigueur,
        overlay=args.overlay,
        max_bytes=int(args.max_gb * 1024 ** 3),
    )
    dumps: List[str] = []
    blockers: List[str] = []
    for i, p in enumerate(args.tars):
        if not p.exists():
            blockers.append(f"missing dump {p}")
            log.error("missing %s", p)
            continue
        overlay = args.overlay or i > 0
        try:
            col.process_tar(p, overlay=overlay)
            dumps.append(p.name)
        except Exception as exc:
            blockers.append(f"failed {p.name}: {exc}")
            log.exception("failed processing %s", p)
    extra = {
        "blockers": blockers,
        "dump_bytes": sum((p.stat().st_size for p in args.tars if p.exists()), 0),
        "remainder": [
            "Historical (*_non_vigueur*) texts omitted to keep current consolidations under ~25 GB.",
            "Historical article versions (MODIFIE/ABROGE/…) omitted; documents[] is the current consolidated text.",
            "Daily incrementals after 2025-07-13 were listed but not downloaded in this run.",
        ],
        "incrementals": [],
    }
    inc_list = Path("/workspace/legal-corpora/fr/tmp/incrementals.txt")
    if inc_list.exists():
        extra["incrementals"] = [ln.strip() for ln in inc_list.read_text().splitlines() if ln.strip()][:20]
        extra["incrementals"].append(f"… {sum(1 for ln in inc_list.read_text().splitlines() if ln.strip())} incremental dumps listed, none applied")
    write_summary(root, col, dumps, extra)
    log.info("index.jsonl is append-only; not rebuilt. records=%s", col.n_records)
    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(main())
