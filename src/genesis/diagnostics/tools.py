import subprocess
import psutil
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger("AgentTools")


class AgentTools:
    """
    Tools available to the DiagnosticAgent for observing and acting on the system.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

    def check_service_status(self, service_name: str) -> Dict[str, Any]:
        result = {"service": service_name, "status": "unknown", "details": {}}
        
        docker_names = ["temporal", "qdrant", "redis", "litellm", "postgres"]
        if service_name in docker_names:
            try:
                proc = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Status}}", service_name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    result["status"] = proc.stdout.strip()
                else:
                    result["status"] = "not_found"
                    result["details"]["error"] = proc.stderr
            except Exception as e:
                result["details"]["error"] = str(e)
        else:
            try:
                proc = subprocess.run(
                    ["systemctl", "is-active", service_name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                result["status"] = proc.stdout.strip()
            except Exception as e:
                result["details"]["error"] = str(e)
        
        return result

    def read_logs(
        self, service_name: str, lines: int = 100, since: str = "1h"
    ) -> Dict[str, Any]:
        result = {"service": service_name, "logs": "", "error": None}
        
        docker_names = ["temporal", "qdrant", "redis", "litellm", "postgres"]
        
        try:
            if service_name in docker_names:
                cmd = ["docker", "logs", "--tail", str(lines), "--since", since, service_name]
            else:
                cmd = ["journalctl", "-u", service_name, "-n", str(lines), "--since", since]
            
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            result["logs"] = proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout
            if proc.stderr:
                result["error"] = proc.stderr[:500]
        except subprocess.TimeoutExpired:
            result["error"] = "Log fetch timed out"
        except Exception as e:
            result["error"] = str(e)
        
        return result

    def read_metrics(self) -> Dict[str, Any]:
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            
            return {
                "cpu_percent": cpu_percent,
                "memory": {
                    "total_gb": round(memory.total / (1024**3), 2),
                    "available_gb": round(memory.available / (1024**3), 2),
                    "percent": memory.percent,
                },
                "disk": {
                    "total_gb": round(disk.total / (1024**3), 2),
                    "free_gb": round(disk.free / (1024**3), 2),
                    "percent": disk.percent,
                },
            }
        except Exception as e:
            return {"error": str(e)}

    def list_docker_containers(self) -> Dict[str, Any]:
        result = {"containers": [], "error": None}
        
        try:
            proc = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if proc.returncode == 0:
                for line in proc.stdout.strip().split("\n"):
                    if line:
                        parts = line.split("\t")
                        result["containers"].append({
                            "name": parts[0] if len(parts) > 0 else "",
                            "status": parts[1] if len(parts) > 1 else "",
                            "ports": parts[2] if len(parts) > 2 else "",
                        })
            else:
                result["error"] = proc.stderr
        except Exception as e:
            result["error"] = str(e)
        
        return result

    def get_port_bindings(self) -> Dict[str, Any]:
        result = {"ports": {}, "error": None}
        
        try:
            proc = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if proc.returncode == 0:
                for line in proc.stdout.strip().split("\n"):
                    if line:
                        parts = line.split("\t")
                        if len(parts) >= 2:
                            result["ports"][parts[0]] = parts[1]
        except Exception as e:
            result["error"] = str(e)
        
        return result

    def check_port(self, host: str, port: int, timeout: float = 3.0) -> Dict[str, Any]:
        import socket
        
        result = {"host": host, "port": port, "open": False, "error": None}
        
        try:
            with socket.create_connection((host, port), timeout=timeout):
                result["open"] = True
        except socket.timeout:
            result["error"] = "timeout"
        except ConnectionRefusedError:
            result["error"] = "connection_refused"
        except Exception as e:
            result["error"] = str(e)
        
        return result

    def http_health(self, url: str, timeout: float = 5.0) -> Dict[str, Any]:
        import requests
        
        result = {"url": url, "status": None, "latency_ms": None, "error": None}
        
        try:
            import time
            start = time.time()
            resp = requests.get(url, timeout=timeout)
            result["latency_ms"] = round((time.time() - start) * 1000, 2)
            result["status"] = resp.status_code
        except requests.exceptions.Timeout:
            result["error"] = "timeout"
        except requests.exceptions.ConnectionError:
            result["error"] = "connection_failed"
        except Exception as e:
            result["error"] = str(e)
        
        return result

    def get_system_processes(self, filter_name: str = None) -> List[Dict[str, Any]]:
        processes = []
        
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                if filter_name and filter_name.lower() not in info["name"].lower():
                    continue
                processes.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return sorted(processes, key=lambda x: x.get("cpu_percent", 0), reverse=True)[:20]

    def kill_process(self, pid: int) -> Dict[str, Any]:
        result = {"pid": pid, "killed": False, "error": None}
        
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
            result["killed"] = True
        except psutil.NoSuchProcess:
            result["error"] = "process_not_found"
        except psutil.TimeoutExpired:
            try:
                proc.kill()
                result["killed"] = True
            except Exception as e:
                result["error"] = str(e)
        except Exception as e:
            result["error"] = str(e)
        
        return result
