# Africa + Middle East lane progress (updated 2026-10-10 16:05 PT)

## Resume instructions
- Helper (DONE, tested on joradp.dz): ~/.ipfs_datasets/legal_collectors/common_crawl_helper.py + README_COMMON_CRAWL_HELPER.md
- Pipeline: ~/.ipfs_datasets/legal_collectors/africa_me_cc/{domains.py,build_pack.py,run_worker.sh}; logs worker_A.log / worker_B.log
- Restart workers (skip finished packs automatically; max 2):
  cd ~/.ipfs_datasets/legal_collectors/africa_me_cc && nohup ./run_worker.sh A <CCs> & ; nohup ./run_worker.sh B <CCs> &
  Worker A list: KW LB AE ER SZ LY SO GA LS GM GH BJ BW SL CV KM CG SN MU DJ TG ML
  Worker B list: SY YE BH IQ SD DZ CI BI SS GQ CF TD TZ NE GN ST SC UG BF LR MZ CD CM GW MG
- Packs: ~/.ipfs_datasets/legal_collectors/ready_africa_me_cc_packs_20261010/<cc>/ (data/laws.parquet, articles.parquet, provenance, MANIFEST.json). NOT uploaded (Chief of Staff owns HF).
- Do-not-touch: BO AZ AL AO DO ET IR MW ZM LA LK TN RS IT RO SI BG CY.
- To-do at end: re-run KW SY YE BH LB AE IQ ER SZ SD (built before the Arabic article regex relax / strong gate tweaks) by deleting their pack dir then run_worker.
- SendToAgent tool is NOT available to this executor; milestone messages are written to handoffs/20261010_*.txt for the parent to relay.

## Packs done so far (laws/articles)
KW 107/682, LB 253/997, AE 151/2345, ER 2/0, SZ 107/642, SY 91/1816, YE 184/511, BH 199/346, IQ 137/802, SD 55/57, DZ 195/10853
In progress: LY, CI, ML, MG ...
## Resource status
Mem avail ~10-11 GiB, disk free ~27 GiB (limits 3.5 / 20) OK.

## Update 16:55 PT
Packs present (30): ae bh bi bj bw cf ci cv dz er ga gh gm gn gq iq kw lb ls ly ne sd sl so ss sy sz td tz ye. In progress: ST, KM (worker A/B).
MEM BREACH: MemAvailable ~1.5 GiB caused by a NON-lane process (hf-venv logs/tip31zg_exec_verify.py, ~10 GB RSS, pid 775571). Lane build_pack procs (ST, KM; ~140 MB each) SIGSTOPped at 16:55 (kill -CONT <pid> when MemAvailable >= 4 GiB). Not killing the other agent's process.
Remaining queue after ST/KM: A: CG SN MU DJ TG ML ; B: SC UG BF LR MZ CD CM GW MG. Then rerun KW SY YE BH LB AE IQ ER SZ SD.
16:56 PT: mem recovered to ~11.5 GiB; ST/KM resumed (SIGCONT).
16:58 PT: rerun_chain.sh started (waits for ALLDONE in worker_A/B logs, moves 10 early packs to africa_me_cc/old_pre_rerun, reruns via workers A2/B2; log worker_A2.log/worker_B2.log, rerun_chain.log gets CHAINDONE).
17:10 PT: 34 packs present; building SN, UG; mem ~11.5 GiB OK. Chain will rerun early 10 after A/B finish.
17:20 PT: 37 packs; building MU, LR.
17:34 PT: 43 packs; building ML, CM; then GW MG.
17:41 PT: 46 packs; only MG left in phase 1; chain rerun starts after.
17:46 PT: MemAvailable 2.7 GiB (breach); checking offender; MG still building, chain waiting.
17:47 PT: MG SIGSTOPped (mem 2.7 GiB, offender outside lane/not visible in ps). Writing check_gates.py meanwhile (light).
17:52 PT: check_gates.py written (not yet run). MG stopped until mem recovers.
17:47(box clock) MG resumed, mem 6.8 GiB.
17:58 PT: ran check_gates --fix on 36 non-rebuild packs -> gates_report_main.json (only DZ, LY pass never-thin so far; verifying Hub sources).
18:00 PT: fixed Hub live lookup (datasets-server size.configs); rerunning gates.
18:05 PT: wrote handoffs/20261010_africa_me_READY.txt for 36 packs (LY pass all; 35 hard-gate pass but increment < Hub). MG + 10 rebuild packs pending.
18:10 PT: GQ (0 CC pointers for candidate domains) and ST (263 fetched, all gated out as non-law) = BLOCKED, NO_ROWS packs (excluded from READY; listed as FAIL/unusable). MG still building then chain reruns 10 Arabic packs.
18:14 PT: phase 1 ALLDONE (MG 57/89). MG gated -> gates_report_mg.json. Chain rerun starting.
18:16 PT: READY file regenerated incl. MG (37 packs). Waiting on chain (KW SY YE BH LB | AE IQ ER SZ SD) -> then gates + READY_rebuild.
18:22 PT: rebuild done so far KW 110/686, SY 92/1878, AE 164/4071; others running.
18:27 PT: rebuild YE 186/1189, IQ 151/1188 done; BH LB ER SZ SD pending.
18:38 PT: CHAINDONE. Running gates on rebuild set.

## FINAL (18:41 PT)
- All phases complete; no workers running. Rebuild (CHAINDONE) done and gated: gates_report_rebuild.json; handoffs/20261010_africa_me_READY_rebuild.txt
- 47 pack dirs, 45 usable (3,821 laws / 50,698 articles). G1-G4 pass for all 45. G5 never-thin pass: KW LB IQ LY; other 41 are increments requiring merge into Hub repos.
- Blocked: GQ (no CC captures), ST (nothing law-like). Weak: ER (1 law), NE/TG (0 articles).
- Final note: handoffs/20261010_africa_me_FINAL.txt. Resources OK at end (mem ~6.9 GiB, disk 36 GiB free).
