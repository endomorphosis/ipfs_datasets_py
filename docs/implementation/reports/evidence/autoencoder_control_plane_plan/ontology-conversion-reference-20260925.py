"""Historical recipient/procedure functions before observation-only hooks.

Diagnostic reference: execute each function with its original module globals.
No runtime cache or complete-capture assertion is implied.
"""
from __future__ import annotations


# Source: ipfs_datasets_py/logic/autoformal/recipient_reference.py
# Original source SHA-256: 4f180765d49b173772eaa17e7582e0de9185a700e52bb7c235f966c24d517217

def recipient_surface_from_sentence(text: str) -> str:
    """Surface the deontic parser already stored. Does not invent a recipient."""

    from ipfs_datasets_py.logic.deontic import DeonticConverter

    converted = DeonticConverter(
        jurisdiction="us",
        document_type="statute",
        use_ml=False,
        use_cache=False,
        enable_monitoring=False,
    ).convert(text)
    elements = list(getattr(getattr(converted, "output", None), "parser_elements", ()) or [])
    for element in elements:
        if not isinstance(element, dict):
            continue
        surface = " ".join(str(element.get("action_recipient") or "").split())
        if surface:
            return surface
    from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_action_recipient

    return " ".join(str(extract_action_recipient(text) or "").split())


# Source: ipfs_datasets_py/logic/autoformal/procedure_slot.py
# Original source SHA-256: f0de735845451825858ae5b6cabc1fe5f76acf435d211f985aec6ec73ea7238b

def procedure_from_sentence(text: str) -> dict[str, Any]:
    """The procedure record the deontic parser already stored. Does not invent events."""

    from ipfs_datasets_py.logic.deontic import DeonticConverter

    converted = DeonticConverter(
        jurisdiction="us",
        document_type="statute",
        use_ml=False,
        use_cache=False,
        enable_monitoring=False,
    ).convert(text)
    elements = list(getattr(getattr(converted, "output", None), "parser_elements", ()) or [])
    for element in elements:
        if not isinstance(element, dict):
            continue
        record = element.get("procedure") or {}
        events = [str(event) for event in record.get("events") or [] if str(event).strip()]
        if events:
            return {
                "events": events,
                "procedure_id": procedure_id(events),
                "surface": " -> ".join(events),
                "admitted": False,
            }
    return {"events": [], "procedure_id": "", "surface": "", "admitted": False}
