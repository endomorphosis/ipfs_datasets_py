"""France tranche 1 — Besançon build, sharded runner.

Usage: fr_build_shard.py SHARD_INDEX SHARD_COUNT
Processes corpus docs where position % SHARD_COUNT == SHARD_INDEX,
skipping doc_ids already checkpointed in the main checkpoint or in
this shard's own checkpoint file. Rows/checkpoint format identical
to fr_full_build.py (which it imports for doc_rows()).
"""
import json
import sys
import time
from pathlib import Path

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_tranche1" / "scripts"))
import fr_full_build as F  # noqa: E402

OUT = HF / "fr_tranche1"
SHARD = int(sys.argv[1])
NSHARDS = int(sys.argv[2])
MY_CKPT = OUT / f"checkpoint_25056_shard{SHARD}.jsonl"


def load_ids(path):
    ids = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(json.loads(line)["doc_id"])
    return ids


def main():
    corpus = json.loads((OUT / "besancon_corpus.json").read_text(encoding="utf-8"))["docs"]
    done = load_ids(F.CKPT)
    for p in OUT.glob("checkpoint_25056_shard*.jsonl"):
        done |= load_ids(p)
    mine = [d for i, d in enumerate(corpus) if i % NSHARDS == SHARD]
    print(f"shard {SHARD}/{NSHARDS}: {len(mine)} docs, already done: "
          f"{sum(1 for d in mine if d['url'].rsplit('/', 1)[-1].rsplit('.', 1)[0].lower() in done)}",
          flush=True)
    n = 0
    with MY_CKPT.open("a", encoding="utf-8") as fh:
        for doc in mine:
            did = doc["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
            if did in done:
                continue
            rec = F.doc_rows(doc)
            rec["rows"] = [dict(r) for r in rec["rows"]]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            done.add(did)
            n += 1
            if n % 20 == 0:
                print(f"shard {SHARD}: +{n} docs", flush=True)
            time.sleep(0.2)
    print(f"shard {SHARD} DONE (+{n})", flush=True)


if __name__ == "__main__":
    main()
