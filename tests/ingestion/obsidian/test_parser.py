from __future__ import annotations

from pathlib import Path

from src.ingestion.obsidian.parser import (
    OVERSIZED_CHUNK_CHARS,
    _split_frontmatter,
    parse_note,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_frontmatter_parses_tags(tmp_path: Path):
    f = _write(
        tmp_path / "a.md",
        "---\ntags: [x, y]\n---\n\n# H\n\nbody\n",
    )
    note = parse_note(f, tmp_path)
    assert note.frontmatter == {"tags": ["x", "y"]}
    assert any("x" in c.tags for c in note.chunks)


def test_no_frontmatter(tmp_path: Path):
    f = _write(tmp_path / "a.md", "# H\n\nbody\n")
    note = parse_note(f, tmp_path)
    assert note.frontmatter == {}


def test_malformed_frontmatter_degrades(tmp_path: Path):
    data, body = _split_frontmatter("---\n: bad: yaml:\n---\nbody\n")
    assert body.strip() == "body"


def test_heading_split_with_preamble(tmp_path: Path):
    content = "intro paragraph\n\n# Section A\n\naaa\n\n## Sub\n\nbbb\n\n# Section B\n\nccc\n"
    f = _write(tmp_path / "n.md", content)
    note = parse_note(f, tmp_path)
    headings = [c.heading for c in note.chunks]
    assert headings == ["_preamble", "Section A", "Sub", "Section B"]


def test_heading_path_is_built(tmp_path: Path):
    content = "# A\ntop\n## B\nmid\n### C\nleaf\n# D\nnext\n"
    note = parse_note(_write(tmp_path / "n.md", content), tmp_path)
    paths = [tuple(c.heading_path) for c in note.chunks]
    assert ("A",) in paths
    assert ("A", "B") in paths
    assert ("A", "B", "C") in paths
    assert ("D",) in paths


def test_no_headings_single_chunk(tmp_path: Path):
    f = _write(tmp_path / "n.md", "just one line\nand another")
    note = parse_note(f, tmp_path)
    assert len(note.chunks) == 1
    assert note.chunks[0].heading == "_preamble"


def test_wikilinks_and_attachments(tmp_path: Path):
    content = (
        "# H\n\n"
        "See [[Other Note]] and [[Piped|Alias]] and [[Anchor#sub]].\n"
        "Embed image ![[diagram.png]] and ![alt](path/to/pic.jpg).\n"
        "Markdown link [text](https://example.com).\n"
    )
    note = parse_note(_write(tmp_path / "n.md", content), tmp_path)
    chunk = note.chunks[0]
    targets = [l["target"] for l in chunk.links]
    assert "Other Note" in targets
    assert "Piped" in targets
    assert "Anchor" in targets
    assert "https://example.com" in targets
    att_paths = [a["path"] for a in chunk.attachments]
    assert "diagram.png" in att_paths
    assert "path/to/pic.jpg" in att_paths
    types = {a["type"] for a in chunk.attachments}
    assert "image" in types


def test_inline_tags_extracted(tmp_path: Path):
    note = parse_note(
        _write(tmp_path / "n.md", "# H\n\nbody with #alpha and #beta/nested\n"),
        tmp_path,
    )
    tags = note.chunks[0].tags
    assert "alpha" in tags
    assert "beta/nested" in tags


def test_oversized_chunk_still_returned(tmp_path: Path, caplog):
    big = "x" * (OVERSIZED_CHUNK_CHARS + 100)
    note = parse_note(_write(tmp_path / "n.md", f"# H\n\n{big}\n"), tmp_path)
    assert note.chunks[0].is_oversized
    assert len(note.chunks) == 1


def test_chunks_are_hashed(tmp_path: Path):
    note = parse_note(_write(tmp_path / "n.md", "# H\n\nbody\n"), tmp_path)
    assert note.chunks[0].content_hash.startswith("sha256:")
