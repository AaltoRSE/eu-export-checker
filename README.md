# eu-export-checker

Screen a research paper PDF against the EU dual-use regulation via an
OpenAI-compatible chat API.

- **Paper** — Docling: markdown + figure/table images
- **Regulation** — EUR-Lex consolidated HTML (`data/regulation.html`)

Two backends, llm gateway and local vllm on Triton, share the same `screen_pdfs.py` entry point.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
bash fetch_regulation_html.sh   # → data/regulation.html
```

On Triton, point caches at scratch (optional elsewhere):

```bash
export HF_HOME=${WRKDIR:-/scratch/work/$USER}/.cache/huggingface
export PIP_CACHE_DIR=${WRKDIR:-/scratch/work/$USER}/.cache/pip
```

Compute nodes cannot reach EUR-Lex — run `fetch_regulation_html.sh` on a login before submitting a Slurm job.

## LLM Gateway

`.env.example` is preconfigured for the gateway. Set your API key, then screen:

```bash
# edit .env: LLM_API_KEY=your-llm-gateway-key
bash run_all_screenings.sh          # all data/*.pdf
python screen_pdfs.py data/some-paper.pdf
python screen_pdfs.py data/some-paper.pdf --json
```

`run_all_screenings.sh` reads `LLM_API_URL`, `LLM_MODEL`, and `LLM_API_KEY`
from `.env`

## Local vLLM on Triton

`run_triton_screening.sh` requests a GPU, starts vLLM with Qwen, points
`LLM_API_URL` at `http://127.0.0.1:<port>/v1/chat/completions`, and runs
`run_all_screenings.sh`. You do not need a gateway key for this path.

```bash
mkdir -p logs
sbatch run_triton_screening.sh    # screens all data/*.pdf
```

## Output

```
YES / NO / MAYBE
<summary>
1C001 - <name> (<reason>) (<location>)
IMAGES: paper=… (figures=…, tables=…)
USAGE: input_tokens=… output_tokens=… total_tokens=…
REASONING: .cache/reasoning/<paper>.txt (… chars)
```

## Environment

| Variable | Description |
|---|---|
| `LLM_API_URL` | Chat/completions endpoint (gateway URL in `.env`; overridden to localhost by `run_triton_screening.sh`) |
| `LLM_MODEL` | Model id |
| `LLM_API_KEY` | Bearer key for the gateway; use `local` (or leave unset) for vLLM on localhost |
| `ENABLE_THINKING` | `1` on localhost by default, `0` on gateway unless set |
| `REGULATION_HTML_PATH` | Local regulation HTML (default `data/regulation.html`) |
| `REGULATION_CELEX` | CELEX id for fetch script |
