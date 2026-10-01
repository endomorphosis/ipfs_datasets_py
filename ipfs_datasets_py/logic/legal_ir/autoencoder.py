"""Opt-in legal_ir inference from the pinned shared 384D development release."""
from __future__ import annotations


def open_autoencoder(*, optimized=False, **options):
    """Load this domain's actual checkpoint; cold imports remain offline."""
    if type(optimized) is not bool:
        raise ValueError("optimized must be a boolean")
    from ..formalization.autoencoder.checkpoint_hub import open_autoencoder as open_domain
    runtime = open_domain("legal_ir", **options)
    if optimized:
        from ..formalization.autoencoder.legal_inference_session import optimize_autoencoder
        runtime = optimize_autoencoder(runtime)
    return runtime


def formalize_with_autoencoder(source_text, *, autoencoder=None, **load_options):
    """Return a learned candidate IR, with no execution or proof authority.

    The current release is experimental and may abstain. This function does
    not silently replace the domain's deterministic compiler or invoke an LLM.
    Callers can retain their existing workflow when inference abstains.
    """
    runtime = autoencoder if autoencoder is not None else open_autoencoder(**load_options)
    if runtime.domain != "legal_ir":
        raise ValueError("checkpoint belongs to another IR domain")
    return runtime.infer_texts([source_text])
