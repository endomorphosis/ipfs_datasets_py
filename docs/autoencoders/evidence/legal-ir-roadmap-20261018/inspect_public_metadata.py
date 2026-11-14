"""Bounded, standard-library-only public metadata inspection for a planning snapshot.

No authentication, parquet, weights, dataset/package imports, or model execution.
Usage: python inspect_public_metadata.py --output NEW_FILE.json
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPOSITORIES = (
    "justicedao/ipfs_uscode",
    "justicedao/uscode-autoformal-span-cache",
    "justicedao/uscode-autoformal-entity-cache",
)
MAX_BYTES = 2_000_000


def fetch(url, parse_json=True):
    observation = {"url": url}
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "LegalIR-planning-readonly/1.0"}
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read(MAX_BYTES + 1)
            observation["http_status"] = response.status
        if len(raw) > MAX_BYTES:
            return {**observation, "error": "response_exceeds_byte_limit"}, None
        observation.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        return observation, json.loads(raw) if parse_json else raw.decode("utf-8")
    except urllib.error.HTTPError as error:
        observation.update(http_status=error.code, error="http_error")
    except Exception as error:
        observation["error"] = type(error).__name__
    return observation, None


def inspect(repository):
    meta_receipt, meta = fetch("https://huggingface.co/api/datasets/" + repository)
    result = {"repository": repository, "metadata_observation": meta_receipt}
    if not isinstance(meta, dict) or not meta.get("sha"):
        return result
    revision = meta["sha"]
    result.update(
        revision=revision,
        last_modified=meta.get("lastModified"),
        license_metadata=(meta.get("cardData") or {}).get("license"),
        file_count=len(meta.get("siblings", [])),
    )
    readme_receipt, readme = fetch(
        f"https://huggingface.co/datasets/{repository}/resolve/{revision}/README.md",
        parse_json=False,
    )
    result["pinned_readme_observation"] = readme_receipt
    if isinstance(readme, str):
        # Retain bounded planning statements, not dataset row bodies.
        terms = ("source revision", "release point", "vector space", "not gold",
                 "diagnostic", "admitted", "formalized", "config_name")
        result["card_planning_lines"] = [
            line[:1000] for line in readme.splitlines()
            if any(term in line.lower() for term in terms)
        ][:32]
    query = urllib.parse.urlencode({"dataset": repository})
    split_receipt, split_body = fetch("https://datasets-server.huggingface.co/splits?" + query)
    result["viewer_splits_observation"] = split_receipt
    splits = split_body.get("splits", []) if isinstance(split_body, dict) else []
    result["viewer_splits"] = [{"config": s["config"], "split": s["split"]} for s in splits]
    selected = {"paired_spans", "formal_logic_text", "retained_outputs_v1", "autoformal_uscode"}
    result["viewer_schemas"] = []
    for split in splits:
        if split["config"] not in selected:
            continue
        params = urllib.parse.urlencode(
            {"dataset": repository, "config": split["config"], "split": split["split"]}
        )
        receipt, body = fetch("https://datasets-server.huggingface.co/first-rows?" + params)
        schema = {"config": split["config"], "split": split["split"], "observation": receipt}
        if isinstance(body, dict):
            schema["features"] = body.get("features", [])
            schema["returned_rows_count"] = len(body.get("rows", []))
            schema["row_content_exported"] = False
        result["viewer_schemas"].append(schema)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; preserve old observations and choose a new path")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        datasets = list(pool.map(inspect, REPOSITORIES))
    result = {
        "schema": "legal-ir-roadmap-public-metadata/v1",
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "public metadata and bounded first-row schema observations only",
        "limitations": [
            "Viewer endpoints are mutable and are not cryptographically joined to Hub revisions.",
            "README bytes were hashed; corpus/checkpoint payloads were not downloaded or verified.",
            "Sampled schemas and file presence establish neither population quality nor legal meaning.",
            "HTTP failures are access observations, not proof that repository data is absent.",
            "No training, inference, tests, Lean builds, uploads, or runtime state changes occurred.",
        ],
        "datasets": datasets,
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "datasets": [
        {"repository": item["repository"], "revision": item.get("revision"),
         "viewer_status": item.get("viewer_splits_observation", {}).get("http_status"),
         "sampled_schemas": len(item.get("viewer_schemas", []))}
        for item in datasets]}, indent=2))


if __name__ == "__main__":
    main()
