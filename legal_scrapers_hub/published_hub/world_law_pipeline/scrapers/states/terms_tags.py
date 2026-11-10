"""Terms-policy tagging for sources whose site terms restrict reuse.
Decision (Benjamin, 2026-10-25 08:05 PT): "Collect live where reachable, tagged".
Every row from these sources gets: source_policy token 'terms_restrict_reuse', a license_note suffix with a short
summary + terms URL, and extra_metadata.terms_policy {restricts_reuse, summary, quote, terms_url, checked, decision}."""
import json

DECISION = "Benjamin 2026-10-25 08:05 PT: collect live where reachable, tagged"
TOKEN = "terms_restrict_reuse"

TERMS = {
    "us_dc_code": dict(
        terms_url="https://code.dccouncil.gov/robots.txt",
        summary="DC Council code site robots.txt: crawling allowed (Allow: /) but Content-Signal search=yes, ai-train=no.",
        quote="Content-signal: search=yes,ai-train=no",
        checked="2026-10-25"),
    "us_nm_nmsa": dict(
        terms_url="https://www.nmcompcomm.us/scope-of-coverage-2/",
        summary="NMSA 1978 via NMOneSource: New Mexico Compilation Commission claims copyright, all rights reserved; free public access, no reuse licence.",
        quote="© Copyright New Mexico Compilation Commission All Rights Reserved",
        checked="2026-10-25"),
    "ca_nl_assembly": dict(
        terms_url="https://www.assembly.nl.ca/CopyrightPrivacyStatement.aspx",
        summary="House of Assembly NL: content protected by copyright; permission only to excerpt and cite (education, research, etc.); commercial use needs the Speaker's written approval.",
        quote="Use of publications, web content, or portions thereof, for commercial purpose or financial gain requires the express written approval of the Speaker of the House of Assembly.",
        checked="2026-10-25"),
    "us_co_crs": dict(
        terms_url="https://content.leg.colorado.gov/agencies/office-legislative-legal-services/colorado-revised-statutes",
        summary="Colorado OLLS offers the C.R.S. title downloads 'for personal use'; C.R.S. 2-5-115 declares the statutes the sole property of the state.",
        quote="You may download DOCX, PDF, or HTM copies of the Colorado Revised Statutes for personal use",
        checked="2026-10-25"),
    "us_ky_krs": dict(
        terms_url="https://legislature.ky.gov/policies-security/Pages/default.aspx",
        summary="Kentucky LRC site terms: access subject to terms; commercial use of records requires an agreement with the LRC (KRS 61.874).",
        quote="Under KRS 61.874, it is unlawful to use any records available on this site for a commercial purpose without agreement with the Legislative Research Commission.",
        checked="2026-10-25"),
    "_kenyalaw": dict(
        terms_url="https://new.kenyalaw.org/terms-of-use/",
        summary="Kenya Law terms: scraping, unauthorized bots and bulk downloading prohibited (bulk access by email request); robots.txt Content-Signal ai-train=no.",
        quote="Scraping, deployment of unauthorized bots and bulk downloading from this website is strictly prohibited.",
        checked="2026-10-25"),
    "my_13_lawnet": dict(
        terms_url="https://lawnet.sarawak.gov.my/lawnet/",
        summary="Sarawak LawNet: 'Copyright 2011 Sarawak Government. All Rights Reserved'; no reuse licence; no statutory-text exception in Malaysian copyright law.",
        quote="Copyright 2011 Sarawak Government. All Rights Reserved.",
        checked="2026-10-25"),
    "pk_ba_code": dict(
        terms_url="https://balochistancode.gob.pk/",
        summary="Balochistan Code site footer: all rights reserved by the Law & Parliamentary Affairs Department Balochistan; no reuse licence.",
        quote="All rights reserved by Law & parliamentary affairs department Balochistan",
        checked="2026-10-25"),
    "ae_du_dlp": dict(
        terms_url="https://dlp.dubai.gov.ae/en/Pages/TermsAndConditions.aspx",
        summary="Dubai Legislation Portal terms: material may be used for personal use and/or research only; no republishing or redistribution.",
        quote="you may download, store and/or use the Portal material for your own personal use and/or research purposes only. You may not, however, republish, retransmit, redistribute or otherwise make the material available to any other party",
        checked="2026-10-25"),
    "ae_az_gazette": dict(
        terms_url="https://www.abudhabi.gov.ae/en/terms-of-use",
        summary="Abu Dhabi Government website terms: content owned by the Media Office; downloading, reproduction, republication or distribution without express written consent is prohibited.",
        quote="Any downloading, reproduction, republication, extraction, modification, copying, distribution, transmission, display or sale of Content or any other part of the Website without the express written consent of The Media Office for any purpose is strictly prohibited.",
        checked="2026-10-25"),
    "ca_ns_regs": dict(
        terms_url="https://novascotia.ca/just/regulations/consregs.htm#disclaimer",
        summary="Nova Scotia Registry of Regulations: consolidations are unofficial, for reference only; the disclaimer must not be removed (kept in the text). The Legislature's statute site states its content is for convenience and personal use only.",
        quote="This consolidation is unofficial and is for reference only.",
        checked="2026-10-25"),
    "ca_pe_pdf": dict(
        terms_url="https://www.princeedwardisland.ca/en/information/executive-council-office/website-disclaimer-and-copyright-policy",
        summary="PEI Government copyright policy: one unmodified non-commercial copy without permission; additional copies need permission; commercial reproduction needs prior written permission. PDFs are office consolidations for reference only.",
        quote="This website (and materials on it) may not be copied and/or distributed for commercial purposes without prior written permission",
        checked="2026-10-25"),
    "us_me_mrs": dict(
        terms_url="https://legislature.maine.gov/statutes/",
        summary="Maine Revisor of Statutes: the State of Maine claims a copyright in its codified statutes (all rights reserved); republication must carry the State's disclaimer (kept at the end of each chapter text) and the Revisor asks for a copy of any publication.",
        quote="The State of Maine claims a copyright in its codified statutes. If you intend to republish this material, we require that you include the following disclaimer in your publication",
        checked="2026-10-26"),
    "ca_sk_freelaw": dict(
        terms_url="https://publications.saskatchewan.ca/#/freelaw/content/copyright",
        summary="Saskatchewan King's Printer holds copyright in all legislation; release of copyright only on written request, and does not authorize unlimited reproduction.",
        quote="In exceptional circumstances, copyright may be released ... This does not, however, authorize unlimited photocopying or reproduction.",
        checked="2026-10-25"),
}


