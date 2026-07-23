from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.email_workspace import (
    canonical_email_corpus_paths,
    import_local_eml_directory,
    merge_email_manifests,
)


def test_import_local_eml_directory_materializes_manifest_and_attachments(tmp_path: Path) -> None:
    source_dir = tmp_path / "emails"
    source_dir.mkdir()
    sample_eml = (
        b"From: \"Tilton, Kati\" <KTilton@clackamas.us>\r\n"
        b"To: benjamin barber <starworks5@gmail.com>\r\n"
        b"Subject: RE: HCV Orientation\r\n"
        b"Date: Thu, 26 Mar 2026 09:36:46 -0700\r\n"
        b"Message-ID: <msg-1@example.com>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=\"sep\"\r\n"
        b"\r\n"
        b"--sep\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Please see the attached denial for the living room accommodation.\r\n"
        b"--sep\r\n"
        b"Content-Type: text/plain; name=\"note.txt\"\r\n"
        b"Content-Disposition: attachment; filename=\"note.txt\"\r\n"
        b"\r\n"
        b"Attachment text.\r\n"
        b"--sep--\r\n"
    )
    (source_dir / "message.eml").write_bytes(sample_eml)

    payload = import_local_eml_directory(
        source_dir=source_dir,
        output_dir=tmp_path / "output",
        case_slug="local-confirmed",
        complaint_query="hcv orientation living room accommodation",
        complaint_keywords=["voucher"],
    )

    manifest_path = Path(payload["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["email_count"] == 1
    assert manifest["matched_email_count"] == 1
    assert manifest["complaint_terms"][:3] == ["hcv", "orientation", "living"]
    record = manifest["emails"][0]
    assert Path(record["email_path"]).is_file()
    assert Path(record["parsed_path"]).is_file()
    assert len(record["attachment_paths"]) == 1
    assert Path(record["attachment_paths"][0]).is_file()
    assert record["message_id_header"] == "<msg-1@example.com>"
    assert record["relevance_score"] > 0


def test_merge_email_manifests_deduplicates_by_message_id(tmp_path: Path) -> None:
    manifest_one = tmp_path / "one.json"
    manifest_two = tmp_path / "two.json"
    shared = {
        "message_id_header": "<shared@example.com>",
        "subject": "Shared thread",
        "date": "2026-03-01T10:00:00+00:00",
        "from": "a@example.com",
        "to": "b@example.com",
        "bundle_dir": "/tmp/shared",
        "attachment_paths": [],
    }
    manifest_one.write_text(
        json.dumps(
            {
                "complaint_terms": ["hcv", "orientation"],
                "min_relevance_score": 1.0,
                "emails": [
                    shared,
                    {
                        "message_id_header": "<one@example.com>",
                        "subject": "Only one",
                        "date": "2026-03-02T10:00:00+00:00",
                        "from": "a@example.com",
                        "to": "b@example.com",
                        "bundle_dir": "/tmp/one",
                        "attachment_paths": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_two.write_text(
        json.dumps(
            {
                "complaint_terms": ["living", "room"],
                "min_relevance_score": 2.0,
                "emails": [
                    shared,
                    {
                        "message_id_header": "<two@example.com>",
                        "subject": "Only two",
                        "date": "2026-03-03T10:00:00+00:00",
                        "from": "c@example.com",
                        "to": "d@example.com",
                        "bundle_dir": "/tmp/two",
                        "attachment_paths": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = merge_email_manifests(
        manifest_paths=[manifest_one, manifest_two],
        output_dir=tmp_path / "output",
        case_slug="merged",
    )

    merged = json.loads(Path(payload["manifest_path"]).read_text(encoding="utf-8"))
    ids = [record["message_id_header"] for record in merged["emails"]]

    assert payload["email_count"] == 3
    assert payload["duplicate_email_count"] == 1
    assert merged["matched_email_count"] == 3
    assert merged["duplicate_email_count"] == 1
    assert merged["min_relevance_score"] == 2.0
    assert ids == [
        "<shared@example.com>",
        "<one@example.com>",
        "<two@example.com>",
    ]
    assert merged["complaint_terms"] == ["hcv", "orientation", "living", "room"]


def test_canonical_email_corpus_paths_builds_expected_layout(tmp_path: Path) -> None:
    paths = canonical_email_corpus_paths(repo_root=tmp_path, case_slug="master-email")

    assert paths.manifest_path == tmp_path / "evidence" / "email_imports" / "master-email" / "email_import_manifest.json"
    assert paths.graphrag_dir == tmp_path / "evidence" / "email_imports" / "master-email" / "graphrag"
    assert paths.duckdb_path == tmp_path / "evidence" / "email_imports" / "master-email" / "graphrag" / "duckdb" / "email_search.duckdb"
