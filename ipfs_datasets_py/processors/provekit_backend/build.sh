#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: build.sh [--check | --prepare] [--circuit NAME] [--output DIR]

Manual ProveKit packaging helper.

Modes:
  --check      Validate local ProveKit packaging inputs without preparing keys.
  --prepare    Run provekit-cli prepare for packaged circuit sources.

Environment:
  IPFS_DATASETS_PROVEKIT_CLI       Explicit provekit-cli path.
  IPFS_DATASETS_PROVEKIT_HOME      ProveKit install root with bin/provekit-cli.
  IPFS_DATASETS_PROVEKIT_BUILD_DIR Output directory for prepared artifacts.

This script never clones repositories, builds Rust code, downloads artifacts, or
runs at Python import/install time. Operators must install ProveKit separately.
EOF
}

mode="check"
circuit="knowledge_of_axioms"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
package_root="$(cd "$script_dir/../.." && pwd)"
circuits_root="$package_root/logic/zkp/provekit/circuits"
output_dir="${IPFS_DATASETS_PROVEKIT_BUILD_DIR:-$script_dir/artifacts}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)
            mode="check"
            shift
            ;;
        --prepare)
            mode="prepare"
            shift
            ;;
        --circuit)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                printf 'error: --circuit requires a value\n' >&2
                exit 2
            fi
            circuit="$2"
            shift 2
            ;;
        --output)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                printf 'error: --output requires a value\n' >&2
                exit 2
            fi
            output_dir="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'error: unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$mode" != "check" && "$mode" != "prepare" ]]; then
    printf 'error: unsupported mode: %s\n' "$mode" >&2
    exit 2
fi

circuit_dir="$circuits_root/$circuit"
if [[ ! -f "$circuit_dir/Nargo.toml" || ! -f "$circuit_dir/src/main.nr" ]]; then
    printf 'error: packaged ProveKit circuit is incomplete: %s\n' "$circuit_dir" >&2
    exit 1
fi

provekit_cli=""
if [[ -n "${IPFS_DATASETS_PROVEKIT_CLI:-}" ]]; then
    provekit_cli="$IPFS_DATASETS_PROVEKIT_CLI"
elif [[ -n "${IPFS_DATASETS_PROVEKIT_HOME:-}" ]]; then
    for candidate in \
        "$IPFS_DATASETS_PROVEKIT_HOME/bin/provekit-cli" \
        "$IPFS_DATASETS_PROVEKIT_HOME/target/release/provekit-cli" \
        "$IPFS_DATASETS_PROVEKIT_HOME/provekit-cli"; do
        if [[ -x "$candidate" ]]; then
            provekit_cli="$candidate"
            break
        fi
    done
else
    provekit_cli="$(command -v provekit-cli || true)"
fi

if [[ -n "$provekit_cli" && ! -x "$provekit_cli" ]]; then
    printf 'error: ProveKit CLI is not executable: %s\n' "$provekit_cli" >&2
    exit 1
fi

printf 'ProveKit circuit: %s\n' "$circuit_dir"
printf 'ProveKit CLI: %s\n' "${provekit_cli:-not configured}"

if [[ "$mode" == "check" ]]; then
    printf 'Packaging check passed. Use --prepare to create local keys explicitly.\n'
    exit 0
fi

if [[ -z "$provekit_cli" ]]; then
    printf 'error: ProveKit CLI not found. Set IPFS_DATASETS_PROVEKIT_CLI or IPFS_DATASETS_PROVEKIT_HOME.\n' >&2
    exit 1
fi

mkdir -p "$output_dir/$circuit"
exec "$provekit_cli" prepare \
    --target-dir "$output_dir/$circuit" \
    --pkp "$output_dir/$circuit/$circuit.pkp" \
    --pkv "$output_dir/$circuit/$circuit.pkv" \
    "$circuit_dir"
