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
#   ./build.sh --stage-bin  # copy release binary into bin/<platform>/groth16
#   ./build.sh --platform-name linux-x86_64 --stage-bin
#
# After running this script, real Groth16 proofs are enabled by default in
# Python when the binary is present. Set IPFS_DATASETS_ENABLE_GROTH16=0 only
# when you intentionally want to disable the Rust backend.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="${SCRIPT_DIR}/target/release/groth16"
DEBUG_BINARY="${SCRIPT_DIR}/target/debug/groth16"

BUILD=1
SETUP=1
DEBUG_MODE=0
SEED=""
STAGE_BIN=0
PLATFORM_NAME=""

detect_platform_name() {
  local os_name arch
  os_name="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m | tr '[:upper:]' '[:lower:]')"
  case "$arch" in
    arm64) arch="aarch64" ;;
    amd64) arch="x86_64" ;;
  esac
  echo "${os_name}-${arch}"
}

# ── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug)         DEBUG_MODE=1; SETUP=0; shift ;;
    --setup-only)    BUILD=0; shift ;;
    --no-setup)      SETUP=0; shift ;;
    --stage-bin)     STAGE_BIN=1; shift ;;
    --platform-name) PLATFORM_NAME="$2"; shift 2 ;;
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

# ── Package binary staging ───────────────────────────────────────────────────
if [[ $STAGE_BIN -eq 1 ]]; then
  if [[ ! -f "$BINARY" ]]; then
    echo "ERROR: Binary not found at ${BINARY}. Run without --setup-only first." >&2
    exit 1
  fi
  if [[ -z "$PLATFORM_NAME" ]]; then
    PLATFORM_NAME="$(detect_platform_name)"
  fi
  PACKAGE_BIN_DIR="${SCRIPT_DIR}/bin/${PLATFORM_NAME}"
  mkdir -p "$PACKAGE_BIN_DIR"
  install -m 0755 "$BINARY" "${PACKAGE_BIN_DIR}/groth16"
  echo "Packaged binary staged: ${PACKAGE_BIN_DIR}/groth16"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "Done!  Real Groth16 proofs are enabled by default when this binary is present."
echo "  python -c \"from ipfs_datasets_py.logic.zkp.backends import get_backend; print(get_backend('groth16').get_backend_info())\""
