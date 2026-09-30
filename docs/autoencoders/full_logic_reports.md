# Full legacy logic reports

The full-report publisher preserves an original legacy CUDA producer receipt
byte for byte using standard gzip. It does not rerun the model, reconstruct
missing targets, change weights, or admit legal statements.

Files live in `autoformal/uscode/reports/v1/` in
`justicedao/uscode-autoformal-span-cache`. Each report manifest records both the
compressed file hash and the exact original JSON byte hash, source identities,
checkpoint provenance, actual output counts, and unavailable-document reasons.
Only an exact-commit remote hash/size verification permits an uploaded receipt.
Original local files remain in place.

To read a downloaded report:

```python
import gzip, hashlib, json
from pathlib import Path
compressed = Path("report.json.gz").read_bytes()
raw = gzip.decompress(compressed)
# Verify both hashes and expected lengths against its manifest before use.
report = json.loads(raw)
for row in report["rows"]:
    target = row.get("logic_target_observation", {})
    document = target.get("document")
    print(row["source_span_id"], target.get("status"), target.get("reason"))
    if document is not None:
        print(document["views"].keys())
```

The September 30 retained archive has 32 decoder observations, two compiler
rules, and 22 complete captured bridge documents with 30 views each. Ten
other documents were excluded by the historical 4 MiB export bound; their
absence is retained explicitly. For these 22 historical documents, the
recorded inner hash uses `json.dumps(document, sort_keys=True,
allow_nan=False)` with default spacing. Compact JSON produces a different
byte hash even when the parsed object is the same.

The complete receipt retains raw vectors, projected vectors, direct compiler
outputs, original logic targets, loss values, timing and source provenance.
This historical batch predates the guided compiler comparison. No independent
learned formula decoder or guided output is invented during publication.
Source-derived bridge targets remain source-derived evidence.

These files can support later dataset curation and teacher-target experiments.
They are not automatically qualified training labels. Keep source splits,
producer identity, diagnostic vector provenance and compiler failures when
building next week's training inputs. Goals are imported separately after
review; this publisher never opens the agent supervisor database. Lake remains
the only Lean admission and every report publication remains unadmitted.

Verified publication: [report manifest](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/4f7922a2188c111e30841a08769f0f989d0b7c61/autoformal/uscode/reports/v1/manifests/0f2431a7c4746625fdbf693b312447f138d7ff4b820774ed4990dc334caa84ed.json).
The archived report is 3,959,482 bytes compressed and reconstructs all
73,673,016 original bytes. The local original remains retained.
