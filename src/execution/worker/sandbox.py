"""
Workspace isolation and command safety for the autonomous agent worker.
"""
import os
import re
import shutil
import tempfile
import logging

logger = logging.getLogger("AgentSandbox")

WORKSPACE_ROOT = os.path.join(tempfile.gettempdir(), "agent-workspaces")  # nosec B108

# Shell commands that are never allowed
COMMAND_BLOCKLIST = [
    r"\brm\s+-rf\s+/",          # rm -rf /
    r"\bsudo\b",                 # any sudo
    r"\bcurl\b.*\|\s*bash",      # curl | bash
    r"\bwget\b.*\|\s*bash",      # wget | bash
    r"\bdd\b\s+if=",            # dd if=
    r"\bmkfs\b",                 # mkfs
    r":>\s*/etc/",              # truncate system files
    r"\bchmod\s+777\s+/",       # chmod 777 /
    r"\bchown\b.*\s+/",         # chown system dirs
    r"\bshutdown\b",            # shutdown
    r"\breboot\b",              # reboot
    r"\binit\s+[0-6]\b",        # init levels
    r"\bkill\s+-9\s+-1\b",      # kill all processes
    r":\(\)\s*\{.*\};\s*:",     # fork bomb
    # Credential leakage prevention
    r"\bgit\s+config\b.*credential",   # git credential store/cache
    r"\bprintenv\b",                    # printenv (list all env vars)
    r"\benv\b\s*$",                     # bare `env` command
    r"\becho\s+\$[A-Z_]",              # echo $ENV_VAR
    r"\bprintf\s.*\$[A-Z_]",           # printf $ENV_VAR
    r"\bcat\s+/proc/.*environ",         # /proc/self/environ
    r"\bset\b\s*$",                     # bare `set` (dumps shell vars)
    r"\bexport\s+-p\b",                 # export -p (list all exports)
]

_BLOCKLIST_COMPILED = [re.compile(p, re.IGNORECASE) for p in COMMAND_BLOCKLIST]


def create_workspace(task_id: str) -> str:
    """Create an isolated workspace directory for an agent task."""
    workspace_dir = os.path.join(WORKSPACE_ROOT, task_id)
    os.makedirs(workspace_dir, exist_ok=True)
    logger.info(f"Created workspace: {workspace_dir}")
    return workspace_dir


def cleanup_workspace(workspace_dir: str):
    """Remove a workspace directory and all its contents."""
    if not workspace_dir or not workspace_dir.startswith(WORKSPACE_ROOT):
        logger.warning(f"Refusing to clean up non-workspace path: {workspace_dir}")
        return
    try:
        shutil.rmtree(workspace_dir, ignore_errors=True)
        logger.info(f"Cleaned up workspace: {workspace_dir}")
    except Exception as e:
        logger.error(f"Failed to clean up workspace {workspace_dir}: {e}")


def validate_path(path: str, workspace_dir: str) -> str:
    """
    Resolve a path and ensure it stays within the workspace.
    Returns the resolved absolute path.
    Raises ValueError if the path escapes the workspace.
    """
    # Handle relative paths by joining with workspace
    if not os.path.isabs(path):
        path = os.path.join(workspace_dir, path)
    resolved = os.path.realpath(path)
    workspace_resolved = os.path.realpath(workspace_dir)
    if not resolved.startswith(workspace_resolved + os.sep) and resolved != workspace_resolved:
        raise ValueError(f"Path '{path}' resolves to '{resolved}' which is outside workspace '{workspace_resolved}'")
    return resolved


def validate_command(cmd: str) -> bool:
    """
    Check a shell command against the blocklist.
    Returns True if the command is safe, False if blocked.
    """
    for pattern in _BLOCKLIST_COMPILED:
        if pattern.search(cmd):
            logger.warning(f"Blocked dangerous command matching pattern: {pattern.pattern}")
            return False
    return True
