# Upload backlog results

Generated: 2026-09-04 (PT afternoon). User approved all HF uploads to endomorphosis.

| Code | Country | Kind | Status | Laws | Articles | URL | Errors |
|------|---------|------|--------|------|----------|-----|--------|
| ZW | Zimbabwe | create | ok | 80 | 3775 | https://huggingface.co/datasets/endomorphosis/ipfs_zimbabwe_laws |  |
| TZ | Tanzania | create | ok | 60 | 1329 | https://huggingface.co/datasets/endomorphosis/ipfs_tanzania_laws |  |
| RS | Serbia | create | ok | 66 | 1037 | https://huggingface.co/datasets/endomorphosis/ipfs_serbia_laws |  |
| AL | Albania | create | ok | 60 | 3120 | https://huggingface.co/datasets/endomorphosis/ipfs_albania_laws |  |
| BA | Bosnia | create | ok | 50 | 2764 | https://huggingface.co/datasets/endomorphosis/ipfs_bosnia_laws |  |
| BW | Botswana | create | ok | 80 | 477 | https://huggingface.co/datasets/endomorphosis/ipfs_botswana_laws |  |
| MZ | Mozambique | create | ok | 91 | 2937 | https://huggingface.co/datasets/endomorphosis/ipfs_mozambique_laws |  |
| TN | Tunisia | deepen | ok | 248 | 12908 | https://huggingface.co/datasets/endomorphosis/ipfs_tunisia_laws |  |
| ET | Ethiopia | deepen | ok | 64 | 80 | https://huggingface.co/datasets/endomorphosis/ipfs_ethiopia_laws |  |
| DO | Dominican Republic | deepen | ok | 101 | 103509 | https://huggingface.co/datasets/endomorphosis/ipfs_dominicanrepublic_laws |  |
| SV | El Salvador | deepen | ok | 106 | 5770 | https://huggingface.co/datasets/endomorphosis/ipfs_elsalvador_laws |  |
| CM | Cameroon | deepen | ok | 300 | 1062 | https://huggingface.co/datasets/endomorphosis/ipfs_cameroon_laws |  |

## Notes

- Method: `hf repo create --exist-ok` + `hf upload` of whole `staging_*` folder (README, data/, scrapers/); MANIFEST.md excluded.
- Parquet counts verified against staging README Snapshot before each upload (except DO was re-checked after concurrent deepen).
- Live README Snapshot verified via curl after each upload.
- DO: backlog expected 90/92457; at upload time staging_do had been updated to **101/103509** with matching README — uploaded that version.
- Several uploads reported `0/0 uploaded` (content already identical on Hub / LFS dedup) but commit URLs returned and live Snapshot matched.
- Disk free remained >100G; Iceland / FI / HR / SK not touched; no scraping performed.

