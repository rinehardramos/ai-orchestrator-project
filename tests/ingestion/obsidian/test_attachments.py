from pathlib import Path

from src.ingestion.obsidian.attachments import AttachmentRegistry, default_registry


def test_unknown_extension_returns_none(tmp_path: Path):
    reg = AttachmentRegistry()
    p = tmp_path / "file.xyz"
    p.write_text("hi")
    assert reg.process(p) is None


def test_callable_processor_registered(tmp_path: Path):
    reg = AttachmentRegistry()
    reg.register(".txt", lambda path: f"processed:{path.name}")
    p = tmp_path / "a.txt"
    p.write_text("x")
    assert reg.process(p) == "processed:a.txt"


def test_raising_processor_degrades_to_none(tmp_path: Path):
    reg = AttachmentRegistry()

    def boom(path):
        raise RuntimeError("nope")

    reg.register(".foo", boom)
    p = tmp_path / "a.foo"
    p.write_text("x")
    assert reg.process(p) is None


def test_default_registry_registers_pdf():
    reg = default_registry()
    assert ".pdf" in reg.registered_extensions()


def test_extension_normalization():
    reg = AttachmentRegistry()
    reg.register("txt", lambda p: "ok")  # no dot
    assert reg.get(".txt") is not None
    assert reg.get("TXT") is not None
