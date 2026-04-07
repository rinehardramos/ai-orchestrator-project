# Obsidian Vault Ingestion Tool — Design Spec

**Date:** 2026-04-08
**Status:** Draft, pending user review
**Owner:** Genesis / shared ingestion

## 1. Purpose

Build a reusable ingestion tool that syncs an Obsidian vault (markdown notes + attachments) into a dedicated Qdrant collection, making personal notes, research, links, and ideas semantically searchable by workers and Claude Code agents for project work and daily decision-making.

The tool must be usable three ways from one core implementation:

1. **Standalone CLI** — one-shot sync or long-running daemon.
2. **Python library** — workers and Genesis code import `ObsidianVaultIngestor` directly.
3. **MCP server** — exposes `search_vault`, `get_note`, `sync_vault`, `analyze_vault`, `apply_vault_optimization` tools to Claude Code and other MCP-aware agents.

Vault location: `~/Projects/obsidian-vault` (configurable).

## 2. Non-Goals (v1)

- Writing back to the vault. Tool is ingestion-only.
- Graph queries over wikilinks (stored in payload for future use but not retrieved).
- Automatic transcription / OCR / vision captioning (extension points defined, implementations deferred).
- Cross-vault federation.
- Running on the remote worker. v1 runs on the Genesis node because the vault is local. This is an intentional, scoped exception to the "Genesis does not execute" rule: the vault is personal-data-at-rest on the local machine and ingestion is a pure read + HTTP-upsert to remote Qdrant, not shell execution or IaC.

## 3. Architecture

### 3.1 Package layout

```
src/ingestion/obsidian/
├── __init__.py
├── ingestor.py        # ObsidianVaultIngestor — core library
├── parser.py          # Markdown → frontmatter + heading-based chunks
├── attachments.py     # AttachmentProcessor protocol + built-ins + registry
├── analyzer.py        # analyze_vault + apply_optimization
├── watcher.py         # watchdog-based daemon
├── cli.py             # `python -m src.ingestion.obsidian ...`
└── mcp_server.py      # stdio MCP server
```

**Design rationale:** three consumers share one ingestion core. CLI, library, and MCP server are thin wrappers over `ingestor.py` so that behavior (chunking, hashing, upsert semantics) cannot diverge across entry points. This is the main reason for the separate module rather than a single script.

### 3.2 Qdrant collection

- **Collection name:** `obsidian_vault_v1`
- **Embedding model:** `nomic-embed-code` via LMStudio (reuse `KnowledgeBaseClient` pipeline — 3584 dims) so the vault is searchable with the same embeddings the rest of the system already uses.
- **Isolation:** a brand-new collection, not `knowledge_v1` or `agent_insights`. Personal notes are a distinct corpus with different provenance, different trust level, and different lifecycle than curated agent knowledge; mixing them would pollute retrieval for agent memory and make it impossible to evict the vault without disturbing the rest of the system.

### 3.3 Embedding client

New thin wrapper around the existing `HybridMemoryStore` that targets `obsidian_vault_v1`. Reuses the LMStudio embedding call. No duplication of transport or auth logic.

## 4. Parser and Chunking

### 4.1 Chunking strategy: heading-based

For each `.md` file:

1. Parse YAML frontmatter if the file begins with `---`. Store as `frontmatter` dict.
2. Split body on ATX headings (`#`, `##`, `###`, …). Each heading plus its content until the next heading of equal-or-higher level is one chunk.
3. Content before the first heading becomes chunk `#0` with heading `_preamble`.
4. Files with no headings produce a single chunk containing the whole body.
5. Oversized chunks (> 8,000 characters) are still embedded as a single chunk in v1 and a warning is logged. Splitting oversized sections is left to `analyze_vault --apply=rechunk`, which can flip an offending file to a hybrid heading+window strategy on demand.

**Why heading-based:** markdown headings already encode the author's semantic boundaries. Fixed-size windows fragment mid-thought; whole-note embedding loses precision on long notes. Heading-based chunking preserves natural sections, keeps chunks retrievable in context, and matches how a human would scan the note. The hybrid fallback is kept behind `analyze --apply` so the common case stays simple.

### 4.2 Change detection: per-chunk SHA-256 hash

Each chunk's text is hashed (SHA-256) and stored in the point payload as `content_hash`. On incremental sync, the ingestor re-chunks the file, hashes each chunk, and upserts only chunks whose hash differs from the stored value. Unchanged chunks are skipped. Chunks that no longer exist (section removed) are deleted.

**Why hashes over mtime:**
- Correctly handles partial edits: if only one section of a long note changed, only that chunk is re-embedded.
- Correctly handles file moves, renames, and mtime-preserving sync tools (git, rsync with `-t`).
- Cost is negligible — reading markdown is cheap and hashing is faster than the embedding call it avoids.
- A sidecar manifest DB (SQLite) was considered but rejected as a second source of truth; Qdrant is the one authoritative index and the hash lives with the data.

