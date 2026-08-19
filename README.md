# eu-export-pdf

Screen a research paper PDF against a regulation PDF for EU dual-use export
controls using the Azure OpenAI **Responses API** (native PDF input — no local
text extraction required).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set OCP_APIM_SUBSCRIPTION_KEY
```

## Usage

```bash
python screen_pdfs.py paper.pdf regulation.pdf
python screen_pdfs.py paper.pdf regulation.pdf --message "Additional context"
python screen_pdfs.py paper.pdf regulation.pdf --json   # raw JSON output
```

## Output

```
YES / NO / MAYBE

<summary>

1C001 - <name> (<reason>) (<section>)
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `RESPONSES_API_URL` | Aalto gateway | Azure OpenAI Responses API endpoint |
| `RESPONSES_MODEL` | `gpt-5-2025-08-07` | Model deployment ID |
| `OCP_APIM_SUBSCRIPTION_KEY` | — | Subscription key (required) |
