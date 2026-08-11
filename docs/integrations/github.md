# GitHub Integration

**Status**: Proposed
**Date**: 2026-08-02

## Context

GitHub hosts repositories, manages pull requests, runs CI/CD via GitHub Actions, and tracks issues. The GitHub integration enables AiosDeck to: create pull requests from completed features, comment on PRs with review results, link commits to issues, and trigger CI/CD workflows.

The GitHub integration is v1.0+. Earlier versions work locally with Git. The GitHub adapter adds remote collaboration capabilities.

## Decision

### Authentication

```python
class GitHubAdapter:
    async def is_available(self) -> bool:
        return self._has_env("GITHUB_TOKEN") or self._run("gh auth status").returncode == 0

    async def health_check(self) -> bool:
        return await self.is_available()
```

Authentication uses:
1. `GITHUB_TOKEN` environment variable
2. GitHub CLI (`gh`) authentication
3. SSH key configured for GitHub

### Capabilities (v1.0+)

| Action | Description |
|--------|-------------|
| Create PR | Open a pull request from feature branch to main |
| Comment on PR | Post review findings as PR comments |
| Create Issue | Create an issue from a bug report |
| Trigger Workflow | Run a GitHub Actions workflow |
| Get PR Status | Check CI/CD status of a pull request |

### Workflow Integration

```
/feature add-oauth2-login
   │
   ├── Plan → Implement → Test → Review → Commit
   │
   └── (v1.0+) GitHub Adapter
          ├── Push feature branch
          ├── Create PR with description
          ├── Post review results as PR comments
          └── Trigger CI workflow
```

### Configuration

```yaml
# ~/.config/aiosdeck/config.yaml
github:
  enabled: true
  token_source: env  # env, gh-cli, ssh
  auto_create_pr: false  # Manual PR creation by default
  auto_comment: true     # Post review results as comments
```

### Future (v1.0+)

- PR template generation from project context
- Automated PR labeling based on change type (feat, fix, docs, etc.)
- CI/CD failure analysis: agent reviews failed workflow and suggests fixes
- Issue-to-feature workflow: issue assigned → Planner → Developer → PR → close issue

## Consequences

- **Remote collaboration**: GitHub integration enables team workflows.
- **Authentication required**: Requires `GITHUB_TOKEN` or `gh` CLI authentication.
- **Optional**: Git operations work locally without GitHub. GitHub adds remote capabilities.

## Implementation Notes

- [ ] GitHub adapter: detect authentication (env token or gh CLI)
- [ ] PR creation: `gh pr create` with auto-generated description
- [ ] PR comments: `gh pr comment` with review findings
- [ ] Issue creation: `gh issue create` from bug reports
- [ ] Auto-PR must require human approval (Approval Gate)
- [ ] Test: GitHub token present → adapter reports available
- [ ] Test: no GitHub auth → adapter reports unavailable, git operations still work locally
