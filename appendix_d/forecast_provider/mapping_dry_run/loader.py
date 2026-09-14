"""pathを外へ出さずに入力CSVとmappingを検証する。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePath

from ..ingestion.processor import detect_encoding
from ..normalization.contracts import ColumnMapping
from ..normalization.domain import make_mapping
from .contracts import DryRunLimits, InputFailure


@dataclass(frozen=True)
class SourceInput:
    data: bytes
    size_bytes: int
    sha256: str
    encoding: str


def _relative_source(input_root: Path, relative_source: str) -> Path:
    untrusted = PurePath(relative_source)
    if untrusted.is_absolute() or not untrusted.parts or ".." in untrusted.parts:
        raise InputFailure("SOURCE_PATH_SAFE")
    root = input_root.resolve()
    candidate = root
    for part in untrusted.parts:
        candidate /= part
        if candidate.is_symlink():
            raise InputFailure("SOURCE_PATH_SAFE")
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise InputFailure("SOURCE_PATH_SAFE") from exc
    if root not in resolved.parents or not resolved.is_file():
        raise InputFailure("SOURCE_PATH_SAFE")
    return resolved


def load_source(input_root: Path, relative_source: str, limits: DryRunLimits) -> SourceInput:
    source = _relative_source(input_root, relative_source)
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise InputFailure("SOURCE_PATH_SAFE") from exc
    if not 0 < size <= limits.max_source_bytes:
        raise InputFailure("SOURCE_SIZE_LIMIT")
    try:
        with source.open("rb") as stream:
            data = stream.read(limits.max_source_bytes + 1)
    except OSError as exc:
        raise InputFailure("SOURCE_PATH_SAFE") from exc
    if not data or len(data) > limits.max_source_bytes:
        raise InputFailure("SOURCE_SIZE_LIMIT")
    encoding, error = detect_encoding(data)
    if error or encoding is None:
        raise InputFailure("SOURCE_ENCODING")
    return SourceInput(data, len(data), hashlib.sha256(data).hexdigest(), encoding)


def load_mapping(mapping_file: Path, limits: DryRunLimits):
    try:
        if mapping_file.is_symlink() or not mapping_file.is_file():
            raise InputFailure("MAPPING_CONTRACT")
        size = mapping_file.stat().st_size
        if not 0 < size <= limits.max_mapping_bytes:
            raise InputFailure("MAPPING_CONTRACT")
        value = json.loads(mapping_file.read_text(encoding="utf-8", errors="strict"))
        if not isinstance(value, dict):
            raise ValueError
        return make_mapping(value)
    except InputFailure:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InputFailure("MAPPING_CONTRACT") from exc


def validate_mapping(mapping: ColumnMapping) -> ColumnMapping:
    """台帳から読んだ不変mappingを同じcontractで再検証する。"""
    try:
        validated = make_mapping(mapping.definition)
        if validated != mapping:
            raise ValueError
        return validated
    except ValueError as exc:
        raise InputFailure("MAPPING_CONTRACT") from exc