### 4.3 Point ID

Deterministic UUIDv5 derived from `(vault_relative_path, chunk_index)`. Re-embedding the same chunk upserts in place rather than creating duplicates. Renaming a file produces new IDs and the old ones are cleaned up via orphan pruning (see §7).

### 4.4 Payload schema

```json
{
  "vault_path": "daily/2026-04-08.md",
  "absolute_path": "/Users/.../obsidian-vault/daily/2026-04-08.md",
  "chunk_index": 2,
  "heading_path": ["Projects", "Orchestrator", "TODO"],
  "heading": "TODO",
  "content": "<chunk text>",
  "content_hash": "sha256:...",
  "frontmatter": {"tags": ["project"], "created": "..."},
  "tags": ["project", "orchestrator"],
  "links": [{"type": "wikilink", "target": "Other Note"}],
  "attachments": [{"path": "assets/diagram.png", "type": "image", "alt": "arch"}],
  "source_type": "note",
  "file_mtime": 1712000000,
  "indexed_at": "2026-04-08T12:34:56Z"
}
```

`source_type` is `"note" | "pdf" | "image_caption" | "audio_transcript"` so search can filter by modality.

## 5. Multimedia Handling

Obsidian notes embed attachments via `![[file.png]]` or `![](path/to/file.pdf)`. The parser extracts these per chunk and the ingestor dispatches them to an `AttachmentProcessor` registry keyed by file extension.

### 5.1 v1 behavior by type

| Type                 | v1 behavior |
|----------------------|-------------|
| Images (png/jpg/webp/gif) | Reference + alt text stored in payload. Optional caption processor (off by default). |
| PDFs                 | Text extracted via existing `src/shared/document_processor.py`. Each PDF becomes a sibling "virtual note" with `source_type: "pdf"` and `parent_note: <vault_path>`. |
| Audio (mp3/m4a/wav)  | Reference-only. Whisper transcription is a pluggable processor — off by default. |
| Video (mp4/mov)      | Reference-only. Transcription processor extension point. |
| Other binaries       | Reference-only. |

### 5.2 `AttachmentProcessor` protocol

```python
class AttachmentProcessor(Protocol):
    def process(self, path: Path) -> Optional[str]: ...
```

A registry maps extensions to processors. Unregistered extensions are reference-only. This keeps v1 lean (only the PDF processor is wired in by default, because the code already exists) while providing a single clean extension point for vision captioning, Whisper, OCR, etc. New processors do not require touching the core ingestor.

**Why pluggable instead of built-in multimedia:** transcription and vision are expensive, model-dependent, and not always wanted. A registry lets the user opt in per modality via config without forking the ingestion flow.

## 6. Sync Modes

The ingestor exposes four top-level operations:

| Mode | What it does |
|------|--------------|
| `sync --full` | Walk the entire vault, re-chunk every file, upsert all points regardless of hash. Use after embedding-model or schema changes. |
| `sync --incremental` (default) | Walk the vault, compute hashes, upsert only chunks whose hash differs, delete chunks that disappeared, prune orphaned points whose source file is gone. |
| `sync --path <file>` | Sync exactly one file (used by MCP `sync_vault(path=...)` for "I just saved this note" flows). |
| `daemon` | Run a `watchdog` observer on the vault, debounce events (coalesce rapid saves within ~500ms), and run `sync --path` for each affected file. No polling fallback in v1. |

**Why `watchdog` only (no polling):** the vault is on a local filesystem on the Genesis node, which is the only place this daemon runs. `watchdog` on macOS uses FSEvents, which is reliable for local disks. A periodic full reconciliation was considered for network-filesystem robustness but rejected as YAGNI for v1 since the vault is local. It can be added behind a config flag if needed.

## 7. Analyze Function

A separate module (`analyzer.py`) exposes `analyze_vault()` and `apply_optimization(action)` as a library function, a CLI subcommand, and two MCP tools.

### 7.1 What analyze reports

- Note count, attachment count by type, total chunks, total vector storage.
- **Chunk size distribution:** p50 / p90 / p99 / max in chars and token estimates. Flags files producing oversized chunks.
- **Heading-structure health:** notes with no headings, notes producing >50 chunks (likely dumps that should be split), heading-depth distribution.
- **Payload bloat:** largest payloads, average payload size, which fields contribute the most bytes.
- **Duplication:** hash-collision duplicates; optional top-N cosine-similarity spot-check for near-duplicates above a threshold.
- **Orphans and stale data:** Qdrant points whose source file no longer exists; files on disk with no points; files where disk hash differs from stored hash (re-sync needed).
- **Attachment coverage:** referenced attachments that do / don't exist on disk; indexed vs reference-only counts.

### 7.2 What analyze suggests and can apply

`analyze_vault()` is always read-only. Mutations live behind explicit `--apply=<action>` flags and a separate MCP tool.

