#!/usr/bin/env python3
"""Create a new source-complete ownership corpus, without fitting or promotion."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from ipfs_datasets_py.logic.autoformal import legal_paired_temporal_ownership_corpus as corpus
load_training_inputs=corpus.load_training_inputs
validate_target=corpus.validate_target
validate_units=corpus.validate_units
validate_source_query=corpus.validate_source_query
propose_time_spans=corpus.propose_time_spans
SEALED=corpus.SEALED


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--prior-corpus',type=Path,required=True)
 args=parser.parse_args();print(json.dumps(corpus.build_corpus(args.output,args.prior_corpus),sort_keys=True))


if __name__=='__main__':main()
