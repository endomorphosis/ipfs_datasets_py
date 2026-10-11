#!/usr/bin/env python3
"""Census immutable local US Code sources without models, network, or admission."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_source_census import run_source_census


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["progress-parquet","progress-sha256","progress-revision","source-parquet","source-sha256","output-directory"]:
        p.add_argument("--"+name,required=True)
    p.add_argument("--source-revision",default="5016b86a273ce5e4ffd066c5ae9f5fe494dd417e")
    p.add_argument("--release-id",default="ipfs-uscode-5016b86a")
    for name,default in [("section-batch-size",4),("memory-mb",1024),("storage-max-bytes",128*1024*1024),
        ("max-row-group-bytes",2*1024*1024*1024),("max-section-bytes",8*1024*1024),
        ("max-batch-bytes",32*1024*1024),("max-batch-spans",8192)]:
        p.add_argument("--"+name,type=int,default=default)
    p.add_argument("--max-batches",type=int)
    p.add_argument("--export-full-parquet",action="store_true",help="Duplicate full inventory exports; requires separately admitted storage")
    for name in ["tokenizer-json","tokenizer-sha256","tokenizer-id","tokenizer-revision"]:
        p.add_argument("--"+name)
    report = run_source_census(**vars(p.parse_args()))
    print(json.dumps({"schema":report["schema"],"complete_source_scan":report["complete_source_scan"],
                      "statistics":report["statistics"],"inference_executed":False,"training_executed":False},sort_keys=True))


if __name__ == "__main__":
    main()
