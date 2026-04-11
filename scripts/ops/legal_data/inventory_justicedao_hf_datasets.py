from __future__ import annotations

import argparse
import json

from ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory import (
    dataset_profiles_to_dict,
    inspect_justicedao_datasets,
    render_dataset_profiles_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect JusticeDAO Hugging Face dataset structures.")
    parser.add_argument("--author", default="justicedao")
    parser.add_argument("--prefix", default="ipfs_")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    profiles = inspect_justicedao_datasets(author=args.author, dataset_prefix=args.prefix)
    if args.format == "json":
        print(json.dumps(dataset_profiles_to_dict(profiles), indent=2, sort_keys=True))
    else:
        print(render_dataset_profiles_markdown(profiles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())