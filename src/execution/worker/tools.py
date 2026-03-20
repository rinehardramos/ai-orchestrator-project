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
            shell=True,
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

        # Convert SSH or HTTPS URL to authenticated HTTPS
        # Handle git@github.com:owner/repo.git
        if original_url.startswith("git@github.com:"):
            repo_path = original_url.replace("git@github.com:", "").rstrip(".git")
            auth_url = f"https://x-access-token:{token}@github.com/{repo_path}.git"
        elif "github.com" in original_url:
            # Handle https://github.com/owner/repo.git — inject token
            auth_url = original_url.replace("https://", f"https://x-access-token:{token}@")
        else:
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


def memory_search(workspace_dir: str, query: str) -> str:
    """Semantic search for past insights in Qdrant L2."""
    try:
        import litellm as _litellm
        from src.shared.memory.hybrid_store import HybridMemoryStore
        store = HybridMemoryStore()
        embed_response = _litellm.embedding(model="gemini/gemini-embedding-001", input=[query])
        vector = embed_response.data[0]["embedding"]
        results = store.query_l2("agent_insights", vector, limit=3)
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
        import litellm as _litellm
        from src.shared.memory.hybrid_store import HybridMemoryStore, MemoryEntry
        store = HybridMemoryStore()
        embed_response = _litellm.embedding(model="gemini/gemini-embedding-001", input=[content])
        vector = embed_response.data[0]["embedding"]
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            content=content,
            metadata={"source": "agent", "tags": tags},
        )
        store.store_l2("agent_insights", entry, vector=vector)
        return "OK: Insight stored in L2 memory."
    except Exception as e:
        return f"Memory store failed: {e}"


def task_complete(workspace_dir: str, summary: str, status: str = "success") -> str:
    """Signal that the agent has completed its task."""
    return json.dumps({"action": "task_complete", "summary": summary, "status": status})


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
]


def get_tool_schemas() -> list[dict]:
    """Return the list of tool schemas for the LiteLLM tools parameter."""
    return [t["schema"] for t in TOOL_REGISTRY]


def get_tool_fn(name: str) -> Callable | None:
    """Look up a tool function by name."""
    for t in TOOL_REGISTRY:
        if t["name"] == name:
            return t["fn"]
    return None
