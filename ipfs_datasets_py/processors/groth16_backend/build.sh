#!/usr/bin/env bash
# groth16_backend/build.sh
# Convenience script: compile the Groth16 Rust binary and run trusted setup.
#
# Usage:
#   cd ipfs_datasets_py/processors/groth16_backend
#   ./build.sh              # release build + setup v1 + v2
#   ./build.sh --debug      # debug build only (no setup)
#   ./build.sh --setup-only # skip build, run setup only
#   ./build.sh --seed 42    # deterministic setup seed
#
# After running this script, enable real Groth16 proofs in Python by setting:
#   export IPFS_DATASETS_ENABLE_GROTH16=1
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="${SCRIPT_DIR}/target/release/groth16"
DEBUG_BINARY="${SCRIPT_DIR}/target/debug/groth16"

BUILD=1
SETUP=1
DEBUG_MODE=0
SEED=""

# ── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug)         DEBUG_MODE=1; SETUP=0; shift ;;
    --setup-only)    BUILD=0; shift ;;
    --no-setup)      SETUP=0; shift ;;
    --seed)          SEED="$2"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ── Rust check ───────────────────────────────────────────────────────────────
if ! command -v cargo &>/dev/null; then
  echo "ERROR: Rust/Cargo not found."
  echo "Install via:  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  exit 1
fi

echo "Rust version: $(rustc --version)"
echo "Cargo version: $(cargo --version)"

# ── Build ────────────────────────────────────────────────────────────────────
if [[ $BUILD -eq 1 ]]; then
  if [[ $DEBUG_MODE -eq 1 ]]; then
    echo "Building groth16_backend (debug)..."
    cargo build --manifest-path "${SCRIPT_DIR}/Cargo.toml" 2>&1
    ACTIVE_BINARY="$DEBUG_BINARY"
  else
    echo "Building groth16_backend (release, optimised)..."
    cargo build --release --manifest-path "${SCRIPT_DIR}/Cargo.toml" 2>&1
    ACTIVE_BINARY="$BINARY"
  fi
  echo "Build complete: ${ACTIVE_BINARY}"
fi

# ── Trusted setup ────────────────────────────────────────────────────────────
if [[ $SETUP -eq 1 ]]; then
  if [[ ! -f "$BINARY" ]]; then
    echo "ERROR: Binary not found at ${BINARY}. Run without --setup-only first."
    exit 1
  fi

  SEED_ARGS=()
  if [[ -n "$SEED" ]]; then
    SEED_ARGS=(--seed "$SEED")
  fi

  for VER in 1 2; do
    ARTIFACTS_DIR="${SCRIPT_DIR}/artifacts/v${VER}"
    PK="${ARTIFACTS_DIR}/proving_key.bin"
    VK="${ARTIFACTS_DIR}/verifying_key.bin"

    if [[ -f "$PK" && -f "$VK" ]]; then
      echo "Trusted setup v${VER}: artifacts already exist (skipping)."
    else
      echo "Running trusted setup for circuit v${VER}..."
      MANIFEST=$("$BINARY" setup --version "$VER" "${SEED_ARGS[@]}" 2>&1)
      echo "Setup v${VER} complete:"
      echo "$MANIFEST" | python3 -m json.tool 2>/dev/null || echo "$MANIFEST"
    fi
  done
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "Done!  To enable real Groth16 proofs in Python, run:"
echo "  export IPFS_DATASETS_ENABLE_GROTH16=1"
echo "  python -c \"from ipfs_datasets_py.logic.zkp.backends import get_backend; print(get_backend('groth16').get_backend_info())\""
