"""Hermetic self-check for LFP2-040 agency profiles (no pytest required)."""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    failures = 0

    def check(name: str, fn) -> None:
        nonlocal failures
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {exc}")
            traceback.print_exc()

    from ipfs_datasets_py.logic.parsers.agency import (
        BDI_FAMILY_ID,
        CODE_AGENT_REQUIRED,
        CODE_DCEC_HOOK_REQUIRED,
        CODE_TIME_REQUIRED,
        DCEC_FAMILY_ID,
        DCECImporterHook,
        parse_agency,
        parse_print_parse,
        profile_agency,
        profile_bdi,
        profile_epistemic_temporal,
        profile_intention,
    )
    from ipfs_datasets_py.logic.syntax_core.ast import NodeKind

    def t_bdi() -> None:
        r = parse_agency(
            "believes[alice] p and desires[alice] q and intends[alice] r",
            profile_bdi(),
        )
        assert r.ok, [d.message for d in r.diagnostics]
        assert r.profile is not None
        assert r.profile.family_id == BDI_FAMILY_ID
        assert r.profile.family_id != DCEC_FAMILY_ID

    def t_agent_required() -> None:
        r = parse_agency("believes p", profile_bdi())
        assert not r.ok
        assert any(d.code == CODE_AGENT_REQUIRED for d in r.diagnostics)

    def t_et() -> None:
        r = parse_agency("knows[alice]@t0 safe", profile_epistemic_temporal())
        assert r.ok, [d.message for d in r.diagnostics]
        payload = dict(r.root.extension.payload)  # type: ignore[union-attr]
        assert payload["agent"] == "alice"
        assert payload["time"] == "t0"
        assert payload["frame"] == "s5"
        assert payload["is_dcec"] is False

    def t_et_time_required() -> None:
        r = parse_agency("knows[alice] safe", profile_epistemic_temporal())
        assert not r.ok
        assert any(d.code == CODE_TIME_REQUIRED for d in r.diagnostics)

    def t_agency() -> None:
        r = parse_agency(
            "does[alice]@t0 open_door and action(alice, open_door, t0)",
            profile_agency(),
        )
        assert r.ok, [d.message for d in r.diagnostics]

    def t_intention() -> None:
        r = parse_agency(
            "intends[alice] report and goal(alice, compliance)",
            profile_intention(),
        )
        assert r.ok, [d.message for d in r.diagnostics]

    def t_dcec_rejected() -> None:
        r = parse_agency("happens(turn_on, 1)", profile_bdi())
        assert not r.ok
        assert any(d.code == CODE_DCEC_HOOK_REQUIRED for d in r.diagnostics)

    def t_dcec_hook() -> None:
        hook = DCECImporterHook.enabled_bridge()
        prof = profile_bdi(dcec_hook=hook)
        assert prof.family_id == BDI_FAMILY_ID
        r = parse_agency("happens(turn_on, 1)", prof)
        assert r.ok, [d.message for d in r.diagnostics]
        assert r.root is not None and r.root.extension is not None
        assert r.root.extension.family.value == BDI_FAMILY_ID
        payload = dict(r.root.extension.payload)
        assert payload["imported_family"] == DCEC_FAMILY_ID
        assert payload["source_family"] == BDI_FAMILY_ID
        assert payload["source_family"] != payload["imported_family"]

    def t_round_trip() -> None:
        first, second, eq = parse_print_parse(
            "believes[alice] p implies intends[alice] q",
            profile_bdi(),
        )
        assert first.ok and second.ok and eq

    def t_implies_right() -> None:
        r = parse_agency("p -> q -> r", profile_bdi())
        assert r.ok, [d.message for d in r.diagnostics]
        assert r.root is not None
        assert r.root.kind is NodeKind.IMPLIES
        assert r.root.arguments[1].kind is NodeKind.IMPLIES

    for name, fn in [
        ("bdi", t_bdi),
        ("agent_required", t_agent_required),
        ("epistemic_temporal", t_et),
        ("et_time_required", t_et_time_required),
        ("agency", t_agency),
        ("intention", t_intention),
        ("dcec_rejected", t_dcec_rejected),
        ("dcec_hook", t_dcec_hook),
        ("round_trip", t_round_trip),
        ("implies_right", t_implies_right),
    ]:
        check(name, fn)

    if failures:
        print(f"\n{failures} failure(s)")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
