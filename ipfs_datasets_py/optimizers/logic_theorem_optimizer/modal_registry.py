"""Modal logic registry for deterministic legal parsing.

The registry is deliberately data-oriented: parser code can ask for a profile
by family or system without hard-coding modal cue words throughout the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, Mapping, Optional, Tuple


class ModalLogicFamily(Enum):
    """Modal logic families planned for deterministic legal parsing."""

    ALETHIC = "alethic"
    DEONTIC = "deontic"
    TEMPORAL = "temporal"
    EPISTEMIC = "epistemic"
    DOXASTIC = "doxastic"
    DYNAMIC = "dynamic"
    CONDITIONAL_NORMATIVE = "conditional_normative"
    FRAME = "frame"
    HYBRID = "hybrid"


NORMATIVE_MODAL_FAMILIES: Tuple[ModalLogicFamily, ...] = (
    ModalLogicFamily.DEONTIC,
    ModalLogicFamily.CONDITIONAL_NORMATIVE,
)

COMPILER_AMBIGUITY_CORE_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000177_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_006115_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002055_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002864_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000008_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_011135_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_006897_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_006902_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003057_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003062_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003166_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003171_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003229_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003360_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005348_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
)

COMPILER_REFINED_PACKET_002542_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001314_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001268_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001479_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002328_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001316_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001029_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000536_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000629_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000599_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000224_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_007373_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_REFINED_PACKET_000225_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000226_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REFINED_PACKET_000581_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000538_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001308_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001265_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_006116_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_006816_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000697_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000180_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000535_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000348_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002327_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000534_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000521_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000495_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002295_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002296_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000486_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000619_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000393_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000394_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000406_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000853_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001233_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_001040_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000893_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001703_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000542_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000545_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003336_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003328_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002204_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002212_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002580_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002578_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000594_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000587_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000580_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003559_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002315_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002414_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002094_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002602_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002607_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001068_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000588_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000613_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000610_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000560_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000561_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005247_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005266_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000653_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000111_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000117_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000118_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000120_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000121_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000161_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000162_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000175_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000166_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000165_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000167_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000168_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000128_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000130_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000131_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000132_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000133_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000134_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000135_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000136_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000164_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000496_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000498_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005849_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000157_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000160_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000159_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000158_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000720_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000781_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000721_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001059_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001512_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001529_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001550_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000119_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000214_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000114_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000115_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000124_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000125_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000205_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000206_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000254_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000964_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000148_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000154_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000155_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000109_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000207_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000297_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000280_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000298_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000228_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000223_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000306_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003094_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003158_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_REFINED_PACKET_000953_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_001581_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_001615_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REFINED_PACKET_000192_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000194_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_001702_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_001117_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_003369_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_003148_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000043_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_REFINED_PACKET_000044_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_000112_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001032_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_001033_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003130_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005045_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_006301_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_RESCUE_REFRESH_PACKET_004444_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_001264_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003056_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
)

COMPILER_REFINED_PACKET_001981_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_002346_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_009945_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_002643_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_002787_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000461_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_001627_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_001844_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_002474_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_002342_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REFINED_PACKET_002051_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_003282_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000593_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_000042_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_REFINED_PACKET_000543_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000169_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000170_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_000172_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000258_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_000259_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000301_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000346_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000467_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000407_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_001095_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REFINED_PACKET_001096_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_004070_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_004071_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_004348_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000399_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_004762_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000138_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_003186_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_REFINED_PACKET_005718_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_005786_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_000165_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_001063_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000520_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000176_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_003357_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_004489_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_REFINED_PACKET_004558_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_003200_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
)

COMPILER_REFINED_PACKET_007187_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    *COMPILER_REFINED_PACKET_001040_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000306_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000169_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002346_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000170_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000172_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000258_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000259_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000301_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000346_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001096_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000467_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000407_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001095_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001702_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001117_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000194_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_004070_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_004071_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_004348_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000399_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000138_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000520_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000176_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_004489_FAMILY_PAIRS,
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    *COMPILER_REFINED_PACKET_000461_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001627_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001844_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002787_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002474_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002342_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002051_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003282_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001033_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000593_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000165_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001063_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003357_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_004558_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003200_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_007187_FAMILY_PAIRS,
)

COMPILER_AMBIGUITY_PACKET_000669_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005496_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000509_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000139_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000140_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000431_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000421_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000951_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001061_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001547_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002162_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002163_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002823_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002363_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004164_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004926_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004997_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005687_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002840_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002877_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005886_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005912_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005985_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001444_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_008598_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_008285_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_007995_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_012436_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_011661_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002254_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_012544_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_012244_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000005_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001108_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001104_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_011996_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_002506_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_002150_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000619_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_005212_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_002430_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004160_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_009549_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000319_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001127_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001151_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001257_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001472_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001518_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001605_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001638_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001674_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001551_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001247_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001540_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001730_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_001753_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001759_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001807_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002415_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001840_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000186_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000188_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000189_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000194_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000191_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REFINED_PACKET_000583_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000102_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002561_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000746_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001976_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_001976_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    *COMPILER_AMBIGUITY_PACKET_001976_FAMILY_PAIRS,
)

COMPILER_AMBIGUITY_PACKET_002110_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002111_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002300_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002364_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002638_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002681_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002717_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002740_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002859_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002890_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002900_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000163_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002929_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002993_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003205_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003527_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003746_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003818_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003760_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003275_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002719_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004476_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003775_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003779_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003791_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_006483_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003279_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003615_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003688_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002998_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002777_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003252_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003103_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003321_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003341_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004179_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004121_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000127_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004364_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004103_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004036_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003703_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004796_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_002234_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_002544_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS = (
    *COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000561_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001581_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001615_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003369_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003703_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004796_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002234_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002544_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001976_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_011996_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002506_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002150_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000619_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_005212_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002430_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000042_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000543_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000225_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000226_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000581_FAMILY_PAIRS,
)

COMPILER_AMBIGUITY_PACKET_004147_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000914_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002216_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001514_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001954_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000766_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS = (
    *COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    *COMPILER_REFINED_PACKET_000766_FAMILY_PAIRS,
)

COMPILER_AMBIGUITY_PACKET_001983_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004362_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004156_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004009_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000795_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004100_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000499_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003624_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002680_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003643_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003653_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003296_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003829_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003819_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003886_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003906_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS = (
    *COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003906_FAMILY_PAIRS,
)

COMPILER_AMBIGUITY_PACKET_003934_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003996_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000819_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002015_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_007034_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_006057_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001622_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004913_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002650_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002228_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004344_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000738_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003786_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001808_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002788_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_014167_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002920_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001944_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000906_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000353_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000269_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000354_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000099_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000105_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000108_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000522_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001248_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000220_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000242_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_005573_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_003022_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000001_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_003992_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_002968_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REFINED_PACKET_002605_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000001_RESCUE_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000232_RESCUE_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_002694_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_002695_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_002827_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_004382_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000440_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_003441_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_001099_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_001115_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000260_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_000114_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000496_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000519_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_002666_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000123_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000124_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000126_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000122_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_000146_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000111_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_000222_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_003313_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_003650_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_003960_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_004579_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_004746_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REFINED_PACKET_000507_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001879_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000745_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_REFINED_PACKET_001386_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000116_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000113_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000151_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_007352_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_005680_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_005581_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000518_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000179_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_002303_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS = (
    *COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    *COMPILER_REFINED_PACKET_002542_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000191_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_005573_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003022_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000001_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003992_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002968_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002605_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000001_RESCUE_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000232_RESCUE_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002694_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002695_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002827_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_004382_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000440_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003441_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000745_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003313_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002303_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003650_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003960_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_004579_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_004746_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000507_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001386_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001115_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000260_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000953_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000114_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000496_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000519_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002666_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000123_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000124_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000126_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000122_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000146_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000111_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000222_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000043_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000044_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000112_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000192_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000113_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000116_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000151_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_007352_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_005680_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_005581_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000518_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000179_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001095_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001753_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003186_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_004762_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_005718_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_005786_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000162_FAMILY_PAIRS,
)

COMPILER_AMBIGUITY_PACKET_000183_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000080_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000101_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000018_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000696_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000295_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000179_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002123_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000652_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002271_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_007716_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001057_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001528_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001552_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000577_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004053_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002155_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000782_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000662_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001691_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001392_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001692_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_003238_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_002330_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004540_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004656_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004672_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004673_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004674_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_004828_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005115_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005157_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000935_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000661_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000778_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001001_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001002_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001309_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_001310_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000182_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000618_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_000202_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_000601_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    *COMPILER_AMBIGUITY_PACKET_001032_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003130_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005045_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006301_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005157_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000935_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000661_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000778_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001001_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001002_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001309_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001310_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000182_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001029_FAMILY_PAIRS,
    *COMPILER_RESCUE_REFRESH_PACKET_004444_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001879_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000509_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000139_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000140_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000431_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000421_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000669_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005496_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001127_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001151_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001257_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001472_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001518_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001605_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001638_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001674_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001551_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001730_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001759_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001807_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002415_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001840_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000583_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000102_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002561_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000746_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001976_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002110_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002111_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002364_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002638_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002681_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002717_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002740_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002859_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002890_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002900_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000163_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002929_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002993_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003205_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003527_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003746_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003818_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003760_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002998_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002777_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003275_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002719_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004476_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003775_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003779_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003791_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006483_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003279_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003615_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003688_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003252_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003103_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003321_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003341_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003624_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002680_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003643_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003296_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003653_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003829_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003819_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003886_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003906_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003934_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003996_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004362_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004156_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000127_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004121_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004179_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004364_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004009_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004100_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004103_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004036_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003703_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004796_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004147_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000914_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002216_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000819_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002015_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007034_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006057_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001622_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004913_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002650_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002228_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004344_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000738_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003786_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001808_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002788_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_014167_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001944_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000906_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000269_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000353_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000354_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000099_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000109_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000105_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000108_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000130_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000131_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000132_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000133_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000134_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000135_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000136_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001691_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001392_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001692_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002330_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004540_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004656_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004672_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004673_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004674_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004828_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005266_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002315_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002414_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002602_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000496_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000498_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005849_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000157_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000160_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000159_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000158_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000720_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000781_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000721_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001059_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001512_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001529_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001550_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000119_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000214_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000114_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000124_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000522_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001248_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000008_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000220_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000242_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000183_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000080_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000101_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000018_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000696_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000295_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000486_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000179_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002123_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000652_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002271_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007716_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001057_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001528_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001552_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000577_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004053_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000182_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000618_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002155_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000953_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003094_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003158_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000534_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000535_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000348_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002327_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001479_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001316_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001029_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000536_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000629_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000224_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007373_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000225_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000538_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001308_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001265_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006116_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006816_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000697_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000180_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000521_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000393_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000394_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000495_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000619_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000406_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000542_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000545_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000228_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000223_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003336_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002204_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002580_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002578_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000594_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000587_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000580_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003559_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001068_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002315_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002414_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002602_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002607_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000588_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000613_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000610_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000782_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000662_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001691_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001392_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001692_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003238_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004540_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004656_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004672_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004674_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004828_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005266_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000653_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000111_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000117_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000118_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000120_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000121_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000161_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000162_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000165_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000166_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000167_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000168_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000128_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000131_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000132_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000133_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000134_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000135_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000136_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000205_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000206_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000254_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000964_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000148_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000154_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000155_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000207_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000297_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000298_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001514_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001954_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001983_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000951_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001061_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001547_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002162_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002163_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002823_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002363_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004164_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004926_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004997_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005687_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002840_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002877_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005886_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005912_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005985_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001444_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_008598_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_008285_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007995_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012436_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_011661_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002254_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012544_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012244_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000005_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004160_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_009549_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001981_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001264_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_009945_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001581_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003148_FAMILY_PAIRS,
    *COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    *COMPILER_AMBIGUITY_CORE_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000177_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_011135_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006897_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003057_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001001_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001002_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001309_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001310_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000521_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000853_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001040_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000893_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001703_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001314_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001479_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001316_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000269_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000353_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000354_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000099_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000105_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000108_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000522_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001248_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002055_FAMILY_PAIRS,
)

COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.HYBRID.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    *COMPILER_AMBIGUITY_PACKET_006115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000697_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000154_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000155_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000124_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000125_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001032_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003130_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005045_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006301_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005157_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000935_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000661_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000778_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001001_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001002_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001309_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001310_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001029_FAMILY_PAIRS,
    *COMPILER_RESCUE_REFRESH_PACKET_004444_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001879_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000509_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000139_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000140_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000431_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000421_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000669_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005496_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000319_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000795_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001127_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001151_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001257_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001472_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001605_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001638_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001674_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001551_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002638_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001247_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001540_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001730_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001759_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001807_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002415_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001840_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000583_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000102_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002561_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000746_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001976_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002110_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002111_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002300_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002364_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002681_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002717_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002740_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002859_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002890_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002900_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000163_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002929_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002993_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003205_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003527_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003746_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003818_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003760_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002998_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002777_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003275_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002719_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004476_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003775_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003779_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003791_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006483_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003279_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003615_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003688_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003252_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003103_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003321_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003341_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003624_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003643_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003296_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003653_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003829_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003886_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003906_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003934_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003996_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004362_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004156_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004121_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004179_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004364_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004009_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004100_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004103_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004036_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003703_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004147_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000914_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002216_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000499_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000819_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002015_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007034_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001622_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004913_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002650_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002228_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004344_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000738_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003786_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001808_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002788_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_014167_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001944_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000906_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000008_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000220_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000242_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000183_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000080_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000101_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000018_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000696_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000295_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000179_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002123_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000652_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002271_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007716_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001057_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001528_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001552_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000577_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004053_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000182_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000618_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002155_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000953_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003094_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003158_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000534_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000535_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000348_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001268_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002327_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001479_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000536_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000629_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000599_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000224_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007373_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000538_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001308_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001265_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006116_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000180_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006816_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000521_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000393_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000394_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000495_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000486_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000619_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000406_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000542_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003336_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002204_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001514_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001954_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001983_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000951_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001061_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001547_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002162_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002163_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002823_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002363_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004164_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004926_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004997_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005687_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002840_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002877_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005886_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005912_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005985_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001444_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_008598_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_008285_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007995_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012436_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_011661_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002254_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012544_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012244_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000005_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001108_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001104_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_009549_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001981_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_011996_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001264_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_009945_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003148_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000043_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000169_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000170_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002506_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002643_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000114_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002666_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000123_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000126_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000146_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_007352_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000194_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000114_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000177_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000124_FAMILY_PAIRS,
    *COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    *COMPILER_AMBIGUITY_CORE_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_011135_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006897_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003057_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000206_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000853_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001040_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000893_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001314_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001479_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001316_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000207_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000297_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000298_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000228_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000223_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000120_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000121_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000161_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000162_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000165_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000166_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000167_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000168_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000128_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000132_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000133_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000134_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000135_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000136_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000164_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000496_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000498_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005849_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000157_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000160_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000159_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000158_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000720_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000781_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000721_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001059_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001512_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001529_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001550_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000119_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000214_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000964_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000269_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000353_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000354_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000522_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000105_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000108_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001248_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000588_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002330_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004540_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004656_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004672_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004673_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004674_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004828_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002055_FAMILY_PAIRS,
)

ZERO_MARGIN_CONTESTED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_WEAK_TYPED_SELF_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR: Mapping[
    Tuple[str, str],
    float,
] = {
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): 0.135,
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ): 0.17,
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ): 0.155,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ): 0.19,
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ): 0.195,
}

COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR: Mapping[
    Tuple[str, str],
    float,
] = {
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.ALETHIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ): 0.0015,
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): 0.02,
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.ALETHIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.EPISTEMIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ): 0.0015,
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DYNAMIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): 0.095,
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ): 0.086,
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ): 0.08,
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ): 0.28,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): 0.095,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ): 0.105,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ): 0.095,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ): 0.49,
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ): 0.085,
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ): 0.006,
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ): 0.325,
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): 0.0015,
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): 0.18,
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): 0.0015,
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ): 0.0015,
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ): 0.0015,
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DOXASTIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): 0.52,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ): 0.415,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ): 0.53,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ): 0.135,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ): 0.24,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DYNAMIC.value,
    ): 0.0015,
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ): 0.18,
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ): 0.02,
}

SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.HYBRID.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    *COMPILER_AMBIGUITY_PACKET_001032_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003130_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005045_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006301_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005157_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000935_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000661_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000778_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001002_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001309_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001310_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001029_FAMILY_PAIRS,
    *COMPILER_RESCUE_REFRESH_PACKET_004444_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001879_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001127_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001151_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001257_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001472_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001605_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001638_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001674_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001551_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001540_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001730_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002638_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001759_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001807_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002415_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001840_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000583_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000102_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002561_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000746_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001976_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002110_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002111_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002364_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002681_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002717_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002740_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002859_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002890_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002929_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002993_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003205_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003527_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003746_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003818_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003760_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002998_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002777_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003275_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002719_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004476_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003775_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003779_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003791_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006483_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003279_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003615_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003688_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003252_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003103_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003321_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003341_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003624_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003643_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003296_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003653_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003829_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003886_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003906_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003934_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003996_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004362_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004156_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004121_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004179_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004364_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004009_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004100_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004103_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004036_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003703_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004147_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000914_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002216_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000819_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002015_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007034_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006057_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001622_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004913_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002650_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002228_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004344_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000738_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003786_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001808_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002788_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001944_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001954_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000509_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000139_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000140_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000431_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000421_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000669_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005496_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000951_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001061_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001547_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002162_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002163_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002823_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002363_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004164_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004926_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004997_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005687_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002840_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002877_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005886_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005912_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005985_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001444_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_008598_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_008285_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007995_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012436_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_011661_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002254_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012544_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012244_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000005_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001108_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001104_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004160_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_009549_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001981_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_011996_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001264_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_009945_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002506_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000114_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002666_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000114_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000124_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_014167_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000906_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000353_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000354_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000522_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000105_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000108_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001248_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002920_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000008_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000220_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000242_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000183_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000080_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000101_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000018_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000696_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000295_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000179_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002123_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000652_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002271_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007716_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001057_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001528_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001552_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000577_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004053_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000182_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000618_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002155_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000953_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003094_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003158_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000157_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000160_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000159_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000158_FAMILY_PAIRS,
    *COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    *COMPILER_REFINED_PACKET_000114_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002666_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000123_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000126_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000122_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_007352_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000114_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000124_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001581_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000169_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002346_FAMILY_PAIRS,
    *COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001944_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_011135_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006897_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000521_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000393_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000394_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000495_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000486_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000619_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000406_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000893_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001703_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001233_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001314_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001479_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001316_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000120_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000121_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000161_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000162_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000165_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000166_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000167_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000168_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000534_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000535_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000348_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002327_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001479_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000536_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000629_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000224_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007373_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000538_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001308_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001265_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006116_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000180_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000521_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000542_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000206_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000545_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000207_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000297_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000298_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000228_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000223_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003336_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002204_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002212_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002580_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000594_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000587_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000580_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003559_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001068_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002315_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002414_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002602_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000588_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000613_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000610_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000782_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000662_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001691_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001392_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001692_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003238_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002330_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004540_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004656_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004672_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004673_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004674_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004828_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005157_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000935_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000661_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000778_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001002_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001309_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001310_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001029_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000560_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000561_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005247_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005266_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000653_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000111_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000205_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000254_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000964_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000148_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000154_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000155_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001514_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003056_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000120_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000121_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000161_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000162_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000166_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000167_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000168_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000128_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000130_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000131_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000132_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000133_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000134_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000135_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000136_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000164_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002055_FAMILY_PAIRS,
)


def _ordered_unique_adaptive_ambiguity_family_pairs(
    pairs: Iterable[Tuple[str, str]],
) -> Tuple[Tuple[str, str], ...]:
    """Return a stable pair table with duplicates removed and order preserved."""
    unique_pairs: list[Tuple[str, str]] = []
    seen_pairs: set[Tuple[str, str]] = set()
    for pair in pairs:
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        unique_pairs.append(pair)
    return tuple(unique_pairs)


COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000601_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002295_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002296_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000186_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000188_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000189_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000194_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000280_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000191_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000202_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003057_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003166_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003171_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003229_FAMILY_PAIRS,
        )
    )
)

COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000601_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002295_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002296_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000186_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000188_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000189_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000194_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000280_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000191_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000202_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003057_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003166_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003171_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003229_FAMILY_PAIRS,
        )
    )
)

SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000601_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002295_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002296_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000186_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000188_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000189_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000194_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000280_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000191_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000202_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003057_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003166_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003171_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003229_FAMILY_PAIRS,
        )
    )
)

PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.HYBRID.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    *COMPILER_AMBIGUITY_PACKET_001127_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001151_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001257_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001472_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001605_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001638_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001674_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001551_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001730_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001753_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002638_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001759_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001807_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002415_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001840_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000583_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000102_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002561_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000746_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001976_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002110_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002111_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002364_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002681_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002717_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002740_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002859_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002929_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002993_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003205_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003527_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003746_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003818_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003760_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002998_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002777_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003275_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002719_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004476_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003775_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003779_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003791_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006483_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003615_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003688_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003252_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003103_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003321_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003341_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003624_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003643_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003296_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003653_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003829_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003886_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003906_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003934_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003996_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000127_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004121_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004179_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004364_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004009_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004100_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004103_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004036_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003703_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004147_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000819_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002015_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001954_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001983_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006057_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001622_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004913_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002650_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002228_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003786_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004344_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000509_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000139_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000140_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000431_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000421_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000669_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000951_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001061_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001547_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002162_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002163_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002823_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002363_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004164_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004926_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004997_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005687_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002840_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002877_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005886_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005912_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005985_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001444_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_008598_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_008285_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007995_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012436_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_011661_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002254_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012544_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_012244_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000005_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001108_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001104_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004160_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_009549_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001981_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_011996_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_001264_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_009945_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002506_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002788_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_014167_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000906_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000008_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005496_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000220_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000242_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000183_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000080_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000101_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000018_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000696_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000295_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000179_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002123_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002271_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007716_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001057_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001528_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001552_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000577_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004053_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000182_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000618_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000393_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002155_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000953_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003094_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003158_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000157_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000160_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000159_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000158_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002580_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000594_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000587_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000580_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003559_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002094_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001068_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000588_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000613_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000610_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000782_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000662_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001691_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001392_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001692_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002330_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004540_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004656_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004672_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004673_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004674_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_004828_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005115_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000560_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000561_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005247_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005266_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000653_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000111_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000205_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000206_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001514_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000109_FAMILY_PAIRS,
    *COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    *COMPILER_REFINED_PACKET_001581_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_011135_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006897_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000893_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001479_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002328_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001316_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000534_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000535_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000348_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002327_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000536_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000629_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000224_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_007373_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000538_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006116_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_006816_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000697_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000180_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000521_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000542_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000207_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000297_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000298_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000228_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000223_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_003336_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002204_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000254_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000964_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000148_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000154_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000155_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000109_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001514_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001529_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001550_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000119_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000214_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000120_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000121_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000161_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000162_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000175_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002212_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000165_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000166_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000167_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000168_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000128_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000131_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000132_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000133_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000134_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000135_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000136_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000125_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000496_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000498_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_005849_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000778_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001001_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001002_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001309_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001310_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_000486_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_001029_FAMILY_PAIRS,
    *COMPILER_AMBIGUITY_PACKET_002055_FAMILY_PAIRS,
)

PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000601_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002295_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002296_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000186_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000188_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000189_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000194_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000280_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000191_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000202_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003057_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003166_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003171_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003229_FAMILY_PAIRS,
        )
    )
)


COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002864_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003062_FAMILY_PAIRS,
        )
    )
)

COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002864_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003062_FAMILY_PAIRS,
        )
    )
)

SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002864_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003062_FAMILY_PAIRS,
        )
    )
)

PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_002864_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003062_FAMILY_PAIRS,
        )
    )
)

class ModalSystem(Enum):
    """Common modal systems and legal-parser profiles."""

    K = "K"
    T = "T"
    D = "D"
    K4 = "K4"
    S4 = "S4"
    S5 = "S5"
    KD = "KD"
    KD45 = "KD45"
    LTL = "LTL"
    CTL = "CTL"
    PDL = "PDL"
    STIT = "STIT"
    FRAME_BM25 = "FRAME_BM25"
    HYBRID = "HYBRID"


@dataclass(frozen=True)
class ModalOperatorSpec:
    """Description of an operator and its deterministic text cues."""

    symbol: str
    aliases: Tuple[str, ...]
    arity: int = 1
    cue_terms: Tuple[str, ...] = ()
    allowed_systems: Tuple[ModalSystem, ...] = ()


@dataclass(frozen=True)
class ModalSemanticsSpec:
    """Frame constraints for a modal profile."""

    reflexive: bool = False
    transitive: bool = False
    serial: bool = False
    symmetric: bool = False
    euclidean: bool = False
    tree_time: bool = False
    action_transition: bool = False
    ontology_frame_grounded: bool = False

    def to_dict(self) -> Dict[str, bool]:
        """Return a stable JSON-ready mapping."""
        return {
            "action_transition": self.action_transition,
            "euclidean": self.euclidean,
            "ontology_frame_grounded": self.ontology_frame_grounded,
            "reflexive": self.reflexive,
            "serial": self.serial,
            "symmetric": self.symmetric,
            "transitive": self.transitive,
            "tree_time": self.tree_time,
        }


@dataclass(frozen=True)
class ModalParseProfile:
    """Registry entry for one modal parsing profile."""

    family: ModalLogicFamily
    system: ModalSystem
    operators: Tuple[ModalOperatorSpec, ...]
    semantics: ModalSemanticsSpec = field(default_factory=ModalSemanticsSpec)
    description: str = ""

    @property
    def profile_id(self) -> str:
        """Stable profile identifier."""
        return f"{self.family.value}:{self.system.value}"

    def to_dict(self) -> Dict[str, object]:
        """Return a stable JSON-ready mapping."""
        return {
            "description": self.description,
            "family": self.family.value,
            "operators": [
                {
                    "aliases": list(operator.aliases),
                    "allowed_systems": [system.value for system in operator.allowed_systems],
                    "arity": operator.arity,
                    "cue_terms": list(operator.cue_terms),
                    "symbol": operator.symbol,
                }
                for operator in self.operators
            ],
            "profile_id": self.profile_id,
            "semantics": self.semantics.to_dict(),
            "system": self.system.value,
        }


def _op(
    symbol: str,
    aliases: Iterable[str],
    cue_terms: Iterable[str],
    systems: Iterable[ModalSystem],
) -> ModalOperatorSpec:
    return ModalOperatorSpec(
        symbol=symbol,
        aliases=tuple(aliases),
        cue_terms=tuple(cue_terms),
        allowed_systems=tuple(systems),
    )


DEFAULT_MODAL_PROFILES: Tuple[ModalParseProfile, ...] = (
    ModalParseProfile(
        family=ModalLogicFamily.ALETHIC,
        system=ModalSystem.S5,
        operators=(
            _op("□", ("necessary", "must_be"), ("necessary", "impossible", "cannot"), (ModalSystem.K, ModalSystem.T, ModalSystem.S4, ModalSystem.S5)),
            _op("◇", ("possible",), ("possible", "can be"), (ModalSystem.K, ModalSystem.T, ModalSystem.S4, ModalSystem.S5)),
        ),
        semantics=ModalSemanticsSpec(reflexive=True, transitive=True, symmetric=True, euclidean=True),
        description="Alethic necessity and possibility.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.DEONTIC,
        system=ModalSystem.D,
        operators=(
            _op(
                "O",
                ("obligation", "obligatory"),
                (
                    "shall",
                    "shall administer",
                    "shall apply",
                    "shall appoint",
                    "shall bear",
                    "shall become",
                    "shall be administered",
                    "shall be deposited",
                    "shall be fined",
                    "shall be the trustee",
                    "shall conduct",
                    "shall contain",
                    "shall consult",
                    "shall collect",
                    "shall collect duties",
                    "shall develop",
                    "shall determine",
                    "shall discontinue",
                    "shall establish",
                    "shall establish a program",
                    "shall have jurisdiction",
                    "shall have jurisdiction over",
                    "shall issue",
                    "shall issue guidelines",
                    "shall make",
                    "shall prepare and submit",
                    "shall prepare and transmit",
                    "shall provide",
                    "shall regularly monitor",
                    "shall reserve",
                    "shall solicit",
                    "shall study",
                    "shall state",
                    "shall take",
                    "shall take appropriate actions",
                    "shall take effect",
                    "shall transmit",
                    "shall deputize",
                    "must",
                    "must be undertaken",
                    "requirement for",
                    "on-site manager requirement",
                    "before obligating",
                    "required",
                    "required submission",
                    "obligated",
                    "has a duty to",
                    "have a duty to",
                    "under an obligation to",
                    "provide for",
                    "continuing responsibility",
                    "continuing secretarial responsibility",
                    "shall have a continuing responsibility",
                    "shall serve",
                    "shall be appointed",
                    "may be appointed",
                    "may be promoted",
                    "shall be retired",
                    "commissioned officer",
                    "commissioned officer corps",
                    "is entitled to",
                    "shall be entitled to",
                    "shall be applicable",
                    "shall be appointed by",
                    "shall be construed",
                    "shall be construed to",
                    "shall be construed to limit",
                    "shall be construed to restrict",
                    "shall be construed to circumvent",
                    "shall be consistent",
                    "shall be deemed",
                    "shall be ineligible",
                    "shall not affect",
                    "shall not be construed",
                    "shall not be construed to limit",
                    "shall not be construed to restrict",
                    "shall not be construed to circumvent",
                    "shall not apply",
                    "provisions of this subchapter shall not apply",
                    "shall be unlawful",
                    "it is unlawful",
                    "may accept",
                    "may accept and expend",
                    "may be made available",
                    "may be construed",
                    "may discontinue",
                    "may be extended",
                    "may designate",
                    "may appoint a board of inquiry",
                    "required quarterly reports",
                    "shall be punished",
                    "shall be fined or imprisoned",
                    "subject to a civil penalty",
                    "subject to penalty",
                    "liable for a civil penalty",
                    "is liable for",
                    "shall be eligible",
                    "shall pay",
                    "shall pay to",
                    "shall provide benefits",
                    "shall be received",
                    "shall be received in all courts",
                    "shall make payments",
                    "may make grants",
                    "shall furnish hospitalization",
                    "shall administer the park",
                    "shall ensure",
                    "shall keep",
                    "shall have the right",
                    "shall have access",
                    "shall be exercised",
                    "shall file",
                    "administer and enforce",
                    "administer and enforce the collection",
                    "collection of customs duties",
                    "unlawful",
                    "unlawful activities",
                ),
                (ModalSystem.D, ModalSystem.KD),
            ),
            _op(
                "P",
                ("permission", "permitted"),
                (
                    "may",
                    "may acquire",
                    "may be administered",
                    "may be used",
                    "may carry out",
                    "may collect",
                    "may deem",
                    "may guarantee",
                    "may obtain",
                    "may present",
                    "may prescribe",
                    "may provide",
                    "may take",
                    "may use",
                    "may make and file",
                    "may inspect",
                    "may declare",
                    "permitted",
                    "authorized",
                    "authorization to purchase",
                    "is authorized to",
                    "is authorized to conduct",
                    "authorized and empowered",
                    "is authorized and empowered",
                    "are authorized to be appropriated",
                    "there are authorized to be appropriated",
                    "allowed",
                ),
                (ModalSystem.D, ModalSystem.KD),
            ),
            _op(
                "F",
                ("prohibition", "forbidden"),
                (
                    "may not",
                    "shall be construed to limit",
                    "shall be construed to restrict",
                    "shall be construed to circumvent",
                    "shall not be construed to limit",
                    "shall not be construed to restrict",
                    "shall not be construed to circumvent",
                    "may not be closed",
                    "must not",
                    "no member",
                    "no person",
                    "no funds may",
                    "no amount may",
                    "no person shall",
                    "may not declare",
                    "prohibited",
                    "forbidden",
                ),
                (ModalSystem.D, ModalSystem.KD),
            ),
        ),
        semantics=ModalSemanticsSpec(serial=True),
        description="Legal obligations, permissions, and prohibitions.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.TEMPORAL,
        system=ModalSystem.LTL,
        operators=(
            _op("G", ("always",), ("always", "throughout", "until"), (ModalSystem.LTL, ModalSystem.CTL)),
            _op(
                "F",
                ("eventually",),
                (
                    "eventually",
                    "temporary withdrawal",
                    "withdrawal from settlement",
                    "entry of desert lands",
                    "within",
                    "by",
                    "effective date",
                    "effective date of repeal",
                    "renumbered",
                    "renumbered as",
                    "renumbered section",
                    "section renumbered",
                    "sections renumbered",
                    "sec. renumbered",
                    "repealed",
                    "repealed by",
                    "repealed effective",
                    "section repealed",
                    "sections repealed",
                    "repeal of",
                    "as amended",
                    "amended by",
                    "effective on first day",
                    "effective on and after",
                    "fiscal year",
                    "fiscal years",
                    "calendar year",
                    "calendar years",
                    "for each fiscal year",
                    "for each of fiscal years",
                    "for fiscal years",
                    "for each succeeding fiscal year",
                    "for each subsequent fiscal year",
                    "for the first fiscal year",
                    "for the subsequent fiscal year",
                    "for each year thereafter",
                    "for each calendar year",
                    "for calendar years",
                    "on january 1",
                    "beginning of each subsequent calendar year",
                    "subsequent calendar year",
                    "authorization of appropriations",
                    "authorizations of appropriations",
                    "expenses of carrying out",
                    "for the expenses of carrying out",
                    "study authorized by section",
                    "grant period",
                    "fellowship period",
                    "award period",
                    "during each fiscal year",
                    "preceding fiscal year",
                    "beginning after",
                    "appropriations for fiscal year",
                    "appropriations for fiscal years",
                    "for fiscal year",
                    "for a period of",
                    "for a period not to exceed",
                    "until expended",
                    "until recommendations are made",
                    "available until expended",
                    "remain available until expended",
                    "period of not less than",
                    "period not to exceed",
                    "not less than",
                    "not more than",
                    "not to exceed",
                    "from time to time",
                    "immediate use",
                    "immediate prosecution",
                    "remain available",
                    "available without fiscal year limitation",
                    "without fiscal year limitation",
                    "thereafter",
                    "on or after",
                    "on and after",
                    "prior to",
                    "beginning on or after",
                    "no earlier than",
                    "no later than",
                    "not earlier than",
                    "not later than",
                    "at such time",
                    "as of",
                    "on the date before",
                    "at any reasonable time",
                    "regular and periodic",
                    "periodic audits",
                    "preceding 2 years",
                    "time prescribed",
                    "time and manner",
                    "due date",
                    "filing date",
                    "notification of an active measures campaign",
                    "receive notification after",
                    "notification after the director determines",
                    "after the director determines",
                ),
                (ModalSystem.LTL, ModalSystem.CTL),
            ),
            _op(
                "X",
                ("next",),
                (
                    "next",
                    "after",
                    "following",
                    "after notice and hearing",
                    "after notice and opportunity for hearing",
                ),
                (ModalSystem.LTL, ModalSystem.CTL),
            ),
        ),
        semantics=ModalSemanticsSpec(tree_time=True),
        description="Deadlines, effective dates, and temporal scopes.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.EPISTEMIC,
        system=ModalSystem.S5,
        operators=(
            _op(
                "K",
                ("knows", "knowledge"),
                (
                    "knows",
                    "finds",
                    "congress finds",
                    "finds and declares",
                    "in the opinion of",
                    "board of inquiry",
                    "inquiry into",
                    "inquire into",
                    "determines",
                    "determined",
                    "determine whether",
                    "has reason to know",
                    "has reason to believe",
                    "actual knowledge",
                    "knowledge of",
                    "knowingly",
                    "likely to",
                    "reasonable basis",
                    "reasonable cause",
                    "reason to believe",
                    "in the opinion of",
                    "opinion of",
                    "public interests require",
                    "monitoring and enforcement",
                    "report to congress",
                    "annual report to congress",
                    "assessment",
                    "assessments",
                ),
                (ModalSystem.S4, ModalSystem.S5),
            ),
        ),
        semantics=ModalSemanticsSpec(reflexive=True, transitive=True, symmetric=True, euclidean=True),
        description="Knowledge, findings, and determinations.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.DOXASTIC,
        system=ModalSystem.KD45,
        operators=(
            _op(
                "B",
                ("believes", "belief"),
                (
                    "believe",
                    "believed",
                    "belief",
                    "believes",
                    "intend",
                    "intended",
                    "intends",
                    "intent to",
                    "with intent",
                    "with intent to",
                    "intent to defraud",
                    "with the intent to",
                    "knowingly",
                    "willful",
                    "willfully",
                    "knowingly",
                    "knowingly and willfully",
                    "false statement",
                    "misrepresentation",
                    "fraudulent",
                    "reasonably believes",
                    "suspect",
                    "suspected",
                    "suspects",
                ),
                (ModalSystem.KD45,),
            ),
        ),
        semantics=ModalSemanticsSpec(serial=True, transitive=True, euclidean=True),
        description="Belief and intent-style legal states.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.DYNAMIC,
        system=ModalSystem.PDL,
        operators=(
            _op(
                "[a]",
                ("after_action",),
                (
                    "files",
                    "serves",
                    "transfers",
                    "transferred to and vested in",
                    "vested in",
                    "terminates",
                    "enforces",
                ),
                (ModalSystem.PDL, ModalSystem.STIT),
            ),
        ),
        semantics=ModalSemanticsSpec(action_transition=True),
        description="Action transitions and pre/postconditions.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.CONDITIONAL_NORMATIVE,
        system=ModalSystem.KD,
        operators=(
            _op(
                "O|",
                ("conditional_obligation",),
                (
                    "if",
                    "unless",
                    "unless the aggregate amount appropriated",
                    "except",
                    "all conditions",
                    "conditions and exclusions",
                    "conditions, exclusions",
                    "failure of",
                    "failure to",
                    "there is authorized to be appropriated",
                    "authorized to be appropriated",
                    "no funds are authorized to be appropriated",
                    "in lieu of",
                    "be in lieu of",
                    "provided that",
                    "provided, that",
                    "provided , that",
                    "subject to",
                    "severability",
                    "held invalid",
                    "held to be invalid",
                    "remainder of this",
                    "validity of the remainder",
                    "shall not be affected",
                    "shall not affect",
                    "as provided by",
                    "as provided under",
                    "as otherwise provided in",
                    "as otherwise provided by",
                    "as otherwise provided under",
                    "except as otherwise provided",
                    "except as provided in",
                    "except as provided by",
                    "does not affect",
                    "except to the extent",
                    "except to the extent provisions",
                    "to the extent provided",
                    "to the extent that",
                    "in the event that",
                    "in the case of",
                    "as a condition of",
                    "as a condition to",
                    "at the request of",
                    "upon the request of",
                    "upon request",
                    "request of the governor",
                    "on the basis of",
                    "shall be considered as amounts received in exchange",
                    "provided, however, that",
                    "only if",
                    "for purposes of",
                    "for the purposes of",
                    "for purposes of this subchapter",
                    "for that purpose",
                    "the following definitions shall apply",
                    "section applicable to",
                    "amendment made by this section",
                    "shall apply to taxable years beginning after",
                    "provided that this title apply",
                    "to the extent consistent with",
                    "in accordance with",
                    "in accordance with the provisions",
                    "notwithstanding",
                    "pursuant to",
                    "under applicable law",
                    "under such regulations",
                    "under terms and conditions",
                    "under such terms and conditions",
                    "on such terms and conditions",
                    "upon terms and conditions",
                    "upon such terms and conditions",
                    "subject to terms and conditions",
                    "subject to such terms and conditions",
                    "subject to the terms and conditions",
                    "subject to subsection",
                    "subject to subsection b",
                    "subject to section",
                    "subject to paragraph",
                    "subject to subparagraph",
                    "subject to chapter",
                    "subject to this section",
                    "subject to this chapter",
                    "subject to this title",
                    "applies to",
                    "applicable to",
                    "when used in this chapter",
                    "when used in this section",
                    "subject only to",
                    "subject, however, to",
                    "subject however to",
                    "with respect to",
                    "insofar as",
                    "insofar as practicable",
                ),
                (ModalSystem.KD,),
            ),
        ),
        semantics=ModalSemanticsSpec(serial=True),
        description="Conditions, exceptions, provisos, and scoped norms.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.FRAME,
        system=ModalSystem.FRAME_BM25,
        operators=(
            _op(
                "Frame",
                ("ontology_frame",),
                (
                    "is a",
                    "part of",
                    "administered by",
                    "jurisdiction",
                    "jurisdiction of",
                    "jurisdiction of state courts",
                    "authority",
                    "authority of",
                    "authority for employment",
                    "authority under",
                    "amendments to orders",
                    "beneficial interest",
                    "board of directors",
                    "class of licensed facilities",
                    "compensation of",
                    "corporation",
                    "director or officer",
                    "does not apply",
                    "duties and powers",
                    "effective date of repeal",
                    "exclusive right",
                    "law enforcement authority",
                    "licensed facility",
                    "mechanisms to evaluate",
                    "employment and retention",
                    "power development",
                    "provided for compensation",
                    "rule of construction",
                    "rules and regulations",
                    "savings provision",
                    "title to said",
                    "transfer of title",
                    "unrestricted deed",
                    "vested rights",
                    "this chapter applies",
                    "as used in this chapter",
                    "purposes of the corporation",
                    "articles of incorporation",
                    "civil actions",
                    "courts in civil actions",
                    "state courts",
                ),
                (ModalSystem.FRAME_BM25,),
            ),
        ),
        semantics=ModalSemanticsSpec(ontology_frame_grounded=True),
        description="Ontology-grounded frame logic selected with BM25.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.HYBRID,
        system=ModalSystem.HYBRID,
        operators=(),
        description="Composed profiles for statutory clauses with mixed modal content.",
    ),
)


class ModalRegistry:
    """Lookup table for modal parse profiles."""

    def __init__(self, profiles: Iterable[ModalParseProfile] = DEFAULT_MODAL_PROFILES) -> None:
        self._profiles: Dict[str, ModalParseProfile] = {
            profile.profile_id: profile for profile in profiles
        }
        self._by_family: Dict[ModalLogicFamily, ModalParseProfile] = {
            profile.family: profile for profile in profiles
        }

    def get_profile(
        self,
        family: ModalLogicFamily | str,
        system: Optional[ModalSystem | str] = None,
    ) -> ModalParseProfile:
        """Get a profile by family, optionally constrained by system."""
        resolved_family = family if isinstance(family, ModalLogicFamily) else ModalLogicFamily(str(family))
        if system is None:
            return self._by_family[resolved_family]
        resolved_system = system if isinstance(system, ModalSystem) else ModalSystem(str(system))
        return self._profiles[f"{resolved_family.value}:{resolved_system.value}"]

    def all_profiles(self) -> Tuple[ModalParseProfile, ...]:
        """Return all profiles in deterministic order."""
        return tuple(sorted(self._profiles.values(), key=lambda profile: profile.profile_id))

    def to_dict(self) -> Mapping[str, object]:
        """Return a stable JSON-ready registry mapping."""
        return {profile.profile_id: profile.to_dict() for profile in self.all_profiles()}


def is_normative_modal_family(family: ModalLogicFamily | str) -> bool:
    """Return whether a modal family encodes normative legal force."""
    if isinstance(family, ModalLogicFamily):
        resolved = family
    else:
        try:
            resolved = ModalLogicFamily(str(family))
        except ValueError:
            return False
    return resolved in NORMATIVE_MODAL_FAMILIES


def supports_signal_free_adaptive_ambiguity_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether an adaptive pair should emit ambiguity without target cues."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(
        target_family,
        prefer_target_side=True,
    )
    return (
        resolved_target_family
        in compiler_ambiguity_policy_targets(resolved_predicted_family)
        or is_signal_free_adaptive_ambiguity_pair(
            resolved_predicted_family,
            resolved_target_family,
        )
        or resolved_target_family
        in compiler_required_adaptive_ambiguity_targets(resolved_predicted_family)
    )


def compiler_refined_modal_family_cue_margin_buffer(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> float:
    """Return an additive low-margin threshold buffer for refined cue-policy pairs."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(
        target_family,
        prefer_target_side=True,
    )
    return float(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (
                resolved_predicted_family,
                resolved_target_family,
            ),
            0.0,
        )
    )


