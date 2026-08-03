"""Synthetic USPTO office-action fixtures for PATLAW-032."""

from tests.fixtures.uspto.office_actions.generators import (
    NON_FINAL_CANARY,
    RESCIND_CANARY,
    REISSUE_CANARY,
    MALFORMED_CANARY,
    build_non_final_office_action_text,
    build_final_office_action_text,
    build_rescinded_reissued_pair,
    build_malformed_office_action_text,
    build_ambiguous_claim_range_text,
    build_notice_text,
    fixture_manifest,
)

__all__ = [
    "NON_FINAL_CANARY",
    "RESCIND_CANARY",
    "REISSUE_CANARY",
    "MALFORMED_CANARY",
    "build_non_final_office_action_text",
    "build_final_office_action_text",
    "build_rescinded_reissued_pair",
    "build_malformed_office_action_text",
    "build_ambiguous_claim_range_text",
    "build_notice_text",
    "fixture_manifest",
]
