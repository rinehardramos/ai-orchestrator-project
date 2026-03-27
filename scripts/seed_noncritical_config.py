"""
Seed non-critical configuration into Postgres app_config.

This script seeds default configuration values from the original YAML configs.

Usage:
  python scripts/seed_noncritical_config.py --dry-run
  python scripts/seed_noncritical_config.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, dict[str, object]] = {
    "profiles": {
        "default_model": "gemini/gemini-2.5-flash",
        "fallback_model": "openai/gpt-4o-mini",
        "models": [
            # === GOOGLE GEMINI ===
            {"id": "gemini-2.5-flash-lite", "provider": "google", "cost_per_1k_tokens": 1.0e-05, "context_window": 1000000, "reasoning_capability": "low", "speed": "ultra_fast"},
            {"id": "gemini-2.5-flash", "provider": "google", "cost_per_1k_tokens": 0.0001, "context_window": 1000000, "reasoning_capability": "medium", "speed": "very_fast"},
            {"id": "gemini-2.5-pro-preview-05-06", "provider": "google", "cost_per_1k_tokens": 0.00125, "context_window": 1000000, "reasoning_capability": "high", "speed": "medium"},
            {"id": "gemini-2.0-flash", "provider": "google", "cost_per_1k_tokens": 0.0001, "context_window": 1000000, "reasoning_capability": "medium", "speed": "very_fast"},
            {"id": "gemini-2.0-flash-lite", "provider": "google", "cost_per_1k_tokens": 5.0e-06, "context_window": 1000000, "reasoning_capability": "low", "speed": "ultra_fast"},
            {"id": "gemini-1.5-flash", "provider": "google", "cost_per_1k_tokens": 7.5e-05, "context_window": 1000000, "reasoning_capability": "medium", "speed": "very_fast"},
            {"id": "gemini-1.5-pro", "provider": "google", "cost_per_1k_tokens": 0.00125, "context_window": 2000000, "reasoning_capability": "high", "speed": "medium"},
            
            # === ANTHROPIC CLAUDE ===
            {"id": "claude-3-5-sonnet-20241022", "provider": "anthropic", "cost_per_1k_tokens": 0.003, "context_window": 200000, "reasoning_capability": "high", "speed": "fast"},
            {"id": "claude-3-5-haiku-20241022", "provider": "anthropic", "cost_per_1k_tokens": 0.0008, "context_window": 200000, "reasoning_capability": "medium", "speed": "very_fast"},
            {"id": "claude-sonnet-4-20250514", "provider": "anthropic", "cost_per_1k_tokens": 0.003, "context_window": 200000, "reasoning_capability": "high", "speed": "fast"},
            {"id": "claude-opus-4-20250514", "provider": "anthropic", "cost_per_1k_tokens": 0.015, "context_window": 200000, "reasoning_capability": "high", "speed": "medium"},
            {"id": "claude-3-opus-20240229", "provider": "anthropic", "cost_per_1k_tokens": 0.015, "context_window": 200000, "reasoning_capability": "high", "speed": "medium"},
            
            # === OPENAI ===
            {"id": "gpt-4o", "provider": "openai", "cost_per_1k_tokens": 0.005, "context_window": 128000, "reasoning_capability": "high", "speed": "fast"},
            {"id": "gpt-4o-mini", "provider": "openai", "cost_per_1k_tokens": 0.00015, "context_window": 128000, "reasoning_capability": "medium", "speed": "very_fast"},
            {"id": "gpt-4-turbo", "provider": "openai", "cost_per_1k_tokens": 0.01, "context_window": 128000, "reasoning_capability": "high", "speed": "medium"},
            {"id": "gpt-3.5-turbo", "provider": "openai", "cost_per_1k_tokens": 0.0005, "context_window": 16384, "reasoning_capability": "low", "speed": "very_fast"},
            {"id": "o1-preview", "provider": "openai", "cost_per_1k_tokens": 0.015, "context_window": 128000, "reasoning_capability": "high", "speed": "slow"},
            {"id": "o1-mini", "provider": "openai", "cost_per_1k_tokens": 0.003, "context_window": 128000, "reasoning_capability": "high", "speed": "medium"},
            
            # === ZHIPU GLM ===
            {"id": "glm-4-plus", "provider": "openrouter", "cost_per_1k_tokens": 0.00005, "context_window": 128000, "reasoning_capability": "medium", "speed": "fast"},
            {"id": "glm-4-flash", "provider": "openrouter", "cost_per_1k_tokens": 0.00001, "context_window": 128000, "reasoning_capability": "low", "speed": "ultra_fast"},
            {"id": "glm-4-air", "provider": "openrouter", "cost_per_1k_tokens": 0.00001, "context_window": 128000, "reasoning_capability": "low", "speed": "very_fast"},
            {"id": "glm-4-long", "provider": "openrouter", "cost_per_1k_tokens": 0.0001, "context_window": 1000000, "reasoning_capability": "medium", "speed": "fast"},
            {"id": "glm-5", "provider": "litellm", "cost_per_1k_tokens": 0.00001, "context_window": 128000, "reasoning_capability": "medium", "speed": "very_fast"},
            
            # === DEEPSEEK ===
            {"id": "deepseek/deepseek-chat", "provider": "openrouter", "cost_per_1k_tokens": 0.00014, "context_window": 64000, "reasoning_capability": "medium", "speed": "fast"},
            {"id": "deepseek/deepseek-reasoner", "provider": "openrouter", "cost_per_1k_tokens": 0.00055, "context_window": 64000, "reasoning_capability": "high", "speed": "medium"},
            {"id": "deepseek/deepseek-coder", "provider": "openrouter", "cost_per_1k_tokens": 0.00014, "context_window": 64000, "reasoning_capability": "medium", "speed": "fast"},
            
            # === META LLAMA ===
            {"id": "meta-llama/llama-3.1-405b-instruct", "provider": "openrouter", "cost_per_1k_tokens": 0.002, "context_window": 131072, "reasoning_capability": "high", "speed": "medium"},
            {"id": "meta-llama/llama-3.1-70b-instruct", "provider": "openrouter", "cost_per_1k_tokens": 0.0003, "context_window": 131072, "reasoning_capability": "medium", "speed": "fast"},
            {"id": "meta-llama/llama-3.1-8b-instruct", "provider": "openrouter", "cost_per_1k_tokens": 0.00002, "context_window": 131072, "reasoning_capability": "low", "speed": "very_fast"},
            {"id": "meta-llama/llama-3.2-90b-vision-instruct", "provider": "openrouter", "cost_per_1k_tokens": 0.00035, "context_window": 131072, "reasoning_capability": "medium", "speed": "fast"},
            {"id": "meta-llama/llama-3.2-11b-vision-instruct", "provider": "openrouter", "cost_per_1k_tokens": 0.00002, "context_window": 131072, "reasoning_capability": "low", "speed": "very_fast"},
            
            # === MISTRAL ===
            {"id": "mistralai/mistral-large-2411", "provider": "openrouter", "cost_per_1k_tokens": 0.002, "context_window": 128000, "reasoning_capability": "high", "speed": "medium"},
            {"id": "mistralai/mistral-small-2409", "provider": "openrouter", "cost_per_1k_tokens": 0.0001, "context_window": 128000, "reasoning_capability": "medium", "speed": "fast"},
            {"id": "mistralai/codestral-mamba", "provider": "openrouter", "cost_per_1k_tokens": 0.00025, "context_window": 256000, "reasoning_capability": "medium", "speed": "fast"},
            {"id": "mistralai/pixtral-12b", "provider": "openrouter", "cost_per_1k_tokens": 0.0001, "context_window": 128000, "reasoning_capability": "low", "speed": "fast"},
            
            # === QWEN ===
            {"id": "qwen/qwen-2.5-72b-instruct", "provider": "openrouter", "cost_per_1k_tokens": 0.00035, "context_window": 131072, "reasoning_capability": "medium", "speed": "fast"},
            {"id": "qwen/qwen-2.5-32b-instruct", "provider": "openrouter", "cost_per_1k_tokens": 0.00008, "context_window": 131072, "reasoning_capability": "medium", "speed": "fast"},
            {"id": "qwen/qwen-2.5-coder-32b-instruct", "provider": "openrouter", "cost_per_1k_tokens": 0.00008, "context_window": 131072, "reasoning_capability": "medium", "speed": "fast"},
            {"id": "qwen/qwq-32b-preview", "provider": "openrouter", "cost_per_1k_tokens": 0.00012, "context_window": 32768, "reasoning_capability": "high", "speed": "medium"},
            
            # === LOCAL ===
            {"id": "llama-3.1-8b-local", "provider": "lmstudio", "cost_per_1k_tokens": 0.0, "context_window": 128000, "reasoning_capability": "low", "speed": "fast"},
            
            # === EMBEDDING MODELS ===
            {"id": "nomic-embed-text-v1.5", "provider": "lmstudio", "cost_per_1k_tokens": 0.0, "context_window": 8192, "reasoning_capability": "low", "speed": "ultra_fast", "type": "embedding", "dim": 768},
            {"id": "nomic-embed-code", "provider": "lmstudio", "cost_per_1k_tokens": 0.0, "context_window": 8192, "reasoning_capability": "low", "speed": "ultra_fast", "type": "embedding", "dim": 3584},
            {"id": "text-embedding-3-small", "provider": "openai", "cost_per_1k_tokens": 0.00002, "context_window": 8191, "reasoning_capability": "low", "speed": "ultra_fast", "type": "embedding", "dim": 1536},
            {"id": "text-embedding-3-large", "provider": "openai", "cost_per_1k_tokens": 0.00013, "context_window": 8191, "reasoning_capability": "low", "speed": "ultra_fast", "type": "embedding", "dim": 3072},
            {"id": "text-embedding-ada-002", "provider": "openai", "cost_per_1k_tokens": 0.0001, "context_window": 8191, "reasoning_capability": "low", "speed": "ultra_fast", "type": "embedding", "dim": 1536},
        ],
        "task_routing": {
            "planning": {"model": "gemini-2.5-flash", "provider": "google"},
            "coding": {"model": "gemini-2.5-flash", "provider": "google"},
            "agent_step": {"model": "gemini-2.5-flash", "provider": "google"},
            "analysis": {"provider": "google", "model": "gemini-2.5-flash"},
            "fast": {"provider": "google", "model": "gemini-2.5-flash-lite"},
            "execute": {"provider": "google", "model": "gemini-2.5-flash"},
            "embeddings_text": {"provider": "lmstudio", "model": "nomic-embed-text-v1.5", "dim": 768},
            "embeddings_code": {"provider": "lmstudio", "model": "nomic-embed-code", "dim": 3584},
        },
    },
    "jobs": {
        "max_tool_calls": 50,
        "max_cost_usd": 0.5,
        "shell_timeout_seconds": 120,
        "activity_timeout_minutes": 30,
    },
    "media": {
        "transcription": {
            "tiers": {
                "fast": {"primary": "groq/whisper-large-v3-turbo", "fallback": "gemini/gemini-2.5-flash-preview-05-20", "max_latency_ms": 2000, "description": "Interactive voice messages - optimized for speed (<2s)"},
                "accurate": {"primary": "openai/gpt-4o-mini-transcribe", "fallback": "openai/whisper-1", "max_latency_ms": 10000, "description": "High-quality transcription for podcasts, interviews"},
                "diarize": {"primary": "openai/gpt-4o-transcribe-diarize", "fallback": "google/chirp-3", "max_latency_ms": 15000, "description": "Multi-speaker transcription with speaker identification"},
            },
            "formats": {
                "audio/ogg": {"native_support": ["groq", "gemini"], "convert_to": "wav", "description": "Telegram voice messages"},
                "audio/oga": {"native_support": ["groq", "gemini"], "convert_to": "wav", "description": "Telegram voice messages (alternate)"},
                "audio/mpeg": {"native_support": ["openai", "groq", "google", "gemini"], "description": "MP3 audio files"},
                "audio/mp4": {"native_support": ["openai", "groq", "gemini"], "description": "M4A/AAC audio"},
                "audio/wav": {"native_support": ["openai", "groq", "google", "gemini"], "description": "WAV audio"},
                "audio/webm": {"native_support": ["openai", "groq"], "description": "WebM audio"},
            },
        },
        "vision": {
            "tiers": {
                "fast": {"primary": "google/gemini-2.0-flash", "fallback": "openai/gpt-4o-mini", "max_latency_ms": 3000, "description": "Quick image analysis"},
                "accurate": {"primary": "openai/gpt-4o", "fallback": "google/gemini-2.5-pro-preview-05-06", "max_latency_ms": 10000, "description": "Detailed image analysis"},
            },
            "formats": {
                "image/jpeg": {"native_support": ["openai", "google", "anthropic"]},
                "image/png": {"native_support": ["openai", "google", "anthropic"]},
                "image/gif": {"native_support": ["openai", "google"]},
                "image/webp": {"native_support": ["openai", "google"]},
            },
        },
        "limits": {"max_file_size_mb": 25, "max_audio_duration_seconds": 3600, "timeout_seconds": 60},
    },
    "specializations": {
        "general": {"model": "gemini-2.5-flash", "provider": "google", "allowed_tools": ["list_files", "read_file", "write_file", "search_web", "read_url_content", "task_complete", "git_clone", "run_command", "email_send", "email_read_inbox", "email_search", "email_get", "email_delete", "drive_list", "drive_read", "drive_write", "drive_delete", "drive_search", "drive_create_folder", "drive_share"]},
        "coding": {"model": "gemini-2.5-flash", "provider": "google", "allowed_tools": ["list_files", "read_file", "write_file", "run_command", "git_clone", "task_complete", "search_web"]},
        "research": {"model": "gemini-2.5-flash", "provider": "google", "allowed_tools": ["search_web", "read_url_content", "task_complete", "write_file"]},
        "image_generation": {"model": "gemini-2.5-flash", "provider": "google", "allowed_tools": ["generate_image", "task_complete"]},
        "video_generation": {"model": "gemini-2.5-flash", "provider": "google", "allowed_tools": ["generate_video", "task_complete"]},
        "audio_generation": {"model": "gemini-2.5-flash", "provider": "google", "allowed_tools": ["generate_audio", "task_complete"]},
        "planner": {"model": "gemini-2.5-flash", "provider": "google", "allowed_tools": ["task_complete"]},
        "copywriting": {"model": "gemini-2.5-flash", "provider": "google", "allowed_tools": ["write_file", "read_file", "task_complete", "submit_for_review"]},
        "quality_control": {"model": "gemini-2.5-flash", "provider": "google", "allowed_tools": ["read_file", "task_complete", "delegate_task"]},
    },
    "cluster_nodes": {
        "nodes": [
            {"name": "genesis", "host": "localhost", "role": "genesis", "project_dir": "/home/pi/Projects/ai-orchestration-project"},
            {"name": "worker-main", "host": "macbook.local", "role": "execution", "user": "rinehardramos", "project_dir": "/Users/rinehardramos/Projects/ai-orchestrator-project"},
            {"name": "worker-sigbin", "host": "192.168.100.100", "port": 22002, "role": "execution", "user": "sigbin"},
        ]
    },
}


def seed(dry_run: bool) -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url and not dry_run:
        log.error("DATABASE_URL is required for live run")
        sys.exit(1)

    payload: list[tuple[str, str, object]] = []
    for namespace, config in DEFAULT_CONFIG.items():
        for key, value in config.items():
            payload.append((namespace, str(key), value))

    if dry_run:
        log.info("DRY RUN - no database writes")
        for namespace, key, value in payload:
            rendered = json.dumps(value)[:200]
            log.info(f"upsert app_config ({namespace}, {key}) = {rendered}")
        log.info(f"Total rows prepared: {len(payload)}")
        return

    try:
        import psycopg2
        from psycopg2.extras import Json
    except ImportError:
        log.error("psycopg2 is required. Install with: pip install psycopg2-binary")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            for namespace, key, value in payload:
                cur.execute(
                    """
                    INSERT INTO app_config (namespace, key, value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (namespace, key)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                    """,
                    (namespace, key, Json(value)),
                )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.error(f"Seeding failed: {exc}")
        raise
    finally:
        conn.close()

    log.info(f"Seeding complete. Upserted {len(payload)} rows into app_config.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed default config to Postgres app_config")
    parser.add_argument("--dry-run", action="store_true", help="Show planned writes only")
    args = parser.parse_args()

    seed(dry_run=args.dry_run)
