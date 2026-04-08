"""Standalone markdown parser (lifted from src.ingestion.obsidian.parser).

Stripped of project imports so it runs inside the shared mcp image.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

OVERSIZED_CHUNK_CHARS = 8000

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_WIKILINK_RE = re.compile(r"(!?)\[\[([^\]]+)\]\]")
_MD_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)]+)\)")
_INLINE_TAG_RE = re.compile(r"(?<![\w/])#([A-Za-z][\w/-]*)")

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
_PDF_EXTS = {".pdf"}
_AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".ogg"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}


def _attachment_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _PDF_EXTS:
        return "pdf"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _VIDEO_EXTS:
        return "video"
    return "other"


@dataclass
class Chunk:
    index: int
    heading: str
    heading_path: list[str]
    content: str
    content_hash: str
    links: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @property
    def is_oversized(self) -> bool:
        return len(self.content) > OVERSIZED_CHUNK_CHARS


@dataclass
class ParsedNote:
    vault_path: str
    absolute_path: str
    frontmatter: dict[str, Any]
    chunks: list[Chunk]
    file_mtime: float


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            raw = "".join(lines[1:i])
            body = "".join(lines[i + 1 :])
            try:
                data = yaml.safe_load(raw) or {}
                if not isinstance(data, dict):
                    data = {}
                return data, body
            except Exception as exc:
                logger.warning("Malformed frontmatter, skipping: %s", exc)
                return {}, body
    return {}, text


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_links_and_attachments(
    text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    links: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []
    for match in _WIKILINK_RE.finditer(text):
        is_embed = match.group(1) == "!"
        target_raw = match.group(2)
        target = target_raw.split("|", 1)[0].split("#", 1)[0].strip()
        if not target:
            continue
        if is_embed:
            attachments.append({"path": target, "type": _attachment_type(target), "alt": ""})
        else:
            links.append({"type": "wikilink", "target": target})
    for match in _MD_LINK_RE.finditer(text):
        is_embed = match.group(1) == "!"
        alt = match.group(2)
        target = match.group(3).split(" ", 1)[0]
        if not target:
            continue
        if is_embed:
            attachments.append({"path": target, "type": _attachment_type(target), "alt": alt})
        else:
            links.append({"type": "markdown", "target": target, "text": alt})
    return links, attachments


def _extract_inline_tags(text: str) -> list[str]:
    return sorted({m.group(1) for m in _INLINE_TAG_RE.finditer(text)})


def _chunk_from_section(
    index: int,
    heading: str,
    heading_path: list[str],
    content: str,
    frontmatter_tags: list[str],
) -> Chunk:
    content = content.strip("\n")
    links, attachments = _extract_links_and_attachments(content)
    tags = sorted(set(frontmatter_tags) | set(_extract_inline_tags(content)))
    chunk = Chunk(
        index=index,
        heading=heading,
        heading_path=heading_path,
        content=content,
        content_hash=_sha256(content),
        links=links,
        attachments=attachments,
        tags=tags,
    )
    if chunk.is_oversized:
        logger.warning("Oversized chunk (%d chars) idx=%d heading=%r", len(content), index, heading)
    return chunk


def _split_into_chunks(body: str, frontmatter_tags: list[str]) -> list[Chunk]:
    lines = body.splitlines(keepends=True)
    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []
    current_heading: str = "_preamble"
    current_path: list[str] = []
    buf: list[str] = []

    def flush():
        nonlocal buf
        content = "".join(buf)
        if content.strip() or chunks:
            if current_heading == "_preamble" and not content.strip():
                buf = []
                return
            chunks.append(
                _chunk_from_section(
                    index=len(chunks),
                    heading=current_heading,
                    heading_path=list(current_path),
                    content=content,
                    frontmatter_tags=frontmatter_tags,
                )
            )
        buf = []

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            text = m.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, text))
            current_heading = text
            current_path = [h for _, h in heading_stack]
            buf.append(line)
        else:
            buf.append(line)

    flush()

    if not chunks:
        content = body.strip("\n")
        chunks.append(
            _chunk_from_section(
                index=0,
                heading="_preamble",
                heading_path=[],
                content=content,
                frontmatter_tags=frontmatter_tags,
            )
        )
    return chunks


def parse_note(path: Path, vault_root: Path) -> ParsedNote:
    abs_path = path.resolve()
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)

    fm_tags_raw = frontmatter.get("tags", []) if isinstance(frontmatter, dict) else []
    if isinstance(fm_tags_raw, str):
        fm_tags: list[str] = [fm_tags_raw]
    elif isinstance(fm_tags_raw, list):
        fm_tags = [str(t) for t in fm_tags_raw]
    else:
        fm_tags = []

    chunks = _split_into_chunks(body, fm_tags)

    try:
        vault_path = str(abs_path.relative_to(vault_root.resolve()))
    except ValueError:
        vault_path = str(abs_path)

    return ParsedNote(
        vault_path=vault_path,
        absolute_path=str(abs_path),
        frontmatter=frontmatter,
        chunks=chunks,
        file_mtime=abs_path.stat().st_mtime,
    )
