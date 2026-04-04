"""
Google Voice export parsing utilities.

This module focuses on export-based ingestion instead of direct live API access.
That covers the Google Voice integration points that are currently practical:

- consumer Google Takeout exports
- Google Workspace Vault Voice exports
- Google Workspace Data Export bundles staged locally or copied from GCS
- local watch-folder automation that hydrates new exports into normalized bundles
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HTML_SUFFIXES = {".html", ".htm"}
_TEXT_SUFFIXES = {".txt", ".csv", ".vcf"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".amr", ".opus"}
_SIDECAR_SUFFIXES = {
    ".json",
    *_TEXT_SUFFIXES,
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    *_AUDIO_SUFFIXES,
    ".pdf",
}
_PHONE_RE = re.compile(
    r"(?<!\w)(\+?\d[\d().\-\s]{6,}\d|\(\d{3}\)\s*\d{3}[-.\s]?\d{4})(?!\w)"
)
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = str(data or "").strip()
        if text:
            self.parts.append(text)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip(".-")
    return cleaned or "item"


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mediator_evidence_record(bundle: dict[str, Any]) -> dict[str, Any]:
    participants = ", ".join(str(item or "") for item in list(bundle.get("phone_numbers") or []))
    return {
        "title": str(bundle.get("title") or bundle.get("event_type") or "Google Voice event"),
        "kind": "document",
        "source": "google_voice_import",
        "content": (
            f"Title: {bundle.get('title', '')}\n"
            f"Event type: {bundle.get('event_type', '')}\n"
            f"Date: {bundle.get('timestamp', '')}\n"
            f"Participants: {participants}\n"
            f"Transcript path: {bundle.get('transcript_path', '')}"
        ),
        "attachment_names": [Path(path).name for path in list(bundle.get("attachment_paths") or [])],
        "metadata": {
            "event_id": bundle.get("event_id"),
            "event_type": bundle.get("event_type"),
            "event_json_path": bundle.get("event_json_path"),
            "transcript_path": bundle.get("transcript_path"),
            "source_html_path": bundle.get("source_html_path"),
        },
    }


def _source_key_for_kind(source_kind: str) -> str:
    mapping = {
        "takeout": "google_voice_takeout",
        "vault_export": "google_voice_vault_export",
        "data_export": "google_voice_data_export",
    }
    return mapping.get(source_kind, "google_voice_import")


def materialize_google_voice_events(
    events: list[dict[str, Any]],
    *,
    output_dir: str | os.PathLike[str],
    start_index: int = 1,
    filename_prefix: str = "",
    manifest_name: str = "google_voice_manifest.json",
    source: str = "",
    source_kind: str = "takeout",
) -> dict[str, Any]:
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    bundles: list[dict[str, Any]] = []
    for offset, event in enumerate(events, start=start_index):
        title_part = _slugify(str(event.get("title") or event.get("event_type") or "google-voice"))
        id_part = _slugify(str(event.get("event_id") or offset))
        prefix = f"{filename_prefix}-" if filename_prefix else ""
        bundle_dir = output_root / f"{prefix}{offset:04d}-{title_part}-{id_part}"
        attachments_dir = bundle_dir / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)

        transcript_text = str(event.get("text_content") or "")
        transcript_path = bundle_dir / "transcript.txt"
        transcript_path.write_text(transcript_text, encoding="utf-8")

        source_html_path = Path(str(event.get("source_html") or "")).expanduser()
        exported_html_path = bundle_dir / "source.html"
        if source_html_path.is_file():
            exported_html_path.write_bytes(source_html_path.read_bytes())
        else:
            exported_html_path.write_text("", encoding="utf-8")

        attachment_records: list[dict[str, Any]] = []
        for raw_path in list(event.get("sidecar_paths") or []):
            source_path = Path(str(raw_path or "")).expanduser()
            if not source_path.is_file():
                continue
            destination = attachments_dir / source_path.name
            destination.write_bytes(source_path.read_bytes())
            attachment_records.append(
                {
                    "filename": destination.name,
                    "path": str(destination),
                    "size": destination.stat().st_size,
                    "content_type": mimetypes.guess_type(destination.name)[0] or "",
                    "sha256": _sha256_bytes(destination.read_bytes()),
                    "source_path": str(source_path),
                }
            )

        event_payload = {
            **event,
            "bundle_dir": str(bundle_dir),
            "transcript_path": str(transcript_path),
            "source_html_path": str(exported_html_path),
            "attachments": attachment_records,
            "attachment_count": len(attachment_records),
        }
        event_json_path = bundle_dir / "event.json"
        event_json_path.write_text(json.dumps(event_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        bundles.append(
            {
                "source_type": "google_voice",
                "event_id": event.get("event_id"),
                "event_type": event.get("event_type"),
                "title": event.get("title"),
                "subject": event.get("title"),
                "timestamp": event.get("timestamp"),
                "date": event.get("timestamp"),
                "phone_numbers": list(event.get("phone_numbers") or []),
                "participants": list(event.get("phone_numbers") or []),
                "bundle_dir": str(bundle_dir),
                "event_json_path": str(event_json_path),
                "parsed_path": str(event_json_path),
                "transcript_path": str(transcript_path),
                "source_html_path": str(exported_html_path),
                "attachment_paths": [item["path"] for item in attachment_records],
                "attachments": attachment_records,
                "text_content": transcript_text,
                "deduped_gmail_message_ids": list(event.get("deduped_gmail_message_ids") or []),
                "evidence_title": str(event.get("title") or event.get("event_type") or "Google Voice event"),
                "source_kind": str(event.get("source_kind") or source_kind),
            }
        )

    manifest = {
        "status": "success",
        "source": source,
        "source_kind": source_kind,
        "output_dir": str(output_root),
        "event_count": len(bundles),
        "bundles": bundles,
        "mediator_evidence_records": [
            {
                **_mediator_evidence_record(bundle),
                "source": _source_key_for_kind(str(bundle.get("source_kind") or source_kind)),
            }
            for bundle in bundles
        ],
    }
    manifest_path = output_root / manifest_name
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _guess_event_type(path: Path, title: str, text: str) -> str:
    haystack = " ".join(
        [
            path.stem.lower(),
            str(path.parent.name or "").lower(),
            str(title or "").lower(),
            str(text[:400] or "").lower(),
        ]
    )
    if "voicemail" in haystack:
        return "voicemail"
    if "missed" in haystack:
        return "missed_call"
    if "received" in haystack:
        return "received_call"
    if "placed" in haystack or "outgoing" in haystack:
        return "placed_call"
    if "recorded" in haystack or "recording" in haystack:
        return "recorded_call"
    if "text" in haystack or "message" in haystack or "sms" in haystack:
        return "text_message"
    return "voice_event"


def _extract_title(html_text: str, path: Path) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return path.stem.replace("_", " ")
    return _normalize_whitespace(html.unescape(match.group(1)))


def _extract_plain_text(html_text: str) -> str:
    parser = _TextHTMLParser()
    try:
        parser.feed(html_text)
    except Exception:
        return _normalize_whitespace(re.sub(r"<[^>]+>", " ", html_text))
    return _normalize_whitespace("\n".join(parser.parts))


def _extract_phone_numbers(*values: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for value in values:
        for match in _PHONE_RE.findall(str(value or "")):
            cleaned = _normalize_whitespace(match)
            digit_count = sum(1 for char in cleaned if char.isdigit())
            if 7 <= digit_count <= 15 and cleaned and cleaned not in seen:
                seen.add(cleaned)
                results.append(cleaned)
    return results


def _extract_timestamp(*values: str) -> str | None:
    for value in values:
        match = _ISO_RE.search(str(value or ""))
        if not match:
            continue
        raw = match.group(0)
        normalized = raw.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).astimezone(UTC).isoformat()
        except Exception:
            continue
    return None


def _load_sidecar_payload(path: Path) -> Any | None:
    try:
        if path.suffix.lower() == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        if path.suffix.lower() in {".txt", ".csv", ".vcf"}:
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return None


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _candidate_html_paths(root: Path) -> list[Path]:
    voice_roots = [candidate for candidate in [root, root / "Takeout" / "Voice", root / "Voice"] if candidate.exists()]
    html_paths: list[Path] = []
    for voice_root in voice_roots:
        html_paths.extend(
            path for path in sorted(voice_root.rglob("*")) if path.is_file() and path.suffix.lower() in _HTML_SUFFIXES
        )
    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in html_paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _iter_candidate_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in _HTML_SUFFIXES or suffix in _SIDECAR_SUFFIXES:
            candidates.append(path)
    return candidates


def _looks_like_voice_path(path: Path) -> bool:
    text = str(path).lower()
    markers = (
        "voice",
        "voicemail",
        "googlevoice",
        "google_voice",
        "call log",
        "call-log",
        "text message",
        "messages",
        "sms",
    )
    return any(marker in text for marker in markers)


def _candidate_voice_roots(root: Path) -> list[Path]:
    direct_candidates = [
        root,
        root / "Takeout" / "Voice",
        root / "Voice",
        root / "Google Voice",
        root / "Exports" / "Voice",
        root / "Voice" / "Messages",
    ]
    roots = [candidate for candidate in direct_candidates if candidate.exists()]
    for path in sorted(root.rglob("*")):
        if path.is_dir() and _looks_like_voice_path(path):
            roots.append(path)
    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in roots:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped or [root.resolve()]


def _group_export_files(root: Path) -> list[list[Path]]:
    groups: dict[Path, set[Path]] = {}
    for candidate_root in _candidate_voice_roots(root):
        for path in _iter_candidate_files(candidate_root):
            if not _looks_like_voice_path(path) and path.suffix.lower() not in _AUDIO_SUFFIXES:
                continue
            groups.setdefault(path.parent.resolve(), set()).add(path.resolve())
    deduped_groups: list[list[Path]] = []
    seen_dirs: set[Path] = set()
    for directory, paths in sorted(groups.items()):
        if directory in seen_dirs:
            continue
        seen_dirs.add(directory)
        deduped_groups.append(sorted(paths))
    return deduped_groups


def _build_export_event(root: Path, paths: list[Path], *, source_kind: str) -> dict[str, Any]:
    html_path = next((path for path in paths if path.suffix.lower() in _HTML_SUFFIXES), None)
    metadata_paths = [path for path in paths if path.suffix.lower() == ".json"]
    text_paths = [path for path in paths if path.suffix.lower() in _TEXT_SUFFIXES]
    audio_paths = [path for path in paths if path.suffix.lower() in _AUDIO_SUFFIXES]

    html_text = _read_text_file(html_path) if html_path else ""
    text_sections: list[str] = []
    sidecar_payloads: dict[str, Any] = {}

    if html_path:
        text_sections.append(_extract_plain_text(html_text))
    for path in metadata_paths + text_paths:
        payload = _load_sidecar_payload(path)
        if payload is not None:
            sidecar_payloads[path.name] = payload
        if isinstance(payload, str):
            text_sections.append(payload)
        elif payload is not None:
            text_sections.append(json.dumps(payload, ensure_ascii=False))

    title = _extract_title(html_text, html_path) if html_path else paths[0].parent.name.replace("_", " ")
    text_content = _normalize_whitespace("\n".join(section for section in text_sections if section))
    event_type = _guess_event_type(paths[0], title, text_content)
    timestamp = _extract_timestamp(title, text_content, *text_sections)
    phone_numbers = _extract_phone_numbers(title, text_content, *text_sections)
    relative_paths = [str(path.relative_to(root)) for path in paths if path.exists()]
    event_hash = hashlib.sha256("|".join(relative_paths).encode("utf-8")).hexdigest()[:16]

    return GoogleVoiceEvent(
        event_id=f"gv:{source_kind}:{event_hash}",
        event_type=event_type,
        title=title,
        timestamp=timestamp,
        text_content=text_content,
        phone_numbers=phone_numbers,
        source_html=str(html_path) if html_path else "",
        sidecar_paths=[str(path) for path in paths if path != html_path],
        sidecar_payloads=sidecar_payloads,
        metadata={
            "source_kind": source_kind,
            "relative_group_dir": str(paths[0].parent.relative_to(root)),
            "relative_paths": relative_paths,
            "audio_paths": [str(path.relative_to(root)) for path in audio_paths],
            "sidecar_count": len(paths) - (1 if html_path else 0),
        },
    ).as_dict()


def _is_gs_uri(value: str | os.PathLike[str]) -> bool:
    return str(value).startswith("gs://")


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a gs:// URI: {uri}")
    without_scheme = uri[5:]
    bucket, _, prefix = without_scheme.partition("/")
    return bucket, prefix.rstrip("/")


def _copy_local_source_to_stage(source: Path, stage_root: Path) -> Path:
    if stage_root.exists():
        shutil.rmtree(stage_root)
    if source.is_dir():
        shutil.copytree(source, stage_root)
        return stage_root
    stage_root.mkdir(parents=True, exist_ok=True)
    destination = stage_root / source.name
    shutil.copy2(source, destination)
    return destination


@dataclass(slots=True)
class GoogleVoiceEvent:
    event_id: str
    event_type: str
    title: str
    timestamp: str | None
    text_content: str
    phone_numbers: list[str]
    source_html: str
    sidecar_paths: list[str]
    sidecar_payloads: dict[str, Any]
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "title": self.title,
            "timestamp": self.timestamp,
            "text_content": self.text_content,
            "phone_numbers": list(self.phone_numbers),
            "source_html": self.source_html,
            "sidecar_paths": list(self.sidecar_paths),
            "sidecar_payloads": self.sidecar_payloads,
            "metadata": self.metadata,
        }


class GoogleVoiceProcessor:
    """
    Parse Google Voice export data from a Takeout directory or zip archive.
    """

    def __init__(self) -> None:
        self._temp_dirs: list[Path] = []

    def close(self) -> None:
        while self._temp_dirs:
            shutil.rmtree(self._temp_dirs.pop(), ignore_errors=True)

    def __enter__(self) -> "GoogleVoiceProcessor":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _materialize_root(self, source: str | os.PathLike[str]) -> Path:
        if _is_gs_uri(source):
            raise FileNotFoundError(
                f"GCS source requires stage_gcs_export() before parsing: {source}"
            )
        path = Path(source).expanduser().resolve()
        if path.is_dir():
            return path
        if path.is_file() and path.suffix.lower() == ".zip":
            temp_root = Path(tempfile.mkdtemp(prefix="google_voice_takeout_"))
            self._temp_dirs.append(temp_root)
            with zipfile.ZipFile(path) as zf:
                zf.extractall(temp_root)
            return temp_root
        raise FileNotFoundError(f"Google Voice source not found or unsupported: {path}")

    def _parse_export_groups(self, root: Path, *, source_kind: str) -> dict[str, Any]:
        groups = _group_export_files(root)
        events = [_build_export_event(root, paths, source_kind=source_kind) for paths in groups if paths]
        return {
            "status": "success",
            "source": str(root),
            "source_kind": source_kind,
            "event_count": len(events),
            "events": events,
        }

    def stage_gcs_export(
        self,
        source: str | os.PathLike[str],
        *,
        staging_dir: str | os.PathLike[str],
    ) -> dict[str, Any]:
        stage_root = Path(staging_dir).expanduser().resolve()
        stage_root.parent.mkdir(parents=True, exist_ok=True)

        if _is_gs_uri(source):
            source_uri = str(source)
            if stage_root.exists():
                shutil.rmtree(stage_root)
            stage_root.mkdir(parents=True, exist_ok=True)
            bucket_name, prefix = _parse_gs_uri(source_uri)
            try:
                from google.cloud import storage  # type: ignore

                client = storage.Client()
                blobs = list(client.list_blobs(bucket_name, prefix=prefix or None))
                for blob in blobs:
                    if not blob.name or blob.name.endswith("/"):
                        continue
                    relative_name = blob.name[len(prefix):].lstrip("/") if prefix else blob.name
                    destination = stage_root / relative_name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    blob.download_to_filename(str(destination))
                method = "google-cloud-storage"
            except Exception:
                if shutil.which("gcloud"):
                    subprocess.run(
                        ["gcloud", "storage", "cp", "--recursive", source_uri, str(stage_root)],
                        check=True,
                    )
                    method = "gcloud"
                elif shutil.which("gsutil"):
                    subprocess.run(
                        ["gsutil", "-m", "cp", "-r", source_uri, str(stage_root)],
                        check=True,
                    )
                    method = "gsutil"
                else:
                    raise RuntimeError(
                        "Unable to stage Google Voice data from GCS. Install google-cloud-storage, "
                        "or ensure gcloud/gsutil is available."
                    )
            return {
                "status": "success",
                "source": source_uri,
                "staging_dir": str(stage_root),
                "method": method,
            }

        local_source = Path(source).expanduser().resolve()
        staged_path = _copy_local_source_to_stage(local_source, stage_root)
        return {
            "status": "success",
            "source": str(local_source),
            "staging_dir": str(stage_root),
            "method": "local-copy",
            "staged_path": str(staged_path),
        }

    def parse_takeout(self, source: str | os.PathLike[str]) -> dict[str, Any]:
        root = self._materialize_root(source)
        html_paths = _candidate_html_paths(root)
        events: list[dict[str, Any]] = []

        for html_path in html_paths:
            try:
                html_text = html_path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                logger.warning("Failed to read Google Voice HTML %s: %s", html_path, exc)
                continue

            title = _extract_title(html_text, html_path)
            text_content = _extract_plain_text(html_text)
            sidecar_paths = [
                candidate
                for candidate in sorted(html_path.parent.iterdir())
                if candidate.is_file()
                and candidate != html_path
                and candidate.suffix.lower() in _SIDECAR_SUFFIXES
            ]
            sidecar_payloads = {
                sidecar.name: payload
                for sidecar in sidecar_paths
                if (payload := _load_sidecar_payload(sidecar)) is not None
            }
            timestamp = _extract_timestamp(
                title,
                text_content,
                *(json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload for payload in sidecar_payloads.values()),
            )
            phone_numbers = _extract_phone_numbers(
                title,
                text_content,
                *(str(payload) for payload in sidecar_payloads.values()),
            )
            event_type = _guess_event_type(html_path, title, text_content)
            event_hash = hashlib.sha256(str(html_path.relative_to(root)).encode("utf-8")).hexdigest()[:16]
            event = GoogleVoiceEvent(
                event_id=f"gv:{event_hash}",
                event_type=event_type,
                title=title,
                timestamp=timestamp,
                text_content=text_content,
                phone_numbers=phone_numbers,
                source_html=str(html_path),
                sidecar_paths=[str(path) for path in sidecar_paths],
                sidecar_payloads=sidecar_payloads,
                metadata={
                    "source_kind": "takeout",
                    "relative_html_path": str(html_path.relative_to(root)),
                    "html_sha256": _sha256_path(html_path),
                    "sidecar_count": len(sidecar_paths),
                },
            )
            payload = event.as_dict()
            payload["source_kind"] = "takeout"
            events.append(payload)

        return {
            "status": "success",
            "source": str(Path(source).expanduser()),
            "source_kind": "takeout",
            "event_count": len(events),
            "events": events,
        }

    def parse_vault_export(self, source: str | os.PathLike[str]) -> dict[str, Any]:
        root = self._materialize_root(source)
        return self._parse_export_groups(root, source_kind="vault_export")

    def parse_data_export(
        self,
        source: str | os.PathLike[str],
        *,
        staging_dir: str | os.PathLike[str] | None = None,
    ) -> dict[str, Any]:
        if _is_gs_uri(source):
            if staging_dir is None:
                raise ValueError("parse_data_export(gs://...) requires staging_dir")
            staged = self.stage_gcs_export(source, staging_dir=staging_dir)
            root = self._materialize_root(staged["staging_dir"])
            result = self._parse_export_groups(root, source_kind="data_export")
            result["staging_dir"] = staged["staging_dir"]
            result["staged_via"] = staged["method"]
            result["source"] = str(source)
            return result

        root = self._materialize_root(source)
        if _candidate_html_paths(root):
            parsed = self.parse_takeout(root)
            parsed["source_kind"] = "data_export"
            for event in parsed.get("events", []):
                event["source_kind"] = "data_export"
            return parsed
        return self._parse_export_groups(root, source_kind="data_export")

    def export_bundles(
        self,
        source: str | os.PathLike[str],
        *,
        output_dir: str | os.PathLike[str],
    ) -> dict[str, Any]:
        parsed = self.parse_takeout(source)
        return materialize_google_voice_events(
            list(parsed.get("events") or []),
            output_dir=output_dir,
            source=str(parsed.get("source") or ""),
            source_kind="takeout",
        )

    def export_vault_bundles(
        self,
        source: str | os.PathLike[str],
        *,
        output_dir: str | os.PathLike[str],
    ) -> dict[str, Any]:
        parsed = self.parse_vault_export(source)
        return materialize_google_voice_events(
            list(parsed.get("events") or []),
            output_dir=output_dir,
            source=str(parsed.get("source") or ""),
            source_kind="vault_export",
        )

    def export_data_export_bundles(
        self,
        source: str | os.PathLike[str],
        *,
        output_dir: str | os.PathLike[str],
        staging_dir: str | os.PathLike[str] | None = None,
    ) -> dict[str, Any]:
        parsed = self.parse_data_export(source, staging_dir=staging_dir)
        manifest = materialize_google_voice_events(
            list(parsed.get("events") or []),
            output_dir=output_dir,
            source=str(parsed.get("source") or ""),
            source_kind="data_export",
        )
        if parsed.get("staging_dir"):
            manifest["staging_dir"] = parsed["staging_dir"]
        if parsed.get("staged_via"):
            manifest["staged_via"] = parsed["staged_via"]
        return manifest

    def watch_and_materialize(
        self,
        watch_dir: str | os.PathLike[str],
        *,
        output_dir: str | os.PathLike[str],
        source_kind: str = "takeout",
        poll_interval: float = 5.0,
        once: bool = False,
        max_events: int | None = None,
        state_path: str | os.PathLike[str] | None = None,
        staging_dir: str | os.PathLike[str] | None = None,
    ) -> dict[str, Any]:
        watch_root = Path(watch_dir).expanduser().resolve()
        output_root = Path(output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        state_file = (
            Path(state_path).expanduser().resolve()
            if state_path
            else output_root / "google_voice_watch_state.json"
        )
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                state = {"seen": {}}
        else:
            state = {"seen": {}}
        seen = dict(state.get("seen") or {})
        processed: list[dict[str, Any]] = []

        def _candidate_key(path: Path) -> str:
            try:
                stat = path.stat()
                return f"{path.resolve()}::{stat.st_mtime_ns}::{stat.st_size}"
            except Exception:
                return str(path.resolve())

        while True:
            candidates: list[Path] = []
            for child in sorted(watch_root.iterdir()):
                if child.name.startswith("."):
                    continue
                if child.is_file() and child.suffix.lower() == ".zip":
                    candidates.append(child)
                elif child.is_dir():
                    if (child / "Takeout" / "Voice").exists() or (child / "Voice").exists() or _looks_like_voice_path(child):
                        candidates.append(child)

            for candidate in candidates:
                key = _candidate_key(candidate)
                if key in seen:
                    continue
                bundle_root = output_root / _slugify(candidate.stem)
                if source_kind == "vault_export":
                    manifest = self.export_vault_bundles(candidate, output_dir=bundle_root)
                elif source_kind == "data_export":
                    manifest = self.export_data_export_bundles(
                        candidate,
                        output_dir=bundle_root,
                        staging_dir=staging_dir,
                    )
                else:
                    manifest = self.export_bundles(candidate, output_dir=bundle_root)
                processed.append(
                    {
                        "source_path": str(candidate.resolve()),
                        "manifest_path": manifest.get("manifest_path"),
                        "event_count": manifest.get("event_count", 0),
                        "source_kind": source_kind,
                    }
                )
                seen[key] = {
                    "source_path": str(candidate.resolve()),
                    "manifest_path": manifest.get("manifest_path"),
                    "processed_at": datetime.now(UTC).isoformat(),
                }
                if max_events is not None and len(processed) >= max_events:
                    break

            state_file.write_text(json.dumps({"seen": seen}, indent=2, ensure_ascii=False), encoding="utf-8")
            if once or (max_events is not None and len(processed) >= max_events):
                break
            time.sleep(max(0.1, float(poll_interval)))

        return {
            "status": "success",
            "watch_dir": str(watch_root),
            "output_dir": str(output_root),
            "state_path": str(state_file),
            "processed_count": len(processed),
            "processed": processed,
            "source_kind": source_kind,
        }


def create_google_voice_processor() -> GoogleVoiceProcessor:
    return GoogleVoiceProcessor()
