import re
KW=re.compile(r"(employment opportunit|privacy policy|visitor|skip to|sitemap|copyright|accessibility|complain|you can |will now|learn more|click |read more|subscribe|cookie|forms? & fees|copies of|official information|\bact \d{4}|disclaimer|terms of use|contact us|download|e-?filing|directions? to|periodic review|procedure for)",re.I)
STREET=re.compile(r"\b(street|st\.?|road|rd\.?|avenue|ave\.?|drive|dr\.?|boulevard|blvd\.?|lane|ln\.?|way|place|pl\.?|court|square|highway|hwy\.?|suite|ste\.?|floor|po box|p\.?o\.? box|box|parade|terrace|crescent|plaza|center|centre|building|bldg|rue|avenue|calle|route|pkwy|parkway|mall|circuit|close|esplanade|broadway|main|room|rm)\b",re.I)
ZIP=re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b|\b[A-Z]\d{2} ?[A-Z0-9]{4}\b|\b\d{4}\b ?[A-Z]{0,3}|\b\d{4,5}(-\d{4})?\b|\b[A-Z]\d[A-Z] ?\d[A-Z]\d\b")
EXTRACT=re.compile(r"\b(\d{1,5}[A-Za-z]?(?:[-–/]\d{1,5})?,?\s+[A-Za-z0-9.'#&\- ]{3,60}?(?:,\s*|\s)[A-Za-z .'\-]{2,30}?,?\s+(?:[A-Z]{2,3}|Qld|NSW|Vic|Tas|NT|ACT)\.?\s+\d{4,5}(?:-\d{4})?)")
def addr_like(a):
    return bool(re.search(r"\d",a)) and bool(STREET.search(a) or ZIP.search(a))
def is_junk(a):
    if not a: return False
    if len(a)>120: return True
    if KW.search(a): return True
    if not addr_like(a) and len(a)>40: return True
    return False
def clean(a):
    m=EXTRACT.search(a)
    if m and not re.search(r'(p\.?\s?o\.?\s*)?box\s*$',a[:m.start()],re.I) and len(m.group(1))<=100 and not KW.search(m.group(1)): return m.group(1).strip(' ,')
    return None
FALLBACK=re.compile(r"\b(\d{1,5}[A-Za-z]?\s[^|]{5,90}?\b[A-Z]{2}\.?,?\s\d{5}(?:-\d{4})?)")
_orig_clean=clean
def clean(a):
    c=_orig_clean(a)
    if c: return c
    m=FALLBACK.search(a)
    if m and len(m.group(1))<=100 and not KW.search(m.group(1)) and not re.search(r'(p\.?\s?o\.?\s*)?box\s*$',a[:m.start()],re.I):
        return m.group(1).strip(' ,')
    return None
LEAD=re.compile(r"^(contact us|physical address:?|address:?|accessibility|location:?|courthouse address:?|map\b[^A-Z]*|visit us:?)\s*",re.I)
NAMEOK=re.compile(r"^[A-Z][\w .,'&()\-]{3,80}$")
COURTWORD=re.compile(r"\b(court|courthouse|court house|justice|judicial|tribunal|law courts|palais de justice|county building)\b",re.I)
def recover_name(a):
    """name = text before the first street number/PO box, if it reads like a court name"""
    m=re.search(r"\b(\d{1,5}[A-Za-z]?\b|P\.?\s?O\.?\s*Box)",a)
    if not m or m.start()<4: return None
    pre=a[:m.start()].strip(' ,:-')
    for _ in range(3): pre=LEAD.sub('',pre).strip(' ,:-')
    if NAMEOK.match(pre) and COURTWORD.search(pre) and not KW.search(pre) and not re.search(r"\bAct\b",pre) and len(pre.split())<=10:
        return pre
    return None
