#!/usr/bin/env python3
"""Materialize one new authored temporal-ownership corpus; never fit a model."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_corpus as corpus

load_training_inputs = corpus.load_training_inputs
propose_time_spans = corpus.propose_time_spans
validate_source_query = corpus.validate_source_query
validate_target = corpus.validate_target
SEALED = corpus.SEALED


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exclude-source-pack',type=Path,action='append',default=[])
    args=parser.parse_args()
    result=corpus.build_corpus(args.output,args.exclude_source_pack)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
