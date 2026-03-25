"""
Mark setup as complete after all config is seeded.

Usage:
    python scripts/complete_setup.py
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL not set")
        sys.exit(1)
    
    try:
        from src.config_db import get_loader
    except ImportError:
        print("❌ Could not import src.config_db")
        sys.exit(1)
    
    loader = get_loader()
    
    # Check for missing config
    missing = loader.get_missing_config()
    if missing:
        print("❌ Cannot complete setup. Missing:")
        for m in missing:
            print(f"   - {m}")
        sys.exit(1)
    
    # Mark complete
    loader.mark_setup_complete()
    print("✅ Setup complete. System ready to start.")

if __name__ == "__main__":
    main()
