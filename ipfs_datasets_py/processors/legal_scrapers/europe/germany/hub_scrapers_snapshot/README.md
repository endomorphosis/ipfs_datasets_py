# German Landesrecht densify lane (ipfs_germany_laws, DE-<Land> rows)

Densifies endomorphosis/ipfs_germany_laws **append-only at tip 4911b83b** (no new repo). The tip already holds federal GII
(DE) + DE-NW 1,264 / DE-BB 962 / DE-SN 934 laws. See /workspace/world_laws_plan/de_es_overlap.md.
Pattern: gi_build (Gibraltar), itself based on endomorphosis/ipfs_datasets_py @ a1b5c73e world collectors.

Queue (`$DE_WORK/de_queue.txt`, CoS GO 2026-10-13, user decision "entire law"), run in this order behind GI:

| # | Line (`LAND TAG KINDS`) | Adapter | Size (probe 2026-10-13) |
|---|---|---|---|
| 1 | `SN - law,vwv,bek` | revosax.sachsen.de sitemap -> /vorschrift/<id> | 1,967 missing (1,234 law / 579 VwV / 154 Bek) |
| 2 | `SN amending amending` | same, Änderungs-Vorschriften | 3,456 missing |
| 3 | `BB vwv vwv,amending` | BRAVORS VwV chronological year lists -> /verwaltungsvorschriften/<slug> (Crawl-delay 20 s) | see DENSIFY_REPORT / size probe |
| 4 | `NW delta law,bek,vwv` | recht.nrw.de sitemap, lastmod > 2026-10-02T15:43Z (tip harvest); pages whose id is on the tip = `tip_update` records, packed only with `--include-updates` as `<id>@<valid_from>` rows | see size probe |
| 4b | `NW bek bek` | all recht.nrw.de Bekanntmachungen (no lastmod floor; none on the tip) | ~1,258 sitemap URLs (version URLs collapse to one row per term id) |
| 4c | `NW vwv vwv` | the NRW Verwaltungsvorschriften | 6 |
| — | `#PACK NW delta,bek,vwv --include-updates` | pack default: the 1 changed tip law goes in as a separate `<id>@<valid_from>` version row | 1 |
| 5 | `NI - law,vwv,bek,amending` | NI-VORIS alphabetical browse tree (letter -> bigram -> law node -> head + article documents) | **gated: needs `$DE_WORK/LICENCE_GO_NDS_HB`** |
| 6 | `HB - law,vwv,bek,amending` | transparenz.bremen.de in-force lists (Gesetze+RVO 1,617; VwV 437) -> /metainformationen/ | **gated: needs `$DE_WORK/LICENCE_GO_NDS_HB`** |

### source_terms_note
User decision relayed by Chief of Staff on 2026-10-13: *"I want the entire law, the government laws are not copyrighted"*
(official statute text, § 5 UrhG). Recorded in `de_lib.SOURCE_TERMS_NOTE`, on every added row
(`metadata_json.metadata.source_terms_note`), in `DENSIFY_REPORT.json` and in the pack's `CARD_SECTION.md`.
NI (portal TDM reservation § 44b(3) UrhG) and HB (CC BY-NC-ND portal labels) still do not run until the flag file
`$DE_WORK/LICENCE_GO_NDS_HB` exists; the collector exits 5 before any request and the waiter keeps them queued.

## Safety
- `robots_guard.py` (fleet copy, fail-closed): every request and **every redirect hop** goes through `GuardedSession` -> robots check
  of that hop's host; off-host/off-scope final URL -> host stop. 5xx/timeout/challenge robots = refuse. 3rd consecutive robots.txt
  network failure -> exit 2 (PARKED_robots by the waiter). 401/403/429/challenge page -> `PARKED_host`, exit 6, never retried.
- Spacing per host = max(land min_delay, robots Crawl-delay). One worker.
- Bounds (`de_lib.BOUNDS`): ≤2,500 laws / 200 MB text per pack, page ≤8 MB, ≤3,000 sections/law, text ≥80 chars, 1800 ≤ date ≤ 2026.
  Out-of-bound records are kept in records/ but excluded from the pack and listed in DENSIFY_REPORT.json.
- `pii_scan`: redacts private e-mail, IBAN, Steuer-IdNr shapes; keeps official authority mailboxes. Count in metadata_json.
- Memory: MemAvailable < 3 GiB for 15 s or RSS > 1 GiB -> exit 4. SIGTERM only.
- Ids already on the tip (`hub_tip_ids.txt`) are never fetched (SN/BB: before the request; NW/HB/NI: ids known only after
  the fetch are dropped, NW keeps them as `tip_update` records); the collector refuses to run without that list.
- Scope: `de_lib.path_allowed(land, url)` whitelists only listing/document paths of the official host; a request or final
  redirect outside it is refused / parks the host. Listing failures are retried 3x, an unreachable seed parks the sub-lane.
