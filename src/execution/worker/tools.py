from __future__ import annotations

"""
Tool registry for the autonomous agent worker.

Each tool has:
  - name: str
  - schema: dict (OpenAI-compatible JSON Schema for LiteLLM tools param)
  - fn: Callable(workspace_dir, **kwargs) -> str
"""
import os
import json
import subprocess
import logging
from typing import Callable

from src.execution.worker.sandbox import validate_path, validate_command

logger = logging.getLogger("AgentTools")

# Maximum lines to read from a file
MAX_READ_LINES = 2000
# Shell command timeout
SHELL_TIMEOUT = 120
# Default repo for persisting agent work
AGENT_DEFAULT_REPO = os.environ.get("AGENT_DEFAULT_REPO", "ssh://git@github.com/rinehardramos/workspaces.git")


# ── Tool Implementations ──

def _sanitize_output(text: str) -> str:
    """Strip any known secrets from tool output before returning to the LLM."""
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        val = os.environ.get(key, "")
        if val and val in text:
            text = text.replace(val, "***")
    return text


def shell_exec(workspace_dir: str, command: str) -> str:
    """Run a shell command inside the workspace."""
    if not validate_command(command):
        return "ERROR: Command blocked by safety filter."
    try:
        result = subprocess.run(
            command,
            shell=True,  # nosec B602 — command is validated by validate_command() blocklist before reaching here
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=SHELL_TIMEOUT,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n--- stderr ---\n" + result.stderr) if output else result.stderr
        if not output:
            output = f"(exit code {result.returncode})"
        # Truncate very large outputs
        if len(output) > 50000:
            output = output[:50000] + "\n... [truncated]"
        return _sanitize_output(output)
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {SHELL_TIMEOUT}s."
    except Exception as e:
        return f"ERROR: {e}"


def read_file(workspace_dir: str, path: str, offset: int = 0, limit: int = MAX_READ_LINES) -> str:
    """Read file contents with optional line offset and limit."""
    try:
        resolved = validate_path(path, workspace_dir)
        with open(resolved, "r") as f:
            lines = f.readlines()
        total = len(lines)
        selected = lines[offset:offset + limit]
        numbered = "".join(f"{i + offset + 1:>6}\t{line}" for i, line in enumerate(selected))
        if total > offset + limit:
            numbered += f"\n... ({total - offset - limit} more lines)"
        return numbered if numbered else "(empty file)"
    except ValueError as e:
        return f"ERROR: {e}"
    except FileNotFoundError:
        return f"ERROR: File not found: {path}"
    except Exception as e:
        return f"ERROR: {e}"


def write_file(workspace_dir: str, path: str, content: str) -> str:
    """Create or overwrite a file."""
    try:
        resolved = validate_path(path, workspace_dir)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w") as f:
            f.write(content)
        return f"OK: Wrote {len(content)} bytes to {path}"
    except ValueError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def edit_file(workspace_dir: str, path: str, old_string: str, new_string: str) -> str:
    """Replace a specific string in a file (first occurrence)."""
    try:
        resolved = validate_path(path, workspace_dir)
        with open(resolved, "r") as f:
            content = f.read()
        if old_string not in content:
            return f"ERROR: old_string not found in {path}"
        new_content = content.replace(old_string, new_string, 1)
        with open(resolved, "w") as f:
            f.write(new_content)
        return f"OK: Replaced in {path}"
    except ValueError as e:
        return f"ERROR: {e}"
    except FileNotFoundError:
        return f"ERROR: File not found: {path}"
    except Exception as e:
        return f"ERROR: {e}"


def list_files(workspace_dir: str, path: str = ".", max_depth: int = 3) -> str:
    """List directory tree up to max_depth."""
    try:
        resolved = validate_path(path, workspace_dir)
        entries = []
        base_depth = resolved.rstrip(os.sep).count(os.sep)
        for root, dirs, files in os.walk(resolved):
            depth = root.rstrip(os.sep).count(os.sep) - base_depth
            if depth >= max_depth:
                dirs.clear()
                continue
            indent = "  " * depth
            entries.append(f"{indent}{os.path.basename(root)}/")
            for fname in sorted(files):
                entries.append(f"{indent}  {fname}")
        return "\n".join(entries) if entries else "(empty directory)"
    except ValueError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def search_files(workspace_dir: str, pattern: str, path: str = ".", glob: str = "") -> str:
    """Search for a regex pattern across files using grep."""
    try:
        resolved = validate_path(path, workspace_dir)
        cmd = ["grep", "-rn", "--include", glob if glob else "*", pattern, resolved]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=workspace_dir)
        output = result.stdout
        if len(output) > 30000:
            output = output[:30000] + "\n... [truncated]"
        return output if output else "No matches found."
    except subprocess.TimeoutExpired:
        return "ERROR: Search timed out."
    except Exception as e:
        return f"ERROR: {e}"


def _to_authenticated_https(url: str) -> str:
    """Convert SSH or plain HTTPS GitHub URLs to token-authenticated HTTPS."""
    token = os.environ.get("GITHUB_TOKEN", "")
    # ssh://git@github.com/owner/repo.git → https://x-access-token:TOKEN@github.com/owner/repo.git
    if url.startswith("ssh://git@github.com/"):
        repo_path = url.replace("ssh://git@github.com/", "").rstrip(".git")
        if token:
            return f"https://x-access-token:{token}@github.com/{repo_path}.git"
        return f"https://github.com/{repo_path}.git"
    # git@github.com:owner/repo.git
    if url.startswith("git@github.com:"):
        repo_path = url.replace("git@github.com:", "").rstrip(".git")
        if token:
            return f"https://x-access-token:{token}@github.com/{repo_path}.git"
        return f"https://github.com/{repo_path}.git"
    # Already HTTPS — inject token if missing
    if "github.com" in url and token and "x-access-token" not in url:
        return url.replace("https://", f"https://x-access-token:{token}@")
    return url