def compiler_weak_typed_self_family_cue_margin_buffer(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> float:
    """Return extra weak-evidence buffer for typed self-family adaptive pairs."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(
        target_family,
        prefer_target_side=True,
    )
    return float(
        COMPILER_WEAK_TYPED_SELF_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (
                resolved_predicted_family,
                resolved_target_family,
            ),
            0.0,
        )
    )


def compiler_ambiguity_policy_targets(
    predicted_family: ModalLogicFamily | str,
) -> Tuple[str, ...]:
    """Return ordered targets covered by the compiler_ambiguity policy bundle."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    return tuple(
        target_family
        for source_family, target_family in COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS
        if source_family == resolved_predicted_family
    )


def signal_free_adaptive_ambiguity_targets(
    predicted_family: ModalLogicFamily | str,
) -> Tuple[str, ...]:
    """Return ordered adaptive-ambiguity targets requiring signal-free handling."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    return tuple(
        target_family
        for source_family, target_family in SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
        if source_family == resolved_predicted_family
    )


def is_signal_free_adaptive_ambiguity_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether a pair is in the signal-free adaptive ambiguity policy."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(
        target_family,
        prefer_target_side=True,
    )
    return (
        resolved_predicted_family,
        resolved_target_family,
    ) in SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS


def priority_signal_free_adaptive_ambiguity_targets(
    predicted_family: ModalLogicFamily | str,
) -> Tuple[str, ...]:
    """Return ordered high-priority adaptive-ambiguity targets."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    return tuple(
        target_family
        for source_family, target_family in PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
        if source_family == resolved_predicted_family
    )


