#!/bin/bash -l
# Qwen3.8-27B on Triton: vLLM + run_all_screenings.sh

#SBATCH --job-name=qwen-screen
#SBATCH --time=04:00:00
#SBATCH --gpus=1
#SBATCH --gres=min-vram:80g,min-cuda-cc:80
#SBATCH --cpus-per-task=8
#SBATCH --mem=80G
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
mkdir -p logs

export WRKDIR="${WRKDIR:-/scratch/work/$USER}"
export HF_HOME="$WRKDIR/.cache/huggingface"
export XDG_CACHE_HOME="$WRKDIR/.cache"
export PIP_CACHE_DIR="$WRKDIR/.cache/pip"
export TORCH_HOME="$WRKDIR/.cache/torch"
export TRITON_CACHE_DIR="$WRKDIR/.cache/triton"
export VLLM_CACHE_ROOT="$WRKDIR/.cache/vllm"
export FLASHINFER_WORKSPACE_BASE="$WRKDIR"

# Shared Qwen weights: https://scicomp.aalto.fi/triton/apps/llms/#huggingface-models
module load model-huggingface scicomp-llm-env/2026.1
export LD_LIBRARY_PATH="$(dirname "$(dirname "$(command -v python)")")/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# vLLM on Triton needs a libcuda.so on LIBRARY_PATH
STUB="$WRKDIR/.cache/cuda-stubs"
mkdir -p "$STUB"
if [[ ! -e "$STUB/libcuda.so" ]]; then
  for cand in /usr/lib64/libcuda.so.1 /usr/lib64/libcuda.so \
      /usr/lib64/nvidia/libcuda.so.1 /usr/local/cuda/lib64/stubs/libcuda.so; do
    [[ -e "$cand" ]] && ln -sfn "$cand" "$STUB/libcuda.so" && break
  done
fi
export LIBRARY_PATH="$STUB${LIBRARY_PATH:+:$LIBRARY_PATH}"

MODEL="${LLM_MODEL:-Qwen/Qwen3.8-27B}"
PORT="${VLLM_PORT:-$((8000 + ${SLURM_JOB_ID:-$$} % 1000))}"
VLLM_LOG="logs/vllm-${SLURM_JOB_ID:-local}.log"

vllm serve "$MODEL" \
  --host 127.0.0.1 --port "$PORT" --tensor-parallel-size 1 \
  --max-model-len "${MAX_MODEL_LEN:-262144}" --kv-cache-dtype fp8 \
  --reasoning-parser qwen3 --gpu-memory-utilization 0.90 --max-num-seqs 1 \
  --limit-mm-per-prompt '{"image":256}' --served-model-name "$MODEL" \
  >"$VLLM_LOG" 2>&1 &
VLLM_PID=$!
trap 'kill "$VLLM_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 180); do
  kill -0 "$VLLM_PID" 2>/dev/null || { tail -80 "$VLLM_LOG" >&2; exit 1; }
  curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null && break
  sleep 10
done
curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null || { tail -80 "$VLLM_LOG" >&2; exit 1; }

# Docling downloads to a writable cache; vLLM already holds Qwen.
export HF_HUB_CACHE="$HF_HOME/hub" HUGGINGFACE_HUB_CACHE="$HF_HOME/hub"
mkdir -p "$HF_HUB_CACHE"
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE

export LLM_API_URL="http://127.0.0.1:${PORT}/v1/chat/completions"
export LLM_MODEL="$MODEL"
export LLM_API_KEY="${LLM_API_KEY:-local}"

bash run_all_screenings.sh