def git_clone(workspace_dir: str, repo_url: str = "", target_dir: str = "repo", shallow: bool = True) -> str:
    """Clone a git repository into the workspace. Defaults to the shared workspaces repo."""
    repo_url = repo_url or AGENT_DEFAULT_REPO
    # Convert SSH URLs to authenticated HTTPS (containers don't have SSH keys)
    clone_url = _to_authenticated_https(repo_url)
    try:
        resolved = validate_path(target_dir, workspace_dir)
        cmd = ["git", "clone"]
        if shallow:
            cmd.append("--depth=1")
        cmd.extend([clone_url, resolved])
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120, cwd=workspace_dir,
        )
        if result.returncode != 0:
            return f"ERROR: git clone failed: {_sanitize_output(result.stderr)}"
        # Set git identity for commits in this repo
        subprocess.run(["git", "config", "user.email", "agent@ai-orchestrator.local"],
                       capture_output=True, cwd=resolved, timeout=5)
        subprocess.run(["git", "config", "user.name", "AI Agent"],
                       capture_output=True, cwd=resolved, timeout=5)
        # Restore the original URL (without token) so token doesn't persist on disk
        if clone_url != repo_url:
            subprocess.run(["git", "remote", "set-url", "origin", repo_url],
                           capture_output=True, cwd=resolved, timeout=5)
        depth_str = "shallow" if shallow else "full"
        return f"OK: Cloned {repo_url} into {target_dir} ({depth_str})"
    except subprocess.TimeoutExpired:
        return "ERROR: git clone timed out."
    except Exception as e:
        return f"ERROR: {_sanitize_output(str(e))}"


def git_commit(workspace_dir: str, message: str, path: str = ".") -> str:
    """Stage all changes and commit in a repo directory."""
    try:
        resolved = validate_path(path, workspace_dir)
        add_result = subprocess.run(
            ["git", "add", "-A"], capture_output=True, text=True, cwd=resolved, timeout=30
        )
        if add_result.returncode != 0:
            return f"ERROR: git add failed: {add_result.stderr}"
        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, cwd=resolved, timeout=30,
        )
        if commit_result.returncode != 0:
            return f"ERROR: git commit failed: {commit_result.stderr}"
        return f"OK: Committed with message: {message}"
    except Exception as e:
        return f"ERROR: {e}"


def git_create_branch(workspace_dir: str, branch_name: str, path: str = ".") -> str:
    """Create and switch to a new git branch."""
    try:
        resolved = validate_path(path, workspace_dir)
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            capture_output=True, text=True, cwd=resolved, timeout=30,
        )
        if result.returncode != 0:
            return f"ERROR: git checkout -b failed: {result.stderr}"
        return f"OK: Created and switched to branch '{branch_name}'"
    except Exception as e:
        return f"ERROR: {e}"


