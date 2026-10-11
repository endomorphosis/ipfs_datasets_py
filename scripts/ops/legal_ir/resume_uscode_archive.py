#!/usr/bin/env python3
"""Authenticate a stopped archived-target generation, clone and resume locally."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_archive_resume import run_archive_resume


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("parent-directory","expected-parent-database-sha256","expected-parent-manifest-sha256",
                 "expected-parent-report-sha256","progress-parquet","progress-sha256","progress-revision",
                 "source-parquet","source-sha256","output-directory"):
        parser.add_argument("--"+name,required=True)
    parser.add_argument("--source-revision",default="5016b86a273ce5e4ffd066c5ae9f5fe494dd417e")
    parser.add_argument("--release-id",default="ipfs-uscode-5016b86a")
    for name,default in (("max-clone-bytes",128*1024*1024),("max-page-spans",1024),("max-page-bytes",4*1024*1024),
            ("max-section-bytes",8*1024*1024),("max-row-group-bytes",2*1024*1024*1024),
            ("memory-mb",768),("storage-max-bytes",128*1024*1024),("example-limit",16)):
        parser.add_argument("--"+name,type=int,default=default)
    parser.add_argument("--max-pages",type=int)
    parser.add_argument("--seed-census-directory")
    print(json.dumps(run_archive_resume(**vars(parser.parse_args())),sort_keys=True))


if __name__=="__main__":
    main()
