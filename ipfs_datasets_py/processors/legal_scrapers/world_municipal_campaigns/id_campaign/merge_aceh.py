"""Merge a partial Aceh rebuild into the published parquet:
published (complete Perda set from tranche 2, already validated and
remote-verified) + staged partial (new Qanun docs) -> one complete
staged parquet, re-validated as a whole. Refuses if doc_id sets
overlap or the merged table fails validation."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

import harvest as H

C = Path(__file__).parent
STAGE = C / "staging"
STATE = C / "id_campaign_tranche3_aceh_state.json"
REPO = "endomorphosis/ipfs_indonesia_municipal_laws"

bps = sys.argv[1]
state = json.load(open(STATE))
entry = state[bps]
assert entry["status"] == "staged", entry["status"]

remote = hf_hub_download(REPO, f"data/{bps}_html.parquet", repo_type="dataset")
old = pq.read_table(remote)
new = pq.read_table(STAGE / f"{bps}_html.parquet")
old_ids = set(old.column("doc_id").to_pylist())
new_ids = set(new.column("doc_id").to_pylist())
overlap = old_ids & new_ids
union = len(sys.argv) > 2 and sys.argv[2] == "--union"
if overlap and not union:
    raise AssertionError(f"doc_id overlap: {list(overlap)[:5]}")
if overlap:
    # union mode: drop the published copies of docs the rebuild
    # re-harvested (fresher extraction wins), keep the rest.
    import pyarrow.compute as pc
    keep = pc.invert(pc.is_in(old.column("doc_id"),
                              value_set=pa.array(sorted(overlap))))
    old = old.filter(keep)
    print(f"{bps}: union mode — {len(overlap)} overlapping docs refreshed, "
          f"{old.num_rows} published rows kept")
merged = pa.concat_tables([old, new], promote_options="default")
# doc_order is a file-global sequence (the harvester's finalize step
# renumbers it the same way); each doc's rows stay contiguous and
# internally ordered under a global renumber.
import pyarrow.compute as pc
idx = merged.schema.get_field_index("doc_order")
merged = merged.set_column(
    idx, "doc_order",
    pa.chunked_array([pa.array(range(merged.num_rows),
                                 type=merged.schema.field(idx).type)]))
errors = H.validate_table(merged, jurisdiction_id=bps,
                          jurisdiction_name=entry["name"], country="ID")
assert not errors, f"merged validation FAILED: {errors}"
pq.write_table(merged, STAGE / f"{bps}_html.parquet")

acts = len(set(merged.column("regeling_id").to_pylist()))
entry["acts"] = acts
entry["rows"] = merged.num_rows
note = (f"merged: tranche-2 Perda set ({old.num_rows} rows) + tranche-3 "
        f"Qanun top-up ({new.num_rows} rows, {entry.get('qanun_acts', 0)} "
        f"Qanun of {entry.get('qanun_catalog', '?')} in catalog; remainder "
        f"pending a further top-up pass)")
entry["truncation"] = ((entry.get("truncation") or "") + "; " + note).strip("; ")
json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=1)
print(f"{bps}: merged {old.num_rows} + {new.num_rows} = {merged.num_rows} rows, "
      f"{acts} acts, validation clean")