def git_push(workspace_dir: str, path: str = ".", remote: str = "origin", branch: str = "") -> str:
    """Push commits to the remote repository using GITHUB_TOKEN from environment."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return "ERROR: GITHUB_TOKEN not available in environment."

    def _sanitize(text: str) -> str:
        return text.replace(token, "***") if token else text

    try:
        resolved = validate_path(path, workspace_dir)

        # Get current branch if not specified
        if not branch:
            br = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, cwd=resolved, timeout=10,
            )
            if br.returncode != 0:
                return f"ERROR: Could not determine current branch: {_sanitize(br.stderr)}"
            branch = br.stdout.strip()

        # Get the current remote URL
        get_url = subprocess.run(
            ["git", "remote", "get-url", remote],
            capture_output=True, text=True, cwd=resolved, timeout=10,
        )
        if get_url.returncode != 0:
            return f"ERROR: Could not get remote URL: {_sanitize(get_url.stderr)}"
        original_url = get_url.stdout.strip()

        # Convert any GitHub URL format to authenticated HTTPS
        auth_url = _to_authenticated_https(original_url)
        if auth_url == original_url and "x-access-token" not in auth_url:
            return f"ERROR: Unsupported remote URL format: {_sanitize(original_url)}"

        # Temporarily set the authenticated URL
        subprocess.run(
            ["git", "remote", "set-url", remote, auth_url],
            capture_output=True, text=True, cwd=resolved, timeout=10,
        )

        try:
            result = subprocess.run(
                ["git", "push", "-u", remote, branch],
                capture_output=True, text=True, cwd=resolved, timeout=120,
            )
            output = _sanitize(result.stdout + "\n" + result.stderr).strip()
            if result.returncode != 0:
                return f"ERROR: git push failed: {output}"
            return f"OK: Pushed branch '{branch}' to {remote}\n{output}"
        finally:
            # Always restore the original URL to prevent token persistence on disk
            subprocess.run(
                ["git", "remote", "set-url", remote, original_url],
                capture_output=True, text=True, cwd=resolved, timeout=10,
            )
    except subprocess.TimeoutExpired:
        return "ERROR: git push timed out."
    except Exception as e:
        return f"ERROR: {_sanitize(str(e))}"


# ── Gmail (IMAP/SMTP) ─────────────────────────────────────────────────────
# Reads credentials from env: GMAIL_USERNAME + GMAIL_APP_PASSWORD (a Google
# App Password — Gmail rejects regular account passwords for IMAP/SMTP).
# Optional overrides: GMAIL_IMAP_HOST, GMAIL_SMTP_HOST, GMAIL_SMTP_PORT.

def _gmail_creds() -> tuple[str | None, str | None]:
    return os.environ.get("GMAIL_USERNAME"), os.environ.get("GMAIL_APP_PASSWORD")


def _gmail_decode_header(header: str) -> str:
    if not header:
        return ""
    from email.header import decode_header as _dh
    parts = []
    for part, enc in _dh(header):
        if isinstance(part, bytes):
            parts.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(part)
    return "".join(parts)


def _gmail_body_preview(msg, full: bool = False) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")
    return body if full else body[:500]


def _gmail_format_list(emails: list[dict]) -> str:
    if not emails:
        return "No emails found."
    lines = [f"Found {len(emails)} email(s):\n"]
    for i, e in enumerate(emails, 1):
        lines.append(f"{i}. ID: {e['id']}")
        lines.append(f"   From: {e['from']}")
        lines.append(f"   Subject: {e['subject']}")
        lines.append(f"   Date: {e['date']}")
        if "preview" in e:
            lines.append(f"   Preview: {e['preview']}")
        lines.append("")
    return "\n".join(lines)


def gmail_send(workspace_dir: str, to: str, subject: str, body: str,
               cc: str = "", bcc: str = "") -> str:
    """Send an email via Gmail SMTP. Recipients comma-separated."""
    user, pw = _gmail_creds()
    if not user or not pw:
        return "ERROR: GMAIL_USERNAME or GMAIL_APP_PASSWORD not set in worker env."
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        smtp_host = os.environ.get("GMAIL_SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("GMAIL_SMTP_PORT", "587"))

        msg = MIMEMultipart()
        msg["From"] = user
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc
        msg.attach(MIMEText(body, "plain"))

        recipients = [a.strip() for a in to.split(",") if a.strip()]
        if cc:
            recipients += [a.strip() for a in cc.split(",") if a.strip()]
        if bcc:
            recipients += [a.strip() for a in bcc.split(",") if a.strip()]

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(user, pw)
            server.sendmail(user, recipients, msg.as_string())
        return f"Email sent successfully to: {to}"
    except Exception as e:
        return f"gmail_send failed: {e}"


def gmail_create_draft(workspace_dir: str, to: str, subject: str, body: str,
                       cc: str = "", bcc: str = "") -> str:
    """Create an email DRAFT in Gmail (does NOT send).

    Appends a fully-formed RFC822 message with the ``\\Draft`` flag to the
    ``[Gmail]/Drafts`` folder via IMAP. The draft appears in the user's Gmail
    web interface and Gmail apps, ready for the user to review and send
    manually.
    """
    user, pw = _gmail_creds()
    if not user or not pw:
        return "ERROR: GMAIL_USERNAME or GMAIL_APP_PASSWORD not set in worker env."
    try:
        import imaplib
        import time
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.utils import formatdate, make_msgid

        imap_host = os.environ.get("GMAIL_IMAP_HOST", "imap.gmail.com")
        imap_port = int(os.environ.get("GMAIL_IMAP_PORT", "993"))
        drafts_folder = os.environ.get("GMAIL_DRAFTS_FOLDER", "[Gmail]/Drafts")

        msg = MIMEMultipart()
        msg["From"] = user
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        msg.attach(MIMEText(body, "plain"))

        with imaplib.IMAP4_SSL(imap_host, imap_port) as mail:
            mail.login(user, pw)
            status, _ = mail.append(
                drafts_folder,
                "\\Draft",
                imaplib.Time2Internaldate(time.time()),
                msg.as_string().encode("utf-8"),
            )
            if status != "OK":
                return f"ERROR: APPEND to {drafts_folder} failed: {status}"

        return (
            f"Draft created in {drafts_folder}. To: {to}  Subject: {subject!r}  "
            f"({len(body)} chars body). Visible in Gmail web/apps for review."
        )
    except Exception as e:
        return f"gmail_create_draft failed: {e}"


def gmail_read_inbox(workspace_dir: str, folder: str = "INBOX",
                     unread_only: bool = True, limit: int = 10,
                     mark_read: bool = False) -> str:
    """Read recent emails from a Gmail folder via IMAP."""
    user, pw = _gmail_creds()
    if not user or not pw:
        return "ERROR: GMAIL_USERNAME or GMAIL_APP_PASSWORD not set in worker env."
    try:
        import imaplib
        import email as _email
        imap_host = os.environ.get("GMAIL_IMAP_HOST", "imap.gmail.com")
        imap_port = int(os.environ.get("GMAIL_IMAP_PORT", "993"))

        with imaplib.IMAP4_SSL(imap_host, imap_port) as mail:
            mail.login(user, pw)
            mail.select(folder)
            status, messages = mail.search(None, "(UNSEEN)" if unread_only else "ALL")
            if status != "OK":
                return "ERROR: Failed to search inbox."
            ids = messages[0].split()[-limit:] if messages[0] else []
            results = []
            for eid in reversed(ids):
                fs, data = mail.fetch(eid, "(RFC822)")
                if fs != "OK":
                    continue
                msg = _email.message_from_bytes(data[0][1])
                preview = _gmail_body_preview(msg)
                results.append({
                    "id": eid.decode(),
                    "from": _gmail_decode_header(msg.get("From", "")),
                    "subject": _gmail_decode_header(msg.get("Subject", "")),
                    "date": msg.get("Date", ""),
                    "preview": preview[:200] + ("…" if len(preview) > 200 else ""),
                })
                if mark_read:
                    mail.store(eid, "+FLAGS", "\\Seen")
            return _gmail_format_list(results)
    except Exception as e:
        return f"gmail_read_inbox failed: {e}"


def gmail_search(workspace_dir: str, query: str, folder: str = "INBOX",
                 limit: int = 10) -> str:
    """IMAP search query (e.g. 'FROM \"alice@example.com\"', 'SUBJECT \"invoice\"')."""
    user, pw = _gmail_creds()
    if not user or not pw:
        return "ERROR: GMAIL_USERNAME or GMAIL_APP_PASSWORD not set in worker env."
    try:
        import imaplib
        import email as _email
        imap_host = os.environ.get("GMAIL_IMAP_HOST", "imap.gmail.com")
        imap_port = int(os.environ.get("GMAIL_IMAP_PORT", "993"))
        with imaplib.IMAP4_SSL(imap_host, imap_port) as mail:
            mail.login(user, pw)
            mail.select(folder)
            status, messages = mail.search(None, f"({query})")
            if status != "OK":
                return "ERROR: Search failed."
            ids = messages[0].split()[-limit:] if messages[0] else []
            results = []
            for eid in reversed(ids):
                fs, data = mail.fetch(eid, "(RFC822)")
                if fs != "OK":
                    continue
                msg = _email.message_from_bytes(data[0][1])
                results.append({
                    "id": eid.decode(),
                    "from": _gmail_decode_header(msg.get("From", "")),
                    "subject": _gmail_decode_header(msg.get("Subject", "")),
                    "date": msg.get("Date", ""),
                })
            return _gmail_format_list(results)
    except Exception as e:
        return f"gmail_search failed: {e}"


def read_vault_note(workspace_dir: str, path: str) -> str:
    """Fetch the full content of a specific Obsidian note by its vault-relative path.

    Use this when the user names a specific note (e.g. ``AGENT INSTRUCTIONS 2.md``)
    or when ``recall_memory`` returns a promising source path you want the full
    body of. Concatenates every chunk of the note in heading order.
    """
    try:
        from src.config_db import get_loader
        from qdrant_client import QdrantClient
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue

        collection = (
            (get_loader().load_namespace("knowledge") or {}).get("vault_collection")
            or "obsidian_vault_v1"
        )
        qdrant_url = os.environ.get("QDRANT_URL", "http://host.docker.internal:6333")
        client = QdrantClient(url=qdrant_url)

        # Try the exact path first; fall back to a basename match if no hits.
        def _scroll(value: str):
            return client.scroll(
                collection_name=collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="vault_path", match=MatchValue(value=value))]
                ),
                limit=200,
                with_payload=True,
                with_vectors=False,
            )[0]

        points = _scroll(path)
        if not points and "/" not in path:
            # Try a forgiving lookup: scan and match by basename.
            all_pts, _ = client.scroll(
                collection_name=collection,
                limit=500,
                with_payload=["vault_path"],
                with_vectors=False,
            )
            candidates = [p.payload.get("vault_path") for p in all_pts if p.payload]
            target = next(
                (c for c in candidates if c and (c == path or c.endswith("/" + path) or c.split("/")[-1] == path)),
                None,
            )
            if target:
                points = _scroll(target)

        if not points:
            return f"Note not found in vault: {path!r}"

        chunks = sorted(
            (p.payload for p in points if p.payload),
            key=lambda pl: pl.get("chunk_index", 0),
        )
        actual_path = chunks[0].get("vault_path", path)
        body = "\n\n".join((c.get("content") or "") for c in chunks)
        return f"--- {actual_path} ({len(chunks)} chunks) ---\n{body}"
    except Exception as e:
        return f"read_vault_note failed: {e}"


def recall_memory(workspace_dir: str, query: str, k: int = 5) -> str:
    """Semantic search over the user's Obsidian vault (long-term memory).

    Use this whenever you need background knowledge, prior decisions, project
    context, or any information from the user's notes that isn't in the current
    conversation. Returns top-k matching note chunks with their source paths.
    """
    try:
        from src.shared.memory.hybrid_store import HybridMemoryStore
        from src.execution.worker.embeddings import get_embedder
        from src.config_db import get_loader
        collection = (
            (get_loader().load_namespace("knowledge") or {}).get("vault_collection")
            or "obsidian_vault_v1"
        )
        store = HybridMemoryStore()
        vector = get_embedder().embed(query, embed_type="text")
        results = store.query_l2(collection, vector, limit=max(1, min(k, 20)))
        if not results:
            return f"No relevant notes found in {collection} for: {query!r}"
        lines = []
        for r in results:
            payload = r.payload or {}
            source = payload.get("source") or payload.get("path") or payload.get("vault_path") or "?"
            content = (payload.get("content") or payload.get("text") or "").strip()
            lines.append(f"[score={r.score:.3f}] {source}\n{content[:600]}")
        return "\n---\n".join(lines)
    except Exception as e:
        return f"recall_memory failed: {e}"


def memory_search(workspace_dir: str, query: str) -> str:
    """Semantic search for past insights in Qdrant L2."""
    try:
        from src.shared.memory.hybrid_store import HybridMemoryStore
        from src.execution.worker.embeddings import get_embedder
        store = HybridMemoryStore()
        vector = get_embedder().embed(query)
        results = store.query_l2("agent_insights_v2", vector, limit=3)
        if not results:
            return "No relevant past insights found."
        entries = []
        for r in results:
            payload = r.payload or {}
            entries.append(f"[score={r.score:.3f}] {payload.get('content', '')[:500]}")
        return "\n---\n".join(entries)
    except Exception as e:
        return f"Memory search unavailable: {e}"


def memory_store(workspace_dir: str, content: str, tags: str = "") -> str:
    """Store a new insight into Qdrant L2."""
    try:
        import uuid
        from src.shared.memory.hybrid_store import HybridMemoryStore, MemoryEntry
        from src.execution.worker.embeddings import get_embedder
        store = HybridMemoryStore()
        vector = get_embedder().embed(content)
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            content=content,
            metadata={"source": "agent", "tags": tags},
        )
        store.store_l2("agent_insights_v2", entry, vector=vector)
        return "OK: Insight stored in L2 memory."
    except Exception as e:
        return f"Memory store failed: {e}"


def task_complete(workspace_dir: str, summary: str, status: str = "success") -> str:
    """Signal that the agent has completed its task."""
    return json.dumps({"action": "task_complete", "summary": summary, "status": status})

def generate_image(workspace_dir: str, prompt: str, filename: str = "") -> str:
    """Generate an image using Google Imagen and save it to the workspace."""
    google_api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not google_api_key:
        return "ERROR: GOOGLE_API_KEY not set — cannot generate image"

    try:
        from google import genai as _genai
    except ImportError:
        return "ERROR: google-genai package not installed"

    client = _genai.Client(api_key=google_api_key)

    # Try models in preference order — fall back if one is unavailable on this account
    models_to_try = [
        "imagen-4.0-generate-001",
        "imagen-3.0-generate-001",
        "imagen-3.0-fast-generate-001",
    ]
    last_error = ""
    for model in models_to_try:
        try:
            response = client.models.generate_images(
                model=model,
                prompt=prompt,
                config={"number_of_images": 1},
            )
            if not response.generated_images:
                last_error = f"model {model} returned no images"
                continue

            image_bytes = response.generated_images[0].image.image_bytes
            safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in prompt[:30])
            fname = filename if filename else f"{safe_stem}.png"
            filepath = os.path.join(workspace_dir, fname)
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            return f"OK: Image saved to '{fname}' ({len(image_bytes):,} bytes) using {model}"
        except Exception as e:
            last_error = f"{model}: {e}"
            logger.warning(f"[generate_image] {model} failed: {e} — trying next model")
            continue

    return f"ERROR: All Imagen models failed. Last error: {last_error}"

def generate_video(workspace_dir: str, prompt: str) -> str:
    """Stub for generating a video."""
    return f"OK: Conceptually generated video for '{prompt}' (Feature pending Sora/Luma/Runway integration)"

def generate_audio(workspace_dir: str, prompt: str) -> str:
    """Stub for generating audio."""
    return f"OK: Conceptually generated audio for '{prompt}' (Feature pending Suno/Udio/ElevenLabs integration)"

def search_web(workspace_dir: str, query: str) -> str:
    """Search the web using DuckDuckGo."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results:
                return "No results found."
            formatted = []
            for r in results:
                formatted.append(f"Title: {r['title']}\nURL: {r['href']}\nSnippet: {r['body']}")
            return "\n\n---\n\n".join(formatted)
    except Exception as e:
        return f"ERROR: Web search failed: {e}"

