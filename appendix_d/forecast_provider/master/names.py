"""規格数字を残す決定論的な商品名比較。"""

import re
import unicodedata
from difflib import SequenceMatcher


def normalize_product_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def name_similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None, normalize_product_name(left), normalize_product_name(right)
    ).ratio()
