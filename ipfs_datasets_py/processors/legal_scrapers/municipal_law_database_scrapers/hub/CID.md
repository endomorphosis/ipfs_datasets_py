# CID generation

HTML `cid` is IPFS CIDv1, multibase base32 (`b`), codec raw (`0x55`), hash sha2-256
of the UTF-8 bytes of `{gnis}_{doc_id}.json`.

This matches all 609 rows in the sample `1008538_html.parquet`
(README says `{gnis}_{doc_title}.json`; the existing files hash `doc_id`,
which is the Municode node id).

Citation `bluebook_cid` hashes `{place_name}{bluebook_state_code}{title}{history_note}`
the same way (no `.json` suffix; that is what the dataset card specifies).