def read_url_content(workspace_dir: str, url: str) -> str:
    """Fetch and parse content from a URL."""
    try:
        import requests
        from bs4 import BeautifulSoup
        response = requests.get(url, timeout=15, headers={"User-Agent": "AI-Orchestrator/1.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.extract()
            
        text = soup.get_text(separator="\n")
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = "\n".join(chunk for chunk in chunks if chunk)
        
        if len(text) > 20000:
            text = text[:20000] + "\n... [truncated]"
        return text
    except Exception as e:
        return f"ERROR: Could not read URL: {e}"
def submit_for_review(workspace_dir: str, artifact_path: str, notes: str = "") -> str:
    """Submit an artifact for review by a Quality Control agent."""
    return json.dumps({
        "action": "submit_for_review",
        "artifact_path": artifact_path,
        "notes": notes
    })

def delegate_task(workspace_dir: str, task_description: str, specialization: str = "general") -> str:
    """Delegate a sub-task to another specialized agent."""
    return json.dumps({
        "action": "delegate_task",
        "task_description": task_description,
        "specialization": specialization
    })


def browser_exec(
    workspace_dir: str,
    action: str,
    url: str = "",
    selector: str = "",
    text: str = "",
    script: str = "",
    cdp_url: str = "",
    headless: bool = True,
    timeout_ms: int = 0,
    frame: str = "",
) -> str:
    """Drive a real browser via Playwright. Supports CDP attach + headless launch."""
    from src.execution.worker.browser import browser_exec as _impl

    return _impl(
        workspace_dir=workspace_dir,
        action=action,
        url=url,
        selector=selector,
        text=text,
        script=script,
        cdp_url=cdp_url,
        headless=headless,
        timeout_ms=timeout_ms,
        frame=frame,
    )


# ── Tool Registry ──

TOOL_REGISTRY: list[dict] = [
    {
        "name": "shell_exec",
        "fn": shell_exec,
        "schema": {
            "type": "function",
            "function": {
                "name": "shell_exec",
                "description": "Run a shell command in the workspace. Sandboxed with 120s timeout.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute"},
                    },
                    "required": ["command"],
                },
            },
        },
    },
    {
        "name": "read_file",
        "fn": read_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read file contents with line numbers. Supports offset and limit for large files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path (relative to workspace)"},
                        "offset": {"type": "integer", "description": "Line offset to start reading from (0-based)", "default": 0},
                        "limit": {"type": "integer", "description": "Max lines to read", "default": 2000},
                    },
                    "required": ["path"],
                },
            },
        },
    },
    {
        "name": "write_file",
        "fn": write_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Create or overwrite a file in the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path (relative to workspace)"},
                        "content": {"type": "string", "description": "File content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
    },
    {
        "name": "edit_file",
        "fn": edit_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": "Replace a specific string in a file (first occurrence).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path (relative to workspace)"},
                        "old_string": {"type": "string", "description": "Exact string to find"},
                        "new_string": {"type": "string", "description": "Replacement string"},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            },
        },
    },
    {
        "name": "list_files",
        "fn": list_files,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List directory tree (up to 3 levels deep).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path (relative to workspace)", "default": "."},
                        "max_depth": {"type": "integer", "description": "Max depth to traverse", "default": 3},
                    },
                    "required": [],
                },
            },
        },
    },
    {
        "name": "search_files",
        "fn": search_files,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_files",
                "description": "Search for a regex pattern across files using grep.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regex pattern to search for"},
                        "path": {"type": "string", "description": "Directory to search in", "default": "."},
                        "glob": {"type": "string", "description": "File glob filter (e.g. '*.py')", "default": ""},
                    },
                    "required": ["pattern"],
                },
            },
        },
    },
    {
        "name": "git_clone",
        "fn": git_clone,
        "schema": {
            "type": "function",
            "function": {
                "name": "git_clone",
                "description": "Clone a git repository into the workspace. Defaults to the shared workspaces repo. Set shallow=false for full history (required if you plan to push).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo_url": {"type": "string", "description": "Git repository URL (leave empty for default workspaces repo)", "default": ""},
                        "target_dir": {"type": "string", "description": "Target directory name", "default": "repo"},
                        "shallow": {"type": "boolean", "description": "Shallow clone (depth=1). Set false if you need to push.", "default": True},
                    },
                    "required": [],
                },
            },
        },
    },
    {
        "name": "git_commit",
        "fn": git_commit,
        "schema": {
            "type": "function",
            "function": {
                "name": "git_commit",
                "description": "Stage all changes and commit in a repo directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Commit message"},
                        "path": {"type": "string", "description": "Repo directory path", "default": "."},
                    },
                    "required": ["message"],
                },
            },
        },
    },
    {
        "name": "git_create_branch",
        "fn": git_create_branch,
        "schema": {
            "type": "function",
            "function": {
                "name": "git_create_branch",
                "description": "Create and switch to a new git branch.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "branch_name": {"type": "string", "description": "Name for the new branch (e.g. agent/fix-readme)"},
                        "path": {"type": "string", "description": "Repo directory path", "default": "."},
                    },
                    "required": ["branch_name"],
                },
            },
        },
    },
    {
        "name": "git_push",
        "fn": git_push,
        "schema": {
            "type": "function",
            "function": {
                "name": "git_push",
                "description": "Push the current branch to the remote. Uses GITHUB_TOKEN for authentication. Token is never exposed in output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Repo directory path", "default": "."},
                        "remote": {"type": "string", "description": "Remote name", "default": "origin"},
                        "branch": {"type": "string", "description": "Branch to push (defaults to current branch)", "default": ""},
                    },
                    "required": [],
                },
            },
        },
    },
    {
        "name": "gmail_send",
        "fn": gmail_send,
        "schema": {
            "type": "function",
            "function": {
                "name": "gmail_send",
                "description": (
                    "SEND an email immediately via Gmail SMTP. The message is delivered "
                    "to recipients right away. Use gmail_create_draft instead if the user "
                    "only wants to draft/compose an email for review."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient(s), comma-separated"},
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {"type": "string", "description": "Plain-text body"},
                        "cc": {"type": "string", "description": "CC recipients (optional)", "default": ""},
                        "bcc": {"type": "string", "description": "BCC recipients (optional)", "default": ""},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
        },
    },
    {
        "name": "gmail_create_draft",
        "fn": gmail_create_draft,
        "schema": {
            "type": "function",
            "function": {
                "name": "gmail_create_draft",
                "description": (
                    "Create an email DRAFT in the user's Gmail (does NOT send). "
                    "The draft appears in Gmail web/apps for the user to review "
                    "and send manually. Use this whenever the user asks you to "
                    "compose, draft, or prepare an email."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient(s), comma-separated"},
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {"type": "string", "description": "Plain-text body"},
                        "cc": {"type": "string", "description": "CC recipients (optional)", "default": ""},
                        "bcc": {"type": "string", "description": "BCC recipients (optional)", "default": ""},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
        },
    },
    {
        "name": "gmail_read_inbox",
        "fn": gmail_read_inbox,
        "schema": {
            "type": "function",
            "function": {
                "name": "gmail_read_inbox",
                "description": "Read recent messages from a Gmail folder (default INBOX, unread only).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "folder": {"type": "string", "default": "INBOX"},
                        "unread_only": {"type": "boolean", "default": True},
                        "limit": {"type": "integer", "default": 10},
                        "mark_read": {"type": "boolean", "default": False},
                    },
                },
            },
        },
    },
    {
        "name": "gmail_search",
        "fn": gmail_search,
        "schema": {
            "type": "function",
            "function": {
                "name": "gmail_search",
                "description": (
                    "Search Gmail using IMAP query syntax. Examples: "
                    "'FROM \"alice@example.com\"', 'SUBJECT \"invoice\"', 'SINCE 1-Jan-2026'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "IMAP search expression"},
                        "folder": {"type": "string", "default": "INBOX"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            },
        },
    },
    {
        "name": "read_vault_note",
        "fn": read_vault_note,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_vault_note",
                "description": (
                    "Fetch the FULL content of a specific Obsidian note by its "
                    "vault-relative path (e.g. 'AGENT INSTRUCTIONS 2.md'). Use this "
                    "whenever the user names a specific note, or after recall_memory "
                    "surfaces a path you want to read in full. Returns all chunks "
                    "of the note concatenated in heading order."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Vault-relative path or basename of the note (e.g. 'EOS REPORT.md')",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
    },
    {
        "name": "recall_memory",
        "fn": recall_memory,
        "schema": {
            "type": "function",
            "function": {
                "name": "recall_memory",
                "description": (
                    "Semantic search over the user's Obsidian vault. Use this BEFORE "
                    "asking the user for context, whenever you need prior decisions, "
                    "project background, instructions, or domain knowledge. Returns "
                    "top-k matching note chunks with their source file paths."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language query"},
                        "k": {"type": "integer", "description": "Number of results (1-20)", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
    },
    {
        "name": "memory_search",
        "fn": memory_search,
        "schema": {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": "Semantic search for past insights and lessons in the L2 vector database.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language search query"},
                    },
                    "required": ["query"],
                },
            },
        },
    },
    {
        "name": "memory_store",
        "fn": memory_store,
        "schema": {
            "type": "function",
            "function": {
                "name": "memory_store",
                "description": "Store a new insight or lesson learned into the L2 vector database.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "The insight or lesson to store"},
                        "tags": {"type": "string", "description": "Comma-separated tags", "default": ""},
                    },
                    "required": ["content"],
                },
            },
        },
    },
    {
        "name": "task_complete",
        "fn": task_complete,
        "schema": {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Signal that the task is complete. Call this when you are done or stuck.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "Summary of what was accomplished"},
                        "status": {"type": "string", "enum": ["success", "partial", "failed"], "description": "Completion status", "default": "success"},
                    },
                    "required": ["summary"],
                },
            },
        },
    },
    {
        "name": "generate_image",
        "fn": generate_image,
        "schema": {
            "type": "function",
            "function": {
                "name": "generate_image",
                "description": "Generate an image via AI model and save to workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Image generation prompt"},
                    },
                    "required": ["prompt"],
                },
            },
        },
    },
    {
        "name": "generate_video",
        "fn": generate_video,
        "schema": {
            "type": "function",
            "function": {
                "name": "generate_video",
                "description": "Generate a video via AI model.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Video generation prompt"},
                    },
                    "required": ["prompt"],
                },
            },
        },
    },
    {
        "name": "generate_audio",
        "fn": generate_audio,
        "schema": {
            "type": "function",
            "function": {
                "name": "generate_audio",
                "description": "Generate audio/music via AI model.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Audio generation prompt"},
                    },
                    "required": ["prompt"],
                },
            },
        },
    },
    {
        "name": "search_web",
        "fn": search_web,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search the live web for information using DuckDuckGo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            },
        },
    },
    {
        "name": "read_url_content",
        "fn": read_url_content,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_url_content",
                "description": "Read the main text content of a webpage.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Full URL to fetch (must start with http/https)"},
                    },
                    "required": ["url"],
                },
            },
        },
    },
    {
        "name": "submit_for_review",
        "fn": submit_for_review,
        "schema": {
            "type": "function",
            "function": {
                "name": "submit_for_review",
                "description": "Submit an artifact for review by a Quality Control agent.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "artifact_path": {"type": "string", "description": "Path to the artifact to review"},
                        "notes": {"type": "string", "description": "Review notes or specific feedback requested", "default": ""},
                    },
                    "required": ["artifact_path"],
                },
            },
        },
    },
    {
        "name": "delegate_task",
        "fn": delegate_task,
        "schema": {
            "type": "function",
            "function": {
                "name": "delegate_task",
                "description": "Delegate a sub-task to another specialized agent.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_description": {"type": "string", "description": "Description of the task to delegate"},
                        "specialization": {"type": "string", "description": "Specialization required for the task", "default": "general"},
                    },
                    "required": ["task_description"],
                },
            },
        },
    },
    {
        "name": "browser_exec",
        "fn": browser_exec,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_exec",
                "description": (
                    "Drive a real browser via Playwright. Use to navigate, click, fill forms, "
                    "read page text, take screenshots, run JS, or wait for elements on pages that "
                    "require JavaScript rendering. Attaches to an existing Chrome (port 9222) when "
                    "cdp_url or CHROME_CDP_URL is set — reuses the user's logged-in session, so "
                    "OAuth/SSO flows just work. Otherwise launches a fresh headless Chromium. "
                    "The session persists across calls within the same task; call action='close' "
                    "when done. Screenshots land in <workspace>/.browser/."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "navigate", "click", "fill", "get_text", "get_html",
                                "screenshot", "wait_for", "eval_js", "close",
                            ],
                            "description": "The browser action to perform.",
                        },
                        "url": {"type": "string", "description": "Target URL for 'navigate'."},
                        "selector": {
                            "type": "string",
                            "description": (
                                "CSS or Playwright selector for click/fill/get_text/get_html/"
                                "wait_for. For get_text and get_html, omit to read the whole page."
                            ),
                        },
                        "text": {"type": "string", "description": "Value to type for 'fill'."},
                        "script": {"type": "string", "description": "JS source for 'eval_js'."},
                        "cdp_url": {
                            "type": "string",
                            "description": (
                                "Chrome DevTools Protocol endpoint (e.g. 'http://localhost:9222'). "
                                "Overrides CHROME_CDP_URL env var. Empty → launch fresh headless."
                            ),
                            "default": "",
                        },
                        "headless": {
                            "type": "boolean",
                            "description": "When launching (not CDP-attaching), run without a window.",
                            "default": True,
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "description": "Per-action timeout override. 0 → default 15000ms.",
                            "default": 0,
                        },
                        "frame": {
                            "type": "string",
                            "description": (
                                "CSS selector for an <iframe> element. When set, "
                                "'selector' resolves INSIDE that iframe instead of "
                                "the top document. Use for Google Identity Services "
                                "OAuth buttons (frame=\"iframe[src*='accounts.google.com']\"), "
                                "reCAPTCHA, Stripe Elements, embedded YouTube, and any "
                                "cross-origin embed. Leave empty for normal top-document "
                                "selectors."
                            ),
                            "default": "",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
    },
]


