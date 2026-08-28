#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

OUTPUT="screening_results_$(date +%Y%m%d_%H%M%S).txt"
MODEL="${LLM_MODEL:-$(grep '^LLM_MODEL=' .env | cut -d= -f2-)}"
URL="${LLM_API_URL:-$(grep '^LLM_API_URL=' .env | cut -d= -f2-)}"

shopt -s nullglob
PAPERS=()
for f in data/*.pdf; do
  [[ "$(basename "$f")" == regulation.pdf ]] && continue
  PAPERS+=("$f")
done
((${#PAPERS[@]})) || { echo "No paper PDFs in data/" >&2; exit 1; }

{
  echo "MODEL: $MODEL"
  echo "BACKEND: $URL"
  echo
  for paper in "${PAPERS[@]}"; do
    echo "================================================================================"
    echo "PAPER: $(basename "$paper" .pdf)"
    echo "================================================================================"
    echo
    .venv/bin/python screen_pdfs.py "$paper" || echo "ERROR: screening failed (see stderr)."
    echo
    echo
  done
} | tee "$OUTPUT"

echo "Results: $OUTPUT"
