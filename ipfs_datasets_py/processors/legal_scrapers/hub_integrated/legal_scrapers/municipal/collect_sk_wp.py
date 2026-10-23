#!/usr/bin/env python3
"""WordPress city sites with a VZN post type, read through the public WP REST API (wp-json):
  mode 'regulations' (Banská Bystrica, Ružomberok, ...): /wp/v2/regulations, meta number/approved_at/declared_at/efficiency_from/
       valid_until/attachment_id, status from regulation_categories (účinné / zrušené / novelizácia);
  mode 'iq' (Žilina): /wp/v2/vzn, meta iq_number/iq_year/iq_approvalDate/iq_announcementDate/iq_validFrom/iq_validUntil/iq_documents,
       status from vzn__state (Schválené / Zrušené; Návrhy and Pripomienky skipped);
  mode 'plain' (Nitra): /wp/v2/vzn without meta; the PDF is the uploads link on the act page.
Usage: collect_sk_wp.py MODE BASE_URL MUNICIPALITY CODE OUT.jsonl"""
import json, re, sys, os, html as H
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_common import Polite, doc_text, clean, write_jsonl
mode, base, muni, code, outp = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3], sys.argv[4], sys.argv[5]
P = Polite(1.0)
strip = lambda s: re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
rest = {"regulations": "regulations", "iq": "vzn", "plain": "vzn"}[mode]
def jget(u): return json.loads(P.get(u)[0])
def allpages(path):
    out, page = [], 1
    while True:
        try: d = jget(f"{base}/wp-json/wp/v2/{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        except Exception as e:
            if page > 1 and "400" in str(e): break
            raise
        if not isinstance(d, list) or not d: break
        out += d
        if len(d) < 100: break
        page += 1
    return out
terms = {}
if mode == "regulations": terms = {t["id"]: t["slug"] for t in allpages("regulation_categories")}
if mode == "iq": terms = {t["id"]: t["name"] for t in allpages("vzn__state")}
items = allpages(rest)
print("discovered", len(items), flush=True)
out, errs, skipped = [], {}, {}
def media(mid):
    try: m = jget(f"{base}/wp-json/wp/v2/media/{mid}"); return m.get("source_url"), m.get("title", {}).get("rendered")
    except Exception: return None, None
for k, it in enumerate(items):
    try:
        title = strip(it["title"]["rendered"]); meta = it.get("meta") or {}
        ex = dict(wp_id=it["id"], wp_type=it["type"], wp_date=it["date"][:10])
        files = []
        if mode == "regulations":
            mb = it.get("meta_box") or meta
            cats = [terms.get(c, str(c)) for c in it.get("regulation_categories", [])]
            ex.update(reg_number=mb.get("number"), approved=mb.get("approved_at"), promulgated=mb.get("declared_at"), effective_from=mb.get("efficiency_from"),
                      valid_until=mb.get("valid_until"), register_status=cats, replaces=mb.get("replaces_regulation_id"))
            for a in mb.get("attachment_id") or []:
                if isinstance(a, dict): files.append((a.get("url"), a.get("title")))
                else: files.append(media(a))
        elif mode == "iq":
            st = [terms.get(c, str(c)) for c in it.get("vzn__state", [])]
            ex.update(reg_number=(f"{meta.get('iq_number')}/{meta.get('iq_year')}" if meta.get("iq_number") else None), approved=meta.get("iq_approvalDate") or None,
                      promulgated=meta.get("iq_announcementDate") or None, effective_from=meta.get("iq_validFrom") or None, valid_until=meta.get("iq_validUntil") or None, register_status=st)
            if any(re.match(r"(?i)návrh|pripomienk", s) for s in st) or re.match(r"(?i)návrh", title):
                skipped["proposal"] = skipped.get("proposal", 0) + 1; continue
            files = [media(m) for m in meta.get("iq_documents") or []]
            ex["appendixes"] = [media(m)[0] for m in meta.get("iq_appendixes") or []]
        else:
            h, _ = P.get(it["link"]); t = h.decode("utf-8", "replace")
            # document links only from the post body (the site menu links the city statute and other PDFs on every page)
            main_html = t[t.find('class="post__main"'):] if 'class="post__main"' in t else re.sub(r"(?s)<(header|nav|footer)[^>]*>.*?</\1>", " ", t)
            files = [(u, None) for u in dict.fromkeys(re.findall(r'href="(https?://[^"]+/wp-content/uploads/[^"]+\.(?:pdf|docx?))"', main_html, re.I))]
            body = strip(re.sub(r"(?s)<(script|style|header|footer|nav)[^>]*>.*?</\1>", " ", t))
            ex["page_text"] = body[:1500]
            num = re.search(r"č\.\s*(\d+\s*/\s*\d{2,4})", title); ex["reg_number"] = re.sub(r"\s", "", num.group(1)) if num else None
        files = [f for f in files if f and f[0]]
        if not files: skipped["no_file"] = skipped.get("no_file", 0) + 1; errs[it["link"]] = "no document file"; continue
        ex["files"] = [f[0] for f in files]
        main = files[0][0]
        rn = ex.get("reg_number")
        nid = ("vzn-" + re.sub(r"[^0-9a-z]+", "-", rn.lower()).strip("-")) if rn and not re.search(r"(?i)dodatok|novel", title) else it["slug"][:80]
        rec = dict(municipality=muni, municipality_code=code, native_id=nid, source_url=main, page_url=it["link"], title=title,
                   retrieved_at=None, text="", extras=dict(ex, status_source=f"{base} WP {rest} record"))
        data, dm = P.get(main, timeout=180)
        tt, how = doc_text(data, dm); rec["text"] = clean(tt); rec["extras"]["extraction"] = how; rec["retrieved_at"] = dm["retrieved_at"]
        out.append(rec)
    except Exception as e:
        errs[it.get("link", str(k))] = str(e)[:200]
    if k % 25 == 0: print(k, len(out), len(errs), flush=True)
write_jsonl(outp, out)
json.dump(dict(discovered=len(items), records=len(out), skipped=skipped, errors=errs), open(outp + ".stats.json", "w"), ensure_ascii=False, indent=1)
print("done", len(out), len(errs), skipped)
