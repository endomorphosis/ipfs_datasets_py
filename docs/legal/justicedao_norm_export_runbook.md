# JusticeDAO normalized export runbook

Raw scrapes land on the Hugging Face `endomorphosis` org. New laws change that dataset's commit SHA. Normalization reads a raw snapshot and writes `legal-record/v1` for the `justicedao` org. `query_legal_records` retrieves only from justicedao. It does not read endomorphosis.

`export_freshness` compares the current raw SHA with `source_revision` on the justicedao manifest (or `dataset_revision` on an older country IR manifest). Equal SHAs are `current`. A newer raw SHA is `stale`. No export SHA is `missing`. A missing raw SHA is `unproven` and must not start a normalize. `stale` and `missing` set `renormalize` true. Retrieval still uses the justicedao copy that exists. It does not switch to the raw org while the export catches up.

Country packs already use the same rule in `classify_gap`: `stale_source_revision` when the endomorphosis SHA and the IR manifest differ. `coverage --gaps` reports those packs. World, HTML municipal, and American norm trees use `freshness_from_manifest` on the `export_norm` manifest. Re-run the local normalize when `renormalize` is true, then stop. Upload stays behind a separate go-ahead.

This runbook is local operator guidance. It is not a pull request, and it does not upload. `export_norm --upload` still raises `ExportUploadBlocked`. `LEGAL_QUERY_NORMALIZED` stays unset. Pins in `justicedao_release_pins.json` stay `searchable: false` with `revision: null` until a separate go-ahead that names the repos.

Work from the training checkout `external/ipfs_datasets` on the legal tip. Set `PYTHONPATH` to that checkout so the shadow package under `ipfs_accelerate_py` is not imported ahead of it. Do not recurse submodule init.

The code this runbook names is `is_world_v11_shard`, the null-text keep in `project_html_municipal_row`, and `review_row`. World-national rows use `admin_level=country`. World-municipal rows use `admin_level=municipality`. A null HTML `text` is kept and `content_complete` is false. Equal non-null `text` and `html` strings still raise. Writer drops stay in `drop_reason`. Review findings (`schema_invalid`, `duplicate_identity`, `unresolved_country_code`, `license_note_missing`, `language_missing`, `temporal_missing`) are reported and do not change `filter_counts`.

## Dry run, then stop

1. Classify the frozen fixture `ipfs_datasets_py/processors/legal_scrapers/world_law/hub_inventory_20261014.json`. A live re-list is optional, read-only, and unauthenticated. It does not upload. The fixture's file counts are bound to the SHA on each row. Canada is 27 `*_html.parquet` files at `7ef1bd20e2eca296c2d106e50ff665bdc2d92c5e` and 28 at `04f02e4cf3ed25558280408ef1bf96761df3cbdd`. Re-read before treating either count as current main.
2. World and HTML dry-run, local. `export_norm --dry-run` writes nothing. It reads `*_html.parquet` world shards and ignores `places.parquet`. A null-text HTML row is kept. Chile and Hungary municipal card configs with zero files print `coverage=not_published`.
3. Country gap report, local. `country_laws_ir coverage --gaps` without `--upload` is the first time SHA staleness replaces the calendar-day count of 21. It may download manifests. It must not rebuild with `--upload`. It does not list municipal gaps. `country_laws_ir` has no municipal catalog.
4. Stop. Leave the flag unset and the pins unsearchable.

Eleven municipal catalog hubs have no IR: `austria`, `belgium`, `brazil`, `canada`, `indonesia`, `korea`, `latvia`, `netherlands`, `new_zealand`, `portugal`, `slovenia`. The six text or mixed creates are `austria`, `korea`, `latvia`, `netherlands`, `slovenia`, and `brazil`. The five HTML hubs are `export_norm_html` destinations `justicedao/ipfs_<slug>_laws_norm`. A default municipal query still names `justicedao/ipfs_<slug>_laws_ir` after that upload. `*_laws_norm` is served only after a pin go-ahead and a gap outside `{unset, current, stub_vectors}`.

`ipfs_egypt_governorate_laws`, `ipfs_south_africa_provincial_laws`, and `ipfs_wallis_futuna_laws` stay unpublished with `route=none`. Queries for those jurisdictions stay `coverage=not_published`. `ipfs_uk_local_acts_ir` stays off the `GB` route. `GB` stays on `justicedao/ipfs_uk_laws_ir`.

Archived and non-official rows stay on endomorphosis. US rows stay out of the world copy. A missing `source_policy` on a 19-column HTML row keeps the row.

## Upload, only after an explicit go-ahead

Do not start these steps from this document alone.

1. The go-ahead names the repos.
2. Re-read SHAs that morning. Refuse to upload when the working tree SHA and the card SHA differ from the dry-run inputs. Dataset SHAs move during the day.
3. Upload with `upload_folder` in a process that is not `export_norm`. huggingface_hub 1.33.0 may split a large folder across commits, and `parent_commit` applies only to the first. `upload_large_folder` is deprecated and cannot delete during the upload. `world_municipal_law` at `1f6823deab034387ea0fb5f8126086f5db798ce9` has 68,248 siblings. Ignore patterns must cover cache, token, `.env`, and `.pem`.
4. Re-read the destination SHA after the last commit. Write it into a scratch pin file. Leave `searchable` false.
5. Canary one HTML slug or a Guam-sized national pack first. Re-read Guam source `f78536f96f4e552c64fb99d66f57283e24a5f93e` and IR `10644136406069e433e053d1b06e603503643443` before using them. A canary upload still leaves the pin unsearchable. Creating the six missing municipal IRs is part of this runbook.
6. A second go-ahead sets `searchable` and the 40-hex revision. A third sets `LEGAL_QUERY_NORMALIZED=1` in a deployment. Those are separate actions. Setting an HTML norm pin searchable does not change a default municipal query.

Rollback: set `searchable` back to false and unset the flag. Queries return `LegalQueryDisabled` or, with the flag still on, `not_published` when the world pin is unreadable. A partial multi-commit upload stays invisible to `query_legal_records` while the pin is unreadable.

Blocked destinations stay blocked: `justicedao/american_municipal_law`, `justicedao/ipfs_state_laws`, and `justicedao/ipfs_federal_register`.

## Git facts observed on 2026-10-14

Local datasets `origin/main` `929647b4` is already merged into legal tip `22be94c8`. Live GitHub datasets `main` `0897aa1d` was `4` ahead and `3` behind that tip, merge-base `929647b4`, and lacks `query_legal_records.py` and `export_norm.py`. The historical pair `382487167...1f9fac75` is history. Do not reset the tip to `382487167`.

Parent GitHub `lift_coding` main `839ef8a9` gitlinks datasets `ebdf6539`. Parent local `origin/main` `e18ce337` gitlinks `c9d0f016`. Neither gitlink contains the query module. There is no parent gitlink change in this work.

Re-read these SHAs on the day you run the upload. This document does not call the Hub.
