"""Official national gazette collectors vendored from Hugging Face datasets.

Python collectors shipped in ``endomorphosis/legal_scrapers`` and in the
per-country ``endomorphosis/ipfs_*_laws`` dataset ``scrapers/`` trees live
here. JusticeDAO ``ipfs_*_laws_ir`` datasets reuse
:mod:`ipfs_datasets_py.processors.legal_scrapers.country_laws_ir`.
"""

from .catalog import (
    BY_DATASET,
    BY_ISO,
    BY_MODULE,
    COLLECTORS,
    COLLECTORS_DIR,
    HF_SOURCE_DATASET,
    IN_TREE_SCRAPERS,
    NationalCollector,
    collector_for_hf_dataset,
    get_national_collector,
    hf_dataset_coverage,
    list_national_collectors,
    load_collector_module,
)

__all__ = [
    "BY_DATASET",
    "BY_ISO",
    "BY_MODULE",
    "COLLECTORS",
    "COLLECTORS_DIR",
    "HF_SOURCE_DATASET",
    "IN_TREE_SCRAPERS",
    "NationalCollector",
    "collector_for_hf_dataset",
    "get_national_collector",
    "hf_dataset_coverage",
    "list_national_collectors",
    "load_collector_module",
]
