"""
Google Drive Tool

Supports multiple instances with different OAuth credentials.
Uses Google Drive API v3 for file operations.

Credentials needed (store in database):
- client_id: Google OAuth client ID
- client_secret: Google OAuth client secret  
- refresh_token: OAuth refresh token for the user

To get credentials:
1. Go to Google Cloud Console > APIs & Services > Credentials
2. Create OAuth 2.0 Client ID (Desktop app)
3. Enable Google Drive API
4. Use OAuth playground to get refresh_token for the user
"""

import os
import io
import json
from typing import Any, Dict, List, Optional
from src.plugins.base import Tool, ToolContext

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False


class GoogleDriveTool(Tool):
    type = "storage"
    name = "gdrive"
    description = "Read, write, and manage files in Google Drive"
    node = "worker"
    
    _method_map = {
        "drive_list": "_list_files",
        "drive_read": "_read_file",
        "drive_write": "_write_file",
        "drive_delete": "_delete_file",
        "drive_search": "_search_files",
        "drive_create_folder": "_create_folder",
        "drive_share": "_share_file",
    }
    
    SCOPES = ['https://www.googleapis.com/auth/drive']

    def initialize(self, config: dict) -> None:
        if not GOOGLE_AVAILABLE:
            raise ImportError("google-api-python-client and google-auth-oauthlib required")
        
        self.config = config
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.refresh_token = config.get("refresh_token", "")
        self._service = None
        self._creds = None

    def _get_service(self):
        if self._service is not None:
            return self._service
        
        if not self.client_id or not self.client_secret or not self.refresh_token:
            raise ValueError("Google Drive credentials not configured. Need client_id, client_secret, and refresh_token")
        
        self._creds = Credentials(
            token=None,
            refresh_token=self.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=self.SCOPES
        )
        
        self._creds.refresh(Request())
        
        self._service = build('drive', 'v3', credentials=self._creds)
        return self._service

    def get_tool_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "drive_list",
                    "description": "List files in Google Drive. Optionally filter by folder ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "folder_id": {
                                "type": "string",
                                "description": "Folder ID to list (optional, defaults to root)"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of files to return (default: 20)",
                                "default": 20
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "drive_read",
                    "description": "Read a file's content from Google Drive by its ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_id": {
                                "type": "string",
                                "description": "The Google Drive file ID"
                            },
                            "export_format": {
                                "type": "string",
                                "description": "For Google Docs/Sheets: export format (text/plain, text/csv, application/pdf)",
                                "default": "text/plain"
                            }
                        },
                        "required": ["file_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "drive_write",
                    "description": "Create or update a file in Google Drive.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "File name"
                            },
                            "content": {
                                "type": "string",
                                "description": "File content (text)"
                            },
                            "folder_id": {
                                "type": "string",
                                "description": "Parent folder ID (optional, defaults to root)"
                            },
                            "mime_type": {
                                "type": "string",
                                "description": "MIME type (default: text/plain)",
                                "default": "text/plain"
                            }
                        },
                        "required": ["name", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "drive_delete",
                    "description": "Delete a file from Google Drive by its ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_id": {
                                "type": "string",
                                "description": "The Google Drive file ID to delete"
                            }
                        },
                        "required": ["file_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "drive_search",
                    "description": "Search for files in Google Drive by name or query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (e.g., 'name contains \"report\"')"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum results (default: 10)",
                                "default": 10
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "drive_create_folder",
                    "description": "Create a new folder in Google Drive.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Folder name"
                            },
                            "parent_id": {
                                "type": "string",
                                "description": "Parent folder ID (optional, defaults to root)"
                            }
                        },
                        "required": ["name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "drive_share",
                    "description": "Share a file with another user by email.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_id": {
                                "type": "string",
                                "description": "File ID to share"
                            },
                            "email": {
                                "type": "string",
                                "description": "Email address to share with"
                            },
                            "role": {
                                "type": "string",
                                "description": "Permission role: reader, writer, commenter",
                                "default": "reader"
                            }
                        },
                        "required": ["file_id", "email"]
                    }
                }
            }
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> Any:
        method_map = {
            "drive_list": self._list_files,
            "drive_read": self._read_file,
            "drive_write": self._write_file,
            "drive_delete": self._delete_file,
            "drive_search": self._search_files,
            "drive_create_folder": self._create_folder,
            "drive_share": self._share_file,
        }
        
        if tool_name in method_map:
            return method_map[tool_name](**args)
        return f"Unknown tool: {tool_name}"

    def _list_files(self, folder_id: str = "root", limit: int = 20) -> str:
        try:
            service = self._get_service()
            
            query = f"'{folder_id}' in parents and trashed = false" if folder_id != "root" else "'root' in parents and trashed = false"
            
            results = service.files().list(
                q=query,
                pageSize=limit,
                fields="files(id, name, mimeType, size, modifiedTime, webViewLink)"
            ).execute()
            
            files = results.get('files', [])
            
            if not files:
                return "No files found in this folder."
            
            lines = [f"Found {len(files)} file(s):\n"]
            for f in files:
                size = f.get('size', 'N/A')
                if size != 'N/A':
                    size = f"{int(size) / 1024:.1f} KB"
                lines.append(f"- {f['name']}")
                lines.append(f"  ID: {f['id']}")
                lines.append(f"  Type: {f.get('mimeType', 'unknown')}")
                lines.append(f"  Size: {size}")
                lines.append(f"  Modified: {f.get('modifiedTime', 'N/A')}")
                lines.append("")
            
            return "\n".join(lines)
            
        except Exception as e:
            return f"ERROR: Failed to list files: {e}"

    def _read_file(self, file_id: str, export_format: str = "text/plain") -> str:
        try:
            service = self._get_service()
            
            file_meta = service.files().get(fileId=file_id).execute()
            mime_type = file_meta.get('mimeType', '')
            
            if 'google-apps' in mime_type:
                if 'document' in mime_type:
                    mime_type = 'text/plain'
                elif 'spreadsheet' in mime_type:
                    mime_type = 'text/csv'
                elif 'presentation' in mime_type:
                    mime_type = 'text/plain'
                else:
                    mime_type = export_format
                
                request = service.files().export_media(fileId=file_id, mimeType=mime_type)
            else:
                request = service.files().get_media(fileId=file_id)
            
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            content = fh.getvalue().decode('utf-8', errors='replace')
            
            if len(content) > 10000:
                content = content[:10000] + "\n\n... [truncated]"
            
            return f"File: {file_meta.get('name', file_id)}\n\n{content}"
            
        except Exception as e:
            return f"ERROR: Failed to read file: {e}"

    def _write_file(self, name: str, content: str, folder_id: str = None, mime_type: str = "text/plain") -> str:
        try:
            service = self._get_service()
            
            file_metadata = {'name': name}
            if folder_id:
                file_metadata['parents'] = [folder_id]
            
            media = MediaIoBaseUpload(
                io.BytesIO(content.encode('utf-8')),
                mimetype=mime_type,
                resumable=True
            )
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()
            
            return f"File created successfully:\n- Name: {file['name']}\n- ID: {file['id']}\n- Link: {file.get('webViewLink', 'N/A')}"
            
        except Exception as e:
            return f"ERROR: Failed to write file: {e}"

    def _delete_file(self, file_id: str) -> str:
        try:
            service = self._get_service()
            service.files().delete(fileId=file_id).execute()
            return f"File {file_id} deleted successfully."
        except Exception as e:
            return f"ERROR: Failed to delete file: {e}"

    def _search_files(self, query: str, limit: int = 10) -> str:
        try:
            service = self._get_service()
            
            full_query = f"name contains '{query}' and trashed = false"
            
            results = service.files().list(
                q=full_query,
                pageSize=limit,
                fields="files(id, name, mimeType, size, modifiedTime, webViewLink)"
            ).execute()
            
            files = results.get('files', [])
            
            if not files:
                return f"No files found matching '{query}'."
            
            lines = [f"Found {len(files)} file(s) matching '{query}':\n"]
            for f in files:
                lines.append(f"- {f['name']} (ID: {f['id']})")
                lines.append(f"  Type: {f.get('mimeType', 'unknown')}")
                lines.append(f"  Link: {f.get('webViewLink', 'N/A')}")
                lines.append("")
            
            return "\n".join(lines)
            
        except Exception as e:
            return f"ERROR: Search failed: {e}"

    def _create_folder(self, name: str, parent_id: str = None) -> str:
        try:
            service = self._get_service()
            
            file_metadata = {
                'name': name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            if parent_id:
                file_metadata['parents'] = [parent_id]
            
            folder = service.files().create(
                body=file_metadata,
                fields='id, name, webViewLink'
            ).execute()
            
            return f"Folder created successfully:\n- Name: {folder['name']}\n- ID: {folder['id']}\n- Link: {folder.get('webViewLink', 'N/A')}"
            
        except Exception as e:
            return f"ERROR: Failed to create folder: {e}"

    def _share_file(self, file_id: str, email: str, role: str = "reader") -> str:
        try:
            service = self._get_service()
            
            permission = {
                'type': 'user',
                'role': role,
                'emailAddress': email
            }
            
            service.permissions().create(
                fileId=file_id,
                body=permission,
                sendNotificationEmail=True
            ).execute()
            
            return f"File shared successfully with {email} as {role}."
            
        except Exception as e:
            return f"ERROR: Failed to share file: {e}"


tool_class = GoogleDriveTool
