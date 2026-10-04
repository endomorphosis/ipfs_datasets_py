"""Authored source/fragment compositions for an explicitly sealed 384D test.

Only call ``rows('test', domain)`` after every compared fit is frozen. The
descriptor functions expose group identities without constructing source text
or targets. This panel measures authored fragment reconstruction, not general
natural-language entailment or a modality Lake build.
"""
from __future__ import annotations

DOMAINS = ("intent_ir", "ui_ux_ir")
SEEDS = (1729, 1730)
ACTORS = ("librarian", "inspector", "operator")
ACTIONS = ("catalog", "forward", "seal", "release")
MODALITIES = (("must", "required"), ("may", "permitted"), ("must not", "prohibited"))
COMPONENTS = ("archive_control", "publish_control", "review_control")
ROLES = ("radio", "combobox", "switch", "slider")
PRIVACIES = ("none", "high", "restricted")


def split_for(i: int, j: int, k: int) -> str:
    if not (0 <= i < 3 and 0 <= j < 4 and 0 <= k < 3):
        raise ValueError("panel coordinate outside fixed bounds")
    if k != (i + j) % 3:
        return "train"
    return "test" if j < 2 else "tuning"


def groups(split: str) -> list[tuple[int, int, int]]:
    if split not in {"train", "tuning", "test"}:
        raise ValueError("unknown split")
    return [(i, j, k) for i in range(3) for j in range(4) for k in range(3)
            if split_for(i, j, k) == split]


def metadata() -> dict:
    return {
        "schema": "source384-authored-composition-panel/v2",
        "domains": list(DOMAINS), "seeds": list(SEEDS),
        "counts_per_domain": {s: len(groups(s)) for s in ("train", "tuning", "test")},
        "split_coordinates": {s: groups(s) for s in ("train", "tuning", "test")},
        "split_rule": "hold out k=(i+j)%3; j<2 test, j>=2 tuning; other k training",
        "all_pair_identities_have_two_training_semantics": True,
        "input_scope": "fresh_authored_controlled_English_native_fragments",
        "source_entailment_proved": False,
        "full_document_coverage": False,
    }


def rows(split: str, domain: str) -> list[dict]:
    if domain not in DOMAINS:
        raise ValueError("unsupported domain")
    result = []
    for i, j, k in groups(split):
        if domain == "intent_ir":
            modal_text, modality = MODALITIES[k]
            source = f"The {ACTORS[i]} {modal_text} {ACTIONS[j]} the packet."
            target = {"kind": "intent_rich_ast", "document": {
                "kind": "atom", "actor": ACTORS[i], "action": ACTIONS[j],
                "modality": modality, "object": "packet",
            }}
        else:
            presentation = ("interactive", "static")[(i + j + k) % 2]
            source = (f"Component {COMPONENTS[i]} has role {ROLES[j]}. "
                      f"Its privacy sensitivity is {PRIVACIES[k]} and its "
                      f"presentation classification is {presentation}.")
            target = {"kind": "ui_component", "document": {
                "component_id": COMPONENTS[i], "role": ROLES[j],
                "privacy_sensitivity": PRIVACIES[k],
                "presentation_classification": presentation,
            }}
        result.append({"id": f"source384-v2:{domain}:{i}:{j}:{k}",
                       "source_text": source, "target": target})
    return result


def critical_paths(domain: str) -> tuple[tuple[str, ...], ...]:
    if domain == "intent_ir":
        names = ("actor", "action", "modality", "object")
    elif domain == "ui_ux_ir":
        names = ("component_id", "role", "privacy_sensitivity", "presentation_classification")
    else:
        raise ValueError("unsupported domain")
    return tuple(("document", name) for name in names)
