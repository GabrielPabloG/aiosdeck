# Ollama Integration

**Status**: Accepted
**Date**: 2026-08-02

## Context

AiosDeck is local-first. Cloud models are optional. Ollama provides local LLM inference — downloading models, running inference, and exposing a REST API. It is the default model provider when no cloud API keys are configured.

The principle is: **local first, cloud optional**. Ollama is the default. If Ollama is not available, the system falls back to configured cloud providers (OpenAI, Anthropic, Google) or reports that no model is available.

## Decision

### Architecture

There are two supported paths and they must not be conflated:

```
OpenCodeAdapter → OpenCode provider (ollama) → Ollama Server (localhost:11434)
OllamaAdapter   → Ollama Server (localhost:11434)
```

The default project path is the first one. OpenCode owns provider registration
and model invocation; AiosDeck's `OpenCodeAdapter` only invokes
`ai-jail opencode`. The second path is AiosDeck's direct runtime adapter and is
not selected by the project manifest.

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
# ~/.config/aiosdeck/config.yaml (AiosDeck routing metadata)
model:
  default: ollama
  ollama_model: llama3.2
  ollama_host: "http://localhost:11434"
runtime:
  adapter: opencode
```

OpenCode's provider configuration is project-scoped in
`.opencode/opencode.json`. It uses the local OpenAI-compatible endpoint
`http://localhost:11434/v1` and contains no credentials. Keep the AiosDeck
manifest at `runtime: opencode` when the desired architecture is
AiosDeck -> OpenCode -> Ollama.

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
2. DeepSeek (Cloud)        → if API key configured
3. OpenAI (cloud)          → if API key configured
4. Anthropic (cloud)       → if API key configured
5. Google Gemini (cloud)   → if API key configured
6. No model available      → error
```

The fallback chain is configured, not hardcoded.

## Consequences

- **Local-first**: Works without internet access. No API keys required.
- **Privacy**: Code and prompts never leave the developer's machine.
- **Dependency**: Requires Ollama to be installed and running locally.

## Implementation Notes

- [x] OpenCode provider: project-scoped Ollama configuration
- [x] Model selection: `ollama/llama3.2` passed to OpenCode
- [x] AiosDeck routing metadata: `ollama_host` and `ollama_model`
- [ ] Direct OllamaAdapter health check via `/api/tags` endpoint
- [ ] Test: Ollama running → available, models listed
- [ ] Test: Ollama not running → unavailable, fallback to next provider
- [ ] Test: no models available → error reported
