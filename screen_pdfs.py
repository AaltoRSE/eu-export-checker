#!/usr/bin/env python3
"""Screen paper.pdf vs regulation.pdf via Azure OpenAI Responses API.

  python screen_pdfs.py paper.pdf regulation.pdf [-m MSG] [--env .env] [--json]

Env: RESPONSES_API_URL, RESPONSES_MODEL, OCP_APIM_SUBSCRIPTION_KEY
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import textwrap
from pathlib import Path

import httpx

SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert EU dual-use export-control analyst.
    You will receive a research paper and the applicable export-control regulation
    (typically Annex I dual-use list). Determine whether any goods, software, or
    technology described in the paper fall under that regulation.

    Respond ONLY with a JSON object with exactly these keys:
    {
      "verdict":  "YES" | "NO" | "MAYBE",
      "summary":  "<one or two sentences describing how controls may or may not apply>",
      "matches": [
        {
          "control_number": "<e.g. 1C001 or 9E001>",
          "name":           "<official name of the controlled item / software / technology>",
          "reason":         "<why this paper is relevant, including any term mapping>",
          "location":       "<where in the paper this was found, e.g. section / page>"
        }
      ]
    }

    Rules:
    - Match semantically, not only by identical wording. Scientific terms often differ
      from legal control-list terms (e.g. drone ≈ UAV ≈ UAS ≈ unmanned aerial vehicle;
      PEEK ≈ polyarylene ketone; CFRP ≈ carbon-fibre / filamentary materials).
    - Translate the paper's scientific language into control-list concepts before deciding.
    - Assess tangible items (typically A/B/C) AND intangible items: software (D) and
      technology (E). Detailed design, manufacturing, process parameters, test methods,
      algorithms, or "use" know-how in a publication or research plan may be controlled
      technology/software relating to a tangible entry even when no hardware is exported.
    - If a tangible control may apply, also check related D/E entries for that item family.
    - Public-domain publication may limit technology controls, but still report candidate
      entries; use MAYBE when classification depends on missing thresholds or intent.
    - Prefer MAYBE over NO when evidence is incomplete (e.g. missing performance figures).
    - Be biased towards YES/MAYBE when unsure, unless clearly NO.
    - Be concise but precise. Never invent control numbers.
    - Do NOT include any text outside the JSON object.
    - verdict = YES if at least one clear match; MAYBE if uncertain; NO if none.
    - matches may be empty when verdict is NO.
""")


def load_dotenv(path: Path) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def b64(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode()


def screen(paper: Path, regulation: Path, message: str = "") -> tuple[dict, dict]:
    key = os.environ["OCP_APIM_SUBSCRIPTION_KEY"]
    text = (
        "The first attached file is the REGULATION. "
        "The second attached file is the PAPER to screen. "
        "Perform the export-control screening and return the JSON."
    )
    if message.strip():
        text += f"\n\n### ADDITIONAL CONTEXT\n\n{message.strip()}"

    payload = {
        "model": os.environ["RESPONSES_MODEL"],
        "instructions": SYSTEM_PROMPT,
        "text": {"format": {"type": "json_object"}},
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_file", "filename": regulation.name,
                 "file_data": f"data:application/pdf;base64,{b64(regulation)}"},
                {"type": "input_file", "filename": paper.name,
                 "file_data": f"data:application/pdf;base64,{b64(paper)}"},
                {"type": "input_text", "text": text},
            ],
        }],
    }
    headers = {
        "Content-Type": "application/json",
        "Ocp-Apim-Subscription-Key": key,
        "api-key": key,
    }
    with httpx.Client(timeout=300.0) as client:
        last_err = ""
        for attempt in range(1, 4):
            resp = client.post(os.environ["RESPONSES_API_URL"].rstrip("/"), headers=headers, json=payload)
            if not resp.is_error:
                data = resp.json()
                break
            last_err = f"HTTP {resp.status_code}: {resp.text[:800]}"
            # Retry transient gateway failures
            if resp.status_code >= 500 and attempt < 3:
                time.sleep(5 * attempt)
                continue
            raise RuntimeError(last_err)
        else:
            raise RuntimeError(last_err)

    content = next(
        part["text"]
        for item in data["output"] if item.get("type") == "message"
        for part in item.get("content", []) if part.get("type") == "output_text"
    )
    return json.loads(content), data.get("usage") or {}


def format_output(result: dict, usage: dict) -> str:
    lines = [result["verdict"].upper(), "", result.get("summary", "")]
    for m in result.get("matches", []):
        lines.append(f"{m['control_number']} - {m['name']} ({m['reason']}) ({m['location']})")
    u = usage
    lines += [
        "",
        f"USAGE: input_tokens={u.get('input_tokens', '?')} "
        f"output_tokens={u.get('output_tokens', '?')} "
        f"total_tokens={u.get('total_tokens', '?')}",
    ]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("paper", type=Path)
    p.add_argument("regulation", type=Path)
    p.add_argument("-m", "--message", default="")
    p.add_argument("--env", type=Path, default=Path(__file__).parent / ".env")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    load_dotenv(args.env)
    result, usage = screen(args.paper, args.regulation, args.message)
    if args.json:
        print(json.dumps({"result": result, "usage": usage}, indent=2, ensure_ascii=False))
    else:
        print(format_output(result, usage))


if __name__ == "__main__":
    main()
