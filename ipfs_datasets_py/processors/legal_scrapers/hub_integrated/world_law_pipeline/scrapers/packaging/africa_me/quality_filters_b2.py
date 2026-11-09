"""Tightened new-row filters for Africa/MENA batch 2 (after the Verifier audit, 2026-10-16).
reject(row) -> list of reasons; empty list = acceptable as a single law instrument.
Rejects news/press items, speeches, reports/plans, forms/notices/tenders, bills/drafts, court rulings,
personnel extracts, web stubs, budget tables and whole gazettes (> MAX_CHARS chars, or a gazette issue
carrying several instruments). title_problem(title) -> reasons a title is body text / generic / OCR soup."""
import re
MAX_CHARS = 200_000
NON = [
 ("news_press", r"(?i)(for immediate release|press release|communiqu[eé] de presse|nota informativa|nota de imprensa|gabinete de comunica|newspaper review|press review|revue de presse|presse nationale|bulletin d.informations du gouvernement|les d[eé]put[eé]s adoptent|l.assembl[eé]e nationale adopte|grandes orientations du budget|acaba de depositar|breaking news|news agency)"),
 ("speech", r"(?i)(keynote address|goodwill (address|message)|inputs to the keynote|discours de|allocution de|budget speech|address by (his|her) excellency|remarks by)"),
 ("report_plan", r"(?i)(report and financial statements|annual report|rapport annuel|rapport de la commission|rapport d.ex[eé]cution|execution report|national action plan|policy brief|project fact sheet|report to the \d+\w* meeting|policy statement|government budget\s+for the fiscal|consultative forum|le parlementarisme depuis|relat[oó]rio (anual|de actividades|de atividades))"),
 ("parl_question_vote", r"(?i)(private notice question|parliamentary question|resultados? d[ae]s? vota[cç]|ordem do dia)"),
 ("bill_draft", r"(?i)(\bBILL\s*,?\s*\(?No\.|\ba bill for an act\b|explanatory memorandum|memorandum of objects and reasons|lei n\.o _+|projet de loi|proposition de loi|proposta de lei|projeto de lei|proyecto de ley|draft (bill|law|regulations?|decree)|مشروع قانون)"),
 ("tender_form_notice", r"(?i)(procurement notice|invitation (for|to) bids?|request for (bids|proposals|quotations)|expression of interest|information request notice|nomination form|application form|application for registration|appendix \d+\s+form|formulaire de|avis d.appel d.offres)"),
 ("court", r"(?i)(ac[oó]rd[aã]o n\.?\s?o|tribunal constitucional\s+ac[oó]rd|supreme court strikes|judgment of the|arr[eê]t n[°o]\s?\d+.{0,40}cour)"),
 ("budget_table", r"(?i)(budget general rectificatif|nature des charges lfi|liste des contrats et conventions)"),
 ("web_stub_spam", r"(?i)(lorem ipsum|programas para espiar|let.s find what you.re looking for|القرارات والتعاميم - CMA|freedom of information portal|log ?in to your account|forgot your password)"),
 ("guide_manual", r"(?i)(ألية تعامل|الدليل(?! الرقمي)|guide pratique|user guide|tax guide)"),
 ("extract_personnel", r"(?i)(extrato do contrato|extrato do despacho)"),
]
TITLE_NON = re.compile(r"(?i)(\bbills?\b|\bdraft\b|projet de loi|proposta de lei|proposition de loi|press release|communiqu[eé]|\bnews\b|\breport\b|\brapport\b|relat[oó]rio|\bforms?\b|formulaire|\bspeech\b|discours|tender notice|procurement notice|newsletter|nota informativa|^\s*journal officiel|^\s*boletim oficial|^\s*di[aá]rio da rep[uú]blica|^\s*official gazette|^\s*gazette\b|مشروع (قانون|نظام|قرار|لائحة))")
GAZ = re.compile(r"(?i)(J\s?OURNAL\s+OFF\S*\s*[-,']*\s*DE\s+LA\s+REPUBLIQUE|NUM[EÉ]R[O0]\S?\s+SP[EÉ]\S*|«\s*\d?o?\s*(SUP\.?\s*)?B\.\s?O\.\s*»|BOLETIM OFICIAL|DI[AÁ]RIO DA REP[UÚ]BLICA|BOLET[IÍ]N OFICIAL|OFFICIAL GAZETTE|GAZETTE EXTRAORDINARY|الجريدة الرسمية|الوقائع المصرية)")
TOCW = re.compile(r"(?i)\b(SUM[AÁ]RIO|SOMMAIRE|[IÍ]NDICE|CONTENTS)\b|الفهرس")
INSTR_HEAD = re.compile(r"(?im)^\s*(d[eé]cret|arr[eê]t[eé]|loi|ordonnance|lei|decreto(-lei)?|resolu[cç][aã]o|despacho|portaria|decree|act|statutory instrument|legal notice)\s+(n[°ºo.]*\s*|no\.?\s*)?([\d][\d\-/.A-Z]*)")
def n_instruments(text):
    return len({(m.group(1).lower()[:4], m.group(4)) for m in INSTR_HEAD.finditer(text or "")})
HEAD_ONLY = {"report_plan", "tender_form_notice", "guide_manual", "bill_draft", "parl_question_vote", "speech"}
def reject(row):
    t = row.get("text") or ""; ttl = row.get("title") or ""; why = []
    for k, p in NON:
        head = t[:250] if k in HEAD_ONLY else t[:2500]
        if re.search(p, head) or re.search(p, ttl): why.append(k)
    if TITLE_NON.search(ttl): why.append("title_nonlaw_keyword")
    nsum = len(re.findall(r"(?i)\b(d[eé]cret|arr[eê]t[eé]|loi|lei|decreto|resolu[cç][aã]o|despacho|portaria)\s+n", t))
    gz = bool(GAZ.search(t[:800]))
    ni = n_instruments(t)
    toc = bool(TOCW.search(t[:3000]))
    if gz and (len(t) > MAX_CHARS or (toc and ni >= 3 and nsum >= 6)): why.append("whole_gazette_issue")
    elif ni >= 3 and (len(t) > MAX_CHARS or (gz and toc)): why.append("multi_instrument")
    return sorted(set(why))
BADT = [
 ("title_body_or_generic", r"(?i)^\s*(vu\b|considérant|article\s+\d|artigo\s+\d|section\s+\d|based on the rules|act,? \d{4} would|\d{3,4}\s+journal|journal officiel|boletim oficial$|bolet[ií]n|commissions? act|communications act|بعد الاطلاع|المادة الأولى|ينفذ النظام|-\s)"),
 ("title_body_or_generic", r"(?i)^(BOLETIM OFICIAL|GDOrcamentoEstado|RSDPR en|July \d|DisplayPDF|DownloadAct|recherche)$|\s(en|En)$"),
 ("title_ocr_soup", r'[~�]|"""|\^|f6v|\?lDl|Rectfu'),
 ("title_filename_hash", r"^[0-9a-f]{3}\s+[0-9a-f]{8,}|\btcm\d+\b|\bv\d{2}\b.*\btcm"),
 ("title_decree_reference_only", r"^\s*(مرسوم ملكي|قرار مجلس الوزراء|قرار وزاري)\s+رقم\s*[\(\s]*م?\s*/?\s*[\d٠-٩]+[\s\)]*(بتاريخ|وتاريخ)[\s\d٠-٩/هـ]*$"),
]
def title_problem(title):
    t = title or ""; out = [k for k, p in BADT if re.search(p, t)]
    if len(t.strip()) < 6: out.append("title_too_short")
    return sorted(set(out))
