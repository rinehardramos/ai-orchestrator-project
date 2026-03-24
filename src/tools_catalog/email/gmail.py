import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from typing import Any, Dict, List, Optional
from src.plugins.base import Tool, ToolContext


class GmailTool(Tool):
    type = "email"
    name = "gmail"
    description = "Send and read emails via Gmail IMAP/SMTP"
    node = "worker"

    def initialize(self, config: dict) -> None:
        self.config = config
        self.imap_host = config.get("imap_host", "imap.gmail.com")
        self.smtp_host = config.get("smtp_host", "smtp.gmail.com")
        self.smtp_port = config.get("smtp_port", 587)
        self.imap_port = config.get("imap_port", 993)
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.use_tls = config.get("encryption", "tls") == "tls"

    def get_tool_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "email_send",
                    "description": "Send an email to one or more recipients. Use this when you need to send an email message.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {
                                "type": "string",
                                "description": "Recipient email address(es), comma-separated for multiple"
                            },
                            "subject": {
                                "type": "string",
                                "description": "Email subject line"
                            },
                            "body": {
                                "type": "string",
                                "description": "Email body text content"
                            },
                            "cc": {
                                "type": "string",
                                "description": "CC recipients, comma-separated (optional)"
                            },
                            "bcc": {
                                "type": "string",
                                "description": "BCC recipients, comma-separated (optional)"
                            }
                        },
                        "required": ["to", "subject", "body"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "email_read_inbox",
                    "description": "Read emails from inbox. Returns list of emails with sender, subject, date, and body preview.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "folder": {
                                "type": "string",
                                "description": "Mail folder to read (default: INBOX)",
                                "default": "INBOX"
                            },
                            "unread_only": {
                                "type": "boolean",
                                "description": "Only return unread emails (default: true)",
                                "default": True
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of emails to return (default: 10)",
                                "default": 10
                            },
                            "mark_read": {
                                "type": "boolean",
                                "description": "Mark emails as read after fetching (default: false)",
                                "default": False
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "email_search",
                    "description": "Search emails by query. Supports Gmail search syntax.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (e.g., 'from:john@example.com', 'subject:meeting')"
                            },
                            "folder": {
                                "type": "string",
                                "description": "Mail folder to search (default: INBOX)",
                                "default": "INBOX"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results (default: 10)",
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
                    "name": "email_get",
                    "description": "Get full content of a specific email by its ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "email_id": {
                                "type": "string",
                                "description": "The email ID to retrieve"
                            },
                            "folder": {
                                "type": "string",
                                "description": "Mail folder (default: INBOX)",
                                "default": "INBOX"
                            }
                        },
                        "required": ["email_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "email_delete",
                    "description": "Delete an email by its ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "email_id": {
                                "type": "string",
                                "description": "The email ID to delete"
                            },
                            "folder": {
                                "type": "string",
                                "description": "Mail folder (default: INBOX)",
                                "default": "INBOX"
                            }
                        },
                        "required": ["email_id"]
                    }
                }
            }
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> Any:
        if tool_name == "email_send":
            return self._send(**args)
        elif tool_name == "email_read_inbox":
            return self._read_inbox(**args)
        elif tool_name == "email_search":
            return self._search(**args)
        elif tool_name == "email_get":
            return self._get_email(**args)
        elif tool_name == "email_delete":
            return self._delete_email(**args)
        else:
            return f"Unknown tool: {tool_name}"

    def _send(self, to: str, subject: str, body: str, cc: str = None, bcc: str = None) -> str:
        if not self.username or not self.password:
            return "ERROR: Gmail credentials not configured. Set username and password."

        try:
            msg = MIMEMultipart()
            msg["From"] = self.username
            msg["To"] = to
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc
            if bcc:
                msg["Bcc"] = bcc

            msg.attach(MIMEText(body, "plain"))

            recipients = [to]
            if cc:
                recipients.extend([a.strip() for a in cc.split(",")])
            if bcc:
                recipients.extend([a.strip() for a in bcc.split(",")])

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, recipients, msg.as_string())

            return f"Email sent successfully to: {to}"

        except smtplib.SMTPAuthenticationError:
            return "ERROR: Authentication failed. Check username and app password."
        except smtplib.SMTPException as e:
            return f"ERROR: SMTP error: {e}"
        except Exception as e:
            return f"ERROR: Failed to send email: {e}"

    def _read_inbox(self, folder: str = "INBOX", unread_only: bool = True,
                    limit: int = 10, mark_read: bool = False) -> str:
        if not self.username or not self.password:
            return "ERROR: Gmail credentials not configured."

        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as mail:
                mail.login(self.username, self.password)
                mail.select(folder)

                search_criteria = "(UNSEEN)" if unread_only else "ALL"
                status, messages = mail.search(None, search_criteria)

                if status != "OK":
                    return "ERROR: Failed to search inbox."

                email_ids = messages[0].split()[-limit:] if messages[0] else []
                results = []

                for email_id in reversed(email_ids):
                    fetch_status, msg_data = mail.fetch(email_id, "(RFC822)")
                    if fetch_status != "OK":
                        continue

                    email_body = msg_data[0][1]
                    email_message = email.message_from_bytes(email_body)

                    subject = self._decode_header(email_message.get("Subject", ""))
                    sender = self._decode_header(email_message.get("From", ""))
                    date = email_message.get("Date", "")

                    body_preview = self._get_body_preview(email_message)

                    results.append({
                        "id": email_id.decode(),
                        "from": sender,
                        "subject": subject,
                        "date": date,
                        "preview": body_preview[:200] + "..." if len(body_preview) > 200 else body_preview
                    })

                    if mark_read:
                        mail.store(email_id, "+FLAGS", "\\Seen")

                return self._format_email_list(results)

        except imaplib.IMAP4.error as e:
            return f"ERROR: IMAP error: {e}"
        except Exception as e:
            return f"ERROR: Failed to read inbox: {e}"

    def _search(self, query: str, folder: str = "INBOX", limit: int = 10) -> str:
        if not self.username or not self.password:
            return "ERROR: Gmail credentials not configured."

        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as mail:
                mail.login(self.username, self.password)
                mail.select(folder)

                status, messages = mail.search(None, f'({query})')

                if status != "OK":
                    return "ERROR: Search failed."

                email_ids = messages[0].split()[-limit:] if messages[0] else []
                results = []

                for email_id in reversed(email_ids):
                    fetch_status, msg_data = mail.fetch(email_id, "(RFC822)")
                    if fetch_status != "OK":
                        continue

                    email_body = msg_data[0][1]
                    email_message = email.message_from_bytes(email_body)

                    results.append({
                        "id": email_id.decode(),
                        "from": self._decode_header(email_message.get("From", "")),
                        "subject": self._decode_header(email_message.get("Subject", "")),
                        "date": email_message.get("Date", "")
                    })

                return self._format_email_list(results)

        except Exception as e:
            return f"ERROR: Search failed: {e}"

    def _get_email(self, email_id: str, folder: str = "INBOX") -> str:
        if not self.username or not self.password:
            return "ERROR: Gmail credentials not configured."

        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as mail:
                mail.login(self.username, self.password)
                mail.select(folder)

                status, msg_data = mail.fetch(email_id.encode(), "(RFC822)")
                if status != "OK":
                    return "ERROR: Email not found."

                email_body = msg_data[0][1]
                email_message = email.message_from_bytes(email_body)

                subject = self._decode_header(email_message.get("Subject", ""))
                sender = self._decode_header(email_message.get("From", ""))
                date = email_message.get("Date", "")
                body = self._get_body_preview(email_message, full=True)

                return f"From: {sender}\nTo: {email_message.get('To', '')}\nDate: {date}\nSubject: {subject}\n\n{body}"

        except Exception as e:
            return f"ERROR: Failed to get email: {e}"

    def _delete_email(self, email_id: str, folder: str = "INBOX") -> str:
        if not self.username or not self.password:
            return "ERROR: Gmail credentials not configured."

        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as mail:
                mail.login(self.username, self.password)
                mail.select(folder)

                mail.store(email_id.encode(), "+FLAGS", "\\Deleted")
                mail.expunge()

                return f"Email {email_id} deleted successfully."

        except Exception as e:
            return f"ERROR: Failed to delete email: {e}"

    def _decode_header(self, header: str) -> str:
        if not header:
            return ""
        decoded_parts = decode_header(header)
        result = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                result.append(part)
        return "".join(result)

    def _get_body_preview(self, email_message: email.message.Message, full: bool = False) -> str:
        body = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")
                        break
        else:
            payload = email_message.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace")

        return body if full else body[:500]

    def _format_email_list(self, emails: List[dict]) -> str:
        if not emails:
            return "No emails found."

        lines = [f"Found {len(emails)} email(s):\n"]
        for i, e in enumerate(emails, 1):
            lines.append(f"{i}. ID: {e['id']}")
            lines.append(f"   From: {e['from']}")
            lines.append(f"   Subject: {e['subject']}")
            lines.append(f"   Date: {e['date']}")
            if 'preview' in e:
                lines.append(f"   Preview: {e['preview']}")
            lines.append("")

        return "\n".join(lines)


tool_class = GmailTool
