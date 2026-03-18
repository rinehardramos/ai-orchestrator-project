#!/usr/bin/env python3
"""
inventory.py — Generates an Ansible inventory from config/cluster_nodes.yaml

Usage:
  python3 scripts/inventory.py              # print INI inventory to stdout
  python3 scripts/inventory.py --json       # print JSON inventory (for ansible --list)
  ansible-playbook -i scripts/inventory.py scripts/deploy.yml

The script is also a valid dynamic inventory script for Ansible.
"""

import yaml
import json
import sys
import os

NODES_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "cluster_nodes.yaml")


def load_nodes():
    with open(NODES_FILE) as f:
        return yaml.safe_load(f).get("nodes", [])


def to_ansible_json(nodes):
    """Output format compatible with Ansible dynamic inventory (--list)."""
    groups = {}
    hostvars = {}

    for n in nodes:
        name = n.get("name", n["host"])
        host = n["host"]
        role = n.get("role", "execution")
        
        # Add to role-specific group
        group = f"{role}_nodes"
        groups.setdefault(group, {"hosts": [], "vars": {}})
        groups[group]["hosts"].append(name)
        
        # Add to convenience plane groups if role matches
        # Observability usually runs on control or execution nodes in small setups
        if role in ['control', 'execution']:
            groups.setdefault("observability_nodes", {"hosts": [], "vars": {}})
            if name not in groups["observability_nodes"]["hosts"]:
                groups["observability_nodes"]["hosts"].append(name)

        # Per-host variables
        hv = {
            "ansible_host": host,
            "plane_role": role,
            "node_name": name,
            "project_dir": n.get("project_dir", "~/ai-orchestrator-project"),
            "ansible_env": {
                "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            }
        }
        if "user" in n:
            hv["ansible_user"] = n["user"]
        if "key" in n:
            hv["ansible_ssh_private_key_file"] = os.path.expanduser(n["key"])
        if host == "localhost":
            hv["ansible_connection"] = "local"

        hostvars[name] = hv

    # Add an "all_nodes" group for convenience
    all_hosts = [n.get("name", n["host"]) for n in nodes]
    groups["all_nodes"] = {"hosts": all_hosts}

    return {
        **groups,
        "_meta": {"hostvars": hostvars},
    }


def to_ini(nodes):
    """Human-readable INI format."""
    lines = []
    groups = {}
    for n in nodes:
        role = n.get("role", "execution")
        groups.setdefault(role, [])
        host = n["host"]
        name = n.get("name", host)
        
        parts = [name]
        parts.append(f"ansible_host={host}")
        if host != "localhost" and "user" in n:
            parts.append(f"ansible_user={n['user']}")
        if "key" in n:
            parts.append(f"ansible_ssh_private_key_file={os.path.expanduser(n['key'])}")
        if host == "localhost":
            parts.append("ansible_connection=local")
        parts.append(f"node_name={name}")
        parts.append(f"project_dir={n.get('project_dir', '~/ai-orchestrator-project')}")
        groups[role].append(" ".join(parts))
        
        # Add to observability group if it's a remote node
        if role in ['control', 'execution']:
            groups.setdefault("observability", [])
            groups["observability"].append(" ".join(parts))

    for group, hosts in groups.items():
        lines.append(f"\n[{group}_nodes]")
        lines.extend(hosts)

    # Combined group
    lines.append("\n[all_nodes:children]")
    for group in groups:
        lines.append(f"{group}_nodes")

    return "\n".join(lines)


if __name__ == "__main__":
    nodes = load_nodes()
    if "--list" in sys.argv or "--json" in sys.argv:
        print(json.dumps(to_ansible_json(nodes), indent=2))
    elif "--host" in sys.argv:
        # Required for Ansible dynamic inventory
        print(json.dumps({}))
    else:
        print(to_ini(nodes))
