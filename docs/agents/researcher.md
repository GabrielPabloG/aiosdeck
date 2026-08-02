# Researcher Agent

**Status**: Proposed
**Date**: 2026-08-02
**Introduced**: v0.8

## Context

Some tasks require external knowledge: API documentation, library usage patterns, best practices for unfamiliar technologies. The Researcher agent searches the web, reads documentation, and returns structured findings to inform other agents.

The Researcher is the only agent with internet access. This is by design: it isolates network access to a single, auditable agent rather than granting every agent internet capabilities.

## Decision

### In → Process → Out

```
In:  Task (type: "research", payload: {query: "FastAPI OAuth2 middleware best practices"})
     Context Packet (project language, framework, existing dependencies)
     Skills: ["project-dna"]

Process:
  1. Parse research query and scope
  2. Search web/documentation for relevant sources
  3. Filter and rank results by relevance
  4. Extract key findings: APIs, patterns, examples, caveats
  5. Summarize into structured research note
  6. Store findings in Memory Engine for future use

Out: AgentResult with structured research findings
```

### Output Format

```python
{
    "query": "FastAPI OAuth2 middleware best practices",
    "sources": [
        {"title": "FastAPI Security Docs", "url": "https://...", "relevance": "high"},
        {"title": "OAuth2 RFC 6749", "url": "https://...", "relevance": "medium"},
    ],
    "findings": [
        "Use fastapi.security.OAuth2PasswordBearer for token extraction",
        "Middleware pattern: dependency injection, not decorator",
        "Session tokens stored in HTTP-only cookies, not localStorage",
    ],
    "code_examples": [
        {
            "description": "Basic OAuth2 middleware setup",
            "language": "python",
            "code": "...",
        },
    ],
    "caveats": [
        "Rate limiting is not built into FastAPI — use slowapi or custom middleware",
        "CSRF protection required for cookie-based auth",
    ],
}
```

### Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `task.created` (type: research) | Consumed | Receive a research task |
| `agent.completed` | Emitted | Research findings ready |

### Required Capabilities

- `filesystem_read` — to access local documentation and cached sources
- `internet` — to search the web and fetch documentation

### Cannot

- Write code
- Execute Git commands
- Run shell commands
- Modify files

### Required Skills

- `project-dna` — must understand project context to filter relevant results
- `coding-style` — must recognize patterns that match project conventions

### Future (v0.9+)

- Cache frequently accessed documentation locally
- Cross-reference findings with Memory Engine (known patterns, prior research)
- Rank findings by project relevance using embedding similarity

## Consequences

### Positive

- **Isolated internet access**: Only one agent connects to the network. Audit trail is clean.
- **Structured output**: Findings are machine-readable. The Coder can consume research results directly.
- **Knowledge retention**: Research findings are stored in Memory Engine for future sessions.
- **Security**: Internet access is auditable per-query. No blanket web access for the system.

### Negative

- **Latency**: Web searches add significant time to workflows.
- **Accuracy**: Researcher output depends on search quality and source reliability.
- **Cost**: Cloud LLM usage (for summarization) if local models are insufficient.

### Neutral

- The Researcher is introduced late (v0.8) because most tasks can be completed with local knowledge alone.
- Web search requires an API key (Tavily, SerpAPI, Brave). Configured via Secret Manager.

## Implementation Notes

- [ ] Implement `agents/researcher.py` — ResearcherAgent class
- [ ] Web search integration: support at least one search API (configurable)
- [ ] Research output must be stored in Memory Engine for caching
- [ ] Sources must be validated: HTTPS only, reputable domains preferred
- [ ] Rate limiting: max N searches per session (configurable)
- [ ] Test: simple query → structured findings with sources and code examples
- [ ] Test: empty query → error handled gracefully
- [ ] Test: no internet → agent reports error, does not crash
