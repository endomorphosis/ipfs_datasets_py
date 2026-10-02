#!/usr/bin/env python3
"""Run explicit local workers and versioned exchange for structured 384d heads."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir")


def _positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("a positive integer is required")
    return number


def _nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("a nonnegative integer is required")
    return number


def _result(parser):
    parser.add_argument("--result", type=Path,
        help="also save the returned JSON to an immutable local artifact")


def _round(parser):
    parser.add_argument("--round-dir", type=Path, required=True,
        help="prepared or fetched round directory")


def _store(parser):
    parser.add_argument("--database", type=Path, required=True,
        help="host-local DuckDB journal; one owning process at a time")
    parser.add_argument("--artifact-root", type=Path, required=True,
        help="host-local content-addressed artifacts for the journal")


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    profiles = commands.add_parser("profiles", help="show pinned parents and native family coverage")
    profiles.add_argument("--domain", choices=DOMAINS)
    _result(profiles)

    prepare = commands.add_parser("prepare", help="audit train/validation inputs and freeze a grouped round")
    prepare.add_argument("--domain", choices=DOMAINS, required=True)
    prepare.add_argument("--training", type=Path, required=True, help="closed training rows JSON")
    prepare.add_argument("--validation", type=Path, required=True, help="closed validation rows JSON")
    prepare.add_argument("--source", type=Path, required=True,
        help="ir384-corpus-source/v1 JSON provenance descriptor")
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--base", type=Path,
        help="explicit compatible base checkpoint; otherwise load the immutable published parent")
    prepare.add_argument("--cache-dir", type=Path)
    prepare.add_argument("--local-files-only", action="store_true",
        help="require the parent to be available locally")
    prepare.add_argument("--shard-size", type=_positive, default=32,
        help="desired rows per shard; complete semantic groups stay together (default: 32)")
    prepare.add_argument("--machine-count", type=_positive, default=1,
        help="freeze this many machine partitions into the plan (default: 1)")
    prepare.add_argument("--require-family", dest="required_families", action="append",
        help="required canonical native family; repeat to select several; default is the domain profile")
    _result(prepare)

    publish = commands.add_parser("publish-inputs", help="stage or publish the exact round inputs")
    _round(publish)
    publish.add_argument("--upload", action="store_true",
        help="publish to Hugging Face; requires explicit corpus redistribution permission")
    _result(publish)

    fetch = commands.add_parser("fetch", help="fetch a round from an immutable published input reference")
    fetch.add_argument("--reference", type=Path, required=True,
        help="JSON reference returned by publish-inputs --upload")
    fetch.add_argument("--output-dir", type=Path, required=True)
    fetch.add_argument("--local-files-only", action="store_true")
    _result(fetch)

    work = commands.add_parser("work", help="compute this machine's shard updates with local worker threads")
    _round(work)
    _store(work)
    work.add_argument("--machine-index", type=_nonnegative, default=0,
        help="zero-based index in the prepared machine_count (default: 0)")
    work.add_argument("--workers", type=_positive, default=4,
        help="local numerical worker threads (default: 4)")
    work.add_argument("--upload", action="store_true", help="publish completed shard updates to Hugging Face")
    _result(work)

    merge = commands.add_parser("merge", help="merge every unique shard and select a head on validation")
    _round(merge)
    _store(merge)
    merge.add_argument("--update-path", dest="update_paths", type=Path, action="append", default=[],
        help="additional local immutable shard update JSON; repeat for several")
    merge.add_argument("--discover", action="store_true",
        help="discover this plan's published Hugging Face updates")
    merge.add_argument("--upload", action="store_true", help="publish the resulting candidate checkpoint version")
    merge.add_argument("--full-anchor", action="store_true",
        help="stage/publish a complete checkpoint anchor instead of only a parent-bound patch")
    _result(merge)

    projection_families = commands.add_parser("projection-families", help="show current native projection adapters and default requirements")
    projection_families.add_argument("--domain", choices=DOMAINS)
    _result(projection_families)

    world = commands.add_parser("intent-world", help="inspect exact Intent IDs or bind an explicit guarded world model")
    world.add_argument("--candidate", type=Path, required=True, help="unchanged decoded Intent candidate JSON")
    world.add_argument("--source-text", type=Path, required=True, help="exact UTF-8 instruction file")
    world.add_argument("--world-model", type=Path, help="explicit typed world model JSON; omit to list binding requirements")
    world.add_argument("--additional-inputs", type=Path, help="other formula or native context inputs to retain")
    _result(world)

    source_state = commands.add_parser("source-state", help="derive and check finite operational states from exact Security predictions")
    source_state.add_argument("--rows", type=Path, required=True,
        help="JSON rows with id, original source_text, candidate_ir and explicit input_domains")
    source_state.add_argument("--lake-executable", type=Path)
    source_state.add_argument("--java-executable", type=Path)
    source_state.add_argument("--tla2tools-jar", type=Path)
    source_state.add_argument("--timeout-seconds", type=_positive, default=60)
    source_state.add_argument("--output-dir", type=Path, help="fresh native-check evidence directory")
    _result(source_state)

    code_effects = commands.add_parser("intent-code-effects", help="check explicit Intent effects against bounded code outcomes")
    code_effects.add_argument("--rows", type=Path, required=True,
        help="closed rows with original Intent/code sources, unchanged candidates, domains and explicit association")
    code_effects.add_argument("--lake-executable", type=Path)
    code_effects.add_argument("--timeout-seconds", type=_positive, default=60)
    code_effects.add_argument("--output-dir", type=Path, help="fresh native-check evidence directory")
    _result(code_effects)

    export = commands.add_parser("export-pairs", help="audit reviewed native pairs and bound embeddings for training")
    export.add_argument("--domain", choices=DOMAINS, required=True)
    export.add_argument("--pairs", type=Path, required=True)
    export.add_argument("--embeddings", type=Path, required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--base", type=Path)
    export.add_argument("--cache-dir", type=Path)
    export.add_argument("--local-files-only", action="store_true")
    _result(export)

    project = commands.add_parser("project", help="project merged-checkpoint predictions with source-bound context")
    _round(project)
    project.add_argument("--checkpoint", type=Path, required=True)
    project.add_argument("--output-dir", type=Path, required=True, help="fresh evidence directory")
    project.add_argument("--contexts", type=Path, help="closed checkpoint/candidate-bound context batch")
    project.add_argument("--row-id", dest="row_ids", action="append", help="explicit validation subset; repeat")
    project.add_argument("--require-family", dest="required_families", action="append")
    project.add_argument("--lake-executable", type=Path, help="installed native Lake; omission prepares projections only")
    project.add_argument("--java-executable", type=Path)
    project.add_argument("--tla2tools-jar", type=Path)
    project.add_argument("--timeout-seconds", type=_positive, default=60)
    _result(project)
    return parser


def _dispatch(args):
    from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.contracts import read_json
    if args.command == "profiles":
        from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.profiles import get_profile
        return get_profile(args.domain) if args.domain else {domain: get_profile(domain) for domain in DOMAINS}

    if args.command == "projection-families":
        from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projections_v2 import family_catalog
        return family_catalog(args.domain) if args.domain else {domain: family_catalog(domain) for domain in DOMAINS}
    if args.command == "intent-world":
        from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.intent_world_model import (
            bind_intent_world_model, world_model_requirements)
        candidate, source = read_json(args.candidate), args.source_text.read_bytes().decode("utf-8")
        if args.world_model is None:
            if args.additional_inputs is not None:
                raise ValueError("additional inputs require an explicit world model")
            return world_model_requirements(candidate, source)
        return bind_intent_world_model(candidate, source, read_json(args.world_model),
            additional_inputs=read_json(args.additional_inputs) if args.additional_inputs is not None else None)
    if args.command == "source-state":
        from ipfs_datasets_py.logic.formalization.autoencoder.source_state_lake import (
            prepare_source_state_lean, build_source_state_lake, verify_source_state_lake)
        rows = read_json(args.rows)
        if args.lake_executable is None:
            if any((args.java_executable, args.tla2tools_jar, args.output_dir)):
                raise ValueError("source-state native tools/output require an explicit Lake executable")
            return prepare_source_state_lean(rows)
        execution = build_source_state_lake(rows, lake_executable=args.lake_executable,
            java_executable=args.java_executable, tla2tools_jar=args.tla2tools_jar,
            timeout_seconds=args.timeout_seconds, output_directory=args.output_dir)
        return verify_source_state_lake(execution, rows)
    if args.command == "intent-code-effects":
        from ipfs_datasets_py.logic.formalization.autoencoder.intent_code_effects_lake import (
            prepare_intent_code_effects_lean, build_intent_code_effects_lake, verify_intent_code_effects_lake)
        rows = read_json(args.rows)
        if args.lake_executable is None:
            if args.output_dir is not None:
                raise ValueError("Intent/code native output requires an explicit Lake executable")
            return prepare_intent_code_effects_lean(rows)
        execution = build_intent_code_effects_lake(rows, lake_executable=args.lake_executable,
            timeout_seconds=args.timeout_seconds, output_directory=args.output_dir)
        return verify_intent_code_effects_lake(execution, rows)
    if args.command == "export-pairs":
        from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.paired_export import export_reviewed_pairs
        return export_reviewed_pairs(args.domain, args.pairs, args.embeddings, args.output_dir,
            base_path=args.base, cache_dir=args.cache_dir, local_files_only=args.local_files_only)
    if args.command == "project":
        from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.qualification import qualify_round
        return qualify_round(args.round_dir, args.checkpoint, args.output_dir, contexts_path=args.contexts,
            row_ids=args.row_ids, required_families=args.required_families, lake_executable=args.lake_executable,
            java_executable=args.java_executable, tla2tools_jar=args.tla2tools_jar, timeout_seconds=args.timeout_seconds)
    from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import runner
    if args.command == "prepare":
        return runner.prepare_round(args.domain, args.training, args.validation, args.output_dir,
            source_descriptor=read_json(args.source), base_path=args.base, cache_dir=args.cache_dir,
            local_files_only=args.local_files_only, shard_size=args.shard_size,
            machine_count=args.machine_count, required_families=args.required_families)
    if args.command == "publish-inputs":
        return runner.publish_inputs(args.round_dir, upload=args.upload)
    if args.command == "fetch":
        return runner.fetch_inputs(read_json(args.reference), args.output_dir,
            local_files_only=args.local_files_only)
    if args.command == "work":
        return runner.run_local(args.round_dir, args.database, args.artifact_root,
            machine_index=args.machine_index, workers=args.workers, upload=args.upload)
    if args.command == "merge":
        return runner.merge_round(args.round_dir, args.database, args.artifact_root,
            update_paths=args.update_paths, discover=args.discover, upload=args.upload,
            full_anchor=args.full_anchor)
    raise ValueError("unknown distributed training command")


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        # Keep stdout machine-readable even if optional imports emit diagnostics.
        with redirect_stdout(sys.stderr):
            result = _dispatch(args)
            if args.result is not None:
                from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.contracts import write_json
                write_json(args.result, result)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
    except (ValueError, OSError) as error:
        print("distributed 384 training: " + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
