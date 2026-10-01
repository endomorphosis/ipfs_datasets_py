#!/usr/bin/env python3
"""Stage, publish, receive or register exact formula branches without promotion."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    anchor = sub.add_parser('anchor')
    anchor.add_argument('--version-id', required=True)
    anchor.add_argument('--output', type=Path, required=True)
    publish = sub.add_parser('publish')
    publish.add_argument('--manifest', type=Path, required=True)
    publish.add_argument('--upload', action='store_true')
    receive = sub.add_parser('receive')
    receive.add_argument('--reference', type=Path, required=True, help='Exact commit-pinned formula_reference JSON')
    receive.add_argument('--output', type=Path, required=True)
    receive.add_argument('--allow-weight-download', action='store_true')
    receive.add_argument('--kind', required=True, choices=('anchor', 'update'))
    register = sub.add_parser('register')
    register.add_argument('--manifest', type=Path, required=True)
    register.add_argument('--output', type=Path, required=True, help='Fresh candidate directory')
    for command in (anchor, publish, receive, register):
        command.add_argument('--registry', type=Path, required=True)
        command.add_argument('--artifact-root', type=Path, required=True)
        command.add_argument('--domain', required=True, choices=('legal_ir', 'intent_ir', 'security_ir', 'ui_ux_ir'))
        command.add_argument('--runtime-version', required=True, choices=('native_formula_v1', 'source_conditioned_formula_v1'))
        command.add_argument('--parent-version', help='Locally provisioned exact numerical parent for an update')
        command.add_argument('--receipt', type=Path, required=True, help='Fresh bounded receipt path; no weights printed')
    args = parser.parse_args(argv)
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_formula_exchange as exchange
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_formula_fleet as profile
    require = profile.require
    require(not args.receipt.exists() and args.receipt.parent.is_dir(), 'fresh receipt under existing directory required')
    module = profile.checkpoint_module(args.domain, args.runtime_version)
    with AutoencoderRegistry(args.registry, args.artifact_root) as owner:
        parent = None if args.parent_version is None else module.load_registered_candidate(owner, args.parent_version)
        if args.command == 'anchor':
            result = module.load_registered_candidate(owner, args.version_id)
            binding = exchange.formula_binding(result)
            require((binding['domain_id'], binding['runtime_version']) == (args.domain, args.runtime_version), 'anchor runtime differs')
            receipt = exchange.stage_formula_anchor(result, args.output)
        elif args.command == 'publish':
            standalone = profile.read(args.manifest, 1024 * 1024).get('kind') == 'anchor'
            loaded = exchange.load_formula_bundle(args.manifest, parent_result=None if standalone else parent)
            binding = loaded['binding']
            require((binding['domain_id'], binding['runtime_version']) == (args.domain, args.runtime_version), 'manifest runtime differs')
            receipt = exchange.publish_formula_bundle(args.manifest, parent_result=None if standalone else parent, upload=args.upload)
        elif args.command == 'receive':
            reference = profile.read(args.reference, 1024 * 1024)
            binding = reference.get('binding', {})
            require((binding.get('domain_id'), binding.get('runtime_version')) == (args.domain, args.runtime_version), 'reference runtime differs')
            require(args.kind == 'anchor' or parent is not None, 'updates require an exact local parent')
            loaded = exchange.receive_formula_bundle(reference, args.output, parent_result=None if args.kind == 'anchor' else parent,
                expected_binding=None if parent is None else exchange.formula_binding(parent),
                allow_weight_download=args.allow_weight_download)
            require(profile.read(loaded['manifest_path'], 1024 * 1024)['kind'] == args.kind, 'received bundle kind differs')
            receipt = {key: value for key, value in loaded.items() if key != 'result'}
        else:
            standalone = profile.read(args.manifest, 1024 * 1024).get('kind') == 'anchor'
            loaded = exchange.load_formula_bundle(args.manifest, parent_result=None if standalone else parent)
            binding = loaded['binding']
            require((binding['domain_id'], binding['runtime_version']) == (args.domain, args.runtime_version), 'manifest runtime differs')
            receipt = module.register_candidate(owner, loaded['result'], args.output, parent_version_id=args.parent_version)
        profile.save(args.receipt, receipt)
    print(json.dumps({'receipt': str(args.receipt), 'command': args.command, **profile.FALSE}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
