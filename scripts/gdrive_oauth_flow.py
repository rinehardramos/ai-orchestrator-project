#!/usr/bin/env python3
"""
Interactive Google Drive OAuth Setup

This script runs a local web server to handle the OAuth flow and obtain
a refresh token for Google Drive API.

Usage:
    python scripts/gdrive_oauth_flow.py --tool gdrive_blackopstech047

You'll need:
1. Google Cloud Project with Drive API enabled
2. OAuth 2.0 Client ID (Web application type for this flow)
3. Authorized redirect URI: http://localhost:8080
"""

import argparse
import json
import os
import sys
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# Global to store the auth code
auth_code = None
auth_state = None


class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code, auth_state
        
        if self.path.startswith('/callback'):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            
            if 'code' in query:
                auth_code = query['code'][0]
                auth_state = query.get('state', [None])[0]
                
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'''
                    <html>
                    <head><title>Success</title></head>
                    <body style="font-family: Arial; text-align: center; padding: 50px;">
                        <h1 style="color: green;">Authentication Successful!</h1>
                        <p>You can close this window and return to the terminal.</p>
                    </body>
                    </html>
                ''')
            elif 'error' in query:
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                error = query['error'][0]
                self.wfile.write(f'''
                    <html>
                    <head><title>Error</title></head>
                    <body style="font-family: Arial; text-align: center; padding: 50px;">
                        <h1 style="color: red;">Authentication Failed</h1>
                        <p>Error: {error}</p>
                    </body>
                    </html>
                '''.encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass  # Suppress server logs


def run_oauth_flow(client_id: str, client_secret: str, port: int = 8080):
    """Run the OAuth flow and return the refresh token."""
    import requests
    
    redirect_uri = f'http://localhost:{port}'
    
    # Scopes for Google Drive
    scopes = ['https://www.googleapis.com/auth/drive']
    
    # Build authorization URL
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
        f"response_type=code&"
        f"scope={urllib.parse.quote(' '.join(scopes))}&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    
    print(f"\nStarting OAuth server on port {port}...")
    print(f"Opening browser for authentication...\n")
    
    # Start local server
    server = HTTPServer(('localhost', port), OAuthHandler)
    
    # Open browser
    webbrowser.open(auth_url)
    
    print("Waiting for authorization...")
    print("If the browser doesn't open, visit this URL manually:")
    print(f"\n{auth_url}\n")
    
    # Handle one request (the callback)
    server.handle_request()
    server.server_close()
    
    if not auth_code:
        print("ERROR: No authorization code received")
        return None
    
    print("\nAuthorization code received!")
    print("Exchanging for tokens...")
    
    # Exchange code for tokens
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        'code': auth_code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }
    
    response = requests.post(token_url, data=token_data)
    
    if response.status_code != 200:
        print(f"ERROR: Token exchange failed: {response.text}")
        return None
    
    tokens = response.json()
    refresh_token = tokens.get('refresh_token')
    
    if not refresh_token:
        print("ERROR: No refresh_token in response. Make sure to include 'prompt=consent'")
        return None
    
    print("\nRefresh token obtained successfully!")
    return refresh_token


def save_credentials(tool_name: str, client_id: str, client_secret: str, refresh_token: str):
    """Save encrypted credentials to database."""
    from src.plugins.loader import encrypt_credential, _load_bootstrap
    import psycopg2
    
    bootstrap = _load_bootstrap()
    db_url = bootstrap.get('database_url')
    secret_key = bootstrap.get('secret_key')
    
    if not db_url or not secret_key:
        print("ERROR: database_url and secret_key required in bootstrap.yaml")
        return False
    
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
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
        print(f"  Updated {tool_name}.{key}")
    
    conn.commit()
    conn.close()
    return True


def main():
    parser = argparse.ArgumentParser(description='Interactive Google Drive OAuth setup')
    parser.add_argument('--tool', required=True, help='Tool name (e.g., gdrive_blackopstech047)')
    parser.add_argument('--client-id', required=True, help='Google OAuth client ID')
    parser.add_argument('--client-secret', required=True, help='Google OAuth client secret')
    parser.add_argument('--port', type=int, default=8080, help='Local port for callback (default: 8080)')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print(f"Google Drive OAuth Setup for {args.tool}")
    print("=" * 60)
    
    print("\nPrerequisites:")
    print("1. Go to https://console.cloud.google.com/")
    print("2. Create/select a project")
    print("3. Enable Google Drive API (APIs & Services > Library)")
    print("4. Create OAuth 2.0 Client ID (APIs & Services > Credentials)")
    print("   - Application type: Web application")
    print(f"   - Authorized redirect URI: http://localhost:{args.port}")
    print("5. Copy the client_id and client_secret")
    print()
    
    # Run OAuth flow
    refresh_token = run_oauth_flow(args.client_id, args.client_secret, args.port)
    
    if not refresh_token:
        sys.exit(1)
    
    print("\nSaving credentials to database...")
    if save_credentials(args.tool, args.client_id, args.client_secret, refresh_token):
        print(f"\nCredentials saved for {args.tool}")
        print("\nRestart the worker to load the new credentials:")
        print("  docker restart central_node-ai-worker-1")
    else:
        print("\nFailed to save credentials")
        sys.exit(1)


if __name__ == '__main__':
    main()
