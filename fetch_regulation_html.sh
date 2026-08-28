#!/usr/bin/env bash
# Login node: download Regulation (EU) 2021/821 HTML via EU Cellar.
#   bash fetch_regulation_html.sh && sbatch run_triton_screening.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data

CELEX="${REGULATION_CELEX:-02021R0821-20251115}"
OUT="${REGULATION_HTML_PATH:-data/regulation.html}"
URL="https://publications.europa.eu/resource/celex/${CELEX}.ENG"

curl -fsSL --connect-timeout 30 --max-time 180 \
  -A 'Mozilla/5.0' -H 'Accept: application/xhtml+xml' \
  -o "$OUT" "$URL"
echo "OK: $OUT ($(wc -c <"$OUT" | tr -d ' ') bytes)"
