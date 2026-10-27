from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from llmarena.challenges.schema import ChallengeBank
from llmarena.domain.models import FighterSpec
from llmarena.providers.anthropic_provider import AnthropicProvider
from llmarena.providers.base import Provider
from llmarena.providers.fake import DEMO_MODELS, DemoProvider
from llmarena.providers.openrouter_provider import OpenRouterProvider
from llmarena.settings import Settings


class ModelEntry(BaseModel):
    id: str
    display_name: str
    extra: dict[str, Any] = Field(default_factory=dict)


class ProviderEntry(BaseModel):
    name: str
    display_name: str
    models: list[ModelEntry]


class ModelCatalog(BaseModel):
    providers: list[ProviderEntry]

    def find(self, provider: str, model: str) -> ModelEntry | None:
        for p in self.providers:
            if p.name == provider:
                return next((m for m in p.models if m.id == model), None)
        return None

    def spec(self, provider: str, model: str) -> FighterSpec:
        entry = self.find(provider, model)
        if entry is None:
            raise KeyError(f"unknown model {provider}/{model}")
        return FighterSpec(provider=provider, model=model, display_name=entry.display_name)


def load_catalog(path: Path) -> ModelCatalog:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    providers = [ProviderEntry(name=name, **cfg) for name, cfg in (data.get("providers") or {}).items()]
    return ModelCatalog(providers=providers)


class ProviderRegistry:
    """Instancia os provedores disponíveis a partir das chaves configuradas."""

    def __init__(self, settings: Settings, catalog: ModelCatalog, bank: ChallengeBank) -> None:
        self._providers: dict[str, Provider] = {}
        self.catalog = catalog
        if settings.fake_providers:
            self._providers["demo"] = DemoProvider(bank)
            demo_models = [ModelEntry(id=k, display_name=k.split("/")[1].capitalize()) for k in DEMO_MODELS]
            catalog.providers.insert(
                0, ProviderEntry(name="demo", display_name="Demo (sem API)", models=demo_models)
            )
        if settings.anthropic_api_key:
            self._providers["anthropic"] = AnthropicProvider(
                settings.anthropic_api_key, fallbacks=settings.anthropic_fallbacks
            )
        if settings.openrouter_api_key:
            self._providers["openrouter"] = OpenRouterProvider(settings.openrouter_api_key)
        catalog.providers = [p for p in catalog.providers if p.name in self._providers]

    def available(self) -> list[ProviderEntry]:
        return self.catalog.providers

    def get(self, name: str) -> Provider:
        return self._providers[name]

    def register(self, name: str, provider: Provider, entry: ProviderEntry) -> None:
        self._providers[name] = provider
        self.catalog.providers = [p for p in self.catalog.providers if p.name != name] + [entry]

    async def aclose(self) -> None:
        for p in self._providers.values():
            await p.aclose()
