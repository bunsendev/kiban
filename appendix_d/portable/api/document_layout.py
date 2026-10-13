"""Bounded raster views of a page; never change or replace original bytes."""

import hashlib
import io

from .document_ai import DocumentError


def views(raw):
    import pypdfium2 as pdfium
    from PIL import Image

    try:
        if raw.startswith(b"%PDF-"):
            pdf = pdfium.PdfDocument(raw)
            try:
                if len(pdf) != 1:
                    raise DocumentError("左右2表の読取は1ページずつ実行してください")
                page = pdf[0]
                try:
                    width, height = page.get_size()
                    bitmap = page.render(scale=min(3.0, 3600 / max(width, height)))
                    try:
                        image = bitmap.to_pil().convert("RGB")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                pdf.close()
        else:
            # Inspect dimensions before decoding a potentially oversized image.
            with Image.open(io.BytesIO(raw)) as source:
                if source.width * source.height > 40_000_000:
                    raise DocumentError("画像が大きすぎます。4000万画素以内で確認してください")
                from PIL import ImageOps

                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((3600, 3600))
        width, height = image.size
        if width < 200 or height < 200:
            raise DocumentError("画像が小さすぎます。原本を書き出し直してください")
        overview = image.copy()
        overview.thumbnail((1000, 1000))
        crops = [
            ("overview", overview),
            ("left", image.crop((0, 0, int(width * 0.55), height))),
            ("right", image.crop((int(width * 0.45), 0, width, height))),
        ]
        result = []
        for name, crop in crops:
            stream = io.BytesIO()
            crop.save(stream, "JPEG", quality=95)
            data = stream.getvalue()
            if len(data) > 4 * 1024 * 1024:
                raise DocumentError("読取用画像が大きすぎます。原本を分割してください")
            result.append({"name": name, "data": data, "sha256": hashlib.sha256(data).hexdigest()})
        return result
    except DocumentError:
        raise
    except Exception:
        raise DocumentError(
            "読取用の画像を作れません。原本の形式・大きさを確認してください"
        ) from None
