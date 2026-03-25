"""
Validate database configuration before starting services.

Exit codes:
    0 - Config valid
    1 - Config missing or invalid
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    try:
        from src.config_db import get_loader
    except ImportError:
        print("❌ Could not import src.config_db")
        return 1

    loader = get_loader()
    
    if loader.validate_setup():
        print("✅ Database configuration valid")
        return 0
    
    missing = loader.get_missing_config()
    print("❌ Database configuration incomplete:")
    for m in missing:
        print(f"   - {m}")
    return 1

if __name__ == "__main__":
    sys.exit(main())
