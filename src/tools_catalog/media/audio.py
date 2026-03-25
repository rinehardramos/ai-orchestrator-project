"""
Audio transcription tool with intelligent model selection.

Supports:
- Voice messages (OGG/OGA) - optimized for low latency
- Audio files (MP3, WAV, M4A, etc.) - optimized for quality
- Multi-speaker diarization

Uses configurable model tiers from config/media.yaml.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import subprocess
import tempfile
from typing import Optional

import httpx
import yaml

from src.plugins.base import Tool, ToolContext

log = logging.getLogger(__name__)


class TranscribeAudioTool(Tool):
    type = "media"
    name = "transcribe_audio"
    description = "Transcribe audio files with intelligent model selection for optimal latency/quality"
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
            "transcription": {
                "tiers": {
                    "fast": {"primary": "groq/whisper-large-v3-turbo", "fallback": "gemini/gemini-2.5-flash-preview-05-20"},
                    "accurate": {"primary": "openai/gpt-4o-mini-transcribe", "fallback": "openai/whisper-1"},
                    "diarize": {"primary": "openai/gpt-4o-transcribe-diarize", "fallback": "google/chirp-3"}
                },
                "formats": {
                    "audio/ogg": {"native_support": ["groq", "gemini"], "convert_to": "wav"},
                    "audio/oga": {"native_support": ["groq", "gemini"], "convert_to": "wav"}
                }
            },
            "limits": {"max_file_size_mb": 25, "timeout_seconds": 60}
        }

    def get_tool_schemas(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "transcribe_audio",
                    "description": (
                        "Transcribe an audio file. Use mode='fast' for voice messages (lowest latency), "
                        "'accurate' for podcasts/interviews, 'diarize' for multi-speaker content."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "audio_file": {
                                "type": "string",
                                "description": "Path to the audio file to transcribe"
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["fast", "accurate", "diarize"],
                                "default": "fast",
                                "description": "fast=lowest latency, accurate=higher quality, diarize=speaker identification"
                            },
                            "model_override": {
                                "type": "string",
                                "description": "Override automatic model selection with specific model ID"
                            },
                            "language": {
                                "type": "string",
                                "description": "ISO 639-1 language code (e.g., 'en', 'es'). Auto-detected if not specified."
                            }
                        },
                        "required": ["audio_file"]
                    }
                }
            }
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> str:
        if tool_name != "transcribe_audio":
            return f"ERROR: Unknown tool '{tool_name}'"

        audio_file = args.get("audio_file")
        mode = args.get("mode", "fast")
        model_override = args.get("model_override")
        language = args.get("language")

        if not audio_file:
            return "ERROR: audio_file parameter is required"

        if not os.path.isabs(audio_file):
            audio_file = os.path.join(ctx.workspace_dir, audio_file)

        if not os.path.exists(audio_file):
            return f"ERROR: Audio file not found: {audio_file}"

        config = self._load_media_config()
        limits = config.get("limits", {})

        file_size_mb = os.path.getsize(audio_file) / (1024 * 1024)
        if file_size_mb > limits.get("max_file_size_mb", 25):
            return f"ERROR: File too large ({file_size_mb:.1f}MB). Max: {limits.get('max_file_size_mb', 25)}MB"

        try:
            result = await self._transcribe(audio_file, mode, model_override, language, config)
            return result
        except Exception as e:
            log.exception(f"Transcription failed: {e}")
            return f"ERROR: Transcription failed: {str(e)}"

    async def _transcribe(self, audio_path: str, mode: str, model_override: Optional[str], 
                          language: Optional[str], config: dict) -> str:
        tiers = config["transcription"]["tiers"]
        formats = config["transcription"].get("formats", {})

        model = model_override or tiers.get(mode, tiers["fast"])["primary"]

        mime_type, _ = mimetypes.guess_type(audio_path)
        if not mime_type:
            mime_type = "audio/mpeg"

        format_config = formats.get(mime_type, {})
        needs_conversion = self._needs_conversion(audio_path, model, format_config)

        if needs_conversion:
            audio_path = await self._convert_audio(audio_path, format_config.get("convert_to", "wav"))

        primary_model = model_override or tiers.get(mode, tiers["fast"])["primary"]
        fallback_model = tiers.get(mode, {}).get("fallback")

        result = await self._try_transcribe_with_model(audio_path, primary_model, language)
        
        if result.startswith("ERROR") and fallback_model:
            log.warning(f"Primary model {primary_model} failed, trying fallback {fallback_model}")
            result = await self._try_transcribe_with_model(audio_path, fallback_model, language)

        return result

    def _needs_conversion(self, audio_path: str, model: str, format_config: dict) -> bool:
        if not format_config:
            return False

        native_support = format_config.get("native_support", [])
        provider = model.split("/")[0] if "/" in model else ""

        if provider in native_support:
            return False

        return bool(format_config.get("convert_to"))

    async def _convert_audio(self, audio_path: str, target_format: str) -> str:
        output_path = audio_path.rsplit(".", 1)[0] + f".{target_format}"
        
        cmd = [
            "ffmpeg", "-y", "-i", audio_path,
            "-acodec", "pcm_s16le" if target_format == "wav" else "copy",
            "-ar", "16000",
            output_path
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0:
                log.info(f"Converted {audio_path} to {output_path}")
                return output_path
            else:
                log.error(f"ffmpeg failed: {result.stderr.decode()}")
                return audio_path
        except FileNotFoundError:
            log.warning("ffmpeg not found, using original file")
            return audio_path
        except Exception as e:
            log.error(f"Conversion error: {e}")
            return audio_path

    async def _try_transcribe_with_model(self, audio_path: str, model: str, language: Optional[str]) -> str:
        provider = model.split("/")[0] if "/" in model else ""
        model_name = model.split("/")[-1] if "/" in model else model

        if provider == "groq":
            return await self._transcribe_groq(audio_path, model_name, language)
        elif provider == "openai":
            return await self._transcribe_openai(audio_path, model_name, language)
        elif provider == "gemini":
            return await self._transcribe_gemini(audio_path, model_name, language)
        elif provider == "google":
            return await self._transcribe_google(audio_path, model_name, language)
        else:
            return await self._transcribe_openai(audio_path, model_name, language)

    async def _transcribe_groq(self, audio_path: str, model: str, language: Optional[str]) -> str:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            return "ERROR: GROQ_API_KEY not set"

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        
        with open(audio_path, "rb") as f:
            files = {"file": (os.path.basename(audio_path), f)}
            data = {"model": model}
            if language:
                data["language"] = language

            headers = {"Authorization": f"Bearer {api_key}"}
            
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(url, files=files, data=data, headers=headers)

        if response.status_code == 200:
            return response.json().get("text", "")
        else:
            return f"ERROR: Groq API error: {response.status_code} - {response.text}"

    async def _transcribe_openai(self, audio_path: str, model: str, language: Optional[str]) -> str:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return "ERROR: OPENAI_API_KEY not set"

        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        
        if model.startswith("whisper"):
            url = f"{base_url}/audio/transcriptions"
        elif "transcribe" in model:
            url = f"{base_url}/audio/transcriptions"
        else:
            url = f"{base_url}/audio/transcriptions"

        with open(audio_path, "rb") as f:
            files = {"file": (os.path.basename(audio_path), f)}
            data = {"model": model}
            if language:
                data["language"] = language

            headers = {"Authorization": f"Bearer {api_key}"}
            
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, files=files, data=data, headers=headers)

        if response.status_code == 200:
            result = response.json()
            return result.get("text", "")
        else:
            return f"ERROR: OpenAI API error: {response.status_code} - {response.text}"

    async def _transcribe_gemini(self, audio_path: str, model: str, language: Optional[str]) -> str:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return "ERROR: GOOGLE_API_KEY not set"

        import google.genai as genai

        client = genai.Client(api_key=api_key)

        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        response = client.models.generate_content(
            model=model,
            contents=[
                {
                    "parts": [
                        {"text": "Transcribe this audio. Output only the transcription text."},
                        {"inline_data": {"mime_type": "audio/mp3", "data": base64.b64encode(audio_bytes).decode()}}
                    ]
                }
            ]
        )

        return response.text if response else "ERROR: No response from Gemini"

    async def _transcribe_google(self, audio_path: str, model: str, language: Optional[str]) -> str:
        return await self._transcribe_gemini(audio_path, model, language)


tool_class = TranscribeAudioTool
