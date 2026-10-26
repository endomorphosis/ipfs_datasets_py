import pickle,re,json,collections
from urllib.parse import urlparse, unquote
rows=pickle.load(open('rows.pkl','rb'))
MARK=re.compile(r'(§|\bSection\s+\d|\bSec\.\s*\d|\bChapter\s+[\dIVX]|\bRule\s+\d|\bR\.\s*\d|Admin(istrative)?\.? Code|\b\d{1,3}-\d{1,3}-\d|\bARM\b|\bOAR\b|\bNAC\b|\bCMR\b|\bRICR\b|\bTitle\s+\d+)',re.I)
REF=r'wikipedia\.org|newworldencyclopedia\.org|worldatlas\.com'
STAT=[r'capitol\.hawaii\.gov/hrscurrent', r'legis\.la\.gov/legis/law\.aspx', r'malegislature\.gov/laws/generallaws',
      r'app\.leg\.wa\.gov/rcw', r'sdlegislature\.gov/(api/)?statutes', r'revisor\.mn\.gov/statutes', r'revisor\.mo\.gov/main/onechapter',
      r'code\.wvlegislature\.gov', r'cga\.ct\.gov/current/pub/titles', r'gencourt\.state\.nh\.us/rsa', r'kslegislature\.org/.*/statute',
      r'ilga\.gov/legislation/ilcs', r'delcode\.delaware\.gov', r'rilin\.state\.ri\.us/statutes', r'leg\.state\.fl\.us/(statutes|index\.cfm\?mode=(constitution|search%20statutes))',
      r'leg\.state\.nv\.us/nrs', r'ncleg\.gov/laws/generalstatutestoc', r'scstatehouse\.gov/code/statmast', r'docs\.legis\.wisconsin\.gov/statutes',
      r'code\.dccouncil\.gov', r'legislature\.mi\.gov/search/executesearch', r'law\.justia\.com/codes', r'mgaleg\.maryland\.gov/mgawebsite/laws/statute', r'codes\.ohio\.gov/ohio-(revised-code|constitution)']
BILL=r'billstatus\.ls\.state\.ms\.us|vetobook'
CHAMBER=r'malegislature\.gov/laws/rules/|nebraskalegislature\.gov/floordocs/current/pdf/rules/rulebook'
NONLEGAL=[r'(^|\.)tn\.gov/(bop|business|directory|government|hr|news)', r'sos\.tn\.gov/(civics|elections)', r'capitol\.tn\.gov/legislation/archives',
  r'georgia\.gov/(agency-list|organization)', r'dol\.georgia\.gov', r'pels\.georgia\.gov', r'mvdb\.virginia\.gov', r'commonwealth\.virginia\.gov', r'virginia\.gov/state-government',
  r'newsroom\.ky\.gov', r'alaska\.gov/(akdir1|employeehome)', r'doa\.alaska\.gov', r'dos\.fl\.gov/(about|library)', r'rules\.utah\.gov/(about|contact|help|rulesnews|category|publications/(code-updates|executive)|administrative-rules-(dashboard|register)|[a-z]+-\d+-\d{4}-issue)',
  r'oal\.ca\.gov/publications', r'arkleg\.state\.ar\.us/committees', r'ncleg\.gov/committees', r'nebraskalegislature\.gov/reports', r'legislature\.vermont\.gov/committee',
  r'legislature\.idaho\.gov/sessioninfo/.*/adminrules', r'legis\.nd\.gov/files/resource/miscellaneous/adminrulesdraftingmanual', r'leg\.state\.fl\.us/cgi-bin/view_page',
  r'commerce\.mt\.gov/about', r'montanaheritagecommission', r'fwp\.mt\.gov/binaries/content/assets/fwp/aboutfwp', r'sos\.vermont\.gov/.*/newspapers-of-record',
  r'ndlegis\.gov/library-and-research', r'content\.leg\.colorado\.gov/publication-search', r'leg\.state\.nv\.us/law1', r'in\.gov/core/index', r'rules\.utah\.gov/utah-administrative-code']