def compiler_required_adaptive_ambiguity_targets(
    predicted_family: ModalLogicFamily | str,
) -> Tuple[str, ...]:
    """Return ordered compiler-required adaptive ambiguity targets."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    return tuple(
        target_family
        for source_family, target_family in COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
        if source_family == resolved_predicted_family
    )


def is_compiler_required_adaptive_ambiguity_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether a pair is in the compiler-required ambiguity policy bundle."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(
        target_family,
        prefer_target_side=True,
    )
    return (
        resolved_predicted_family,
        resolved_target_family,
    ) in COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS


def is_compiler_ambiguity_policy_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether a pair is part of the compiler_ambiguity synthesis bundle."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(
        target_family,
        prefer_target_side=True,
    )
    return (
        resolved_predicted_family,
        resolved_target_family,
    ) in COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS


def is_priority_signal_free_adaptive_ambiguity_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether a pair is part of the highest-priority adaptive ambiguity policy."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(
        target_family,
        prefer_target_side=True,
    )
    return (
        resolved_predicted_family,
        resolved_target_family,
    ) in PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS


def prefers_contested_zero_margin_adaptive_ambiguity_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether a zero-margin adaptive pair should be contested, not outvoted."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(
        target_family,
        prefer_target_side=True,
    )
    return (
        resolved_predicted_family,
        resolved_target_family,
    ) in ZERO_MARGIN_CONTESTED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS


def _resolve_modal_family_name(
    family: ModalLogicFamily | str,
    *,
    prefer_target_side: bool = False,
) -> str:
    if isinstance(family, ModalLogicFamily):
        return family.value
    resolved = str(family).strip()
    if not resolved:
        return ""
    if "->" in resolved:
        source_family, target_family = resolved.split("->", maxsplit=1)
        directional_side = target_family if prefer_target_side else source_family
        directional_side = directional_side.strip()
        if directional_side:
            resolved = directional_side
    candidate_tokens: list[str] = []
    seen_tokens: set[str] = set()

    def _remember(token: str) -> None:
        normalized = str(token).strip()
        if not normalized or normalized in seen_tokens:
            return
        seen_tokens.add(normalized)
        candidate_tokens.append(normalized)

    leaf_dot = resolved.rsplit(".", maxsplit=1)[-1].strip()
    leaf_colon = leaf_dot.rsplit(":", maxsplit=1)[-1].strip()
    leaf_slash = leaf_colon.rsplit("/", maxsplit=1)[-1].strip()
    leaf_pipe = leaf_slash.rsplit("|", maxsplit=1)[-1].strip()
    split_tokens: list[str] = []
    delimiters = ("->", ".", ":", "/", "|")
    for delimiter in delimiters:
        if delimiter not in resolved:
            continue
        split_tokens.extend(
            part.strip()
            for part in resolved.split(delimiter)
            if str(part).strip()
        )
    for token in (
        resolved,
        leaf_dot,
        leaf_colon,
        leaf_slash,
        leaf_pipe,
        *split_tokens,
    ):
        _remember(token)
        lowered = token.lower()
        _remember(lowered)
        _remember(lowered.replace("-", "_").replace(" ", "_"))

    for token in candidate_tokens:
        try:
            return ModalLogicFamily(token).value
        except ValueError:
            continue
    return resolved.lower()


COMPILER_REFINED_PACKET_002837_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_002839_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_002842_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_003002_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

COMPILER_REFINED_PACKET_003192_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_003438_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005554_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005666_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_005884_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_005556_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_006096_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
)

COMPILER_REFINED_PACKET_006101_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_007052_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_007710_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_AMBIGUITY_PACKET_007816_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DOXASTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_007144_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_PACKET_000279_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
)

COMPILER_REFINED_PACKET_003200_FAMILY_PAIRS = _ordered_unique_adaptive_ambiguity_family_pairs(
    COMPILER_REFINED_PACKET_003200_FAMILY_PAIRS
)

COMPILER_AMBIGUITY_PACKET_000371_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
)

COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS = (
    *COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    *COMPILER_REFINED_PACKET_002837_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002839_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_002842_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003002_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003192_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003438_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_005884_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_003200_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_006096_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_006101_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_007052_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_007144_FAMILY_PAIRS,
    *COMPILER_REFINED_PACKET_000279_FAMILY_PAIRS,
)

COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002837_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002839_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002842_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003002_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003192_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003438_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_005884_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003200_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003360_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005348_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005554_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005666_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005556_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_006902_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_006096_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_006101_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_007052_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_007710_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_007816_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000371_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_007144_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000279_FAMILY_PAIRS,
        )
    )
)

COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002837_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002839_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002842_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003002_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003192_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003438_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_005884_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003200_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003360_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005348_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005554_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005666_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005556_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_006902_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_006096_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_006101_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_007052_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_007710_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_007816_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000371_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_007144_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000279_FAMILY_PAIRS,
        )
    )
)

SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002837_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002839_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002842_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003002_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003192_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003438_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_005884_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003200_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003360_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005348_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005554_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005666_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005556_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_006902_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_006096_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_006101_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_007052_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_007710_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_007816_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000371_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_007144_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000279_FAMILY_PAIRS,
        )
    )
)

PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        (
            *PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002837_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002839_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_002842_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003002_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003192_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003438_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_005884_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_003200_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_003360_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005348_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005554_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005666_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_005556_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_006902_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_006096_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_006101_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_007052_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_007710_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_007816_FAMILY_PAIRS,
            *COMPILER_AMBIGUITY_PACKET_000371_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_007144_FAMILY_PAIRS,
            *COMPILER_REFINED_PACKET_000279_FAMILY_PAIRS,
        )
    )
)


COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR = {
    **COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR,
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
                ModalLogicFamily.DEONTIC.value,
            ),
            0.0,
        ),
        0.16,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ),
            0.0,
        ),
        0.075,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (
                ModalLogicFamily.DEONTIC.value,
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ),
            0.0,
        ),
        0.45,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (
                ModalLogicFamily.TEMPORAL.value,
                ModalLogicFamily.TEMPORAL.value,
            ),
            0.0,
        ),
        0.035,
    ),
    (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value), 0.0
        ),
        0.36,
    ),
    (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.FRAME.value): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.FRAME.value), 0.0
        ),
        0.38,
    ),
    (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value), 0.0
        ),
        0.12,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (
                ModalLogicFamily.FRAME.value,
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ),
            0.0,
        ),
        0.82,
    ),
    (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value), 0.0
        ),
        0.62,
    ),
    (ModalLogicFamily.FRAME.value, ModalLogicFamily.EPISTEMIC.value): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (ModalLogicFamily.FRAME.value, ModalLogicFamily.EPISTEMIC.value), 0.0
        ),
        0.34,
    ),
    (ModalLogicFamily.FRAME.value, ModalLogicFamily.DOXASTIC.value): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (ModalLogicFamily.FRAME.value, ModalLogicFamily.DOXASTIC.value), 0.0
        ),
        0.5,
    ),
    (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value), 0.0
        ),
        0.7,
    ),
    (ModalLogicFamily.FRAME.value, ModalLogicFamily.FRAME.value): max(
        COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (ModalLogicFamily.FRAME.value, ModalLogicFamily.FRAME.value), 0.0
        ),
        0.16,
    ),
}

COMPILER_WEAK_TYPED_SELF_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR = {
    **COMPILER_WEAK_TYPED_SELF_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR,
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ): max(
        COMPILER_WEAK_TYPED_SELF_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (
                ModalLogicFamily.TEMPORAL.value,
                ModalLogicFamily.TEMPORAL.value,
            ),
            0.0,
        ),
        0.18,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ): max(
        COMPILER_WEAK_TYPED_SELF_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR.get(
            (
                ModalLogicFamily.FRAME.value,
                ModalLogicFamily.FRAME.value,
            ),
            0.0,
        ),
        0.095,
    ),
}


DEFAULT_MODAL_REGISTRY = ModalRegistry()


__all__ = [
    "DEFAULT_MODAL_PROFILES",
    "DEFAULT_MODAL_REGISTRY",
    "COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_006115_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002055_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002864_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000008_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000431_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000421_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000509_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000669_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005496_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000003_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000319_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000795_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000499_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001127_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001151_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001257_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001472_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001518_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001528_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001552_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000577_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004053_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000182_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000618_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000601_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002155_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001605_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001638_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001674_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001551_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001247_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001540_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001730_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001753_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001759_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001807_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002415_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001840_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000186_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000188_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000189_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000194_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000583_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000102_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002561_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000746_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001976_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002110_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002111_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002300_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002364_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002638_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002681_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002717_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002740_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002859_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002890_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002900_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000163_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002929_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002993_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003205_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003527_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003746_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003818_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003760_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002998_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002777_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003275_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002719_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004476_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003775_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003779_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003791_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_006483_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003615_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003688_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003252_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003103_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003321_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003328_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003624_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002680_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003643_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003296_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003653_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003829_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003819_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003886_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003906_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003934_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003996_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004364_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004156_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004100_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000127_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004121_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004179_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004009_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004103_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004036_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003703_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004796_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004147_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000914_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002216_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000819_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002015_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_007034_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_006057_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001622_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004913_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002650_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002228_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004344_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000738_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003786_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001808_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001954_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001983_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000951_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001032_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001033_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003130_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001061_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001547_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001108_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001104_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002162_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002163_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002788_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002823_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002363_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004164_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004926_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004997_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005687_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002840_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002877_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005045_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_006301_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005157_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000935_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000661_FAMILY_PAIRS",
    "COMPILER_RESCUE_REFRESH_PACKET_004444_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005886_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005912_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005985_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001444_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_014167_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002920_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001944_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000906_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000220_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000242_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000183_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000080_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000101_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000018_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000696_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000295_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000179_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000652_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002271_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_007716_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001057_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002123_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003094_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003158_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003369_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003148_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000953_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000114_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000496_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000519_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000123_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000124_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000126_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000122_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000146_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000043_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000044_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000112_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000192_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000194_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003336_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000099_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000269_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000353_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000354_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000104_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000105_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000108_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000522_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001248_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000169_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000165_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000170_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000172_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000258_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000259_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000301_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000346_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000407_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_004070_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002204_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002212_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002580_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002578_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002094_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000594_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000587_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000580_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003559_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001068_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002315_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002414_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002602_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002607_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000588_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000613_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000610_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000782_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000662_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001691_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001392_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001692_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003238_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002330_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004540_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004656_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004672_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004673_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004674_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004828_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005115_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000653_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000111_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000117_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000118_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000120_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000121_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000161_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000162_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000175_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000165_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000166_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000167_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000168_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000128_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000130_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000131_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000132_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000133_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000134_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000135_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000136_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000164_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000496_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000498_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005849_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000157_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000160_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000159_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000158_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000720_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000781_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000721_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001059_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001512_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001529_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001550_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000119_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000214_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000114_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000115_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000124_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000140_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000125_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000205_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000206_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000254_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000964_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000148_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000154_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000155_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000109_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000207_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000297_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000280_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000298_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000228_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000223_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000561_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005247_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005266_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001514_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001581_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001615_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000766_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001702_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001117_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003056_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_008598_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_008285_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_007995_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_012436_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_011661_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002254_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_012544_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_012244_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000005_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000004_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_004160_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_009549_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_CORE_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000177_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_011135_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_006897_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_006902_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003057_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003062_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003166_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003229_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_003360_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005348_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005554_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005666_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_005556_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002542_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000191_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000202_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000534_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000535_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000348_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002327_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000536_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000629_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000599_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000224_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_007373_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000225_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000538_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001308_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001265_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_006116_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_006816_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000697_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000180_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000521_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000393_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000394_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000495_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002295_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002296_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000486_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000619_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000406_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000853_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001233_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001040_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000893_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001703_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001268_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001479_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_002328_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001316_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000542_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000545_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000560_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000778_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001001_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001002_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001309_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001310_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001029_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001264_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001981_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002346_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_009945_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001976_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002643_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002787_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002342_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002506_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002544_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000461_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001627_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001844_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002474_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002051_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003282_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000593_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_001879_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003313_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003650_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003960_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_004579_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_004746_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000507_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_011996_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002150_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000619_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_005212_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002430_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_005573_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003022_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000306_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000001_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000001_RESCUE_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000232_RESCUE_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003992_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002605_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002694_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002695_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001386_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002968_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002827_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_004382_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000440_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003441_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001115_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000745_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000260_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000116_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000113_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000151_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_007352_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_005680_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_005581_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000518_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000179_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000111_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000222_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002666_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000467_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000543_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000226_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000581_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001095_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003186_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_005718_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_005786_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000520_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000176_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002303_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002837_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002839_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_002842_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_006101_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_007052_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_007710_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_007816_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_PACKET_000371_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_007144_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000279_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003002_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003192_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003438_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_005884_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003200_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_001063_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_003357_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_004489_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_004071_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_004348_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000399_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_004762_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_004558_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_000138_FAMILY_PAIRS",
    "COMPILER_REFINED_PACKET_007187_FAMILY_PAIRS",
    "COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS",
    "COMPILER_REFINED_MODAL_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR",
    "COMPILER_WEAK_TYPED_SELF_FAMILY_CUE_MARGIN_BUFFER_BY_PAIR",
    "COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
    "compiler_refined_modal_family_cue_margin_buffer",
    "compiler_weak_typed_self_family_cue_margin_buffer",
    "compiler_ambiguity_policy_targets",
    "is_compiler_ambiguity_policy_pair",
    "ZERO_MARGIN_CONTESTED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
    "compiler_required_adaptive_ambiguity_targets",
    "is_compiler_required_adaptive_ambiguity_pair",
    "NORMATIVE_MODAL_FAMILIES",
    "PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
    "SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
    "is_priority_signal_free_adaptive_ambiguity_pair",
    "ModalLogicFamily",
    "ModalOperatorSpec",
    "ModalParseProfile",
    "ModalRegistry",
    "ModalSemanticsSpec",
    "ModalSystem",
    "is_normative_modal_family",
    "is_signal_free_adaptive_ambiguity_pair",
    "prefers_contested_zero_margin_adaptive_ambiguity_pair",
    "priority_signal_free_adaptive_ambiguity_targets",
    "signal_free_adaptive_ambiguity_targets",
    "supports_signal_free_adaptive_ambiguity_pair",
]
