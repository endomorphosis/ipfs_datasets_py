#!/bin/bash
set -eu
export PYTHONPATH=/home/barberb/lift_coding/.worktrees/ir-release-accelerate-20261002:/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1
export TOKENIZERS_PARALLELISM=false CUDA_VISIBLE_DEVICES='' PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export CODEBASE384_CHECKPOINT=/home/barberb/lift_coding/artifacts/distributed384-20261001/run-01/security_ir/coordinator/checkpoints/2ca38dfcc05536315fc3e2c0647b710b930ef4066b474061a7b4e5bfb9a258c5.json
export CODEBASE384_EMBEDDING_SNAPSHOT=/home/barberb/.cache/huggingface/hub/models--thenlper--gte-small/snapshots/17e1f347d17fe144873b1201da91788898c639cd
export PATH=/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin:$PATH
export CODEBASE384_LAKE=/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lake
python -m pytest -q tests/integration/logic/software_contracts/test_codebase_training_generation.py -k 'actual_strict_child or exact_adaptation_replay or cold_generation_replay or resealed_generation_tampering' --basetemp=/home/barberb/lift_coding/artifacts/registry-bounded-replay-20261003/generation-with-lake-fixture --junitxml=/home/barberb/lift_coding/artifacts/registry-bounded-replay-20261003/generation-with-lake-tests.xml
