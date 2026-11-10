#!/bin/bash
# Detached sequential HF import queue (one country at a time). Resumable: rerun to continue.
cd /workspace/world_law/staging/national/_hf_import
export OMP_NUM_THREADS=1 MALLOC_ARENA_MAX=2 HF_HUB_DISABLE_TELEMETRY=1
ORDER="IN BR DE GB IT KR CO PL PT BE HU RO UA ET CD TW VE CM CI MG AO MZ NE BF ML MW ZM TG SN TD SO ZW GN RW BJ BI TN SS HT DO GT HN NI SV CU BO PY SA YE IL JO LB PS KW OM QA AE EG DZ SD UG AF MM LA KH TL NP BT MN GE AM AZ MD BY BG HR BA RS ME MK AL SI SK CZ LT LV EE CY LU SR GY BB TT JM BS BZ PA CR LR SL GM GW GQ GA CG CF DJ ER KM CV ST SC MU MV MR LS SZ NA BW BN FJ PG SB VU WS TO KI TV PW MH NR CK KY BM AI MS TC KN AG LC VC DM GD EU"
MISSING=$(python3 -c "import json;print(' '.join(json.load(open('missing_ccs.json'))))")
for cc in $ORDER; do
  case " IN BR DE GB IT KR CO PL PT BE HU RO UA $MISSING " in *" $cc "*) ;; *) continue;; esac
  [ -f STOP ] && { echo "STOP file present"; exit 0; }
  AS=${HF_AS:-3000000000}; [ "$cc" = DO ] && AS=5000000000
  nice -n 10 prlimit --as=$AS /workspace/hf-venv/bin/python /workspace/world_law/pipeline/scrapers/national/hf_import/hf_import.py $cc
  [ $? -eq 3 ] && { echo "disk low, stopping queue"; exit 3; }
done
# leftovers missing but not in ORDER
for cc in $MISSING; do case " $ORDER " in *" $cc "*) ;; *) nice -n 10 prlimit --as=${HF_AS:-3000000000} /workspace/hf-venv/bin/python /workspace/world_law/pipeline/scrapers/national/hf_import/hf_import.py $cc;; esac; done
echo QUEUE_DONE
