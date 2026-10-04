#!/usr/bin/env python3
"""Prepare exact owner-anchor supervision and source-only authored evaluation."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_pointer_corpus as corpus

load_training_inputs = corpus.load_training_inputs
prepare = corpus.build_corpus
source_row = corpus.source_row
validate_target = corpus.validate_target
target_projection = corpus.project_reference
validate_source_query = corpus.validate_source_query
SEALED = corpus.SEALED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prior-corpus', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.prior_corpus), sort_keys=True))


if __name__ == '__main__':
    main()
