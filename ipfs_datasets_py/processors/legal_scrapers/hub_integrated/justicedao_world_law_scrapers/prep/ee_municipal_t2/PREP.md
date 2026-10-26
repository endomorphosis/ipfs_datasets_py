# PREP — EE T2 — Riigi Teataja in-force KOV /akt/

Generated: 2026-10-06T14:04:02-0700 (offline). Updated: 2026-10-06 ~2:11 PM PT — exclude list frozen & wired. Status: PREP / READY (not launched; waiting CoS GO).
Slug: `ee_municipal`  |  Script: `/workspace/scripts/ee_t2_collect.py`  |  Root: `/workspace/legal-corpora/ee_municipal/t2`
Slot: **slot-filler**  |  Expected count: 11045

## Source URL(s)
- https://www.riigiteataja.ee/ (HTML /akt/<id> for in-force KOV)
- https://www.riigiteataja.ee/public-api/api/v1/akt/lugeja/ehak (EHAK in-force counts)
- Search: tervikteksti_tulemused.html?kov=true&sakk=kehtivad_kehtetuteta

## Licence
Autoriõiguse seadus § 5 p 3 — õigusaktid/haldusdokumendid not protected.

## Robots / terms constraints (from evidence)
Allowed for /akt/ generally; Disallow */kohtulahendid/*, */kohtuteave/*, some */kronoloogia/*, and a long list of specific */akt/<id>/* (redacted). No crawl-delay. Skip disallowed akt ids. Evidence: municipal_evidence_20261004/ee/ + 20261006/ee/.

## Expected count
~11,045 in-force KOV acts (sum kehtivateAktideArv from /public-api/api/v1/akt/lugeja/ehak); cross-check snippet 11,065. T1 was xml.2024 RT IV dump = 939 (already at ee_municipal/, hub tip 9ef422a2a38a).

## T1 exclude list (frozen 2026-10-06 ~2:11 PM PT)
- **Path (corpus):** `/workspace/legal-corpora/ee_municipal/t2/ref/ee_t1_akt_ids_20261006.txt`
- **Source triage copy:** `/workspace/country-law-triage/ee_t1_akt_ids_20261006.txt`
- **Count:** **939** unique `rt_ref_id` values (one per line)
- **T1 tip sha:** `9ef422a2a38a`
- **Wiring:** `ee_t2_collect.py` loads this set via `load_exclude_set()` / `filter_net_new()`; collect/discovery excludes every id in the file (net-new only). `guard_dryrun` + `selftest` assert `len==939` offline (no network).
- **Blocker cleared:** no longer waiting on verifier for the T1 id set.

## Rate / RSS plan
Floor delay_s=1.5 between request starts (no robots crawl-delay; polite). Host-locked to www.riigiteataja.ee. Never fetch xml.2025/xml.2026 dumps for T2.
- Memory guard (NL-M match): pause 3584 / resume 4200×30s / hard 3000 sustained 5s / instant 2500 / RSS cap 300MB / max pause 900s.
- Delay floor: `1.5` s (from evidence).
- Packed shards under `index/` (sync ignores `out/` `build/` `dist/`).
- `pa_exit_guard` only on offline build/verify/push entrypoints.

## Slot vs alone
slot-filler (≤2 collectors on strict). Not alone-required.

## Resume strategy
state/cursor: t2/state.json with next ehak_code + akt id queue; packed shards under t2/index/laws_shards/. STOP_EE_T2 / PAUSE_EE_T2.

## CoS decisions (2026-10-06 ~2:05 PM PT; updated ~2:11 PM PT)
- **Net-new only:** exclude every akt-id already present in T1 tip `9ef422a2a38a`.
- **Discovery:** Riigi Teataja `/akt/` in-force KOV listing (not xml.2025/xml.2026 dumps).
- **Exclude list frozen & wired** (~2:11 PM PT): 939 ids at `ref/ee_t1_akt_ids_20261006.txt`. Verifier blocker cleared.

## Open questions
- None blocking prep. Still no launch until Watchdog slot-OK + CoS GO.

## Evidence paths
- /workspace/country-law-triage/municipal_followup_20261006.md (EE READY 11,045)
- /workspace/country-law-triage/municipal_evidence_20261006/ee/
- /workspace/country-law-triage/municipal_evidence_20261004/ee/
- /workspace/legal-corpora/ee_municipal/t2/ref/ee_t1_akt_ids_20261006.txt

## Launch gate (do not skip)
- Watchdog slot-OK + CoS GO token required.
- Cap: ≤2 collectors on strict; BR ALESP alone and never with NL-M.
- NL-M PID must remain untouched; CZ STOP_CZ stays in place.
- Offline prep only until GO.
