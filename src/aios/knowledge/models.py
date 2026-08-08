"""Knowledge data models — domain, not database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SourceType = Literal[
    "skill",
    "documentation",
    "adr",
    "code",
    "research",
    "memory",
    "project_dna",
]

VALID_SOURCE_TYPES: tuple[str, ...] = (
    "skill",
    "documentation",
    "adr",
    "code",
    "research",
    "memory",
    "project_dna",
)


class KnowledgeError(Exception):
    """Domain error for knowledge storage failures."""


@dataclass
class KnowledgeSource:
    source_id: str = ""
    type: SourceType = "skill"
    path: str = ""
    hash: str = ""
    version: str = "1"
    metadata_json: dict = field(default_factory=dict)
    indexed_at: str = ""
    status: str = "active"

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "type": self.type,
            "path": self.path,
            "hash": self.hash,
            "version": self.version,
            "metadata_json": self.metadata_json,
            "indexed_at": self.indexed_at,
            "status": self.status,
        }


@dataclass
class KnowledgeDocument:
    document_id: str = ""
    source_id: str = ""
    title: str = ""
    path: str = ""
    content: str = ""
    type: SourceType = "documentation"
    version: str = "1"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "source_id": self.source_id,
            "title": self.title,
            "path": self.path,
            "type": self.type,
            "version": self.version,
            "metadata": self.metadata,
        }


@dataclass
class KnowledgeChunk:
    chunk_id: str = ""
    source_id: str = ""
    document_id: str = ""
    content: str = ""
    metadata: dict = field(default_factory=dict)
    content_hash: str = ""
    position: int = 0
    token_estimate: int = 0
    embedding: list[float] | None = None

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "document_id": self.document_id,
            "content": self.content,
            "metadata": self.metadata,
            "content_hash": self.content_hash,
            "position": self.position,
            "token_estimate": self.token_estimate,
        }


@dataclass
class KnowledgeQuery:
    text: str = ""
    limit: int = 20
    source_types: list[str] | None = None


@dataclass
class KnowledgeResult:
    chunk_id: str = ""
    source_id: str = ""
    source_type: str = ""
    source_path: str = ""
    document_id: str = ""
    content: str = ""
    position: int = 0
    content_hash: str = ""
    token_estimate: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "document_id": self.document_id,
            "content": self.content,
            "position": self.position,
            "content_hash": self.content_hash,
            "token_estimate": self.token_estimate,
            "metadata": self.metadata,
        }


@dataclass
class IndexSummary:
    run_id: str = ""
    scanned: int = 0
    skipped: int = 0
    reindexed: int = 0
    chunks_created: int = 0
    chunks_deleted: int = 0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "scanned": self.scanned,
            "skipped": self.skipped,
            "reindexed": self.reindexed,
            "chunks_created": self.chunks_created,
            "chunks_deleted": self.chunks_deleted,
        }
