"""
Image analysis tool using vision models.

Supports:
- Object detection and description
- Text extraction (OCR)
- Visual question answering
- Multiple providers (Gemini, GPT-4V, Claude)
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from typing import Optional

import httpx
import yaml

from src.plugins.base import Tool, ToolContext

log = logging.getLogger(__name__)


class AnalyzeImageTool(Tool):
    type = "media"
    name = "analyze_image"
    description = "Analyze images using vision AI models"
    node = "worker"

    def initialize(self, config: dict) -> None:
        self.config = config
        self._media_config = None

    def _load_media_config(self) -> dict:
        if self._media_config is None:
            config_path = os.path.join(os.path.dirname(__file__), "../../../config/media.yaml")
            try:
                with open(config_path) as f:
                    self._media_config = yaml.safe_load(f)
            except Exception as e:
                log.warning(f"Could not load media.yaml, using defaults: {e}")
                self._media_config = self._default_config()
        return self._media_config

    def _default_config(self) -> dict:
        return {
            "vision": {
                "tiers": {
                    "fast": {"primary": "google/gemini-2.0-flash", "fallback": "openai/gpt-4o-mini"},
                    "accurate": {"primary": "openai/gpt-4o", "fallback": "google/gemini-2.5-pro-preview-05-06"}
                }
            },
            "limits": {"max_file_size_mb": 25, "timeout_seconds": 30}
        }

    def get_tool_schemas(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "analyze_image",
                    "description": (
                        "Analyze an image and answer questions about its content. "
                        "Can describe objects, read text, identify colors, etc."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "image_file": {
                                "type": "string",
                                "description": "Path to the image file to analyze"
                            },
                            "question": {
                                "type": "string",
                                "description": "What to analyze or ask about the image. Leave empty for general description.",
                                "default": "Describe this image in detail."
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["fast", "accurate"],
                                "default": "fast",
                                "description": "fast=quick analysis, accurate=detailed analysis"
                            },
                            "model_override": {
                                "type": "string",
                                "description": "Override automatic model selection"
                            }
                        },
                        "required": ["image_file"]
                    }
                }
            }
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> str:
        if tool_name != "analyze_image":
            return f"ERROR: Unknown tool '{tool_name}'"

        image_file = args.get("image_file")
        question = args.get("question", "Describe this image in detail.")
        mode = args.get("mode", "fast")
        model_override = args.get("model_override")

        if not image_file:
            return "ERROR: image_file parameter is required"

        if not os.path.isabs(image_file):
            image_file = os.path.join(ctx.workspace_dir, image_file)

        if not os.path.exists(image_file):
            return f"ERROR: Image file not found: {image_file}"

        config = self._load_media_config()
        limits = config.get("limits", {})

        file_size_mb = os.path.getsize(image_file) / (1024 * 1024)
        if file_size_mb > limits.get("max_file_size_mb", 25):
            return f"ERROR: File too large ({file_size_mb:.1f}MB). Max: {limits.get('max_file_size_mb', 25)}MB"

        try:
            result = await self._analyze(image_file, question, mode, model_override, config)
            return result
        except Exception as e:
            log.exception(f"Image analysis failed: {e}")
            return f"ERROR: Image analysis failed: {str(e)}"

    async def _analyze(self, image_path: str, question: str, mode: str, 
                       model_override: Optional[str], config: dict) -> str:
        tiers = config.get("vision", {}).get("tiers", {})
        
        model = model_override or tiers.get(mode, tiers.get("fast", {})).get("primary", "google/gemini-2.0-flash")
        fallback = tiers.get(mode, {}).get("fallback")

        result = await self._try_analyze_with_model(image_path, question, model)

        if result.startswith("ERROR") and fallback:
            log.warning(f"Primary model {model} failed, trying fallback {fallback}")
            result = await self._try_analyze_with_model(image_path, question, fallback)

        return result

    async def _try_analyze_with_model(self, image_path: str, question: str, model: str) -> str:
        provider = model.split("/")[0] if "/" in model else ""
        model_name = model.split("/")[-1] if "/" in model else model

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = "image/jpeg"

        if provider == "google" or provider == "gemini":
            return await self._analyze_gemini(image_bytes, mime_type, model_name, question)
        elif provider == "openai":
            return await self._analyze_openai(image_bytes, mime_type, model_name, question)
        elif provider == "anthropic":
            return await self._analyze_anthropic(image_bytes, mime_type, model_name, question)
        else:
            return await self._analyze_openai(image_bytes, mime_type, model_name, question)

    async def _analyze_gemini(self, image_bytes: bytes, mime_type: str, model: str, question: str) -> str:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return "ERROR: GOOGLE_API_KEY not set"

        try:
            import google.genai as genai
        except ImportError:
            return "ERROR: google-genai package not installed"

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=model,
            contents=[
                {
                    "parts": [
                        {"text": question},
                        {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode()}}
                    ]
                }
            ]
        )

        return response.text if response else "ERROR: No response from Gemini"

    async def _analyze_openai(self, image_bytes: bytes, mime_type: str, model: str, question: str) -> str:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return "ERROR: OPENAI_API_KEY not set"

        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        url = f"{base_url}/chat/completions"

        image_base64 = base64.b64encode(image_bytes).decode()

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}",
                                "detail": "low"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 1000
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            return f"ERROR: OpenAI API error: {response.status_code} - {response.text}"

    async def _analyze_anthropic(self, image_bytes: bytes, mime_type: str, model: str, question: str) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return "ERROR: ANTHROPIC_API_KEY not set"

        url = "https://api.anthropic.com/v1/messages"

        image_base64 = base64.b64encode(image_bytes).decode()

        payload = {
            "model": model,
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": image_base64
                            }
                        },
                        {"type": "text", "text": question}
                    ]
                }
            ]
        }

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            result = response.json()
            return result["content"][0]["text"]
        else:
            return f"ERROR: Anthropic API error: {response.status_code} - {response.text}"


tool_class = AnalyzeImageTool
