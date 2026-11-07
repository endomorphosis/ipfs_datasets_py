#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# States lane (CA+AU+CH+IT) status: rows per place (staging + processed), review holds, process health, discovery progress.
S=${WORLD_LAW_ROOT}/staging/states; P=${WORLD_LAW_ROOT}/processed; L=$S/_logs; D=${WORLD_LAW_ROOT}/pipeline/scrapers/states/data
echo "== $(date '+%F %T %Z')   disk free: $(df -h / | awk 'NR==2{print $4}')   mem avail: $(free -m | awk 'NR==2{print $7}') MB"
echo "== rows per place (staged + processed)"
for p in AU-QLD AU-TAS AU-NT AU-ACT AU-NSW AU-SA AU-VIC CA-ON CA-MB CA-NB CA-NT CA-BC CA-AB CA-QC CA-YT; do
  n=$(find $S/AU $S/CA $P -name "iso_$p.*.jsonl" 2>/dev/null -exec cat {} + | wc -l)
  [ "$n" -gt 0 ] && printf "  %-7s %6d\n" $p $n
done
echo "== published + pruned from processed/ (Hub-verified; not in the local counts)"
${WORLD_LAW_ROOT}/pipeline/venv/bin/python ${WORLD_LAW_ROOT}/pipeline/scrapers/states/published_counts.py 2>/dev/null
echo "== CH cantons (LexFind; staged + processed)"
line=""; tot=0
for c in ZH BE LU UR SZ OW NW GL ZG FR SO BS BL SH AR AI SG GR AG TG TI VD VS NE GE JU; do
  n=$(find $S/CH $P -name "iso_CH-$c.*.jsonl" 2>/dev/null -exec cat {} + | wc -l); tot=$((tot+n)); line="$line $c=$n"
done
echo " $line   total=$tot"
echo "  ch_full: $(tail -n1 $L/ch_full.out 2>/dev/null)"
[ -s $L/DISK_FLOOR_HIT.log ] && echo "!! DISK FLOOR HIT (writers paused): $(tail -n1 $L/DISK_FLOOR_HIT.log)"
echo "  staged files not yet uploaded (HF stalled): $(find $S -path $S/_review -prune -o -name '*.jsonl' -newer $S/_logs -print 2>/dev/null | wc -l) recent; states staging size $(du -sh $S 2>/dev/null | cut -f1)"
echo "== IT regions (staged + processed)"
for c in 65 77 78 72 45 36 62 42 25 57 67 21 75 88 82 52 32 55 23 34 BZ TN; do
  n=$(find $S/IT $P -name "iso_IT-$c.*.jsonl" 2>/dev/null -exec cat {} + | wc -l)
  [ "$n" -gt 0 ] && printf "  IT-%-3s %6d\n" $c $n
done
echo "== held in _review"
echo "  review_holds.tsv (held by design / in progress; routine checks: do not re-dispatch these):"
grep -v "^#" $S/_state/review_holds.tsv 2>/dev/null | awk -F"\t" '{printf "    %-48s %-20s %s\n", $1, $2, substr($3,1,140)}'
ls $S/_review/CA $S/_review/AU $S/_review/CH $S/_review/IT 2>/dev/null | grep jsonl | sed 's/^/  /'
echo "== processes"
for pat in "run_full.py --source" "ch_full.sh" "ch_resume.sh" "act_on_cdx.sh" "cdx_list.py" "act_after_cdx.sh" "archive_discovery.sh" "archive_tests.sh" "archive_discovery_loop.sh" "on_regs_rerun.sh" "tos_post2020.py" "tos_after.sh"; do
  pgrep -fa "$pat" | grep -v pgrep | sed 's/^/  /' | cut -c1-140
done
echo "== latest log lines"
for f in full_ca_on_elaws_regs full_ca_on_elaws_regs2 test_au_act_leg full_au_act_leg full_it_tos_raccolta full_it_lom_crl full_it_er_demetra full_it_cal_crc full_it_laz_crl full_it_fvg_lexview full_it_mar_crm full_it_sar_bdg full_it_tn_codprov full_it_pug_bussola full_it_tos_raccolta_post2020 $(cd $L; ls full_ch_lexfind_*.out -t 2>/dev/null | head -1 | sed 's/\.out$//') $(cd $L; ls test_*_archive.out full_*_archive.out 2>/dev/null | sed 's/\.out$//'); do
  [ -f $L/$f.out ] && echo "  $f: $(grep -v 'paused\|waited' $L/$f.out | tail -n1 | cut -c1-170)"
