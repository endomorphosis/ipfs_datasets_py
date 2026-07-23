from __future__ import annotations

import json
from pathlib import Path
import zipfile

from ipfs_datasets_py.processors.legal_data.courtlistener_cache_packaging import (
    load_packaged_courtlistener_fetch_cache,
    load_packaged_courtlistener_fetch_cache_components,
    package_courtlistener_fetch_cache,
)


def test_package_courtlistener_fetch_cache_writes_manifest_and_parquet(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    index_dir = cache_dir / "courtlistener_json" / "index"
    payload_dir = cache_dir / "courtlistener_json" / "payload"
    index_dir.mkdir(parents=True, exist_ok=True)
    payload_dir.mkdir(parents=True, exist_ok=True)

    payload_path = payload_dir / "abc123.json"
    payload_path.write_text(
        json.dumps({"url": "https://example.test/api", "answer": 42}),
        encoding="utf-8",
    )
    index_path = index_dir / "abc123.json"
    index_path.write_text(
        json.dumps(
            {
                "cache_key": "abc123",
                "url": "https://example.test/api",
                "normalized_url": "https://example.test/api",
                "payload_path": str(payload_path),
                "ipfs_cid": "bafytestcid",
            }
        ),
        encoding="utf-8",
    )

    package = package_courtlistener_fetch_cache(
        cache_dir,
        tmp_path / "bundle",
        package_name="courtlistener_cache_test",
        include_car=False,
    )

    assert Path(package["manifest_json_path"]).exists()
    assert Path(package["manifest_parquet_path"]).exists()
    assert not package["manifest_car_path"]
    assert package["summary"]["cache_index_count"] == 1
    assert package["summary"]["cache_payload_count"] == 1
    assert package["summary"]["mirrored_ipfs_entry_count"] == 1


def test_courtlistener_cache_bundle_can_roundtrip_from_json_parquet_car_and_zip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))
    cache_dir = tmp_path / "cache"
    index_dir = cache_dir / "courtlistener_json" / "index"
    payload_dir = cache_dir / "courtlistener_json" / "payload"
    index_dir.mkdir(parents=True, exist_ok=True)
    payload_dir.mkdir(parents=True, exist_ok=True)

    payload_path = payload_dir / "abc123.json"
    payload_path.write_text(
        json.dumps({"url": "https://example.test/api", "answer": 42}),
        encoding="utf-8",
    )
    index_path = index_dir / "abc123.json"
    index_path.write_text(
        json.dumps(
            {
                "cache_key": "abc123",
                "url": "https://example.test/api",
                "normalized_url": "https://example.test/api",
                "payload_path": str(payload_path),
                "ipfs_cid": "bafytestcid",
            }
        ),
        encoding="utf-8",
    )

    package = package_courtlistener_fetch_cache(
        cache_dir,
        tmp_path / "bundle",
        package_name="courtlistener_cache_roundtrip",
        include_car=True,
    )

    bundle_dir = Path(package["bundle_dir"])
    manifest_json_path = Path(package["manifest_json_path"])
    manifest_parquet_path = Path(package["manifest_parquet_path"])
    manifest_car_path = Path(package["manifest_car_path"])
    zip_path = bundle_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(bundle_dir.parent)))

    loaded_from_json = load_packaged_courtlistener_fetch_cache(manifest_json_path)
    loaded_from_parquet = load_packaged_courtlistener_fetch_cache(manifest_parquet_path)
    loaded_from_car = load_packaged_courtlistener_fetch_cache(manifest_car_path)
    loaded_from_zip = load_packaged_courtlistener_fetch_cache(zip_path)

    for loaded in (loaded_from_json, loaded_from_parquet, loaded_from_car, loaded_from_zip):
        assert loaded["summary"]["cache_index_count"] == 1
        assert len(loaded["cache_index"]) == 1
        assert len(loaded["cache_payloads"]) == 1

    components_from_parquet = load_packaged_courtlistener_fetch_cache_components(
        manifest_parquet_path,
        piece_ids=["cache_index", "cache_payloads"],
    )
    components_from_car = load_packaged_courtlistener_fetch_cache_components(
        manifest_car_path,
        piece_ids=["cache_index", "cache_payloads"],
    )
    components_from_zip = load_packaged_courtlistener_fetch_cache_components(
        zip_path,
        piece_ids=["cache_index", "cache_payloads"],
    )

    assert len(components_from_parquet["cache_index"]) == 1
    assert len(components_from_car["cache_index"]) == 1
    assert len(components_from_zip["cache_index"]) == 1
