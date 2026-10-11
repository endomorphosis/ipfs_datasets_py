#!/usr/bin/env python3
"""Diagnose retained counter identities without source/model bodies or aliases."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_identity_recovery import run_identity_diagnosis


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("database-path","expected-database-sha256","manifest-path","expected-manifest-sha256",
            "report-path","expected-report-sha256","progress-parquet","expected-progress-sha256",
            "accepted-review-path","expected-accepted-review-sha256","output-directory"):
        parser.add_argument("--"+name,required=True)
    for name,default in (("memory-mb",256),("max-retained-rows",65536),("max-archive-rows",500000),
            ("max-input-bytes",128*1024*1024),("max-report-bytes",2*1024*1024),
            ("max-output-bytes",8*1024*1024),("example-limit",32)):
        parser.add_argument("--"+name,type=int,default=default)
    report=run_identity_diagnosis(**vars(parser.parse_args(argv)))
    print(json.dumps(report,sort_keys=True))


if __name__ == "__main__":
    main()