def get_allowed_tools(specialization: str) -> list[str] | None:
    try:
        import yaml
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        profiles_path = os.path.join(project_root, "config/profiles.yaml")
        if os.path.exists(profiles_path):
            with open(profiles_path, "r") as f:
                data = yaml.safe_load(f)
                specs = data.get("specializations", {})
                if specialization in specs:
                    return specs[specialization].get("allowed_tools", None)
    except Exception as e:
        logger.warning(f"Could not load specializations config: {e}")
    return None


# ── Dynamic Tool Registry (self-healing: tools registered at runtime) ──

_DYNAMIC_REGISTRY: dict[str, dict] = {}  # name → {fn, schema}


def register_dynamic_tool(name: str, fn, schema: dict):
    """
    Register a tool at runtime.  Called by the self-healing recovery system after
    it implements a previously-missing capability.  The tool becomes immediately
    available to all future agent calls in this worker process.
    """
    _DYNAMIC_REGISTRY[name] = {"fn": fn, "schema": schema}
    logger.info(f"[DYNAMIC TOOL] Registered '{name}' — now available to all agents")


def get_tool_schemas(specialization: str = "general") -> list[dict]:
    """Return tool schemas filtered by specialization, plus plugin tools."""
    allowed = get_allowed_tools(specialization)
    if allowed is not None:
        base = [t["schema"] for t in TOOL_REGISTRY if t["name"] in allowed]
    else:
        base = [t["schema"] for t in TOOL_REGISTRY]
    # Always append dynamic tools (they are available regardless of specialization)
    dynamic = [entry["schema"] for entry in _DYNAMIC_REGISTRY.values()]
    
    # Add plugin tools from registry with namespaced function names
    plugin_schemas = []
    try:
        from src.plugins.registry import registry
        plugin_schemas = registry.get_all_tool_schemas(specialization=specialization)
    except ImportError:
        pass
    
    return base + dynamic + plugin_schemas


