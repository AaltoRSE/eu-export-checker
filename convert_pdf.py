"""Utility module for converting a PDF into extracted text and image files.

Usage from Python:
    from document_conversion_service import convert_pdf_to_files
    output = convert_pdf_to_files("paper.pdf", "./out")

CLI:
    python document_conversion_service.py paper.pdf ./out
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.io import DocumentStream


@dataclass(frozen=True)
class ConversionOutput:
    """Paths and metadata produced by a PDF conversion run."""

    source_pdf: Path
    output_dir: Path
    text_file: Path
    images_dir: Path
    image_files: list[Path]
    tables_file: Path | None
    manifest_file: Path


class ConversionService:
    """Convert a PDF to markdown text and extracted images on disk."""

    def __init__(self) -> None:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_picture_images = True
        pipeline_options.do_table_structure = True
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

    def convert_pdf(
        self,
        pdf_path: str | Path,
        output_dir: str | Path,
        *,
        text_filename: str = "document.md",
        images_subdir: str = "images",
        tables_filename: str = "tables.md",
        manifest_filename: str = "conversion_manifest.json",
    ) -> ConversionOutput:
        """Convert ``pdf_path`` and write outputs under ``output_dir``.

        The conversion writes:
        - markdown full text
        - one image file per detected picture
        - optional markdown table dump when tables are detected
        - a JSON manifest with metadata and file paths
        """

        source_pdf = Path(pdf_path).expanduser().resolve()
        if not source_pdf.exists() or not source_pdf.is_file():
            raise FileNotFoundError(f"PDF not found: {source_pdf}")
        if source_pdf.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a .pdf file, got: {source_pdf.name}")

        target_dir = Path(output_dir).expanduser().resolve()
        images_dir = target_dir / images_subdir
        text_file = target_dir / text_filename
        tables_file = target_dir / tables_filename
        manifest_file = target_dir / manifest_filename

        target_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        source_data = DocumentStream(
            name=source_pdf.name,
            stream=BytesIO(source_pdf.read_bytes()),
        )
        result = self.converter.convert(source_data)
        document = result.document

        text_content = document.export_to_markdown(page_break_placeholder="\f")
        text_file.write_text(text_content, encoding="utf-8")

        image_files: list[Path] = []
        image_records: list[dict[str, Any]] = []
        for idx, picture in enumerate(document.pictures, start=1):
            image = picture.get_image(document)
            if image is None:
                continue

            page_no = 0
            if picture.prov:
                page_no = getattr(picture.prov[0], "page_no", 0) or 0

            caption = picture.caption_text(document)
            image_name = f"page_{page_no:04d}_image_{idx:03d}.png"
            image_path = images_dir / image_name
            image.save(image_path)

            image_files.append(image_path)
            image_records.append(
                {
                    "index": idx,
                    "page": page_no,
                    "caption": caption,
                    "file": str(image_path),
                }
            )

        tables_written = False
        table_sections: list[str] = []
        for idx, table in enumerate(document.tables, start=1):
            page_no = 0
            if table.prov:
                page_no = getattr(table.prov[0], "page_no", 0) or 0

            caption = table.caption_text(document)
            try:
                table_md = table.export_to_dataframe(document).to_markdown(index=False)
            except Exception:
                # Keep conversion resilient if dataframe export is unavailable.
                try:
                    table_md = table.export_to_markdown()
                except Exception:
                    table_md = "[table content could not be exported in this environment]"

            table_sections.append(f"## Table {idx} (page {page_no})")
            if caption:
                table_sections.append(f"Caption: {caption}")
            table_sections.append("")
            table_sections.append(table_md)
            table_sections.append("")

        if table_sections:
            tables_file.write_text("\n".join(table_sections), encoding="utf-8")
            tables_written = True

        manifest = {
            "source_pdf": str(source_pdf),
            "text_file": str(text_file),
            "images_dir": str(images_dir),
            "images": image_records,
            "tables_file": str(tables_file) if tables_written else None,
            "counts": {
                "images": len(image_files),
                "tables": len(document.tables),
            },
        }
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return ConversionOutput(
            source_pdf=source_pdf,
            output_dir=target_dir,
            text_file=text_file,
            images_dir=images_dir,
            image_files=image_files,
            tables_file=tables_file if tables_written else None,
            manifest_file=manifest_file,
        )


def convert_pdf_to_files(pdf_path: str | Path, output_dir: str | Path) -> ConversionOutput:
    """Convenience wrapper for one-shot PDF conversion."""

    return ConversionService().convert_pdf(pdf_path, output_dir)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a PDF into markdown text and extracted image files"
    )
    parser.add_argument("pdf", type=Path, help="Path to input PDF")
    parser.add_argument("output_dir", type=Path, help="Directory where outputs are written")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    output = convert_pdf_to_files(args.pdf, args.output_dir)

    print(f"Text written to: {output.text_file}")
    print(f"Images directory: {output.images_dir}")
    print(f"Extracted images: {len(output.image_files)}")
    if output.tables_file:
        print(f"Tables written to: {output.tables_file}")
    print(f"Manifest written to: {output.manifest_file}")


if __name__ == "__main__":
    main()
