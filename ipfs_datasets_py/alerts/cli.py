"""Alerts CLI.

Minimal CLI surface for the `ipfs_datasets_py.alerts` feature.

Supports working with alert rules without requiring Discord connectivity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _print(data: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)


def _load_rules(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    suffix = path.suffix.lower()
    if suffix == '.json':
        data = json.loads(path.read_text(encoding='utf-8'))
    else:
        try:
            import yaml  # type: ignore
        except Exception as e:
            raise RuntimeError('PyYAML is required to load YAML rule files') from e
        data = yaml.safe_load(path.read_text(encoding='utf-8'))

    if isinstance(data, dict) and 'rules' in data and isinstance(data['rules'], list):
        return list(data['rules'])
    if isinstance(data, list):
        return list(data)
    return []


def _load_event(event_json: Optional[str], event_file: Optional[str]) -> Dict[str, Any]:
    if event_json:
        return json.loads(event_json)
    if event_file:
        p = Path(event_file)
        return json.loads(p.read_text(encoding='utf-8'))
    raise ValueError('Provide --event-json or --event-file')


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='ipfs-datasets alerts',
        description='Alert rules (load/list/evaluate)'
    )
    parser.add_argument('--json', action='store_true', help='Output JSON')
    parser.add_argument(
        '--rules-file',
        default=None,
        help='Path to alert rules file (YAML or JSON). Defaults to config/alert_rules.yml if present.'
    )

    sub = parser.add_subparsers(dest='command', required=True)

    p_list = sub.add_parser('list', help='List configured rules')
    p_list.add_argument('--enabled-only', action='store_true')

    p_eval = sub.add_parser('evaluate', help='Evaluate an event against rules')
    p_eval.add_argument('--event-json', default=None, help='Event JSON string')
    p_eval.add_argument('--event-file', default=None, help='Path to JSON file with event data')
    p_eval.add_argument('--rule-ids', nargs='*', default=None, help='Optional rule IDs to evaluate')

    return parser


def _default_rules_path() -> Optional[Path]:
    # submodule root/.../config/alert_rules.yml
    cfg = Path(__file__).resolve().parents[2] / 'config' / 'alert_rules.yml'
    if cfg.exists():
        return cfg
    return None


def main(argv: Optional[List[str]] = None) -> int:
    ns = create_parser().parse_args(argv)

    try:
        rules_path = Path(ns.rules_file) if ns.rules_file else _default_rules_path()
        rules = _load_rules(rules_path) if rules_path else []

        cmd = ns.command
        if cmd == 'list':
            out_rules = [r for r in rules if (not ns.enabled_only or r.get('enabled', True))]
            _print({'status': 'success', 'count': len(out_rules), 'rules': out_rules}, json_output=bool(ns.json))
            return 0

        if cmd == 'evaluate':
            from ipfs_datasets_py.alerts.rule_engine import RuleEngine

            event = _load_event(ns.event_json, ns.event_file)
            engine = RuleEngine()

            triggered: List[Dict[str, Any]] = []
            for rule in rules:
                rid = rule.get('rule_id')
                if ns.rule_ids and rid not in ns.rule_ids:
                    continue
                if not rule.get('enabled', True):
                    continue
                cond = rule.get('condition')
                if not isinstance(cond, dict):
                    continue

                ok = engine.evaluate(cond, event)
                if ok:
                    msg_tmpl = str(rule.get('message_template', ''))
                    try:
                        msg = msg_tmpl.format(**event)
                    except Exception:
                        msg = msg_tmpl
                    triggered.append({'rule_id': rid, 'name': rule.get('name'), 'message': msg, 'severity': rule.get('severity', 'info')})

            _print({'status': 'success', 'triggered_rules': len(triggered), 'results': triggered}, json_output=bool(ns.json))
            return 0

        _print({'status': 'error', 'error': f'unknown command: {cmd}'}, json_output=True)
        return 2

    except KeyboardInterrupt:
        return 1
    except Exception as e:
        _print({'status': 'error', 'error': str(e)}, json_output=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