def _lookup(key):
    if key in TERMS:
        return TERMS[key]
    for k, v in TERMS.items():
        if k.startswith("_") and key.endswith(k):
            return v
    return None


def tag(rec, key):
    t = _lookup(key)
    if not t or rec is None:
        return rec
    toks = [x for x in (rec.get("source_policy") or "").split(";") if x]
    if TOKEN not in toks:
        toks.append(TOKEN)
    rec["source_policy"] = ";".join(toks)
    note = f"TERMS RESTRICT REUSE: {t['summary']} Terms: {t['terms_url']}"
    ln = rec.get("license_note") or ""
    if "TERMS RESTRICT REUSE" not in ln:
        rec["license_note"] = (ln + " | " + note) if ln else note
    em = rec.get("extra_metadata")
    if isinstance(em, str):
        em = json.loads(em or "{}")
    em = dict(em or {})
    em["terms_policy"] = dict(restricts_reuse=True, decision=DECISION, **t)
    rec["extra_metadata"] = em
    return rec


def wrap(cls):
    """Subclass an adapter so every fetched record is tagged."""
    key = cls.key
    orig = cls.fetch

    def fetch(self, sess, it):
        rec, st = orig(self, sess, it)
        return tag(rec, key), st
    return type(cls.__name__, (cls,), {"fetch": fetch, "__doc__": cls.__doc__})
