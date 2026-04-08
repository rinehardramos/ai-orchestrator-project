# Obsidian Vault Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a reusable Obsidian vault ingestion tool (CLI + Python library + MCP server) that syncs notes into a dedicated Qdrant collection with real-time watch mode, heading-based chunking, hash-based change detection, pluggable attachment processors, and an analyze function.

**Architecture:** Single core `ObsidianVaultIngestor` in `src/ingestion/obsidian/` wrapped by three thin entry points (CLI, Python library import, stdio MCP server). Heading-based markdown chunking with SHA-256 content hashes for incremental sync. Deterministic UUIDv5 point IDs keyed on `(vault_path, chunk_index)`. Dedicated Qdrant collection `obsidian_vault_v1` reusing the existing `KnowledgeBaseClient` embedding pipeline. `watchdog` observer for real-time sync with 500ms debounce and startup reconciliation.

**Tech Stack:** Python 3.12, `watchdog`, `qdrant-client`, existing `KnowledgeBaseClient` / `HybridMemoryStore`, `pytest`, `mcp` SDK (stdio transport).

**Genesis-node note:** The vault lives on the local Genesis machine, so ingestion runs locally as a scoped exception — it is a pure read + HTTP upsert to remote Qdrant, not shell execution. Running application tests remains a worker-side concern; this plan writes tests but does not execute them from the Genesis node.

---

## File Structure

```
src/ingestion/
├── __init__.py
└── obsidian/
    ├── __init__.py           # Exports ObsidianVaultIngestor
    ├── parser.py             # Markdown → frontmatter + heading chunks
    ├── attachments.py        # AttachmentProcessor protocol + registry + built-ins
    ├── ingestor.py           # Core sync / upsert / delete logic
    ├── watcher.py            # watchdog-based real-time sync daemon
    ├── analyzer.py           # analyze_vault + apply_optimization
    ├── cli.py                # `python -m src.ingestion.obsidian`
    └── mcp_server.py         # stdio MCP server

tests/ingestion/obsidian/
├── __init__.py
├── conftest.py               # Shared fixtures (tmp vault, stub embedder)
├── fixtures/vault/           # Hand-crafted fixture notes
├── test_parser.py
├── test_attachments.py
├── test_ingestor.py
├── test_watcher.py
├── test_analyzer.py
└── test_mcp_server.py
```

---

## Task 1: Package skeleton + parser

**Files:**
- Create: `src/ingestion/__init__.py` (empty)
- Create: `src/ingestion/obsidian/__init__.py`
- Create: `src/ingestion/obsidian/parser.py`
- Create: `tests/ingestion/__init__.py`, `tests/ingestion/obsidian/__init__.py`
- Create: `tests/ingestion/obsidian/test_parser.py`

- [ ] Create empty `__init__.py` files for packages.
- [ ] Write `parser.py` with `Chunk` dataclass (`index`, `heading`, `heading_path`, `content`, `content_hash`, `links`, `attachments`, `tags`) and `parse_note(path) -> ParsedNote` returning frontmatter, chunks, file mtime, and vault-relative path.
- [ ] Heading split uses a line-wise scan over ATX headings (`^#{1,6} `). Content before the first heading is chunk 0 with heading `_preamble` if non-empty; files with no headings produce a single whole-file chunk.
- [ ] Extract wikilinks `[[Target]]` / `[[Target|alias]]` / `[[Target#heading]]` and markdown links `[text](path)` into each chunk's `links` list.
- [ ] Extract attachment references `![[file.ext]]` and `![alt](path)` into each chunk's `attachments` list with `{path, type (by extension), alt}`.
- [ ] Extract inline `#tag` tokens + frontmatter `tags` list, flattened into each chunk's `tags`.
- [ ] SHA-256 hash each chunk's content.
- [ ] Warn (logger) when a chunk exceeds 8000 chars but still return it.
- [ ] Write `test_parser.py` covering every bullet above against inline fixture strings.

**Commit:** `feat(obsidian): add markdown parser with heading chunking`

---

## Task 2: Attachment processor registry

**Files:**
- Create: `src/ingestion/obsidian/attachments.py`
- Create: `tests/ingestion/obsidian/test_attachments.py`

