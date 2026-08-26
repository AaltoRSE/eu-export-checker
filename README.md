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

## PDF conversion utility

Convert a PDF into separate output files (markdown text + extracted images):

```bash
python document_conversion_service.py path/to/input.pdf path/to/output_dir
```

Outputs are written under `output_dir`:

- `document.md` (full extracted markdown text)
- `images/` (one PNG per extracted picture)
- `tables.md` (table dump when tables are detected)
- `conversion_manifest.json` (metadata and file paths)

You can also call it from Python:

```python
from document_conversion_service import convert_pdf_to_files

result = convert_pdf_to_files("path/to/input.pdf", "path/to/output_dir")
print(result.text_file)
print(result.image_files)
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
