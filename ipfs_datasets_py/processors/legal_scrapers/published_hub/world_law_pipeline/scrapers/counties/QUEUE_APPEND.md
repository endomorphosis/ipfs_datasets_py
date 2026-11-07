# Appending to `county_supervisor_queue.jsonl` (safe)

The supervisor (`county_supervisor.sh`) is the **only** process that may run
`pdf_list_fetch.py` for the county lane. Queue-extension workers list + test, then
append `pending` rows; they must not start full fetches.

## Schema (`kind=target`)

```json
{"id":"de_xx","kind":"target","target":"de_xx","qid":"Q…","place_name":"…","listed":123,"status":"pending","queued_at":"YYYY-MM-DDTHH:MM:SSZ"}
```

`kind=chain` uses `script` instead of `target` and runs a `county_chain_*.sh`.

## Preconditions for `kind=target`

1. `entries/cfg/<id>.json` — lister config (`start_urls`, `follow_re`, `pdf_re`, place meta).
2. `entries/<id>_amtsblatt.json` — listed items (`de_amtsblatt_list.py`).
3. `entries/_test_<id>.ok` — empty marker after an 8-item test with `err==0` and
   `ok+scanned >= 6` (`pdf_list_fetch.py entries/_test_<id>.json --delay 2`).

Without (2)+(3) the supervisor marks the row `failed` (`no entries/test-ok`).

## Atomic append

1. Wait until **no** `pdf_list_fetch.py entries/` process (do not race the supervisor).
2. Skip if `id`/`target` already present with any status.
3. Rewrite via temp file + `os.replace` (same pattern as `claim_next` / `county_enqueue_pending.sh`).

```python
# sketch — see county_enqueue_pending.sh append_queue()
rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
if any(r.get("id")==n or r.get("target")==n for r in rows): raise SystemExit("dup")
rows.append({... status:"pending" ...})
tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
os.replace(tmp, path)
```

## Do / Don't

- Do: polite ≥2 s/host, UA `WorldLawBot/1.0`, ignore robots (Benjamin Nov 1), no
  proxies/VPN/WAF/captcha/Cloudflare bypass; stage scans raw; skip spreadsheets;
  URL-hash suffixes for query doc_ids (handled in fetchers).
- Don't: start fetchers; touch `/workspace/ipfs_datasets_py`, `/workspace/municipal_law`,
  or `state/doc_overrides.json`; queue eCode360 / Code Publishing /
  `*.municipal.codes` / `*.county.codes`; Poland / UKIE / Romania / Bavaria.
- Floors (supervisor-owned): disk 10240 MiB free, RAM 2048 MiB available,
  staging/pdf hold at 4 GB.

## Helper

`county_enqueue_pending.sh` — example for two DE Amtsblatt targets.
`county_enqueue_batch.sh` — batch test+append for a list of `id|qid|name` specs.