- NI resumes inside a law: fetched documents are cached in `<lane>/partial/<key>.json` until the law is complete.

## Run
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt     # stdlib regex parsers; no bs4/lxml needed
unset HF_TOKEN HUGGINGFACE_HUB_TOKEN HUGGING_FACE_HUB_TOKEN HF_HUB_TOKEN
export DE_WORK=/workspace/de_laender/work
.venv/bin/python pack_de.py ids --out $DE_WORK/hub_tip_ids.txt           # public Hub read, no token
nohup ./de_waiter.sh >/dev/null 2>&1 &                                   # ONE waiter; walks de_queue.txt behind GI, v2 gate, 300 s stagger
# one slice by hand: .venv/bin/python collect_de_laender.py --land SN --tag amending --kinds amending --existing-ids $DE_WORK/hub_tip_ids.txt
.venv/bin/python pack_de.py build --land SN --tags=-,amending --live-laws tip_laws.parquet --live-articles tip_articles.parquet
.venv/bin/python pack_de.py build --land NW --tags delta [--include-updates] ...
DE_HUB_TIP=<current tip> .venv/bin/python pack_de.py stage --land SN    # tip unchanged -> READY_germany_laws_densify_sn
```
Each Land is packed on the then-current tip (one upload at a time); after an upload set `DE_HUB_TIP` and rebuild the next.
Staging: `/workspace/hf-staging/germany_laws_densify_<land>/pack` (refuses /dev/shm). Upload is CoS's.

Wrappers: `run_de_short.sh` (gate MemAvailable ≥5632 MiB + disk ≥12,600 MiB held 120 s else rc 74; shared short-lane flock rc 75;
300 s stagger rc 76; `timeout -s TERM 40m`), `resume_loop_de.sh` (slices until done; retries 0/75/76 only),
`de_waiter.sh` v2 (flock; waits READ-ONLY until /workspace/gi/work/state.json done=true, a GI PARKED_*, or a gibraltar READY_* in
/workspace/hf-staging; re-reads `de_queue.txt` every cycle, so queue edits and the licence flag apply without a restart; parked
sub-lanes are skipped; logs a gate-wait line every ~10 min; re-queues every 30 min; exit 0 when every line is done/parked).

Tests: `python tests/test_de_laender.py` (40 tests, no network; fixtures = REVOSax page + sitemap excerpt, BRAVORS VwV year list + doc,
recht.nrw.de law page + sitemap page, transparenz.bremen list + doc, NI-VORIS law node + head/article docs, 5 robots.txt).

## Gate profile (fetch lanes; CoS + user approval 2026-10-13)
`gate_profile.sh` is sourced by the waiter (every cycle) and the short-lane wrapper; `<work>/gate.env` is re-read each time.
- **light** (lane work tree <= 300 MB): start MemAvailable >= 4096 MiB held 120 s; hard stop < 1536 MiB for 15 s (rc 4).
- **v2** fallback (tree > 300 MB, or `FORCE_PROFILE=v2`): start >= 5632 MiB; hard stop < 3072 MiB. The collector's guard thread
  re-measures the tree every 60 s and raises its floor to 3072 MiB as soon as the tree passes the cap.
- Unchanged: disk >= 12,600 MiB, 300 s stagger on the shared stamp, RSS <= 1 GiB, SIGTERM only. Builds/packs always run on v2.

## Monotonic gate deadline (2026-10-14)
The wrapper's 1800 s gate deadline and 120 s hold run on `mono()` = `/proc/uptime` seconds, not the wall clock: the box is
paused for long stretches (about 65% of wall time on 2026-10-13), the wall clock jumps forward on resume, and a pause during the hold
used to expire the deadline -> rc 74 with 4.8-6.5 GiB free. The waiter passes `DE_GATE_OK_MONO` (its mono time when its own
120 s hold ended); the first wrapper skips the duplicate hold if that check is <= 60 s old (`DE_GATE_FRESH_S`). Later slices
hold normally. The stagger stamp is written only in the wrapper, after gate + flock, immediately before the collector starts.

## Finalize gate (CoS, 2026-10-15)

`finalize_gate.py` (shared with the DE Länder, GI and territory builders) runs at the end of every build and again before
staging; a failure means no READY file. Checks: (1) 0 contents-list article rows (Inhaltsverzeichnis/Inhaltsübersicht/
Contents/Arrangement of Sections/…), (2) 0 rows with raw HTML or footnote markup (`<a …>`, `class="fussnote_link"`,
`href="#FNID_n"`, stray tags), (3) every count on the card equals the count recomputed from the written parquet (DE: laws,
articles, per-kind counts of the added rows; GI/territory: files-table row counts). DE records also pass
`de_lib.clean_record` first: revosax footnote anchors become `[n]` plus a plain-text `Fußnoten:` block, contents rows are
dropped, heading-only rows (text == title) are folded into the next article (a trailing one is dropped), body text that
leaked into a title after the `Vom <date>` line is cut, and article_count is recomputed. Tests: `tests/test_finalize_gate.py`.
- 2026-10-15 22:50 PT: heading-only detection compares title and text with whitespace collapsed (`finalize_gate.ws`: every run
  of spaces/newlines -> one space, stripped; 'Teil 1\nX' == 'Teil 1 X'). Gate check 4 `heading_only_ok`: such rows must
  be 0 (DE, folded) or equal the number the card discloses as kept (GI/territory one-line sections).
- 2026-10-15 22:55 PT: `fix_sn.py` rewrites the two live shards with only one Land's rows changed (CoS option A for rows already
  on the Hub): footnote HTML cleaned, contents rows dropped, heading-only rows folded, article_count recomputed; every other
  row byte-identical (checked), per-id manifest `manifests/fix_sn_headings_ids.jsonl`. Tests: `tests/test_fix_sn.py`.
- 2026-10-15 23:15 PT: `<br>` now becomes a line break (a space in titles) in `finalize_gate.strip_html_footnotes`, so words are never
  glued. `fix_contents_titles.py` drops contents-list rows in contents-only mode (federal DE except a CoS keep list, DE-BB, DE-NW)
  and restores the `<br>` spaces in DE-SN titles from the pre-fix tip; tests `tests/test_fix_contents_titles.py`.
- 2026-10-15 23:20 PT: `fix_lawtext_br.py` restores, as line breaks, the `<br>` spots the headings fix had glued in DE-SN law texts
  (exact positions from the pre-fix raw text; re-runs the legacy cleaning and requires a byte-exact match). Its `stage` refuses READY
  until `<out>/HUB_PARENT` holds the live commit of the base pack and the live data shas equal the staged base. Tests `tests/test_fix_lawtext_br.py`.

## DE-SN amending rework (CoS rejection 2026-10-17)

- **PII scan** (`de_lib.pii_scan`) redacts only personal data of private individuals. Kept verbatim: official accounts printed in
  law (Bundesbank BLZ `xxx00000`, a public payee such as Landeshauptkasse/Staatskasse within 160 chars before, or BIC MARKDEF1),
  official / functional mailboxes (government domains incl. sub-domains such as `justiz.`, `@sachsen.de`, local parts such as
  poststelle/datenschutz/spammeldung). The tax-id rule needs a Steuer-ID label within 40 chars on the same line, so table numbers
  never match. Tests: `tests/test_sn_rework.py`.
- **SN parser**: tags are removed across lines (attribute-aware), a `>` inside a quoted attribute no longer ends `<section …>`,
  a section without a title attribute takes its own heading line (never the internal anchor such as `a2`), footnote anchors
  become `[n]` + `Fußnoten:`. Word breaks lost in one rendering of a heading (title attribute / Eingangsformel h3) are restored
  from the h4 / h1 / Vollzitat rendering of the same words (`_respace`). Other Länder still use `_text`.
- **finalize_gate**: raw HTML is any tag-shaped string (generic regex, not a tag list), also escaped `&lt;tag`, comments,
  attribute residue `">` and footnote attributes, in titles, texts AND every metadata_json string. `heading_only_ids` lists
  rows with no body beyond their heading; repeal placeholders (`(aufgehoben)`, `weggefallen`, …) are kept and tagged
  `metadata_json.body_status = "repealed_placeholder"` (metadata, no new column).
