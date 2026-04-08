"""stdio MCP server for the info-broker REST API."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

import requests

log = logging.getLogger(__name__)

DEFAULT_URL = "http://host.docker.internal:8000"


class InfoBrokerError(RuntimeError):
    pass


class InfoBrokerClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = (base_url or os.environ.get("INFO_BROKER_URL") or DEFAULT_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("INFO_BROKER_API_KEY") or "changeme"
        self.timeout = timeout
        self._session = requests.Session()

    def _headers(self, auth: bool = True) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if auth:
            h["X-API-Key"] = self.api_key
        return h

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        auth: bool = True,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.request(
                method,
                url,
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=json_body,
                headers=self._headers(auth=auth),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise InfoBrokerError(f"HTTP {method} {url} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise InfoBrokerError(
                f"{method} {path} returned {resp.status_code}: {resp.text[:500]}"
            )
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise InfoBrokerError(
                f"{method} {path} returned non-JSON: {resp.text[:500]}"
            ) from exc

    # ── Tool implementations (1:1 with REST endpoints) ──────────────
    def healthz(self) -> Any:
        return self._request("GET", "/healthz", auth=False)

    def list_profiles(self, limit: int = 10, offset: int = 0) -> Any:
        return self._request("GET", "/profiles", params={"limit": limit, "offset": offset})

    def get_profile(self, profile_id: str) -> Any:
        return self._request("GET", f"/profiles/{profile_id}")

    def get_profile_raw(self, profile_id: str) -> Any:
        return self._request("GET", f"/profiles/{profile_id}/raw")

    def grade_profile(self, profile_id: str, grade: int, feedback: str = "") -> Any:
        return self._request(
            "POST",
            f"/profiles/{profile_id}/grade",
            json_body={"grade": grade, "feedback": feedback},
        )

    def ingest(self, overwrite: bool = False) -> Any:
        return self._request("POST", "/ingest", json_body={"overwrite": overwrite})

    def research(self, limit: int = 5) -> Any:
        return self._request("POST", "/research", json_body={"limit": limit})

    def search(self, query: str, limit: int = 10) -> Any:
        return self._request(
            "POST", "/search", json_body={"query": query, "limit": limit}
        )

    def get_weather(
        self,
        city: Optional[str] = None,
        country_code: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
    ) -> Any:
        if not city and (lat is None or lon is None):
            raise ValueError("city or lat+lon required")
        return self._request(
            "GET",
            "/v1/weather",
            params={"city": city, "country_code": country_code, "lat": lat, "lon": lon},
        )

    def get_news(
        self,
        scope: str = "global",
        topic: str = "any",
        country_code: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 10,
    ) -> Any:
        return self._request(
            "GET",
            "/v1/news",
            params={
                "scope": scope,
                "topic": topic,
                "country_code": country_code,
                "query": query,
                "limit": limit,
            },
        )

    def get_song_enrichment(self, title: str, artist: str) -> Any:
        return self._request(
            "GET", "/v1/songs/enrich", params={"title": title, "artist": artist}
        )

    def get_joke(self, style: str = "any", safe: bool = True) -> Any:
        return self._request(
            "GET", "/v1/jokes", params={"style": style, "safe": str(safe).lower()}
        )


def run() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    client = InfoBrokerClient()
    server: Any = Server("info-broker-mcp")

    tools = [
        Tool(name="healthz", description="Liveness probe for info-broker (no auth).",
             inputSchema={"type": "object", "properties": {}}),
        Tool(name="list_profiles", description="List ingested profiles, paginated.",
             inputSchema={"type": "object", "properties": {
                 "limit": {"type": "integer", "default": 10},
                 "offset": {"type": "integer", "default": 0}}}),
        Tool(name="get_profile", description="Fetch a single profile by id.",
             inputSchema={"type": "object", "properties": {"profile_id": {"type": "string"}},
                          "required": ["profile_id"]}),
        Tool(name="get_profile_raw", description="Fetch the raw scraped JSON for a profile.",
             inputSchema={"type": "object", "properties": {"profile_id": {"type": "string"}},
                          "required": ["profile_id"]}),
        Tool(name="grade_profile", description="Record a 1-5 grade + feedback on a profile.",
             inputSchema={"type": "object", "properties": {
                 "profile_id": {"type": "string"},
                 "grade": {"type": "integer", "minimum": 1, "maximum": 5},
                 "feedback": {"type": "string", "default": ""}},
                 "required": ["profile_id", "grade"]}),
        Tool(name="ingest", description="Pull a fresh profile batch from Apify.",
             inputSchema={"type": "object", "properties": {
                 "overwrite": {"type": "boolean", "default": False}}}),
        Tool(name="research", description="Run the research agent on up to N pending profiles.",
             inputSchema={"type": "object", "properties": {
                 "limit": {"type": "integer", "default": 5}}}),
        Tool(name="search", description="Semantic search over ingested profiles via Qdrant.",
             inputSchema={"type": "object", "properties": {
                 "query": {"type": "string"},
                 "limit": {"type": "integer", "default": 10}},
                 "required": ["query"]}),
        Tool(name="get_weather",
             description="Current weather for a city or lat/lon. Provide 'city' (+ optional 'country_code') or both 'lat' and 'lon'.",
             inputSchema={"type": "object", "properties": {
                 "city": {"type": "string"},
                 "country_code": {"type": "string", "minLength": 2, "maxLength": 2},
                 "lat": {"type": "number"},
                 "lon": {"type": "number"}}}),
        Tool(name="get_news", description="Top news headlines, optionally scoped + filtered.",
             inputSchema={"type": "object", "properties": {
                 "scope": {"type": "string", "enum": ["global", "country", "local"], "default": "global"},
                 "topic": {"type": "string", "default": "any"},
                 "country_code": {"type": "string", "minLength": 2, "maxLength": 2},
                 "query": {"type": "string"},
                 "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50}}}),
        Tool(name="get_song_enrichment",
             description="Enrich a (title, artist) pair with album/year/genre/trivia.",
             inputSchema={"type": "object", "properties": {
                 "title": {"type": "string"},
                 "artist": {"type": "string"}},
                 "required": ["title", "artist"]}),
        Tool(name="get_joke", description="Fetch a single joke, optionally styled + safety-filtered.",
             inputSchema={"type": "object", "properties": {
                 "style": {"type": "string", "default": "any"},
                 "safe": {"type": "boolean", "default": True}}}),
    ]

    dispatch = {
        "healthz": client.healthz,
        "list_profiles": client.list_profiles,
        "get_profile": client.get_profile,
        "get_profile_raw": client.get_profile_raw,
        "grade_profile": client.grade_profile,
        "ingest": client.ingest,
        "research": client.research,
        "search": client.search,
        "get_weather": client.get_weather,
        "get_news": client.get_news,
        "get_song_enrichment": client.get_song_enrichment,
        "get_joke": client.get_joke,
    }

    @server.list_tools()
    async def _list():  # type: ignore[no-untyped-def]
        return tools

    @server.call_tool()
    async def _call(name: str, arguments: dict):  # type: ignore[no-untyped-def]
        arguments = arguments or {}
        fn = dispatch.get(name)
        if fn is None:
            return [TextContent(type="text", text=f"error: unknown tool {name!r}")]
        try:
            result = fn(**arguments)
        except Exception as exc:
            return [TextContent(type="text", text=f"error: {exc}")]
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    async def _main():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_main())
