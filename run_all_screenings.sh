#!/usr/bin/env bash
# Screen all test papers against regulation.pdf and write results to screening_results.txt
set -euo pipefail
cd "$(dirname "$0")"

REGULATION="data/regulation.pdf"
OUTPUT="screening_results_$(date +%Y%m%d_%H%M%S).txt"

# Read model name from .env for display
MODEL="$(grep '^RESPONSES_MODEL=' .env | head -1 | cut -d= -f2- | tr -d ' "'\''')"
if [[ -z "$MODEL" ]]; then
  echo "ERROR: RESPONSES_MODEL not found in .env" >&2
  exit 1
fi

PAPERS=(
  "data/Diabetes or endocrinopathy admitted in the COVID-19 ward.pdf"
  "data/Intra-spacecraft optical communication solutions using discrete transceiver.pdf"
  "data/Hydrofluoric–nitric–sulphuric-acid surface treatment of tungsten for carbon fibre-reinforced composite hybrids in space applications.pdf"
  "data/Overview of ground-based testing of components made from electrically-conducting doped peek for space applications.pdf"
)

: > "$OUTPUT"
{
  echo "MODEL: $MODEL"
  echo
} >> "$OUTPUT"
echo "Model: $MODEL"
echo 

for paper in "${PAPERS[@]}"; do
  title="$(basename "$paper" .pdf)"
  {
    echo "================================================================================"
    echo "PAPER: $title"
    echo "================================================================================"
    echo
    .venv/bin/python screen_pdfs.py "$paper" "$REGULATION"
    echo
    echo
  } >> "$OUTPUT"
  echo "Done: $title"
done

echo "All results written to $OUTPUT"
