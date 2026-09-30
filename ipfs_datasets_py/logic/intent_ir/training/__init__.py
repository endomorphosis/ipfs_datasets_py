"""SkillCenter training campaign for Intent IR feature pretraining.

The public entry points live in ``skillcenter_campaign``. Importing this
package does not download a dataset or start an optimizer.
"""

from .skillcenter_campaign import (
    DATASET_REPO_ID,
    DATASET_REVISION,
    PILOT_SOURCE_LIMIT,
    UPSTREAM_DATASET_ID,
    UPSTREAM_REVISION,
    SkillCenterTrainingError,
)

__all__ = [
    "DATASET_REPO_ID",
    "DATASET_REVISION",
    "PILOT_SOURCE_LIMIT",
    "UPSTREAM_DATASET_ID",
    "UPSTREAM_REVISION",
    "SkillCenterTrainingError",
]
