# eu-export-checker

Screen a research paper PDF against a regulation PDF for EU dual-use export
controls using the Azure OpenAI **Responses API** (native PDF input — no local
text extraction required).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in all values (see below)
```

## Usage

```bash
python screen_pdfs.py paper.pdf regulation.pdf
python screen_pdfs.py paper.pdf regulation.pdf -m "Additional context"
python screen_pdfs.py paper.pdf regulation.pdf --json   # result + usage as JSON
```

Batch-screen papers listed in `run_all_screenings.sh` (writes a timestamped
`screening_results_YYYYMMDD_HHMMSS.txt` each run):

```bash
bash run_all_screenings.sh
```

## Output

```
YES / NO / MAYBE

<summary>

1C001 - <name> (<reason>) (<location>)

USAGE: input_tokens=... output_tokens=... total_tokens=...
```

## Environment variables

All are required via `.env` (no defaults in the script):

| Variable | Description |
|---|---|
| `RESPONSES_API_URL` | Azure OpenAI Responses API endpoint |
| `RESPONSES_MODEL` | Model deployment ID (see `.env.example`) |
| `OCP_APIM_SUBSCRIPTION_KEY` | Subscription key from the Aalto AI API portal |
