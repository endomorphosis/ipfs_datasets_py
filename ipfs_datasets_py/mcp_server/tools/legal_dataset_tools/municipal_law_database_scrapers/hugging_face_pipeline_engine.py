"""HuggingFace upload pipeline engine (re-export shim).

Business logic has been moved to the canonical package location:
``ipfs_datasets_py.processors.legal_scrapers.huggingface_pipeline_engine``.

Import from the canonical location for new code::

    from ipfs_datasets_py.processors.legal_scrapers.huggingface_pipeline_engine import (
        RateLimiter,
        UploadToHuggingFaceInParallel,
    )
"""
# Re-export for backward compatibility
from ipfs_datasets_py.processors.legal_scrapers.huggingface_pipeline_engine import (  # noqa: F401
    RateLimiter,
    UploadToHuggingFaceInParallel,
)