# Map function names to plugin tools for lookup
_plugin_fn_map = {}

def _build_plugin_fn_map():
    """Build a mapping from namespaced function names to (tool, method) tuples."""
    global _plugin_fn_map
    _plugin_fn_map = {}
    try:
        from src.plugins.registry import registry
        for tool in registry._tools.values():
            method_map = getattr(tool, '_method_map', {})
            for schema in tool.get_tool_schemas():
                fn_name = schema.get("function", {}).get("name", "")
                if fn_name:
                    namespaced = f"{tool.name}__{fn_name}"
                    method_name = method_map.get(fn_name, fn_name)
                    _plugin_fn_map[namespaced] = (tool, method_name)
        logger.info(f"Built plugin function map with {len(_plugin_fn_map)} functions")
    except ImportError:
        pass


def get_tool_fn(name: str):
    """Look up a tool function by name — checks static registry, dynamic, then plugins."""
    for t in TOOL_REGISTRY:
        if t["name"] == name:
            return t["fn"]
    if name in _DYNAMIC_REGISTRY:
        return _DYNAMIC_REGISTRY[name]["fn"]
    
    # Check plugin registry by namespaced function name
    if not _plugin_fn_map:
        _build_plugin_fn_map()
    
    if name in _plugin_fn_map:
        tool, method_name = _plugin_fn_map[name]
        
        def plugin_wrapper(workspace_dir, **kwargs):
            from src.plugins.base import ToolContext
            import asyncio
            ctx = ToolContext(workspace_dir=workspace_dir, task_id="", envelope=None)
            return asyncio.get_event_loop().run_until_complete(
                tool.call_tool(method_name, kwargs, ctx)
            )
        return plugin_wrapper
    
    return None
