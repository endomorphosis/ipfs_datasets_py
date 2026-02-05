#!/usr/bin/env python3
"""Manage model selection config for benchmarks."""

from __future__ import annotations

import argparse
import json
from typing import List

from ipfs_datasets_py.utils.model_manager import (
    load_model_config,
    save_model_config,
    update_model_list,
)


def _split_models(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage model selection config.")
    parser.add_argument("--show", action="store_true", help="Print current config.")
    parser.add_argument("--set", metavar="KEY", help="Config key to update.")
    parser.add_argument("--models", metavar="LIST", help="Comma-separated model list.")

    args = parser.parse_args()

    if args.set:
        if not args.models:
            raise SystemExit("--models is required with --set")
        models = _split_models(args.models)
        config = update_model_list(args.set, models)
        print(json.dumps(config, indent=2))
        return 0

    if args.show:
        config = load_model_config()
        print(json.dumps(config, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
