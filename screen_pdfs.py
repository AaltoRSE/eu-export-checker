#!/usr/bin/env python3
"""
screen_pdfs.py – Screen a paper PDF against a regulation PDF for EU dual-use
export controls using the Azure OpenAI Responses API.

Usage:
    python screen_pdfs.py paper.pdf regulation.pdf \
        [--message "Additional context or instructions"] \
        [--env .env] [--json]

Output (printed to stdout):
    YES / NO / MAYBE
    <summary>
    1C001 - <name> (<reason>) (<where found>)
    ...

Environment variables (or .env file):
    RESPONSES_API_URL          Azure OpenAI Responses API endpoint
    RESPONSES_MODEL            Model deployment ID
    OCP_APIM_SUBSCRIPTION_KEY  Subscription key (or OPENAI_API_KEY)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

import httpx


def _load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert EU dual-use export-control analyst.
    You will receive a research paper and the applicable export-control regulation.
    Your task is to determine whether any goods, software, or technology described
    in the paper fall under the export-control regulation.

    Respond ONLY with a JSON object with exactly these keys:
    {
      "verdict":  "YES" | "NO" | "MAYBE",
      "summary":  "<one or two sentences describing how sanctions may or may not apply>",
      "matches": [
        {
          "control_number": "<e.g. 1C001>",
          "name":           "<official name of the controlled item>",
          "reason":         "<why this paper is relevant to this entry>",
          "location":       "<where in the paper this was found, e.g. section / page>"
        }
      ]
    }

    Rules:
    - verdict must be YES if there is at least one clear match, MAYBE if uncertain,
      NO if no matches are found.
    - matches may be an empty list when verdict is NO.
    - Be concise but precise. Do not invent control numbers.
    - Do NOT include any text outside the JSON object.
""")


def _call_responses_api(
    paper_path: Path,
    regulation_path: Path,
    user_message: str,
    cfg: dict[str, str],
) -> dict[str, Any]:
    def _b64(path: Path) -> str:
        return base64.standard_b64encode(path.read_bytes()).decode()

    additional = f"\n\n### ADDITIONAL CONTEXT\n\n{user_message.strip()}" if user_message.strip() else ""
    user_text = (
        "The first attached file is the REGULATION. "
        "The second attached file is the PAPER to screen. "
        "Perform the export-control screening and return the JSON."
        + additional
    )

    payload: dict[str, Any] = {
        "model": cfg["model"],
        "instructions": SYSTEM_PROMPT,
        "text": {"format": {"type": "json_object"}},
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "filename": regulation_path.name,
                     "file_data": f"data:application/pdf;base64,{_b64(regulation_path)}"},
                    {"type": "input_file", "filename": paper_path.name,
                     "file_data": f"data:application/pdf;base64,{_b64(paper_path)}"},
                    {"type": "input_text", "text": user_text},
                ],
            }
        ],
    }

    url = cfg["url"]
    headers = {
        "Content-Type": "application/json",
        "Ocp-Apim-Subscription-Key": cfg["api_key"],
        "api-key": cfg["api_key"],
    }

    with httpx.Client(timeout=300.0) as client:
        resp = client.post(url, headers=headers, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"Responses API HTTP {resp.status_code}: {resp.text[:800]}")

    data = resp.json()
    content = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    content = part.get("text", "")
                    break
        if content:
            break
    if not content:
        raise RuntimeError(f"No output_text in response:\n{json.dumps(data)[:600]}")

    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            return json.loads(match.group(0))
        raise RuntimeError(f"Model did not return valid JSON:\n{content[:600]}")


def format_output(result: dict[str, Any]) -> str:
    lines = [result.get("verdict", "MAYBE").upper(), "", result.get("summary", "").strip()]
    for m in result.get("matches", []):
        lines.append(f"{m.get('control_number','?')} - {m.get('name','')} ({m.get('reason','')}) ({m.get('location','')})")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Screen a research paper PDF against a regulation PDF for EU dual-use export controls."
    )
    parser.add_argument("paper", type=Path)
    parser.add_argument("regulation", type=Path)
    parser.add_argument("--message", "-m", default="")
    parser.add_argument("--env", type=Path, default=Path(__file__).parent / ".env")
    parser.add_argument("--json", action="store_true", dest="output_json")
    args = parser.parse_args()

    _load_dotenv(args.env)

    api_key = os.environ.get("OCP_APIM_SUBSCRIPTION_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    if not api_key:
        sys.exit("ERROR: OCP_APIM_SUBSCRIPTION_KEY (or OPENAI_API_KEY) is not set.")

    cfg = {
        "url": os.environ.get("RESPONSES_API_URL", "https://aalto-openai-apigw.azure-api.net/v1/openai/responses").rstrip("/"),
        "model": os.environ.get("RESPONSES_MODEL", "gpt-5-2025-08-07"),
        "api_key": api_key,
    }

    result = _call_responses_api(args.paper, args.regulation, args.message, cfg)

    if args.output_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_output(result))


if __name__ == "__main__":
    main()
