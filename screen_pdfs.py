#!/usr/bin/env python3
"""Screen a paper PDF against the EU dual-use regulation (EUR-Lex HTML).

  python screen_pdfs.py paper.pdf [-m MSG] [--env .env] [--json]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import textwrap
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import html2text
import httpx
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import PictureItem, TableItem
from PIL import Image

MAX_IMAGE_EDGE = 1280
MIN_IMAGE_EDGE = 64
JPEG_QUALITY = 80

ROOT = Path(__file__).parent
CACHE_DIR = ROOT / ".cache" / "eurlex"
REASONING_DIR = ROOT / ".cache" / "reasoning"
DEFAULT_REGULATION = ROOT / "data" / "regulation.html"

_converter: DocumentConverter | None = None

SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert EU dual-use export-control analyst.
    You will receive a research paper and the full applicable export-control
    regulation (articles and annexes). Determine whether any goods, software, or
    technology described in the paper fall under that regulation.

    When images are provided (figures, tables, diagrams), inspect them as carefully
    as the text — they may show controlled materials, devices, or processes not
    fully described in words. Paper/regulation body text is Markdown (tables included).

    Respond ONLY with a JSON object with exactly these keys:
    {
      "verdict":  "YES" | "NO" | "MAYBE",
      "summary":  "<one or two sentences describing how controls may or may not apply>",
      "matches": [
        {
          "control_number": "<e.g. 1C001 or 9E001>",
          "name":           "<official name of the controlled item / software / technology>",
          "reason":         "<why this paper is relevant, including any term mapping>",
          "location":       "<where in the paper this was found, e.g. section / page / figure>"
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
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def _is_local() -> bool:
    url = os.environ.get("LLM_API_URL", "")
    return "127.0.0.1" in url or "localhost" in url


def auth_headers() -> dict[str, str]:
    key = os.environ.get("LLM_API_KEY", "").strip() or ("local" if _is_local() else "")
    if not key:
        raise RuntimeError("Set LLM_API_KEY in .env")
    return {"Authorization": f"Bearer {key}"}


def _html_to_markdown(html: str) -> str:
    conv = html2text.HTML2Text()
    conv.ignore_links = False
    conv.ignore_images = True
    conv.body_width = 0
    conv.single_line_break = True
    cleaned = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
    return re.sub(r"\n{3,}", "\n\n", conv.handle(cleaned).strip())


def _regulation_path() -> Path:
    raw = os.environ.get("REGULATION_HTML_PATH", "").strip()
    path = Path(raw) if raw else DEFAULT_REGULATION
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise RuntimeError(f"Missing {path}; run: bash fetch_regulation_html.sh")
    return path.resolve()


@lru_cache(maxsize=1)
def load_regulation() -> tuple[str, str]:
    """Return (markdown, label). Cached on disk by source mtime."""
    path = _regulation_path()
    label = path.name
    digest = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}".encode()).hexdigest()[:20]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_md = CACHE_DIR / f"{digest}.md"
    if cache_md.exists():
        return cache_md.read_text(), label
    md = _html_to_markdown(path.read_text(encoding="utf-8", errors="replace"))
    cache_md.write_text(md, encoding="utf-8")
    return md, label


def _get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        opts = PdfPipelineOptions()
        opts.do_ocr = False
        opts.do_table_structure = True
        opts.generate_picture_images = True
        opts.generate_page_images = True
        _converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
    return _converter


def _pil_to_jpeg_b64(img: Image.Image) -> str | None:
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) < MIN_IMAGE_EDGE:
        return None
    if max(img.size) > MAX_IMAGE_EDGE:
        img = img.copy()
        img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode()


def extract_pdf(path: Path) -> tuple[str, list[tuple[str, str, str]], int]:
    doc = _get_converter().convert(str(path)).document
    text = doc.export_to_markdown().strip()
    pages = len(getattr(doc, "pages", {}) or {})
    images: list[tuple[str, str, str]] = []
    picture_n = table_n = 0
    for element, _ in doc.iterate_items():
        if isinstance(element, PictureItem):
            picture_n += 1
            kind, n = "picture", picture_n
        elif isinstance(element, TableItem):
            table_n += 1
            kind, n = "table", table_n
        else:
            continue
        try:
            pil = element.get_image(doc)
        except Exception:
            continue
        if pil is None:
            continue
        data = _pil_to_jpeg_b64(pil)
        if data:
            images.append((f"{path.name} {kind} {n}", data, kind))
    if not text and not images:
        raise RuntimeError(f"No extractable content in {path}")
    return text, images, pages


def build_payload(
    paper: Path,
    paper_text: str,
    paper_images: list[tuple[str, str, str]],
    reg_text: str,
    reg_label: str,
    message: str,
) -> dict:
    parts: list[dict] = [
        {"type": "text", "text": f"### REGULATION ({reg_label})\n\n{reg_text}"},
        {"type": "text", "text": f"### PAPER ({paper.name})\n\n{paper_text or '(no text)'}"},
    ]
    if paper_images:
        parts.append({
            "type": "text",
            "text": f"### PAPER IMAGES ({len(paper_images)} from {paper.name})\n"
            "Inspect these visuals as part of the screening.",
        })
        for label, data, _ in paper_images:
            parts += [
                {"type": "text", "text": f"[image: {label}]"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}},
            ]
    parts.append({"type": "text", "text": "Perform the export-control screening and return the JSON."})
    if message.strip():
        parts.append({"type": "text", "text": f"### ADDITIONAL CONTEXT\n\n{message.strip()}"})

    thinking = os.environ.get("ENABLE_THINKING", "1" if _is_local() else "0").strip().lower() in {
        "1", "true", "yes", "on",
    }
    payload: dict[str, Any] = {
        "model": os.environ["LLM_MODEL"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": parts},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": int(os.environ.get("MAX_OUTPUT_TOKENS", "24576")),
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": float(os.environ.get("TEMPERATURE", "0.1")),
        "chat_template_kwargs": {"enable_thinking": thinking, "preserve_thinking": False},
    }
    if thinking:
        payload["top_p"] = float(os.environ.get("TOP_P", "0.95"))
        payload["reasoning_effort"] = os.environ.get("REASONING_EFFORT", "medium")
    return payload


def _assemble_stream(resp: httpx.Response) -> dict:
    content: list[str] = []
    reasoning: list[str] = []
    finish_reason = ""
    usage: dict[str, Any] = {}
    for line in resp.iter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                content.append(piece)
            for key in ("reasoning_content", "reasoning"):
                r = delta.get(key)
                if isinstance(r, str) and r:
                    reasoning.append(r)
                    break
    return {
        "choices": [{
            "finish_reason": finish_reason,
            "message": {
                "content": "".join(content),
                "reasoning_content": "".join(reasoning),
            },
        }],
        "usage": usage,
    }


def _post_chat(payload: dict) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream", **auth_headers()}
    timeout = httpx.Timeout(float(os.environ.get("HTTP_TIMEOUT_S", "3600")), connect=60.0)
    retries = max(1, int(os.environ.get("HTTP_RETRIES", "6")))
    url = os.environ["LLM_API_URL"].rstrip("/")
    last_err = ""
    with httpx.Client(timeout=timeout) as client:
        for attempt in range(1, retries + 1):
            with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (resp.read() or b"").decode("utf-8", errors="replace")[:800]
                    last_err = f"HTTP {resp.status_code}: {body}"
                    if resp.status_code not in {408, 429, 500, 502, 503, 504} or attempt == retries:
                        raise RuntimeError(last_err)
                else:
                    data = _assemble_stream(resp)
                    content = data["choices"][0]["message"].get("content") or ""
                    if content.strip() or attempt == retries:
                        return data
                    last_err = "empty content after stream"
                    print(f"Incomplete stream; retrying {attempt}/{retries}…", file=sys.stderr)
            time.sleep(min(90, 15 * attempt))
    raise RuntimeError(last_err or "chat request failed")


def _parse_json(text: str) -> dict:
    content = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
        raise RuntimeError(f"Invalid model JSON: {text[:400]!r}") from None


def screen(paper: Path, message: str = "") -> tuple[dict, dict, dict]:
    paper_text, paper_images, pages = extract_pdf(paper)
    reg_text, reg_label = load_regulation()

    pictures = sum(1 for *_, k in paper_images if k == "picture")
    tables = sum(1 for *_, k in paper_images if k == "table")
    stats = {
        "paper_pages": pages,
        "paper_images": len(paper_images),
        "paper_images_picture": pictures,
        "paper_images_table": tables,
        "paper_text_chars": len(paper_text),
        "regulation_text_chars": len(reg_text),
    }

    data = _post_chat(build_payload(paper, paper_text, paper_images, reg_text, reg_label, message))
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    reasoning = ""
    for key in ("reasoning_content", "reasoning"):
        if isinstance(msg.get(key), str) and msg[key].strip():
            reasoning = msg[key].strip()
            break
    if not content.strip() and reasoning:
        start, end = reasoning.find("{"), reasoning.rfind("}")
        if start >= 0 and end > start:
            content = reasoning[start : end + 1]

    usage_raw = data.get("usage") or {}
    usage = {
        "input_tokens": usage_raw.get("prompt_tokens", usage_raw.get("input_tokens", "?")),
        "output_tokens": usage_raw.get("completion_tokens", usage_raw.get("output_tokens", "?")),
        "total_tokens": usage_raw.get("total_tokens", "?"),
    }
    finish = str(data["choices"][0].get("finish_reason") or "")
    REASONING_DIR.mkdir(parents=True, exist_ok=True)
    sidecar = REASONING_DIR / f"{paper.stem}.txt"
    sidecar.write_text(
        f"paper: {paper.name}\nmodel: {os.environ.get('LLM_MODEL', '')}\n"
        f"api: {os.environ.get('LLM_API_URL', '')}\n"
        f"input_tokens: {usage['input_tokens']}\noutput_tokens: {usage['output_tokens']}\n"
        f"finish_reason: {finish or '?'}\n\n{reasoning or '(no reasoning)'}\n",
        encoding="utf-8",
    )
    stats |= {"reasoning_path": str(sidecar), "reasoning_chars": len(reasoning)}
    return _parse_json(content), usage, stats


def format_output(result: dict, usage: dict, stats: dict) -> str:
    lines = [result["verdict"].upper(), "", result.get("summary", "")]
    for m in result.get("matches", []):
        lines.append(f"{m['control_number']} - {m['name']} ({m['reason']}) ({m['location']})")
    lines += [
        "",
        f"IMAGES: paper={stats['paper_images']} "
        f"(figures={stats['paper_images_picture']}, tables={stats['paper_images_table']})",
        "",
        f"USAGE: input_tokens={usage['input_tokens']} "
        f"output_tokens={usage['output_tokens']} total_tokens={usage['total_tokens']}",
        "",
        f"REASONING: {stats['reasoning_path']} ({stats['reasoning_chars']:,} chars)",
    ]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("paper", type=Path)
    p.add_argument("-m", "--message", default="")
    p.add_argument("--env", type=Path, default=ROOT / ".env")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    load_dotenv(args.env)
    result, usage, stats = screen(args.paper, args.message)
    if args.json:
        print(json.dumps({"result": result, "usage": usage, "extraction": stats}, indent=2, ensure_ascii=False))
    else:
        print(format_output(result, usage, stats))


if __name__ == "__main__":
    main()
