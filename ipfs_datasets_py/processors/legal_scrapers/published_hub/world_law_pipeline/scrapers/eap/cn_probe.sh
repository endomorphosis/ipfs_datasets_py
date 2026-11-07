#!/bin/bash
U="Mozilla/5.0 (compatible; world-law-research-bot; eap lane)"
for h in flk.npc.gov.cn www.gov.cn www.npc.gov.cn www.gz.gov.cn www.sz.gov.cn www.hangzhou.gov.cn www.wuhan.gov.cn www.chengdu.gov.cn www.nanjing.gov.cn www.xa.gov.cn www.qingdao.gov.cn www.xm.gov.cn www.nb.gov.cn www.gd.gov.cn www.zj.gov.cn; do
 r=$(timeout 20 curl -s -L -m 15 --connect-timeout 8 -A "$U" -o /tmp/rb_$h -w "%{http_code}" https://$h/robots.txt)
 echo "$h rc=$? http=$r $(head -c 90 /tmp/rb_$h 2>/dev/null | tr "\n\r" "  ")"
done
echo DONE
