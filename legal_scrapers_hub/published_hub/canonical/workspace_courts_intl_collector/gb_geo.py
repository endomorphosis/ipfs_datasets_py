"""GB subdivision from postcode + HMCTS page address parsing (JSON-LD first, then address block)."""
import re,json,html
SCT={'AB','DD','DG','EH','FK','G','HS','IV','KA','KW','KY','ML','PA','PH','TD','ZE'}
WLS_AREA={'CF','LL','NP','SA','LD'}
WTOWN=re.compile(r'\b(Cardiff|Swansea|Newport|Wrexham|Aberystwyth|Caernarfon|Mold|Llandudno|Merthyr|Haverfordwest|Carmarthen|Llanelli|Welshpool|Prestatyn|Port Talbot|Pontypridd|Cwmbran)\b')
PC=re.compile(r'\b([A-Z]{1,2})(\d[A-Z\d]?) ?(\d[A-Z]{2})\b')
def sub_from(postcode=None,text=''):
    m=PC.search((postcode or '').upper())
    if m:
        a,d=m.group(1),m.group(2); dn=int(re.match(r'\d+',d).group())
        if a=='BT': return 'GB-NIR','postcode'
        if a in SCT: return 'GB-SCT','postcode'
        if a in WLS_AREA or (a=='SY' and 15<=dn<=25) or (a=='CH' and 5<=dn<=8): return 'GB-WLS','postcode'
        return 'GB-ENG','postcode'
    if WTOWN.search(text or ''): return 'GB-WLS','town'
    return 'GB-ENG','default_no_postcode'
def parse_addresses(b):
    out=[]
    for blk in re.findall(r'(?s)<script[^>]*ld\+json[^>]*>(.*?)</script>',b):
        try: j=json.loads(blk)
        except Exception: continue
        for o in (j if isinstance(j,list) else [j]):
            a=o.get('address') if isinstance(o,dict) else None
            for x in (a if isinstance(a,list) else [a] if a else []):
                out.append(dict(street=x.get('streetAddress'),locality=x.get('addressLocality'),postal_code=x.get('postalCode'),kind='jsonld'))
    if not out:
        for p in re.findall(r'(?s)<p class="govuk-body-m address">(.*?)</p>',b):
            parts=[html.unescape(re.sub(r'<[^>]+>','',x)).strip() for x in re.split(r'<br\s*/?>',p)]
            parts=[x for x in parts if x]
            if not parts: continue
            pc=parts[-1] if PC.search(parts[-1].upper()) else None
            body=parts[:-1] if pc else parts
            out.append(dict(street=', '.join(body[:-1]) or None,locality=body[-1] if body else None,postal_code=pc,kind='address_block'))
    m=re.search(r'maps\?q=(-?\d+\.\d+),(-?\d+\.\d+)',b)
    ll=(float(m.group(1)),float(m.group(2))) if m else (None,None)
    return out,ll
