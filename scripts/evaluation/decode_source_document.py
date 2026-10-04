#!/usr/bin/env python3
"""Run local frozen IR decoders on complete source units and optional Lean builds."""
from pathlib import Path
import argparse
import json


def descriptor(path):
    if path is None:
        return None
    if path.stat().st_size > 1_048_576:
        raise ValueError("checkpoint descriptor too large")
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--format',choices=('intent','markdown','code','security_prose','diff'),required=True)
    parser.add_argument('--language')
    parser.add_argument('--intent-checkpoint-descriptor',type=Path)
    parser.add_argument('--security-checkpoint-descriptor',type=Path,
        help='Pinned Security decoder v1 or v2; v2 adds typed pure-function IR and native logic projections')
    parser.add_argument('--start-char',type=int,default=0)
    parser.add_argument('--end-char',type=int)
    parser.add_argument('--recover-context',action='store_true')
    parser.add_argument('--lake-executable',help='Installed toolchain bin/lake; enables actual builds')
    parser.add_argument('--project-logic-families',action='store_true',
        help='Project learned Intent candidates to native logic families and typed parametric Lean')
    parser.add_argument('--intent-family-context',type=Path,
        help='Source/checkpoint/candidate-bound family context, including selected fixture or graph slots')
    parser.add_argument('--intent-logic-family',action='append',dest='intent_logic_families',
        help='Canonical Intent family to request; repeat for multiple families')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    from ipfs_datasets_py.logic.formalization.autoencoder.source_document import prepare_source_document, MAX_BYTES
    if args.output.exists():
        raise ValueError('refuse to replace an existing result')
    if args.source.stat().st_size > MAX_BYTES:
        raise ValueError('source exceeds bounded document size')
    source = args.source.read_bytes().decode('utf-8')
    report = prepare_source_document(source,source_path=str(args.source),source_format=args.format,
        language=args.language,intent_checkpoint=descriptor(args.intent_checkpoint_descriptor),
        security_checkpoint=descriptor(args.security_checkpoint_descriptor),start_char=args.start_char,
        end_char=args.end_char,recover_context=args.recover_context,lake_executable=args.lake_executable,
        project_logic_families=args.project_logic_families,intent_family_context=descriptor(args.intent_family_context),
        requested_intent_families=args.intent_logic_families)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(report,stream,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status':report['status'],'counts':report['counts'],'output':str(args.output)}))


if __name__ == '__main__':
    main()
