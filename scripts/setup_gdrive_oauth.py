#!/usr/bin/env python3
"""
Setup Google Drive OAuth Credentials

This script helps you obtain OAuth credentials for Google Drive access.
You'll need:
1. A Google Cloud Project with Drive API enabled
2. OAuth 2.0 Client ID (Desktop app)

Steps:
1. Go to https://console.cloud.google.com/
2. Create a new project or select existing one
3. Enable Google Drive API:
   - Go to "APIs & Services" > "Library"
   - Search for "Google Drive API" and enable it
4. Create OAuth credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Select "Desktop app" as application type
   - Note the client_id and client_secret
5. Get refresh_token using OAuth playground:
   - Go to https://developers.google.com/oauthplayground
   - Click gear icon, check "Use your own OAuth credentials"
   - Enter client_id and client_secret
   - Select "Drive API v3" > "https://www.googleapis.com/auth/drive"
   - Click "Authorize APIs" and complete the OAuth flow
   - Click "Exchange authorization code for tokens"
   - Copy the refresh_token

Usage:
    python scripts/setup_gdrive_oauth.py --tool gdrive_blackopstech047 \\
        --client-id "YOUR_CLIENT_ID" \\
        --client-secret "YOUR_CLIENT_SECRET" \\
        --refresh-token "YOUR_REFRESH_TOKEN"
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.plugins.loader import encrypt_credential, _load_bootstrap
import psycopg2


def update_credentials(tool_name: str, client_id: str, client_secret: str, refresh_token: str):
    bootstrap = _load_bootstrap()
    db_url = bootstrap.get('database_url')
    secret_key = bootstrap.get('secret_key')
    
    if not db_url or not secret_key:
        print("ERROR: database_url and secret_key required in bootstrap.yaml")
        sys.exit(1)
    
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    # Encrypt and update credentials
    credentials = {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token
    }
    
    for key, value in credentials.items():
        encrypted = encrypt_credential(value, secret_key)
        cur.execute("""
            UPDATE credentials SET value = %s 
            WHERE tool_name = %s AND key = %s
        """, (encrypted, tool_name, key))
        print(f"Updated {tool_name}.{key}")
    
    conn.commit()
    conn.close()
    print(f"\nCredentials updated for {tool_name}")
    print("Restart the worker to load the new credentials: docker restart deploy-ai-worker-1")


def main():
    parser = argparse.ArgumentParser(description='Setup Google Drive OAuth credentials')
    parser.add_argument('--tool', required=True, help='Tool name (e.g., gdrive_blackopstech047)')
    parser.add_argument('--client-id', required=True, help='Google OAuth client ID')
    parser.add_argument('--client-secret', required=True, help='Google OAuth client secret')
    parser.add_argument('--refresh-token', required=True, help='OAuth refresh token')
    
    args = parser.parse_args()
    
    update_credentials(args.tool, args.client_id, args.client_secret, args.refresh_token)


if __name__ == '__main__':
    main()
