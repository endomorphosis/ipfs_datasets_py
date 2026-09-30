#!/usr/bin/env python3
"""Train native-projection-feature-space/v2 on the SkillCenter gradient population.

Gradient rows are ready train envelopes plus ready validation envelopes outside
the ranked tune batch. Test and held-out partitions stay out of the gradient
and out of the verb-threshold fit. This does not register a candidate.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.training.skillcenter_campaign import (  # noqa: E402
    SkillCenterTrainingError,
    cache_root,
    train_streamed_features,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, default=None)
    parser.add_argument("--split", default="corpus_split.json")
    args = parser.parse_args(argv)
    try:
        receipt = train_streamed_features(
            args.campaign_dir or cache_root(),
            split_name=args.split,
            tune_limit=1024,
            minibatch_size=1024,
            epochs=8,
            latent_width=16,
            learning_rate=0.02,
            max_seconds=3600.0,
            seed=1729,
        )
    except SkillCenterTrainingError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"gradient_sources={receipt['gradient_source_count']} "
        f"tune={receipt['tuning_source_count']} "
        f"holdout={receipt['holdout_ready_count']} "
        f"min_verb_documents={receipt['min_verb_documents']} "
        f"kept_verbs={receipt['kept_verb_count']} "
        f"columns={receipt['view_column_count']} "
        f"within_feature_bound={receipt['within_feature_bound']} "
        f"full_corpus_gradient={receipt['full_corpus_gradient']} "
        f"full_ready_gradient={receipt['full_ready_gradient']} "
        f"state={receipt['state_sha256']}"
    )
    print("FEATURE_SPACE_V2_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
