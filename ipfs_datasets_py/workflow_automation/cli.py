"""Workflow automation CLI.

Minimal CLI surface for `ipfs_datasets_py.workflow_automation`.

Note: the default service is in-memory and process-local; commands like `create`
+`status` across separate invocations won't share state unless you implement a
persistent backend.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import anyio


def _print(data: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)


def _load_json(value: Optional[str], file_path: Optional[str]) -> Dict[str, Any]:
    if value:
        return json.loads(value)
    if file_path:
        p = Path(file_path)
        return json.loads(p.read_text(encoding='utf-8'))
    return {}


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='ipfs-datasets workflow-automation',
        description='In-memory workflow automation helpers',
    )
    parser.add_argument('--json', action='store_true', help='Output JSON')

    sub = parser.add_subparsers(dest='command', required=True)

    p_demo = sub.add_parser('demo', help='Create+execute a small demo workflow')

    p_run = sub.add_parser('run', help='Create+execute a workflow definition')
    p_run.add_argument('--definition-json', default=None, help='Workflow definition as JSON string')
    p_run.add_argument('--definition-file', default=None, help='Path to workflow definition JSON file')
    p_run.add_argument('--execution-params-json', default=None, help='Execution params JSON string')
    p_run.add_argument('--execution-params-file', default=None, help='Path to execution params JSON file')

    p_status = sub.add_parser('status', help='Get status for an existing workflow id (same-process only)')
    p_status.add_argument('workflow_id')

    p_list = sub.add_parser('list', help='List workflows (same-process only)')
    p_list.add_argument('--status', default=None, help='Filter by status (pending/running/completed/...)')

    return parser


async def _run_async(ns: argparse.Namespace) -> Dict[str, Any]:
    from ipfs_datasets_py.workflow_automation import get_default_workflow_service

    svc = get_default_workflow_service()

    if ns.command == 'demo':
        definition = {
            'name': 'Demo Workflow',
            'description': 'Example workflow created from CLI',
            'steps': [
                {
                    'id': 'step-1',
                    'name': 'Demo Step',
                    'type': 'noop',
                    'parameters': {'message': 'hello'},
                    'dependencies': [],
                }
            ],
        }
        created = await svc.create_workflow(definition)
        executed = await svc.execute_workflow(created['workflow_id'], execution_params={'source': 'cli-demo'})
        status = await svc.get_workflow_status(created['workflow_id'])
        return {'created': created, 'executed': executed, 'status': status}

    if ns.command == 'run':
        definition = _load_json(ns.definition_json, ns.definition_file)
        if not definition:
            raise ValueError('Provide --definition-json or --definition-file')
        exec_params = _load_json(ns.execution_params_json, ns.execution_params_file)

        created = await svc.create_workflow(definition)
        executed = await svc.execute_workflow(created['workflow_id'], execution_params=exec_params or None)
        return {'created': created, 'executed': executed}

    if ns.command == 'status':
        return await svc.get_workflow_status(ns.workflow_id)

    if ns.command == 'list':
        return await svc.list_workflows(status_filter=ns.status)

    raise ValueError(f'unknown command: {ns.command}')


def main(argv: Optional[List[str]] = None) -> int:
    ns = create_parser().parse_args(argv)
    try:
        data = anyio.run(_run_async, ns)
        _print(data, json_output=bool(ns.json))
        return 0
    except KeyboardInterrupt:
        return 1
    except Exception as e:
        _print({'status': 'error', 'error': str(e)}, json_output=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
