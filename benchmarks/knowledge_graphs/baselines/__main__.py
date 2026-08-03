"""CLI helpers for labelled baselines: ``python -m benchmarks.knowledge_graphs.baselines``.

Subcommands:

* ``list`` — show catalog entries
* ``validate`` — validate all baseline documents
* ``show PROFILE`` — print one baseline JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .catalog import load_baseline, load_catalog, scan_environments
from .ratify import validate_baseline_document


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.knowledge_graphs.baselines",
        description="Labelled load baselines and SLO gates (KGP-030).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List catalog baselines.")
    sub.add_parser("validate", help="Validate every baseline document.")
    p_show = sub.add_parser("show", help="Show one baseline document.")
    p_show.add_argument("profile")
    p_show.add_argument("--environment-label", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "list":
        cat = load_catalog()
        print(
            f"environments={cat.environments} "
            f"regression_limit={cat.regression_ratio_limit} "
            f"required={list(cat.required_profiles)}"
        )
        for b in cat.baselines:
            print(
                f"{b.environment_label:32s} {b.profile:20s} "
                f"{b.status:20s} {b.baseline_id}"
            )
        return 0

    if args.cmd == "validate":
        cat = scan_environments()
        failed = 0
        for ref in cat.baselines:
            data = json.loads(ref.path.read_text(encoding="utf-8"))
            problems = validate_baseline_document(data)
            if problems:
                failed += 1
                print(f"FAIL {ref.environment_label}/{ref.profile}")
                for p in problems:
                    print(f"  - {p}")
            else:
                print(f"OK   {ref.environment_label}/{ref.profile}")
        return 1 if failed else 0

    if args.cmd == "show":
        doc = load_baseline(
            args.profile, environment_label=args.environment_label
        )
        print(json.dumps(doc, indent=2, sort_keys=True))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
