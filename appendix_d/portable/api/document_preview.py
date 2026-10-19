"""Bounded page preview; no source replacement or invented row coordinates."""

import io

from .document_ai import DocumentError


def page_preview(raw, number):
    import pypdfium2 as pdfium

    try:
        with pdfium.PdfDocument(raw) as pdf:
            if type(number) is not int or not 1 <= number <= min(len(pdf), 100):
                raise DocumentError("原本ページを確認してください")
            page = pdf[number - 1]
            try:
                width, height = page.get_size()
                bitmap = page.render(scale=min(2.0, 1600 / max(width, height)))
                try:
                    image = bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
            finally:
                page.close()
        out = io.BytesIO()
        image.save(out, "JPEG", quality=90)
        return out.getvalue()
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("原本プレビューを生成できません") from None
