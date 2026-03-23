"""
Pytest configuration. Tests that import optional infrastructure packages
(pulumi, temporalio, etc.) are skipped gracefully when those packages are absent.
"""
import sys


def _importable(module_name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(module_name) is not None


# Files to exclude when their required packages are missing
collect_ignore = []

if not _importable("pulumi"):
    collect_ignore.append("test_local_diagnostics.py")

if not _importable("temporalio"):
    collect_ignore.extend([
        "test_integration_live.py",
        "test_local_diagnostics.py",
    ])

if not _importable("langgraph"):
    collect_ignore.extend([
        "test_all_strategies.py",
        "test_coordination_live.py",
        "test_multi_agent.py",
        "test_multi_agent_v2.py",
    ])

if not _importable("duckduckgo_search"):
    collect_ignore.append("test_search.py")
