"""Chunk document text for embedding."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    document_id: str
    filename: str
    chunk_index: int
    content: str


def chunk_text(
    text: str,
    *,
    document_id: str,
    filename: str,
    chunk_size: int = 800,
    overlap: int = 100,
) -> list[TextChunk]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if chunk_size < 100:
        chunk_size = 100
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 5)

    chunks: list[TextChunk] = []
    start = 0
    index = 0
    length = len(cleaned)
    while start < length:
        end = min(start + chunk_size, length)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(
                TextChunk(
                    document_id=document_id,
                    filename=filename,
                    chunk_index=index,
                    content=piece,
                )
            )
            index += 1
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks
