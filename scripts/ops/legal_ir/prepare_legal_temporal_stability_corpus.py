#!/usr/bin/env python3
"""Prepare evaluation-only temporal ownership stability panels."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.logic.autoformal import legal_temporal_stability_corpus as corpus
load_training_inputs = corpus.load_training_inputs
source_row = corpus.source_row
validate_target = corpus.validate_target
validate_units = corpus.validate_units
validate_source_query = corpus.validate_source_query
validate_query_inventory = corpus.validate_query_inventory
propose_time_spans = corpus.propose_time_spans
candidate_coordinate_inputs = corpus.candidate_coordinate_inputs
SEALED = corpus.SEALED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prior-corpus', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(corpus.build_corpus(args.output, args.prior_corpus), sort_keys=True))


if __name__ == '__main__':
    main()