| Action | Effect |
|--------|--------|
| `--apply=prune` | Delete Qdrant points whose source file no longer exists. Safe. |
| `--apply=rechunk` | Re-ingest flagged oversized-chunk files using a hybrid heading+window split. Idempotent via hash. |
| `--apply=resync` | Force full re-sync of files whose on-disk hash differs from the stored hash (recovery path). |

**MCP exposure:** `analyze_vault()` is always safe to call. `apply_vault_optimization(action: str)` is a separate tool so an agent cannot mutate the index by accident — it must explicitly request the action by name, and unknown actions are rejected.

**Why analyze exists in v1:** a personal vault evolves chaotically. Without a built-in way to inspect chunk sizes, duplication, and orphans, the index will silently drift from the vault. Surfacing this as an agent-callable tool also means Claude Code can self-diagnose retrieval issues ("search is returning stale hits, let me analyze the vault").

## 8. MCP Server Tool Surface

Single stdio MCP server, wraps the core ingestor.

| Tool | Parameters | Mutating | Description |
|------|------------|----------|-------------|
| `search_vault` | `query: str, k: int = 8, filter: dict?` | no | Semantic search over the vault collection. Optional payload filter by `tags`, `source_type`, `vault_path` prefix. |
| `get_note` | `vault_path: str` | no | Return all chunks for a single note in heading order. |
| `sync_vault` | `mode: "full" \| "incremental" = "incremental", path: str?` | yes | Trigger a sync. Defaults to incremental. `path` scopes to one file. |
| `analyze_vault` | — | no | Return the analysis report. |
| `apply_vault_optimization` | `action: "prune" \| "rechunk" \| "resync"` | yes | Apply a named optimization. Unknown actions rejected. |

**Design rationale for exposing `sync_vault` as a tool:** the primary use case is "agent edited or read a note moments ago and wants it searchable now." Without `sync_vault`, the agent has to shell out to the CLI or wait for the daemon. Defaulting to `incremental` with an optional `path` keeps the common case cheap; explicit `mode: "full"` is the escape hatch.

## 9. Configuration

Settings are read from `config/settings.yaml` under a new `obsidian` namespace, with environment variable overrides:

```yaml
obsidian:
  vault_path: ~/Projects/obsidian-vault
  collection: obsidian_vault_v1
  oversized_chunk_chars: 8000
  daemon:
    debounce_ms: 500
    ignore_globs: [".obsidian/**", ".trash/**", "**/.DS_Store"]
  attachments:
    pdf: enabled
    image_caption: disabled
    audio_transcript: disabled
```

Qdrant connection reuses the existing `qdrant` settings block — no duplication.

## 10. Error Handling

- **Embedding failures:** retry with exponential backoff (3 tries), then log the file and continue. One bad note must not abort a full sync.
- **Malformed markdown / frontmatter:** skip the bad section, log, continue. Frontmatter YAML errors degrade gracefully to "no frontmatter."
- **Qdrant unreachable:** fail fast in CLI mode with a clear message. In daemon mode, buffer pending paths and retry on a backoff; drop the buffer after a cap to avoid unbounded memory.
- **Attachment processor errors:** the note itself still ingests; the attachment is logged and stored as reference-only.
- **Partial sync interruption:** per-chunk upserts mean interrupted syncs leave the index in a consistent partial state. The next incremental sync resumes naturally via hash comparison.

## 11. Testing Strategy

- **Unit tests** for `parser.py`: frontmatter variants, heading splits at each depth, preamble handling, wikilink and attachment extraction, oversized-chunk detection.
- **Unit tests** for `analyzer.py`: synthetic vaults with known pathologies (all orphans, all dupes, oversized chunks, missing attachments) and verify the report fields.
- **Integration tests** for `ingestor.py` against a local in-process Qdrant (or a tmpdir-scoped test collection): full sync, incremental sync with a modified chunk, sync after deleting a section, sync after deleting a whole file.
- **Daemon test:** fixture vault + `watchdog` + simulated file writes; assert correct debouncing and single-file sync calls.
- **MCP smoke test:** spawn the server, call each tool, assert schemas.

## 12. Rollout

1. Land the package with CLI + library + tests. No MCP, no daemon. Usable standalone.
2. Add daemon mode.
3. Add MCP server and register it with Claude Code.
4. Add analyze + optimizations.
5. Enable the PDF attachment processor by default once integration is verified.

Each step is independently shippable and testable. This ordering matches the dependency graph: MCP and daemon both depend on a working core; analyze is easier to validate once real data exists in the collection; attachments are the highest-risk integration and come last.

## 13. Open Questions

- Should the vault collection be backed up in the existing `src/backups/` snapshot rotation? Recommended yes, but not required for v1.
- Token-level chunk size limits vs character-level — v1 uses character counts as a proxy to avoid a tokenizer dependency. Revisit if embedding truncation becomes an issue.
