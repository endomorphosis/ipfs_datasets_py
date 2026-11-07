"""Belgian Gerechtelijk Wetboek from Justel (ejustice.just.fgov.be, official Belgisch Staatsblad database). The Justel WAF rejected repeat requests, so only the single page fetched
(articles 1386-1675/27) is parsed from the cached HTML at rules/raw/intl_be_gw_1967101030.html; Parts I-IV are NOT collected. No WAF bypass. -> data/be/be_rules.jsonl"""
import sys, hashlib, html as H
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
def main():
    raw = open(f"{RAW}/intl_be_gw_1967101030.html", "rb").read(); sha = hashlib.sha256(raw).hexdigest(); h = raw.decode("latin1")
    h = h[h.find("<A NAME='Art."):]
    parts = re.split(r"(?=<A NAME='Art\.[^']+'[^>]*>Art\.)", h); rows = []; seen = {}
    for p in parts:
        m = re.match(r"<A NAME='Art\.([^']+)'", p)
        if not m: continue
        nr = m.group(1); body = p.split("<BR><BR>", 1)[0] if "<BR><BR>" in p else p[:20000]
        body = re.sub(r"(?i)<br\s*/?>", " ", body); body = re.sub(r"<[^>]+>", " ", body); body = H.unescape(body)
        body = re.sub(r"\s+", " ", body.replace("\xa0", " ")).strip(); body = re.sub(r"^Art\.\s*\S+\s*\.\s*", "", body)
        if len(body) < 8: continue
        seen[nr] = seen.get(nr, 0) + 1
        rows.append(dict(rule_id=f"be-gw-v-vi:Art. {nr}" + (f"~{seen[nr]}" if seen[nr] > 1 else ""), rule_set_id="be-gw-v-vi", court_id=None, jurisdiction="BE",
                         rule_set="Gerechtelijk Wetboek (Dutch consolidated text; partial: art. 1386-1675/27 only)", rule_number=f"Art. {nr}", title=None, text=body, effective_date=None, pdf_path=None, pdf_sha256=None,
                         source_sha256=sha, source_url="https://www.ejustice.just.fgov.be/cgi_loi/article.pl?language=nl&lg_txt=n&numac_search=1967101056&cn_search=1967101030", site_policy="robots_unreadable:waf_blocked_after_one_request",
                         retrieved_at=NOW(), license="Belgian official legislation (Auteurswet/Loi 30 juin 1994 art. 8: official texts not protected)", language="nl"))
    os.makedirs(f"{ROOT}/data/be", exist_ok=True); wjl(f"{ROOT}/data/be/be_rules.jsonl", rows); print("BE rules", len(rows))
if __name__ == "__main__": main()