OFFPLACE={'smcgov.org':'NC','energy.ca.gov':'NH'}
NAV=r'/(search|home|default\.aspx|index\.html?|toc|allcode|agencies|organizations|register|code)/?$|/search(\?|/|\.)|interface=(landing_page|search_tac)|nmac-titles/?$|nmac-home/?$|/gac/\d+$|ohio-administrative-code$|agency-rules|policies$|browse/home/california/californiacodeofregulations|adminsearch(/pages/default\.aspx)?/?$|checkrule|listagencies|agency-rules/north-dakota-administrative-code/index|laws/statutes?$|statutetext$|/law$|/rules/administrative$|search\.php|chapterhome|jcar/admincode$|index\.cfm\?tab=statutes'
def classify(r):
    u=r['source_url']; ul=unquote(u).lower(); em=r['em']
    m=re.match(r'^https?://web\.archive\.org/web/\d+[a-z_]*/(.+)$',u)
    inner=m.group(1) if m else u; il=unquote(inner).lower()
    pr=urlparse(inner if inner.startswith('http') else 'http://'+inner.lstrip('/:'))
    host=pr.netloc.lower(); path=pr.path.rstrip('/')
    t=r['text'] or ''; title=(r['title_native'] or '')
    if 'huggingface.co' in host: return None
    if re.search(REF,il): return 'reference_site','encyclopedia/atlas page, not a rule'
    for d,sc in OFFPLACE.items():
        if d in il: return 'off_place','page belongs to another jurisdiction (%s), not US-%s'%(host,r['place_id'][-2:])
    if title.strip().lower()=='not found' or (len(t)<150 and not re.search(r'\d',t.replace(r['place_id'][-2:],''))) : return 'error_or_stub','error/placeholder page (%d chars)'%len(t)
    if re.search(BILL,il): return 'legislative_bill','bill status/veto document, not an enacted rule'
    if re.search(CHAMBER,il): return 'legislative_chamber_rules','rules of a legislative chamber, not agency administrative rules'
    for p in STAT:
        if re.search(p,il): return 'statute','statute/code of laws page (%s), not an administrative rule'%host
    for p in NONLEGAL:
        if re.search(p,il): return 'nonlegal_gov_page','government info/news/directory/meta page (%s), no rule text'%host
    if path=='' or path.lower() in ('/home','/main/home.aspx','/public/home'): return 'homepage','site homepage (%s)'%host
    if re.search(NAV,il): return 'navigation_or_toc','search/landing/table-of-contents page, no rule text'
    return None
if __name__=='__main__':
    out=[]
    for r in rows:
        c=classify(r)
        if c: out.append((r,c))
    print(len(out)); print(collections.Counter((('U' if r['em']['legislation_type']=='untyped_agentic_web_capture' else 'T'),c[0]) for r,c in out))
    pickle.dump([(r['place_id'],r['doc_id'],c) for r,c in out],open('drops.pkl','wb'))
    with open('drops.tsv','w') as f:
        for r,c in sorted(out,key=lambda x:(x[1][0],x[0]['source_url'])): f.write('\t'.join([c[0],r['place_id'][-2:],r['em']['legislation_type'][:6],str(len(r['text'])),r['source_url'][:100],(r['title_native'] or '')[:60].replace('\n',' ')])+'\n')
    with open('keep_untyped.tsv','w') as f:
        ds={x[1] for x in [(0,r['doc_id']) for r,c in out]}
        for r in rows:
            if r['em']['legislation_type']=='untyped_agentic_web_capture' and r['doc_id'] not in ds and 'secure.sos.state.or.us' not in r['source_url']:
                f.write('\t'.join([r['place_id'][-2:],str(len(r['text'])),str(len(MARK.findall(r['text']))),r['source_url'][:100],(r['title_native'] or '')[:60]])+'\n')
