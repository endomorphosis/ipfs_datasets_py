#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
U="Mozilla/5.0 (compatible; world-law-research-bot; eap lane)"
O=${WORLD_LAW_ROOT}/staging/eap/_eap_work/cn/probe2.tsv; : > $O
for h in www.hangzhou.gov.cn www.chengdu.gov.cn www.xa.gov.cn www.wuhan.gov.cn www.gd.gov.cn www.hzrd.gov.cn www.cdrd.gov.cn www.xard.gov.cn www.whrd.gov.cn www.rd.gz.cn www.shenyang.gov.cn www.changchun.gov.cn www.harbin.gov.cn www.taiyuan.gov.cn www.shijiazhuang.gov.cn www.hohhot.gov.cn www.jinan.gov.cn www.zhengzhou.gov.cn www.hefei.gov.cn www.nanchang.gov.cn www.changsha.gov.cn www.fuzhou.gov.cn www.nanning.gov.cn www.haikou.gov.cn www.guiyang.gov.cn www.km.gov.cn www.lasa.gov.cn www.lanzhou.gov.cn www.xining.gov.cn www.yinchuan.gov.cn www.urumqi.gov.cn www.suzhou.gov.cn www.wuxi.gov.cn www.changzhou.gov.cn www.tangshan.gov.cn www.dalian.gov.cn www.yantai.gov.cn www.weifang.gov.cn www.luoyang.gov.cn www.wenzhou.gov.cn www.jinhua.gov.cn www.shaoxing.gov.cn www.jiaxing.gov.cn www.taizhou.gov.cn www.xuzhou.gov.cn www.nantong.gov.cn www.yangzhou.gov.cn www.quanzhou.gov.cn www.ganzhou.gov.cn www.yichang.gov.cn www.xiangyang.gov.cn www.zhuzhou.gov.cn www.mianyang.gov.cn www.liuzhou.gov.cn www.baotou.gov.cn www.daqing.gov.cn www.jilin.gov.cn www.baoding.gov.cn www.linyi.gov.cn www.zibo.gov.cn; do
 for s in https http; do
  r=$(timeout 25 curl -s -L -m 20 --connect-timeout 8 -A "$U" -o /tmp/p2_$h -w "%{http_code}" $s://$h/robots.txt); rc=$?
  [ $rc -eq 0 ] && break
 done
 ct=$(head -c 200 /tmp/p2_$h 2>/dev/null | grep -qi '<html' && echo html || echo txt)
 dis=$(grep -iE '^\s*disallow:\s*/\s*$' /tmp/p2_$h 2>/dev/null | wc -l)
 g=$(timeout 25 curl -s -m 20 --connect-timeout 8 -A "$U" -o /dev/null -w "%{http_code}" $s://$h/gkmlpt/policy)
 printf "%s\t%s\t%s\t%s\t%s\t%s\tgkmlpt=%s\n" $h $s $rc $r $ct $dis $g >> $O
done
echo DONE >> $O
