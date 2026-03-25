#!/usr/bin/env python3
"""
Genesis Node - Infrastructure Drift Check

This script checks for infrastructure drift and reports to the control plane.
Run via cron on the Genesis node.
"""

import os
import sys
import json
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_drift():
    """Check for infrastructure drift and report findings."""
    
    control_plane_url = os.environ.get(
        "CONTROL_PLANE_URL", 
        "http://192.168.100.250:8000"
    )
    
    findings = {
        "timestamp": datetime.utcnow().isoformat(),
        "node": "genesis",
        "checks": []
    }
    
    # Add your drift checks here
    # Example: Check if Docker containers are running
    # Example: Check if required services are available
    # Example: Check disk space
    
    # Report to control plane
    try:
        resp = requests.post(
            f"{control_plane_url}/api/infrastructure/report",
            json=findings,
            timeout=30
        )
        if resp.status_code == 200:
            print(f"[OK] Drift check reported to control plane")
        else:
            print(f"[WARN] Failed to report: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] Failed to report: {e}")
    
    return findings


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    result = check_drift()
    print(json.dumps(result, indent=2))
