#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

# DGX Spark has one GB10 GPU and a 20-core Grace CPU. Keep the final run to one
# canonical autoencoder writer, use CUDA for its vector math, and put parallelism
# into bridge evaluation plus demand-weighted Codex consumers.
export AUTOENCODER_DEVICE="${AUTOENCODER_DEVICE:-cuda}"

# A CUDA sweep should avoid six simultaneous model writers on one GPU. This keeps
# the one-hour wall budget while running the six built-in configs in serial waves.
# Bump to 2 only after the bottleneck report shows sustained low GPU utilization.
export TRIAL_PARALLELISM="${TRIAL_PARALLELISM:-1}"
export SWEEP_AUTOENCODER_BRIDGE_WORKERS="${SWEEP_AUTOENCODER_BRIDGE_WORKERS:-8}"

export FINAL_AUTOENCODER_BRIDGE_WORKERS="${FINAL_AUTOENCODER_BRIDGE_WORKERS:-8}"
export BRIDGE_ADAPTER_WORKERS="${BRIDGE_ADAPTER_WORKERS:-4}"
export CODEX_PARALLEL_SCOPES="${CODEX_PARALLEL_SCOPES:-compiler_ambiguity,compiler_registry,ir_decompiler,bridge,compiler_parser,frame_logic,deontic}"
export CODEX_SCOPE_WORKER_MAP="${CODEX_SCOPE_WORKER_MAP:-compiler_ambiguity=3,compiler_registry=3,ir_decompiler=3,bridge=2,compiler_parser=1,frame_logic=1,deontic=1}"

exec "${ROOT_DIR}/scripts/ops/logic/run_hparam_then_8h.sh" "$@"
