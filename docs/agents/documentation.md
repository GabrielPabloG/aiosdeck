# Documentation Agent

**Status**: Draft
**Date**: 2026-08-02
**Introduced**: v0.6

## Context

Code changes without documentation create technical debt. The Documentation agent ensures that every change is reflected in the project's documentation — README updates, API docs, ADR creation, and CHANGELOG entries.

The Documentation agent is part of the Quality Pipeline (v0.6). Its gate checks whether documentation was updated for API changes. It can also be invoked manually via `aios /document`.

## Decision

### In → Process → Out

```
In:  Task (type: "document", payload: {
       change_description: "Added OAuth2 provider integration",
       changed_files: ["src/auth/provider.py"],
       change_type: "feature"  # feature, fix, refactor, breaking
     })
     Context Packet (project structure, existing docs)
     Skills: ["project-dna"]

Process:
  1. Analyze changed files for public API changes
  2. Determine which docs need updating (README, API docs, ADR, CHANGELOG)
  3. Generate documentation updates
  4. Write updated documentation files
  5. Report docs updated

Out: AgentResult with list of documentation files updated
```

### Documentation Checklist

| Change Type | README | API Docs | ADR | CHANGELOG |
|------------|:---:|:---:|:---:|:---:|
| New feature | Yes (if user-facing) | Yes | Yes | Yes |
| Bug fix | No | No | No | Yes |
| Refactor | No | No | No (unless architecture change) | Yes |
| Breaking change | Yes | Yes | Yes | Yes (prominent) |
| Dependency update | No | No | No | Yes |

### Output Format

```python
{
    "change_type": "feature",
    "files_updated": ["README.md", "docs/api/auth.md", "CHANGELOG.md"],
    "adr_created": "docs/adr/2026-08-02-oauth2-provider.md",
    "changelog_entry": "## [Unreleased]\n### Added\n- OAuth2 provider integration",
    "status": "success",
}
```

### Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `task.created` (type: document) | Consumed | Receive a documentation task |
| `agent.completed` | Emitted | Documentation updated |

### Required Capabilities

- `filesystem_read` — to read existing documentation
- `filesystem_write` — to update documentation files

### Cannot

- Write application code
- Execute Git commands
- Access the internet
- Run shell commands

### Required Skills

- `project-dna` — must understand project documentation standards
- `documentation-style` — must follow documentation conventions

### Future (v0.8+)

- Automatic API documentation generation from docstrings
- Cross-reference validation (broken links, missing pages)
- Documentation coverage reporting (% of public API documented)
- Team-specific documentation templates

## Consequences

### Positive

- **Documentation always current**: Every code change triggers a documentation review.
- **Standardized format**: Documentation follows project conventions, not individual style.
- **Zero configuration**: Documentation agent knows what to update based on change type.
- **ADR automation**: Architecture decisions are documented at creation time, not retroactively.

### Negative

- **Over-documentation risk**: Small changes may trigger unnecessary docs updates.
- **Quality dependency**: Generated documentation quality depends on the underlying LLM.
- **File conflicts**: Documentation agent writes to the same files as developers. Merge conflicts possible.

### Neutral

- Documentation is advisory. The human developer reviews and approves all documentation changes.
- The Documentation agent is introduced at v0.6 alongside the Tester.

## Implementation Notes

- [ ] Implement `agents/documentation.py` — DocumentationAgent class
- [ ] Change type detection: analyze changed files for public API additions/modifications
- [ ] Documentation update rules: follow the checklist table above
- [ ] CHANGELOG format: follow Keep a Changelog convention
- [ ] ADR format: follow project ADR template (Status, Context, Decision, Consequences)
- [ ] Documentation agent must not overwrite handwritten docs unless explicitly approved
- [ ] Test: new feature → README, API docs, ADR, CHANGELOG all updated
- [ ] Test: bug fix → only CHANGELOG updated
- [ ] Test: no API changes → no docs needed, agent returns success with no files updated
