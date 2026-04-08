"""Pluggable attachment processor registry.

Each processor takes a filesystem path and returns an optional string of
extracted text to embed. Unknown extensions and raising processors are
handled gracefully (returns ``None``).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class AttachmentProcessor(Protocol):
    def process(self, path: Path) -> Optional[str]: ...


class _CallableProcessor:
    """Adapter that wraps a plain callable into an AttachmentProcessor."""

    def __init__(self, fn: Callable[[Path], Optional[str]]):
        self._fn = fn

    def process(self, path: Path) -> Optional[str]:
        return self._fn(path)


class AttachmentRegistry:
    def __init__(self) -> None:
        self._processors: dict[str, AttachmentProcessor] = {}

    def register(
        self,
        ext: str,
        processor: AttachmentProcessor | Callable[[Path], Optional[str]],
    ) -> None:
        ext = ext.lower()
        if not ext.startswith("."):
            ext = "." + ext
        if not isinstance(processor, AttachmentProcessor):
            processor = _CallableProcessor(processor)  # type: ignore[arg-type]
        self._processors[ext] = processor

    def get(self, ext: str) -> AttachmentProcessor | None:
        ext = ext.lower()
        if not ext.startswith("."):
            ext = "." + ext
        return self._processors.get(ext)

    def process(self, path: Path) -> Optional[str]:
        ext = os.path.splitext(str(path))[1].lower()
        proc = self._processors.get(ext)
        if proc is None:
            return None
        try:
            return proc.process(path)
        except Exception as exc:  # pragma: no cover - logged degraded path
            logger.warning("Attachment processor failed for %s: %s", path, exc)
            return None

    def registered_extensions(self) -> list[str]:
        return sorted(self._processors.keys())


class PdfAttachmentProcessor:
    """Extract text from a PDF using the existing document_processor if available."""

    def __init__(self) -> None:
        self._impl = None
        try:
            from src.shared import document_processor  # noqa: WPS433

            self._impl = document_processor
        except Exception as exc:  # pragma: no cover - optional dep
            logger.info("PDF processor unavailable: %s", exc)

    def process(self, path: Path) -> Optional[str]:
        if self._impl is None:
            return None
        fn = getattr(self._impl, "extract_text", None) or getattr(
            self._impl, "extract_pdf_text", None
        )
        if fn is None:
            return None
        return fn(str(path))


def default_registry() -> AttachmentRegistry:
    """Return a registry with the default processors wired in.

    v1: PDF enabled if ``src/shared/document_processor.py`` exposes a text
    extractor. Audio/video/image-caption are deliberately not registered and
    are left as reference-only data in the payload.
    """
    reg = AttachmentRegistry()
    reg.register(".pdf", PdfAttachmentProcessor())
    return reg
