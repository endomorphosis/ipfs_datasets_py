"""Xaman e2e and runtime trace ingestor.

The Xaman source models are intentionally source-bound.  This module converts
available e2e declarations and optional runtime event files into monitor facts
while keeping deployed runtime equivalence fail-closed when real-device traces
are absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from ..ir.schema import make_evidence_ref

SCHEMA_VERSION = 'xaman-runtime-trace-report/v1'
TASK_ID = 'PORTAL-CXTP-074'
CORPUS = 'xaman-app'
DEFAULT_CORPUS_DIR = Path('security_ir_artifacts/corpora/xaman-app')
DEFAULT_MANIFEST_PATH = DEFAULT_CORPUS_DIR / 'source-manifest.json'
DEFAULT_COVERAGE_PATH = DEFAULT_CORPUS_DIR / 'source-coverage.json'
DEFAULT_CLAIMS_PATH = DEFAULT_CORPUS_DIR / 'security-claims.json'
DEFAULT_REPORT_PATH = DEFAULT_CORPUS_DIR / 'runtime-trace-report.json'

DEPENDENCY_ARTIFACTS = (
    DEFAULT_CORPUS_DIR / 'wallet-auth-facts.json',
    DEFAULT_CORPUS_DIR / 'payload-lifecycle-facts.json',
    DEFAULT_CORPUS_DIR / 'xrpl-transaction-facts.json',
    DEFAULT_CORPUS_DIR / 'security-claims.json',
)

MONITOR_CATEGORIES = (
    'payload_intake',
    'review',
    'auth',
    'signing',
    'rejection',
    'expiration',
    'network_binding',
    'broadcast',
)

CANONICAL_MONITOR_EVENTS = {
    'payload_intake': 'xaman_payload_intake_seen',
    'review': 'xaman_review_displayed',
    'auth': 'xaman_auth_gate_satisfied',
    'signing': 'xaman_transaction_signed',
    'rejection': 'xaman_payload_rejected',
    'expiration': 'xaman_expired_or_resolved_payload_blocked',
    'network_binding': 'xaman_network_binding_applied',
    'broadcast': 'xaman_ledger_broadcast_attempted',
}

RUNTIME_ALIASES = {
    'payload_intake': {
        'payload_intake',
        'payload_fetched',
        'payload_loaded',
        'payload_reference_opened',
        'qr_scan',
        'qr_payload_detected',
        'deep_link_opened',
        'push_payload_opened',
        'event_list_payload_opened',
        'xaman_payload_intake_seen',
    },
    'review': {
        'review',
        'review_displayed',
        'review_preflight',
        'payload_reviewed',
        'transaction_review_opened',
        'xaman_review_displayed',
    },
    'auth': {
        'auth',
        'auth_prompt_shown',
        'authentication_succeeded',
        'passcode_accepted',
        'biometric_accepted',
        'vault_unlocked',
        'xaman_auth_gate_satisfied',
    },
    'signing': {
        'signing',
        'signing_request',
        'payload_approved',
        'transaction_signed',
        'tx_signed',
        'signed_payload_patched',
        'xaman_transaction_signed',
    },
    'rejection': {
        'rejection',
        'payload_rejected',
        'payload_declined',
        'rejection_patched',
        'transaction_cancelled',
        'xaman_payload_rejected',
    },
    'expiration': {
        'expiration',
        'payload_expired',
        'payload_resolved_blocked',
        'expired_payload_blocked',
        'resolved_payload_blocked',
        'xaman_expired_or_resolved_payload_blocked',
    },
    'network_binding': {
        'network_binding',
        'network_bound',
        'force_network_applied',
        'network_id_populated',
        'node_selected',
        'xaman_network_binding_applied',
    },
    'broadcast': {
        'broadcast',
        'broadcast_requested',
        'ledger_submit',
        'tx_broadcast',
        'dispatch_result_patched',
        'xaman_ledger_broadcast_attempted',
    },
}

E2E_KEYWORDS = {
    'payload_intake': (
        'payload',
        'qr',
        'deeplink',
        'deep link',
        'xumm',
        'xaman',
        'request',
        'link',
        'scan',
    ),
    'review': ('review', 'transaction detail', 'details', 'confirm', 'shown', 'display'),
    'auth': ('auth', 'passcode', 'biometric', 'unlock', 'vault', 'login', 'pin'),
    'signing': ('sign', 'approve', 'accept', 'swipe', 'signed'),
    'rejection': ('reject', 'decline', 'cancel'),
    'expiration': ('expire', 'expired', 'resolved', 'stale'),
    'network_binding': ('network', 'mainnet', 'testnet', 'devnet', 'node', 'ledger'),
    'broadcast': ('submit', 'broadcast', 'txid', 'validated', 'ledger result'),
}

FEATURE_EVENT_RE = re.compile(r'^\s*(Feature|Scenario(?: Outline)?|Given|When|Then|And|But):?\s*(.+?)\s*$')
SLUG_RE = re.compile(r'[^a-z0-9]+')


@dataclass(frozen=True)
class RuntimeEvent:
    """Canonical runtime or e2e event used by monitor facts."""

    event: str
    category: str
    source_kind: str
    source_path: str
    trace_id: str
    index: int
    timestamp: str | int | float | None = None
    payload_uuid: str | None = None
    account: str | None = None
    network: str | None = None
    txid: str | None = None
    line_start: int | None = None
    raw_event: str | None = None
    device_class: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'event': self.event,
            'category': self.category,
            'source_kind': self.source_kind,
            'source_path': self.source_path,
            'trace_id': self.trace_id,
            'index': self.index,
        }
        for key in ('timestamp', 'payload_uuid', 'account', 'network', 'txid', 'line_start', 'raw_event', 'device_class'):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload


class XamanRuntimeTraceIngestor:
    """Convert Xaman e2e and runtime events into monitor facts."""

    def build_report(
        self,
        *,
        corpus_root: str | Path | None = None,
        manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
        coverage_path: str | Path = DEFAULT_COVERAGE_PATH,
        claims_path: str | Path = DEFAULT_CLAIMS_PATH,
        runtime_trace_paths: Iterable[str | Path] | None = None,
        out_path: str | Path | None = None,
    ) -> dict[str, Any]:
        manifest_file = Path(manifest_path)
        coverage_file = Path(coverage_path)
        claims_file = Path(claims_path)
        manifest = self._read_json(manifest_file)
        coverage = self._read_json(coverage_file) if coverage_file.exists() else {}
        claims = self._read_json(claims_file) if claims_file.exists() else {}
        root = Path(corpus_root) if corpus_root is not None else None

        e2e_traces = self.e2e_events_from_manifest(manifest=manifest, corpus_root=root)
        runtime_traces = self.runtime_traces_from_paths(runtime_trace_paths or ())
        all_traces = e2e_traces + runtime_traces
        monitor_facts = self.monitor_facts_from_traces(all_traces, manifest=manifest)
        dependency_facts = self.dependency_monitor_facts(manifest=manifest)
        monitor_facts = self._dedupe_monitor_facts(monitor_facts + dependency_facts)

        real_device_traces = [
            trace
            for trace in runtime_traces
            if trace.get('device_class') == 'real_device'
            or any(event.get('device_class') == 'real_device' for event in trace.get('events', []))
        ]
        gap = self.runtime_equivalence_gap(manifest, manifest_path=manifest_file)
        blocking = {
            'status': 'BLOCKING' if not real_device_traces else 'EVIDENCED',
            'absent_real_device_traces': not bool(real_device_traces),
            'blocking_gap_ids': [gap['id']] if not real_device_traces else [],
            'required_evidence': gap['required_evidence_to_model'] if not real_device_traces else [],
        }

        report = {
            'schema_version': SCHEMA_VERSION,
            'task_id': TASK_ID,
            'corpus': manifest.get('corpus', CORPUS),
            'source': self._source_metadata(
                manifest,
                coverage,
                manifest_path=manifest_file,
                coverage_path=coverage_file,
            ),
            'review': {
                'review_status': 'reviewed',
                'reviewed_at': '2026-07-08',
                'review_scope': list(MONITOR_CATEGORIES) + ['runtime_equivalence'],
                'model_boundary': (
                    'E2e feature declarations and optional runtime event files are normalized '
                    'into monitor facts. Source-backed monitor facts are not accepted as '
                    'real-device runtime equivalence without release-window device traces.'
                ),
            },
            'dependency_artifacts': self._dependency_artifacts(claims),
            'trace_inputs': {
                'e2e_feature_count': len(e2e_traces),
                'runtime_trace_count': len(runtime_traces),
                'real_device_trace_count': len(real_device_traces),
                'source_paths': [trace['source_path'] for trace in e2e_traces],
                'runtime_paths': [trace['source_path'] for trace in runtime_traces],
            },
            'runtime_traces': all_traces,
            'monitor_facts': monitor_facts,
            'monitor_coverage': self._monitor_coverage(monitor_facts),
            'blocking_runtime_equivalence': blocking,
            'not_modeled_gaps': [gap],
            'claim_bindings': self._claim_bindings(claims),
        }
        if out_path is not None:
            self.write_report(report, Path(out_path))
        return report

    def e2e_events_from_manifest(
        self,
        *,
        manifest: Mapping[str, Any],
        corpus_root: Path | None = None,
    ) -> list[dict[str, Any]]:
        traces: list[dict[str, Any]] = []
        for entry in manifest.get('files', []):
            if not isinstance(entry, Mapping):
                continue
            path = str(entry.get('path', ''))
            if not path.startswith('e2e/') or PurePosixPath(path).suffix != '.feature':
                continue
            events = self._events_from_feature_path(path, entry)
            if corpus_root is not None:
                source_path = corpus_root / path
                if source_path.is_file():
                    parsed = self.e2e_events_from_feature_text(
                        source_path.read_text(encoding='utf-8'),
                        source_path=path,
                    )
                    if parsed:
                        events = parsed
            trace_id = f'xaman-e2e:{self._slug(path)}'
            traces.append(
                {
                    'id': trace_id,
                    'source_kind': 'e2e_feature',
                    'source_path': path,
                    'device_class': 'simulator_or_declared_e2e',
                    'conformance_status': 'source_declared_not_runtime_equivalent',
                    'manifest_sha256': entry.get('sha256'),
                    'events': [
                        RuntimeEvent(
                            event=event['event'],
                            category=event['category'],
                            source_kind='e2e_feature',
                            source_path=path,
                            trace_id=trace_id,
                            index=index,
                            line_start=event.get('line_start'),
                            raw_event=event.get('raw_event'),
                            device_class='simulator_or_declared_e2e',
                        ).as_dict()
                        for index, event in enumerate(events)
                    ],
                    'evidence': [
                        self._source_evidence(
                            path=path,
                            sha256=str(entry['sha256']) if entry.get('sha256') else None,
                            notes='Pinned Xaman e2e feature manifest entry converted into monitor-event classes.',
                        )
                    ],
                }
            )
        return traces

    def e2e_events_from_feature_text(self, source: str, *, source_path: str = '<memory>') -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            match = FEATURE_EVENT_RE.match(stripped)
            if not match:
                continue
            text = match.group(2).strip()
            categories = self._categories_for_text(text)
            for category in categories:
                events.append(
                    {
                        'event': CANONICAL_MONITOR_EVENTS[category],
                        'category': category,
                        'line_start': line_number,
                        'raw_event': text,
                    }
                )
        if not events:
            return self._events_from_feature_path(source_path, {})
        return self._dedupe_event_templates(events)

    def runtime_traces_from_paths(self, paths: Iterable[str | Path]) -> list[dict[str, Any]]:
        traces: list[dict[str, Any]] = []
        for raw_path in paths:
            path = Path(raw_path)
            traces.extend(self.runtime_traces_from_payload(self._load_trace_payload(path), source_path=path.as_posix()))
        return traces

    def runtime_traces_from_payload(self, payload: Any, *, source_path: str = '<memory>') -> list[dict[str, Any]]:
        trace_payloads = self._coerce_trace_payloads(payload)
        traces: list[dict[str, Any]] = []
        for trace_index, trace_payload in enumerate(trace_payloads):
            trace_id = str(trace_payload.get('id') or f'xaman-runtime:{self._slug(source_path)}:{trace_index}')
            raw_events = trace_payload.get('events', [])
            device_class = str(
                trace_payload.get('device_class')
                or trace_payload.get('device')
                or self._device_class_from_events(raw_events if isinstance(raw_events, list) else [])
                or 'unknown'
            )
            events = self.normalize_runtime_events(
                raw_events if isinstance(raw_events, list) else [],
                source_path=source_path,
                trace_id=trace_id,
                device_class=device_class,
            )
            traces.append(
                {
                    'id': trace_id,
                    'source_kind': str(trace_payload.get('source_kind') or 'runtime_trace'),
                    'source_path': source_path,
                    'device_class': device_class,
                    'conformance_status': (
                        'runtime_monitor_facts_extracted'
                        if events
                        else 'no_security_relevant_runtime_events'
                    ),
                    'events': [event.as_dict() for event in events],
                    'evidence': [
                        make_evidence_ref(
                            kind='test_fixture',
                            path=source_path,
                            line_start=1,
                            line_end=1,
                            review_status='machine_extracted',
                            notes='Runtime trace input normalized into Xaman monitor events.',
                        )
                    ],
                }
            )
        return traces

    def normalize_runtime_events(
        self,
        events: Iterable[Mapping[str, Any]],
        *,
        source_path: str,
        trace_id: str,
        device_class: str = 'unknown',
    ) -> list[RuntimeEvent]:
        normalized: list[RuntimeEvent] = []
        for index, event in enumerate(events):
            if not isinstance(event, Mapping):
                continue
            name = str(event.get('event') or event.get('type') or event.get('name') or '').strip()
            category = self._category_for_runtime_event(name, event)
            if category is None:
                continue
            normalized.append(
                RuntimeEvent(
                    event=CANONICAL_MONITOR_EVENTS[category],
                    category=category,
                    source_kind='runtime_trace',
                    source_path=source_path,
                    trace_id=trace_id,
                    index=index,
                    timestamp=event.get('timestamp') or event.get('time') or event.get('ts'),
                    payload_uuid=self._optional_str(event.get('payload_uuid') or event.get('payload_id') or event.get('uuid')),
                    account=self._optional_str(event.get('account') or event.get('account_id') or event.get('wallet_id')),
                    network=self._optional_str(event.get('network') or event.get('network_id') or event.get('node')),
                    txid=self._optional_str(event.get('txid') or event.get('tx_id') or event.get('hash')),
                    raw_event=name or None,
                    device_class=self._optional_str(event.get('device_class') or event.get('device')) or device_class,
                )
            )
        return normalized

    def monitor_facts_from_traces(
        self,
        traces: Iterable[Mapping[str, Any]],
        *,
        manifest: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        manifest_files = self._manifest_files(manifest)
        facts: list[dict[str, Any]] = []
        for trace in traces:
            source_path = str(trace.get('source_path', '<memory>'))
            events = [event for event in trace.get('events', []) if isinstance(event, Mapping)]
            for category in MONITOR_CATEGORIES:
                category_events = [event for event in events if event.get('category') == category]
                if not category_events:
                    continue
                source_kind = str(trace.get('source_kind') or 'runtime_trace')
                fact_id = f'xaman-runtime-trace:fact:{self._slug(source_kind)}-{self._slug(source_path)}-{category}'
                facts.append(
                    {
                        'id': fact_id,
                        'status': 'MONITOR_FACT',
                        'category': category,
                        'source_kind': source_kind,
                        'trace_id': trace.get('id'),
                        'monitor_event': CANONICAL_MONITOR_EVENTS[category],
                        'event_count': len(category_events),
                        'device_class': trace.get('device_class'),
                        'summary': self._monitor_summary(category, source_kind),
                        'normalized_fact': {
                            'category': category,
                            'monitor_event': CANONICAL_MONITOR_EVENTS[category],
                            'observed_event_names': sorted({str(event.get('event')) for event in category_events}),
                            'trace_source_path': source_path,
                            'real_device_required_for_runtime_equivalence': True,
                        },
                        'evidence': [
                            self._trace_evidence(
                                source_path=source_path,
                                source_kind=source_kind,
                                manifest_entry=manifest_files.get(source_path),
                            )
                        ],
                    }
                )
        return facts

    def dependency_monitor_facts(self, *, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
        manifest_files = self._manifest_files(manifest)
        facts: list[dict[str, Any]] = []
        for category, source in self._dependency_fact_templates():
            source_path = str(source['path'])
            fact_id = f'xaman-runtime-trace:fact:{category}-monitor-from-reviewed-source'
            facts.append(
                {
                    'id': fact_id,
                    'status': 'MONITOR_FACT',
                    'category': category,
                    'source_kind': 'reviewed_source_fact',
                    'trace_id': None,
                    'monitor_event': CANONICAL_MONITOR_EVENTS[category],
                    'event_count': 0,
                    'device_class': 'not_runtime_trace',
                    'summary': source['summary'],
                    'normalized_fact': {
                        'category': category,
                        'monitor_event': CANONICAL_MONITOR_EVENTS[category],
                        'source_fact_ids': source['source_fact_ids'],
                        'required_runtime_fields': source['required_runtime_fields'],
                        'real_device_required_for_runtime_equivalence': True,
                    },
                    'evidence': [
                        self._source_evidence(
                            path=source_path,
                            sha256=manifest_files.get(source_path, {}).get('sha256'),
                            line_start=int(source.get('line_start', 1)),
                            line_end=int(source.get('line_end', source.get('line_start', 1))),
                            notes='Reviewed source fact projected into the runtime monitor vocabulary.',
                        )
                    ],
                }
            )
        return facts

    def runtime_equivalence_gap(self, manifest: Mapping[str, Any], *, manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
        source = manifest.get('source', {}) if isinstance(manifest.get('source'), Mapping) else {}
        aggregate_sha = (
            manifest.get('reproducibility', {}).get('aggregate_sha256')
            if isinstance(manifest.get('reproducibility'), Mapping)
            else None
        )
        return {
            'id': 'xaman-runtime-trace:gap:real-device-runtime-traces-absent',
            'status': 'NOT_MODELED',
            'category': 'runtime_equivalence',
            'blocking': True,
            'summary': (
                'No real-device runtime traces are present in the checked-in Xaman corpus, so e2e declarations '
                'and reviewed source facts cannot discharge deployed runtime equivalence.'
            ),
            'required_evidence_to_model': [
                'Release-window iOS and Android real-device traces covering payload intake, review, auth, signing, rejection, expiration, network binding, and broadcast.',
                'Trace metadata binding app build identifier, commit, backend environment, node URI, device OS, and capture time.',
                'Binary provenance or reproducible-build evidence proving the traced app matches the reviewed source commit.',
            ],
            'evidence': [
                make_evidence_ref(
                    kind='source_manifest',
                    path=self._display_path(manifest_path),
                    line_start=1,
                    line_end=1,
                    sha256=str(aggregate_sha) if aggregate_sha else None,
                    review_status='reviewed',
                    notes=f'Pinned source manifest for {source.get("commit_sha", "unknown commit")} contains e2e declarations but no real-device trace artifacts.',
                )
            ],
        }

    @staticmethod
    def write_report(report: Mapping[str, Any], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding='utf-8'))

    def _load_trace_payload(self, path: Path) -> Any:
        text = path.read_text(encoding='utf-8')
        if path.suffix.lower() in {'.jsonl', '.ndjson'}:
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        return json.loads(text)

    @staticmethod
    def _coerce_trace_payloads(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, Mapping):
            if isinstance(payload.get('traces'), list):
                return [dict(trace) for trace in payload['traces'] if isinstance(trace, Mapping)]
            if isinstance(payload.get('events'), list):
                return [dict(payload)]
            return [{'events': [dict(payload)]}]
        if isinstance(payload, list):
            if all(isinstance(item, Mapping) and isinstance(item.get('events'), list) for item in payload):
                return [dict(item) for item in payload if isinstance(item, Mapping)]
            return [{'events': [dict(item) for item in payload if isinstance(item, Mapping)]}]
        return [{'events': []}]

    def _events_from_feature_path(self, path: str, entry: Mapping[str, Any]) -> list[dict[str, Any]]:
        name = PurePosixPath(path).stem.lower()
        categories: list[str]
        if 'auth' in name:
            categories = ['auth', 'signing']
        elif 'link' in name:
            categories = ['payload_intake', 'review', 'network_binding']
        elif 'account' in name or 'import' in name or 'upgrade' in name:
            categories = ['auth', 'signing']
        elif 'setup' in name:
            categories = ['network_binding']
        else:
            categories = self._categories_for_text(path)
        return [
            {
                'event': CANONICAL_MONITOR_EVENTS[category],
                'category': category,
                'line_start': 1,
                'raw_event': f'manifest-declared {path}',
            }
            for category in categories
        ]

    def _categories_for_text(self, text: str) -> list[str]:
        lowered = text.lower()
        categories = [
            category
            for category, keywords in E2E_KEYWORDS.items()
            if any(keyword in lowered for keyword in keywords)
        ]
        if not categories and 'e2e/' in lowered:
            categories = ['payload_intake']
        return [category for category in MONITOR_CATEGORIES if category in categories]

    def _category_for_runtime_event(self, name: str, event: Mapping[str, Any]) -> str | None:
        explicit = event.get('category') or event.get('monitor_category')
        if isinstance(explicit, str) and explicit in MONITOR_CATEGORIES:
            return explicit
        normalized_name = self._event_token(name)
        for category, aliases in RUNTIME_ALIASES.items():
            if normalized_name in {self._event_token(alias) for alias in aliases}:
                return category
        categories = self._categories_for_text(name)
        return categories[0] if categories else None

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _device_class_from_events(events: Iterable[Any]) -> str | None:
        for event in events:
            if not isinstance(event, Mapping):
                continue
            value = event.get('device_class') or event.get('device')
            if value is not None:
                return str(value)
        return None

    @staticmethod
    def _dedupe_event_templates(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, int | None, str | None]] = set()
        deduped: list[dict[str, Any]] = []
        for event in events:
            key = (str(event.get('category')), event.get('line_start'), event.get('raw_event'))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(event)
        return deduped

    @staticmethod
    def _manifest_files(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(entry['path']): dict(entry)
            for entry in manifest.get('files', [])
            if isinstance(entry, Mapping) and isinstance(entry.get('path'), str)
        }

    def _source_metadata(
        self,
        manifest: Mapping[str, Any],
        coverage: Mapping[str, Any],
        *,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
        coverage_path: Path = DEFAULT_COVERAGE_PATH,
    ) -> dict[str, Any]:
        source = manifest.get('source', {}) if isinstance(manifest.get('source'), Mapping) else {}
        reproducibility = (
            manifest.get('reproducibility', {}) if isinstance(manifest.get('reproducibility'), Mapping) else {}
        )
        return {
            'repo_url': source.get('repo_url') or source.get('repository_url'),
            'commit_sha': source.get('commit_sha') or source.get('commit'),
            'manifest_path': self._display_path(manifest_path),
            'manifest_schema_version': manifest.get('schema_version'),
            'manifest_aggregate_sha256': reproducibility.get('aggregate_sha256'),
            'coverage_path': self._display_path(coverage_path),
            'coverage_schema_version': coverage.get('schema_version'),
        }

    def _dependency_artifacts(self, claims: Mapping[str, Any]) -> list[dict[str, Any]]:
        dependencies = list(claims.get('dependencies', [])) if isinstance(claims.get('dependencies'), list) else []
        dependencies.append(
            {
                'task_id': 'PORTAL-CXTP-067',
                'artifact_path': DEFAULT_CLAIMS_PATH.as_posix(),
                'schema_version': claims.get('schema_version'),
            }
        )
        return dependencies

    @staticmethod
    def _dependency_fact_templates() -> list[tuple[str, dict[str, Any]]]:
        return [
            (
                'payload_intake',
                {
                    'path': 'src/services/LinkingService.ts',
                    'line_start': 513,
                    'line_end': 518,
                    'summary': 'Monitor payload intake from QR, deep-link, push, and event-list sources before review.',
                    'source_fact_ids': [
                        'xaman-payload-lifecycle:fact:qr-payload-reference-intake-fetches-and-routes-to-review',
                        'xaman-payload-lifecycle:fact:deep-link-payload-reference-intake-fetches-and-routes-to-review',
                        'xaman-payload-lifecycle:fact:event-list-loads-pending-payloads-and-opens-review',
                    ],
                    'required_runtime_fields': ['payload_uuid', 'origin', 'request_json_hash'],
                },
            ),
            (
                'review',
                {
                    'path': 'src/screens/Modal/ReviewTransaction/Steps/Review/ReviewStep.tsx',
                    'line_start': 1,
                    'line_end': 1,
                    'summary': 'Monitor review display after preflight and before approval or rejection.',
                    'source_fact_ids': [
                        'xaman-payload-lifecycle:fact:review-preflight-binds-forced-network-and-signer',
                        'xaman-payload-lifecycle:fact:review-ui-displays-app-source-account-transaction-and-accept-control',
                    ],
                    'required_runtime_fields': ['payload_uuid', 'account', 'transaction_type', 'accept_enabled'],
                },
            ),
            (
                'auth',
                {
                    'path': 'src/screens/Overlay/Authenticate/AuthenticateOverlay.tsx',
                    'line_start': 1,
                    'line_end': 1,
                    'summary': 'Monitor biometric or passcode authentication before vault-backed signing.',
                    'source_fact_ids': [
                        'xaman-wallet-auth:fact:authenticate-overlay-allows-passcode-or-enabled-biometrics',
                        'xaman-wallet-auth:fact:passcode-authentication-hashes-and-throttles',
                    ],
                    'required_runtime_fields': ['account', 'auth_method', 'auth_result'],
                },
            ),
            (
                'signing',
                {
                    'path': 'src/common/libs/ledger/mixin/Sign.mixin.ts',
                    'line_start': 318,
                    'line_end': 349,
                    'summary': 'Monitor that signing occurs only after review approval, validation, and vault access.',
                    'source_fact_ids': [
                        'xaman-wallet-auth:fact:software-private-key-signing-requires-vault-open-with-encryption-key',
                        'xaman-payload-lifecycle:fact:approval-revalidates-non-generated-payload-before-signing',
                    ],
                    'required_runtime_fields': ['payload_uuid', 'account', 'txid', 'sign_method'],
                },
            ),
            (
                'rejection',
                {
                    'path': 'src/common/libs/payload/object.ts',
                    'line_start': 1,
                    'line_end': 1,
                    'summary': 'Monitor user and app rejection as a terminal path before signing.',
                    'source_fact_ids': ['xaman-payload-lifecycle:fact:rejection-patches-backend-for-user-or-app-decline'],
                    'required_runtime_fields': ['payload_uuid', 'reject_initiator', 'origin'],
                },
            ),
            (
                'expiration',
                {
                    'path': 'src/common/libs/payload/object.ts',
                    'line_start': 173,
                    'line_end': 198,
                    'summary': 'Monitor already-resolved or expired payloads as blocked before review and signing.',
                    'source_fact_ids': ['xaman-payload-lifecycle:fact:remote-fetch-blocks-resolved-or-expired-payloads'],
                    'required_runtime_fields': ['payload_uuid', 'resolved_at', 'expired'],
                },
            ),
            (
                'network_binding',
                {
                    'path': 'src/common/libs/ledger/mixin/Sign.mixin.ts',
                    'line_start': 1,
                    'line_end': 1,
                    'summary': 'Monitor forced network, selected node, and NetworkID binding before signing and broadcast.',
                    'source_fact_ids': [
                        'xaman-payload-lifecycle:fact:network-binding-applies-to-templates-review-and-signing',
                        'xaman-xrpl-transaction:fact:network-id-is-auto-populated-for-non-legacy-networks-above-1024',
                    ],
                    'required_runtime_fields': ['payload_uuid', 'network', 'node_uri', 'network_id'],
                },
            ),
            (
                'broadcast',
                {
                    'path': 'src/common/libs/ledger/types/methods/submit.ts',
                    'line_start': 41,
                    'line_end': 89,
                    'summary': 'Monitor optional ledger broadcast after signed payload patch and submit guards.',
                    'source_fact_ids': [
                        'xaman-payload-lifecycle:fact:broadcast-only-when-submit-true-non-pseudo-and-not-multisign',
                        'xaman-payload-lifecycle:fact:ledger-submit-has-local-single-submit-and-abort-guards',
                    ],
                    'required_runtime_fields': ['payload_uuid', 'txid', 'node_uri', 'engine_result'],
                },
            ),
        ]

    @staticmethod
    def _monitor_summary(category: str, source_kind: str) -> str:
        return f'Observed {category} monitor event from {source_kind} input.'

    def _trace_evidence(
        self,
        *,
        source_path: str,
        source_kind: str,
        manifest_entry: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if source_kind == 'e2e_feature':
            return self._source_evidence(
                path=source_path,
                sha256=str(manifest_entry['sha256']) if manifest_entry and manifest_entry.get('sha256') else None,
                notes='E2e feature converted to monitor fact; simulator/e2e coverage is not real-device equivalence.',
            )
        return make_evidence_ref(
            kind='test_fixture',
            path=source_path,
            line_start=1,
            line_end=1,
            review_status='machine_extracted',
            notes='Runtime trace event converted to monitor fact.',
        )

    @staticmethod
    def _source_evidence(
        *,
        path: str,
        sha256: str | None,
        line_start: int = 1,
        line_end: int = 1,
        notes: str,
    ) -> dict[str, Any]:
        return make_evidence_ref(
            kind='source_code',
            path=path,
            line_start=line_start,
            line_end=line_end,
            sha256=sha256,
            review_status='reviewed',
            notes=notes,
        )

    @staticmethod
    def _dedupe_monitor_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for fact in facts:
            deduped[str(fact['id'])] = fact
        return [deduped[key] for key in sorted(deduped)]

    @staticmethod
    def _monitor_coverage(facts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        categories = sorted({str(fact.get('category')) for fact in facts if fact.get('category')})
        return {
            'required_categories': list(MONITOR_CATEGORIES),
            'covered_categories': categories,
            'missing_categories': [category for category in MONITOR_CATEGORIES if category not in categories],
            'complete_for_source_and_e2e_inputs': all(category in categories for category in MONITOR_CATEGORIES),
        }

    @staticmethod
    def _claim_bindings(claims: Mapping[str, Any]) -> list[dict[str, Any]]:
        bindings: list[dict[str, Any]] = []
        for claim in claims.get('security_claims', []):
            if not isinstance(claim, Mapping):
                continue
            claim_id = str(claim.get('id', ''))
            category = str(claim.get('category', ''))
            required_categories = {
                'payload_integrity': ['payload_intake', 'review', 'signing'],
                'replay_prevention': ['expiration', 'signing', 'broadcast'],
                'network_binding': ['network_binding', 'signing', 'broadcast'],
                'authentication': ['auth', 'signing'],
                'custody': ['auth', 'signing'],
                'transaction_semantics': ['review', 'signing', 'network_binding'],
                'backend_trust': ['rejection', 'broadcast'],
                'runtime_equivalence': list(MONITOR_CATEGORIES),
            }.get(category, [])
            if required_categories:
                bindings.append(
                    {
                        'claim_id': claim_id,
                        'claim_category': category,
                        'monitor_categories': required_categories,
                        'runtime_equivalence_required': category == 'runtime_equivalence',
                    }
                )
        return bindings

    @staticmethod
    def _slug(value: str) -> str:
        slug = SLUG_RE.sub('-', value.lower()).strip('-')
        digest = hashlib.sha256(value.encode('utf-8')).hexdigest()[:8]
        if len(slug) > 70:
            slug = slug[:70].rstrip('-')
        return f'{slug or "item"}-{digest}'

    @staticmethod
    def _event_token(value: str) -> str:
        return SLUG_RE.sub('_', value.lower()).strip('_')

    @staticmethod
    def _display_path(path: Path) -> str:
        try:
            return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            return path.as_posix()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Build the Xaman runtime trace monitor report.')
    parser.add_argument('--corpus-root', help='Optional Xaman checkout root containing feature text.')
    parser.add_argument('--manifest', default=str(DEFAULT_MANIFEST_PATH), help='Pinned Xaman source manifest path.')
    parser.add_argument('--coverage', default=str(DEFAULT_COVERAGE_PATH), help='Xaman source coverage artifact path.')
    parser.add_argument('--claims', default=str(DEFAULT_CLAIMS_PATH), help='Xaman security claims artifact path.')
    parser.add_argument('--runtime-trace', action='append', default=[], help='JSON or NDJSON runtime trace input.')
    parser.add_argument('--out', default=str(DEFAULT_REPORT_PATH), help='Runtime trace report output path.')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    XamanRuntimeTraceIngestor().build_report(
        corpus_root=args.corpus_root,
        manifest_path=args.manifest,
        coverage_path=args.coverage,
        claims_path=args.claims,
        runtime_trace_paths=args.runtime_trace,
        out_path=args.out,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
