from __future__ import annotations

from dataclasses import replace

from .cache import JsonExtractionCache, extraction_cache_key
from .models import ExtractionRequest, ExtractionResult
from .provider import AIProvider
from .validator import validate_extraction


class ExtractionService:
    def __init__(
        self,
        provider: AIProvider,
        *,
        prompt_version: str,
        cache: JsonExtractionCache | None = None,
    ) -> None:
        self.provider = provider
        self.prompt_version = prompt_version
        self.cache = cache

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        key = extraction_cache_key(
            request,
            provider=self.provider.name,
            model=self.provider.model,
            prompt_version=self.prompt_version,
        )
        cached = self.cache.get(key) if self.cache else None
        if cached is not None:
            return validate_extraction(
                cached,
                allowed_urls=request.allowed_urls,
                provider=self.provider.name,
                model=self.provider.model,
                prompt_version=self.prompt_version,
                cache_hit=True,
            )

        raw = self.provider.extract_event(request)
        result = validate_extraction(
            raw,
            allowed_urls=request.allowed_urls,
            provider=self.provider.name,
            model=self.provider.model,
            prompt_version=self.prompt_version,
        )
        if self.cache:
            self.cache.put(key, result.as_dict())
        return replace(result, cache_hit=False)