- [ ] Define `AttachmentProcessor` Protocol with `process(path: Path) -> Optional[str]`.
- [ ] Define `AttachmentRegistry` with `register(ext, processor)`, `get(ext)`, `process(path)` that dispatches by extension and swallows processor exceptions (logs + returns `None`).
- [ ] Implement `PdfAttachmentProcessor` that wraps `src/shared/document_processor.py` if available, otherwise returns `None` (so the module is importable even if PDF deps are missing).
- [ ] Provide `default_registry()` factory that registers PDF but leaves audio/image-caption/video unregistered.
- [ ] Test: registry returns `None` for unknown extension; registered processor is called; raising processor degrades to `None`.

**Commit:** `feat(obsidian): add pluggable attachment processor registry`

---

## Task 3: Ingestor core

**Files:**
- Create: `src/ingestion/obsidian/ingestor.py`
- Create: `tests/ingestion/obsidian/conftest.py`
- Create: `tests/ingestion/obsidian/test_ingestor.py`

- [ ] `ObsidianVaultIngestor.__init__(vault_path, collection="obsidian_vault_v1", embedder=None, qdrant=None, registry=None)`. If `embedder` is `None`, lazily construct `KnowledgeBaseClient`. If `qdrant` is `None`, use `embedder.store.qdrant`. Registry defaults to `default_registry()`.
- [ ] `_ensure_collection()` creates the collection with the embedder's `_embed_dim` and cosine distance if it doesn't exist.
- [ ] `_point_id(vault_path, chunk_index)` returns `str(uuid.uuid5(NAMESPACE_URL, f"{vault_path}::{chunk_index}"))`.
- [ ] `_fetch_existing(vault_path)` returns `{chunk_index: (point_id, content_hash)}` via Qdrant scroll with a `vault_path` payload filter.
- [ ] `sync_file(path)` — parses the file, computes desired chunks, compares against existing, upserts changed chunks (embedding each new one), deletes chunks whose index is no longer present. Returns a `SyncResult(added, updated, unchanged, deleted)`.
- [ ] `sync_all(full=False)` — walks the vault for `.md` files (honoring ignore globs `.obsidian/**`, `.trash/**`, `**/.DS_Store`), calls `sync_file` for each. When `full=True`, every chunk is re-embedded regardless of hash. After walking, calls `prune_orphans()` to delete points whose `vault_path` no longer exists on disk.
- [ ] `delete_file(vault_path)` deletes every point with that `vault_path`.
- [ ] `prune_orphans()` scrolls the collection grouping by `vault_path` and deletes groups whose source file is gone.
- [ ] `search(query, k=8, filter=None)` embeds the query and runs a Qdrant search, returning a list of `{score, payload}`.
- [ ] `get_note(vault_path)` returns all chunks for a file ordered by `chunk_index`.
- [ ] `conftest.py` provides a `FakeEmbedder` (deterministic hash-to-vector), a `FakeQdrant` in-memory store implementing the narrow slice of methods used, and a `tmp_vault` fixture that copies `fixtures/vault/` into a tmpdir.
- [ ] `test_ingestor.py` covers: full sync, incremental-no-change (zero re-embeds), incremental after edit (only affected chunk re-embedded), section deleted, whole file deleted, file renamed.

**Commit:** `feat(obsidian): add ingestor core with hash-based incremental sync`

---

## Task 4: Real-time watcher

**Files:**
- Create: `src/ingestion/obsidian/watcher.py`
- Create: `tests/ingestion/obsidian/test_watcher.py`

- [ ] `VaultWatcher(ingestor, debounce_ms=500)` wraps a `watchdog.observers.Observer`.
- [ ] `start()` runs `ingestor.sync_all(full=False)` as startup reconciliation, then begins watching.
- [ ] Event handler coalesces events by path into a pending queue with per-path debounce timers; a worker thread pops debounced entries and calls `ingestor.sync_file(path)` for modify/create and `ingestor.delete_file(vault_path)` for delete. Rename events become delete-old + sync-new.
- [ ] Filters out ignored globs.
- [ ] `stop()` cleanly joins the worker and observer.
- [ ] Tests (using a tmp vault, a fake ingestor that records calls, and `time.sleep` windows): debounce coalesces rapid saves, create fires one sync, modify fires one sync, delete fires one delete, rename fires delete+sync, startup reconciliation runs before the watch loop accepts events.

**Commit:** `feat(obsidian): add real-time watcher with debounce and startup reconciliation`

---

## Task 5: Analyzer

