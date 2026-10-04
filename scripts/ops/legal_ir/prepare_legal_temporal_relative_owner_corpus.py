#!/usr/bin/env python3
"""Prepare authored relative-owner data; calibration/test labels have separate seals."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.logic.autoformal import legal_temporal_relative_owner_corpus as corpus

prepare = corpus.prepare
load_training_inputs = corpus.load_training_inputs
source_row = corpus.source_row
validate_target = corpus.validate_target
target_projection = corpus.project_reference
validate_source_query = corpus.validate_source_query
CALIBRATION_SEALED = corpus.CALIBRATION_SEALED
FRESH_SEALED = corpus.FRESH_SEALED
SEALED = corpus.SEALED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.prior_manifest)), flush=True)


if __name__ == '__main__':
    main()
