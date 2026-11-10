import json,re,urllib.request,time,sys
from us_state_judiciaries import STATES
from robots_policy import UA
bad=sys.argv[1:]
for st in bad:
    home=STATES[st][0]
    try:h=urllib.request.urlopen(urllib.request.Request(home,headers={"User-Agent":UA}),timeout=20).read().decode("utf-8","replace")
    except Exception as e: print(st,"HOME_ERR",e);continue
    links=set(re.findall(r'href="([^"#]+)"[^>]*>([^<]{0,80})',h))
    hits=[(u,t.strip()) for u,t in links if re.search(r'locat|director|find.{0,6}court|courthouse|county',u+t,re.I)]
    print(st,hits[:8]);time.sleep(1)