done
echo "== discovery (Wayback CDX)"
for f in act_a_cdx act_sl_cdx on_regulation_cdx_extra archive/nsw archive/qc archive/bc archive/yt archive/ab archive/sa archive/vic; do
  [ -e $D/$f.txt ] && echo "  $f: $(wc -l < $D/$f.txt) lines" || echo "  $f: pending"
done
echo "  parts done: $(ls $D/cdx_parts/*.txt 2>/dev/null | wc -l); wayback breaker: $(python3 -c "import json;print(json.load(open('${WORLD_LAW_ROOT}/pipeline/archive/_ratelimit/wayback.breaker.json'))['state'])")"
echo "== IN/AT/ID/DE (archive + Bremen live; staged + processed)"
for c in IN AT ID; do echo "  $c: $(find $S/$c $P/states/$c -name '*.jsonl' 2>/dev/null -exec cat {} + | wc -l) rows"; done
for p in DE-HB DE-BY DE-SH DE-BE; do echo "  $p: $(find $S/DE $P/states/DE -name "iso_$p.*.jsonl" 2>/dev/null -exec cat {} + | wc -l) rows"; done
ls $S/_review/IN $S/_review/AT $S/_review/AR $S/_review/ID $S/_review/DE 2>/dev/null | grep jsonl | sed 's/^/  held: /'
for pat in "arch_states.py" "chain_full.sh" "de_hb.py" "de_juris_wb_probe.py" "us_gap_tests.sh" "us_gap_fulls.sh" "us_ky_resume.sh" "us_az_arch_queue.sh" "us_arch_states_queue.sh" "terms_full_queue2.sh" "cdx_list.py"; do pgrep -fa "$pat" | grep -v pgrep | sed 's/^/  /' | cut -c1-140; done
for t in in_state at_ris id_bpk_prov de_by_cc de_sh_wb de_be_wb; do f=$(ls -t $L/${t}_full*.log 2>/dev/null | head -1); [ -n "$f" ] && { ln=$(tail -c 30000000 $f | grep -a 'progress\|done' | tail -n1); [ -z "$ln" ] && [ -f ${f%.log}.lastprogress ] && ln=$(cat ${f%.log}.lastprogress); echo "  $t: $(echo "$ln" | cut -c1-170)"; }; done
echo "== federal expansion (AR/MY/ZA/NG/BE/AE)"
for p in AR-B AR-C AR-S AR-R AR-U AR-H AR-J AR-F ZA-WC ZA-EC BA-BIH BA-SRP BA-BRC IQ-KR; do c=${p%%-*}; echo "  $p: $(find $S/$c $P/states/$c -name "iso_$p.*.jsonl" 2>/dev/null -exec cat {} + | wc -l) rows"; done
for p in US-TX US-CA US-WA US-NC US-NJ US-VA US-MN US-WI US-MA US-UT US-NV US-IA US-OR US-CO US-KY US-AZ US-MO US-NE US-PA US-MD US-LA US-DE US-ME US-ND US-WY US-VT US-RI US-AK US-DC US-NM US-SC US-ID US-MI; do echo "  $p: $(find $S/US $P/states/US -name "iso_$p.*.jsonl" 2>/dev/null -exec cat {} + | wc -l) rows (staged, not yet pruned)"; done; for p in CA-NL CA-NS CA-SK CA-PE MY-13 PK-BA AE-DU AE-AZ; do echo "  $p: $(find $S/${p%%-*} $P/states/${p%%-*} -name "iso_$p.*.jsonl" 2>/dev/null -exec cat {} + | wc -l) rows (staged, not yet pruned)"; done
echo "  blocked/held: BE (EU lane), ZA LawLibrary (terms), AR SAIJ texts (terms), AE-DU/AE-AZ/AE-SH (terms), NG-LA (no free text), AR-M/AR-X (robots unreachable), MY-13 (licence: skipped), ZA-MP (backend key in page code: blocked), MX (asia_latam lane), ZA-GP/NC/KZN (no act texts listed), AR-V TDF (robots intent), PK-BA (rights reserved: skipped), AR-V live (archive later), AR-F (scans only)"
for f in $(cd $L; ls -t full_ar_*.out full_za_*.out test_ar_*.out test_za_*.out test_de_sh_wb.out 2>/dev/null | sed 's/\.out$//'); do echo "  $f: $(tail -n1 $L/$f.out | cut -c1-170)"; done
echo "  DE probe: $(wc -l < $S/_work/de_juris_probe/done.tsv 2>/dev/null) done, $(wc -l < $S/_work/de_juris_probe/deferred.tsv 2>/dev/null) deferred-log lines"
echo "== OCR manifest rows: $(cat $S/_scanned_pdfs_manifest.jsonl 2>/dev/null | wc -l)"
