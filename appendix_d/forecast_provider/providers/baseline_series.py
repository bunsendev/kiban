"""旧import pathを保つ日次Series codecの互換module。"""

from .series_codec import decode_series, decode_series_map, encode_series, encode_series_map

__all__ = ["decode_series", "decode_series_map", "encode_series", "encode_series_map"]
