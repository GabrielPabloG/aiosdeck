# Ollama Integration

**Status**: Accepted
**Date**: 2026-08-02

## Context

AiosDeck is local-first. Cloud models are optional. Ollama provides local LLM inference — downloading models, running inference, and exposing a REST API. It is the default model provider when no cloud API keys are configured.

The principle is: **local first, cloud optional**. Ollama is the default. If Ollama is not available, the system falls back to configured cloud providers (OpenAI, Anthropic, Google) or reports that no model is available.

## Decision

### Architecture

```
Agent → OpenCode → Ollama Adapter → Ollama Server (localhost:11434)
```

AiosDeck does not call Ollama directly. OpenCode does. The Ollama adapter is a thin health-check layer that verifies Ollama availability and reports it to the Context Engine.

### Health Check

```python
class OllamaAdapter:
    async def is_available(self) -> bool:
        try:
            response = await self._http_get("http://localhost:11434/api/tags")
            return response.status == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        response = await self._http_get("http://localhost:11434/api/tags")
        return [m["name"] for m in response.json()["models"]]

    async def health_check(self) -> bool:
        return await self.is_available()
```

### Configuration

```yaml
# ~/.config/aiosdeck/config.yaml
default_model: ollama
ollama_model: llama3
ollama_host: "http://localhost:11434"
```

### Model Availability

The Context Engine reports which models are available:

```python
context["models"] = {
    "ollama": {
        "available": True,
        "models": ["llama3", "codellama", "mistral"],
    },
    "openai": {
        "available": False,  # No API key configured
    },
}
```

### Fallback Chain

```
1. Ollama (local)          → if available
2. OpenAI (cloud)          → if API key configured
3. Anthropic (cloud)       → if API key configured
4. Google Gemini (cloud)   → if API key configured
5. No model available      → error
```

The fallback chain is configured, not hardcoded.

## Consequences

- **Local-first**: Works without internet access. No API keys required.
- **Privacy**: Code and prompts never leave the developer's machine.
- **Dependency**: Requires Ollama to be installed and running locally.

## Implementation Notes

- [ ] Ollama adapter: health check via `/api/tags` endpoint
- [ ] Model list: extracted from Ollama API response
- [ ] Configuration: ollama_host and ollama_model from config
- [ ] Fallback chain: configurable model provider priority
- [ ] Test: Ollama running → available, models listed
- [ ] Test: Ollama not running → unavailable, fallback to next provider
- [ ] Test: no models available → error reported