- **clean_record**: an empty `Artikel N` heading is never merged into Artikel N+1 (dropped, listed as a known gap; revosax prints
  the body of a Mantelgesetz's Artikel as its own /vorschrift page); footnote-digit rows and attachment stubs (`Karte`,
  `Anhang` with no text) are dropped; other heading-only rows still fold into the next row.
- **Page cache + re-fetch**: SN/BB/NW/HB pages are cached gzip under `$DE_PAGE_CACHE` (default `/workspace/de_laender/page_cache/<lane>`,
  outside `$DE_WORK`, so not counted in the tree cap). `refetch_de.sh <LAND> <tag> <ids>` re-fetches only uncached pages under
  the light gate, the short-lane flock (`flock -n`, never waits holding it), the 300 s stagger and the robots guard; it does not
  touch the GI/DE turn files. `refetch_de.py reparse` rebuilds records offline from the cache (old record kept once in `records_prev/`).
  A connection dropped mid-body is `Transient` (one retry, then the id is skipped and reported).
- **pack_de build** writes `manifests/<prefix>_added_ids.jsonl` (every added law and article id), `_known_gaps.jsonl` and
  `_not_added.jsonl`, and with `--readme <live README>` a cumulative README (live README + new section); the gate checks the
  README counts and the manifest against the parquet.