**Files:**
- Create: `src/ingestion/obsidian/analyzer.py`
- Create: `tests/ingestion/obsidian/test_analyzer.py`

- [ ] `analyze_vault(ingestor) -> AnalysisReport` — scrolls the collection + walks the vault, returns dataclass with: `note_count`, `chunk_count`, `attachment_counts_by_type`, `chunk_size_stats` (p50/p90/p99/max chars), `notes_without_headings`, `notes_over_50_chunks`, `payload_stats`, `hash_duplicates`, `orphans` (points with missing source), `missing_indexed_files` (files on disk with no points), `hash_mismatches`, `missing_attachments`.
- [ ] `apply_optimization(ingestor, action)` with `action in {"prune", "rechunk", "resync"}`. Unknown actions raise `ValueError`. `prune` deletes orphans. `rechunk` re-ingests flagged files (detected via `chunk_size_stats`) with an alternate hybrid split (heading then 4000-char windows). `resync` forces `sync_file(path)` for hash-mismatch files.
- [ ] Tests use synthetic fixture vaults for each pathology and assert report fields + that `apply_optimization("prune")` removes a known orphan, `apply_optimization("unknown")` raises.

**Commit:** `feat(obsidian): add analyzer with prune/rechunk/resync optimizations`

---

## Task 6: CLI

**Files:**
- Create: `src/ingestion/obsidian/cli.py`

- [ ] `python -m src.ingestion.obsidian sync [--full] [--path PATH]`
- [ ] `python -m src.ingestion.obsidian watch` (alias `daemon`)
- [ ] `python -m src.ingestion.obsidian analyze [--apply {prune,rechunk,resync}]`
- [ ] `python -m src.ingestion.obsidian search QUERY [-k N]`
- [ ] Reads `obsidian.vault_path` from `config/settings.yaml` with `--vault` override. Structured logging.

**Commit:** `feat(obsidian): add CLI entry point`

---

## Task 7: MCP server

**Files:**
- Create: `src/ingestion/obsidian/mcp_server.py`
- Create: `tests/ingestion/obsidian/test_mcp_server.py`

- [ ] stdio MCP server using the `mcp` Python SDK (fallback: if the SDK import fails, module still loads so tests can import it without hard-failing).
- [ ] Tools: `search_vault(query, k=8, filter=None)`, `get_note(vault_path)`, `sync_vault(mode="incremental", path=None)`, `analyze_vault()`, `apply_vault_optimization(action)`.
- [ ] `apply_vault_optimization` rejects unknown actions with a clear error.
- [ ] Unit tests call the underlying tool handler functions directly (no subprocess), using a fake ingestor, and assert argument validation + dispatch.

**Commit:** `feat(obsidian): add MCP server exposing search/sync/analyze`

---

## Task 8: Fixture vault + integration smoke

**Files:**
- Create: `tests/ingestion/obsidian/fixtures/vault/README.md`
- Create: several fixture notes covering: deep headings, frontmatter + tags, wikilinks, attachment refs, a preamble-only note, a UTF-8 note with emoji, an oversized note.

- [ ] Hand-craft the fixture notes.
- [ ] Ensure `conftest.py`'s `tmp_vault` fixture copies the whole tree.

**Commit:** `test(obsidian): add fixture vault`

---

## Task 9: Config + docs

**Files:**
- Modify: `config/settings.yaml` (add `obsidian` block if not present — commented defaults)
- Modify: `CLAUDE.md` or `docs/` README pointer

- [ ] Document the CLI, daemon, and MCP registration steps. Leave the MCP registration as instructions — the user wires it into their own MCP config.

**Commit:** `docs(obsidian): document ingestion tool and config`

---

## Self-review checklist

- Every spec section mapped to at least one task: §3 (skeleton T1-T7), §4 parser (T1), §5 attachments (T2), §6 sync modes (T3, T4, T6), §7 analyzer (T5), §8 MCP (T7), §9 config (T9), §10 error handling (T3 — per-chunk upserts, retry left to embedder), §11 tests (T1-T7), §12 rollout (task order matches).
- No placeholders — each task states exact files and exact behaviors.
- Type names (`ObsidianVaultIngestor`, `SyncResult`, `AnalysisReport`, `VaultWatcher`, `AttachmentProcessor`, `AttachmentRegistry`, `Chunk`, `ParsedNote`) are consistent across tasks.
