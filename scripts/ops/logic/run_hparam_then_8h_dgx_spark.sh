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
# Sweep trials must finish at least one train/validation cycle inside a short
# serial wave. Keep final-grade bridge coverage for the long paired run, but use
# a lean bridge mix and smaller samples for candidate ranking.
export SWEEP_TRAIN_COUNT="${SWEEP_TRAIN_COUNT:-2}"
export SWEEP_VALIDATION_COUNT="${SWEEP_VALIDATION_COUNT:-2}"
export SWEEP_VALIDATION_CANARY_COUNT="${SWEEP_VALIDATION_CANARY_COUNT:-1}"
export SWEEP_MAX_INNER_ITERATIONS="${SWEEP_MAX_INNER_ITERATIONS:-1}"
export SWEEP_MAX_ITEMS="${SWEEP_MAX_ITEMS:-2}"
export SWEEP_MAX_SAMPLE_TEXT_CHARS="${SWEEP_MAX_SAMPLE_TEXT_CHARS:-2048}"
export SWEEP_BRIDGE_LOSS_ADAPTERS="${SWEEP_BRIDGE_LOSS_ADAPTERS:-modal_frame_logic,deontic_norms,fol_tdfol}"
export SWEEP_AUTOENCODER_BRIDGE_WORKERS="${SWEEP_AUTOENCODER_BRIDGE_WORKERS:-4}"
export TRIAL_TIMEOUT_GRACE_SECONDS="${TRIAL_TIMEOUT_GRACE_SECONDS:-600}"

export FINAL_AUTOENCODER_BRIDGE_WORKERS="${FINAL_AUTOENCODER_BRIDGE_WORKERS:-8}"
export FINAL_PROJECTION_EPOCHS="${FINAL_PROJECTION_EPOCHS:-1}"
export BRIDGE_ADAPTER_WORKERS="${BRIDGE_ADAPTER_WORKERS:-4}"
export CODEX_PARALLEL_SCOPES="${CODEX_PARALLEL_SCOPES:-compiler_ambiguity,compiler_registry,ir_decompiler,bridge,compiler_parser,frame_logic,deontic}"
export CODEX_SCOPE_WORKER_MAP="${CODEX_SCOPE_WORKER_MAP:-compiler_ambiguity=3,compiler_registry=3,ir_decompiler=3,bridge=2,compiler_parser=1,frame_logic=1,deontic=1}"

exec "${ROOT_DIR}/scripts/ops/logic/run_hparam_then_8h.sh" "$@"
