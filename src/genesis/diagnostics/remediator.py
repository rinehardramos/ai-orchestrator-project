import subprocess
import time
import logging
import os
from typing import Dict, Optional, List

from src.genesis.diagnostics.models import (
    RemediationAction,
    RemediationStep,
    ActionResult,
    ServiceType,
)

logger = logging.getLogger("Remediator")


class Remediator:
    """
    Executes remediation actions for system recovery.
    Uses systemctl/docker commands for service management.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._dry_run = False

    def set_dry_run(self, enabled: bool = True):
        self._dry_run = enabled

    def _run_command(
        self, command: List[str], timeout: int = 30
    ) -> tuple[bool, str, str]:
        if self._dry_run:
            return True, f"[DRY RUN] Would execute: {' '.join(command)}", ""
        
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            success = result.returncode == 0
            return success, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)

    def restart_service(self, service_name: str) -> ActionResult:
        start = time.time()
        step = RemediationStep(
            action=RemediationAction.RESTART_SERVICE,
            target=service_name,
            description=f"Restart {service_name}",
        )
        
        service_map = {
            "temporal": ["docker", "restart", "temporal"],
            "temporal-ui": ["docker", "restart", "temporal-ui"],
            "qdrant": ["docker", "restart", "qdrant"],
            "redis": ["docker", "restart", "redis"],
            "litellm": ["docker", "restart", "litellm"],
            "postgres": ["docker", "restart", "postgres"],
        }
        
        if service_name in service_map:
            command = service_map[service_name]
        else:
            command = ["systemctl", "restart", service_name]
        
        success, stdout, stderr = self._run_command(command)
        
        return ActionResult(
            step=step,
            success=success,
            output=stdout or None,
            error=stderr if stderr else None,
            duration_ms=(time.time() - start) * 1000,
        )

    def flush_cache(self, target: str = "redis") -> ActionResult:
        start = time.time()
        step = RemediationStep(
            action=RemediationAction.FLUSH_CACHE,
            target=target,
            description=f"Flush {target} cache",
        )
        
        if target == "redis":
            command = ["docker", "exec", "redis", "redis-cli", "FLUSHALL"]
        else:
            command = ["docker", "exec", target, "cache:clear"]
        
        success, stdout, stderr = self._run_command(command)
        
        return ActionResult(
            step=step,
            success=success,
            output=stdout or None,
            error=stderr if stderr else None,
            duration_ms=(time.time() - start) * 1000,
        )

    def cleanup_logs(self, max_age_days: int = 7) -> ActionResult:
        start = time.time()
        step = RemediationStep(
            action=RemediationAction.CLEANUP_LOGS,
            target="system",
            description=f"Clean up logs older than {max_age_days} days",
        )
        
        command = [
            "find",
            "/var/log",
            "-name",
            "*.log",
            "-mtime",
            f"+{max_age_days}",
            "-delete",
        ]
        
        success, stdout, stderr = self._run_command(command)
        
        return ActionResult(
            step=step,
            success=success,
            output=stdout or None,
            error=stderr if stderr else None,
            duration_ms=(time.time() - start) * 1000,
        )

    def execute_shell(self, command: str) -> ActionResult:
        start = time.time()
        step = RemediationStep(
            action=RemediationAction.EXECUTE_SHELL,
            target="system",
            description=f"Execute: {command[:50]}...",
            params={"command": command},
        )
        
        success, stdout, stderr = self._run_command(command.split())
        
        return ActionResult(
            step=step,
            success=success,
            output=stdout or None,
            error=stderr if stderr else None,
            duration_ms=(time.time() - start) * 1000,
        )

    def restart_via_ssh(
        self, host: str, service_name: str, ssh_user: str = None, ssh_key: str = None
    ) -> ActionResult:
        start = time.time()
        step = RemediationStep(
            action=RemediationAction.RESTART_SERVICE,
            target=f"{host}:{service_name}",
            description=f"Restart {service_name} on {host}",
        )
        
        remote_cfg = self.config.get("remote_worker", {})
        ssh_user = ssh_user or remote_cfg.get("user", "root")
        ssh_key = ssh_key or remote_cfg.get("ssh_key_path", "~/.ssh/id_rsa")
        port = remote_cfg.get("port", 22)
        
        command = [
            "ssh",
            "-i", os.path.expanduser(ssh_key),
            "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{ssh_user}@{host}",
            f"docker restart {service_name}",
        ]
        
        success, stdout, stderr = self._run_command(command, timeout=60)
        
        return ActionResult(
            step=step,
            success=success,
            output=stdout or None,
            error=stderr if stderr else None,
            duration_ms=(time.time() - start) * 1000,
        )

    def execute_step(self, step: RemediationStep) -> ActionResult:
        action_handlers = {
            RemediationAction.RESTART_SERVICE: lambda: self.restart_service(step.target),
            RemediationAction.FLUSH_CACHE: lambda: self.flush_cache(step.target),
            RemediationAction.CLEANUP_LOGS: lambda: self.cleanup_logs(
                step.params.get("max_age_days", 7)
            ),
            RemediationAction.EXECUTE_SHELL: lambda: self.execute_shell(
                step.params.get("command", "")
            ),
        }
        
        handler = action_handlers.get(step.action)
        if handler:
            return handler()
        
        return ActionResult(
            step=step,
            success=False,
            error=f"No handler for action: {step.action}",
        )
