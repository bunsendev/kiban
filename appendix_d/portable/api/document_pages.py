"""Bounded PDF page adapter. Original bytes remain unchanged in the intake store."""

import io

from pypdf import PdfReader, PdfWriter

from .document_ai import DocumentError


def pdf_reader(raw):
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
            raise ValueError()
        return reader
    except Exception:
        raise DocumentError(
            "PDFを開けません。暗号化なし・100ページ以内で確認してください"
        ) from None


def page_source(raw, number):
    reader = pdf_reader(raw)
    if type(number) is not int or not 1 <= number <= len(reader.pages):
        raise DocumentError("原本のページ番号を確認してください")
    page = reader.pages[number - 1]
    # Limit content expansion before text extraction; images are not decoded here.
    content = page.get_contents()
    if content is not None and len(content.get_data()) > 5 * 1024 * 1024:
        raise DocumentError("ページの構造が大きすぎます。PDFを書き出し直してください")
    try:
        text = (page.extract_text(extraction_mode="layout") or "") if content is not None else ""
    except Exception:
        raise DocumentError("PDFの文字層を解析できません。PDFを書き出し直してください") from None
    if len(text) > 40000:
        raise DocumentError("ページの文字数が多すぎます。分割してください")
    writer = PdfWriter()
    writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue(), text, len(reader.pages)
