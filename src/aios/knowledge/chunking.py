"""Deterministic chunking and hashing — pure functions, no side effects."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

_MAX_CHUNK_CHARS = 4096
_OVERLAP_CHARS = 200
_MAX_BLANK_RUN = 2

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)
_SYMBOL_RE = re.compile(r"^(class |def |async def )", re.MULTILINE)


def normalize_content(text: str) -> str:
    return _collapse_blank_lines(
        "\n".join(
            line.rstrip().replace("\r\n", "\n").replace("\r", "\n") for line in text.splitlines()
        )
    )


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_content(text).encode("utf-8")).hexdigest()


def token_estimate(text: str) -> int:
    return len(text.split())


def deterministic_chunk_id(source_id: str, position: int) -> str:
    raw = f"{source_id}:{position}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def chunk_text(
    content: str,
    *,
    source_type: Literal[
        "skill", "documentation", "adr", "code", "research", "memory", "project_dna"
    ],
    source_id: str = "",
    doc_metadata: dict | None = None,
) -> list[dict]:
    raw = _chunk_code(content) if source_type == "code" else _chunk_markdown(content)

    meta = dict(doc_metadata or {})
    result: list[dict] = []
    for pos, chunk_content in enumerate(raw):
        norm = normalize_content(chunk_content)
        result.append(
            {
                "chunk_id": deterministic_chunk_id(source_id, pos),
                "content": norm,
                "content_hash": hashlib.sha256(norm.encode("utf-8")).hexdigest(),
                "position": pos,
                "token_estimate": token_estimate(norm),
                "metadata": {
                    **meta,
                    "position": pos,
                },
            }
        )
    return result


# ---------------------------------------------------------------------------
# Markdown chunking — split on headings, fallback to size-based with overlap
# ---------------------------------------------------------------------------


def _chunk_markdown(text: str) -> list[str]:
    headings = list(_HEADING_RE.finditer(text))
    if not headings:
        return _chunk_by_size(text, _MAX_CHUNK_CHARS, _OVERLAP_CHARS)

    chunks: list[str] = []

    if headings[0].start() > 0:
        preamble = text[: headings[0].start()].strip()
        if preamble:
            chunks.extend(_chunk_by_size(preamble, _MAX_CHUNK_CHARS, _OVERLAP_CHARS))

    for i, match in enumerate(headings):
        start = match.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section = text[start:end].strip()
        if len(section) > _MAX_CHUNK_CHARS:
            chunks.append(match.group(0).strip())
            body = text[start + len(match.group(0)) : end].strip()
            chunks.extend(_chunk_by_size(body, _MAX_CHUNK_CHARS, _OVERLAP_CHARS))
        else:
            chunks.append(section)

    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Code chunking — split on top-level symbols, fallback to size-based
# ---------------------------------------------------------------------------


def _chunk_code(text: str) -> list[str]:
    symbols = list(_SYMBOL_RE.finditer(text))
    if not symbols:
        return _chunk_by_size(text, _MAX_CHUNK_CHARS, _OVERLAP_CHARS)

    chunks: list[str] = []

    if symbols[0].start() > 0:
        preamble = text[: symbols[0].start()].strip()
        if preamble:
            chunks.append(preamble)

    for i, match in enumerate(symbols):
        start = match.start()
        end = symbols[i + 1].start() if i + 1 < len(symbols) else len(text)
        section = text[start:end].strip()
        if len(section) > _MAX_CHUNK_CHARS:
            chunks.append(match.group(0).strip())
            body = text[start + len(match.group(0)) : end].strip()
            chunks.extend(_chunk_by_size(body, _MAX_CHUNK_CHARS, _OVERLAP_CHARS))
        else:
            chunks.append(section)

    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Size-based fallback with overlap
# ---------------------------------------------------------------------------


def _chunk_by_size(text: str, max_chars: int, overlap: int) -> list[str]:
    if not text or not text.strip():
        return []
    if len(text) <= max_chars:
        return [text.strip()]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))

        if end < len(text):
            find_from = max(start, end - overlap)
            found = text.rfind("\n\n", find_from, end)
            if found == -1:
                found = text.rfind("\n", find_from, end)
            if found == -1:
                found = text.rfind(". ", find_from, end)
            if found > start:
                end = found + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if end < len(text) else end

    return chunks


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _collapse_blank_lines(text: str) -> str:
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    out: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= _MAX_BLANK_RUN:
                out.append(line)
        else:
            blank_run = 0
            out.append(line)
    while out and out[0] == "":
        out.pop(0)
    return "\n".join(out)
