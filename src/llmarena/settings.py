from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração via variáveis de ambiente / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None
    anthropic_fallbacks: bool = True

    host: str = "127.0.0.1"
    port: int = 8080
    log_level: str = "INFO"

    db_path: Path = Path("data/arena.db")
    bank_path: Path = Path("challenges/bank.yaml")
    models_path: Path = Path("config/models.yaml")
    static_dir: Path = Path("static")

    hp: int = 100
    rounds: int = 3
    round_seconds: float = 90.0
    intermission_seconds: float = 3.0
    max_attempts_per_challenge: int = 4
    max_golpes_per_round: int = 12

    llm_max_tokens: int = 1500
    llm_timeout_s: float = 60.0
    first_token_timeout_s: float = 20.0

    sandbox_wall_s: float = 3.5
    sandbox_cpu_s: int = 3
    sandbox_mem_mb: int = 256
    sandbox_netns: Literal["auto", "on", "off"] = "auto"
    sandbox_parallel: int = 4

    fake_providers: bool = False
