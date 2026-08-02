# Security Manager

**Status**: Proposed
**Date**: 2026-08-02

## Context

AiosDeck agents execute code, access files, make network requests, and interact with version control. Without security boundaries, a misconfigured agent or a prompt injection attack could compromise the entire development environment.

The principle is: **security is architecture, not a feature**. Security is not a module added later. It is embedded in the kernel, the runtime, the agent model, and the event bus — in every component.

The Security Manager enforces zero-trust from day one. Every agent is untrusted until explicitly authorized. Every action is audited. Every boundary is enforced.

## Decision

### Architecture

```
                  Event Bus
                     │
                     ▼
              Security Manager
                     │
    ┌────────────────┼────────────────┐
    │                │                │
    ▼                ▼                ▼
Policy Engine   Capability       Secret
                Manager          Manager
    │                │                │
    ▼                ▼                ▼
Prompt          Approval         Audit
Firewall        Gates            Logger
```

### Sub-Components

#### Policy Engine

Evaluates whether an agent is authorized to perform an action. Policies are YAML files:

```yaml
# aios/policies/default.yaml
agents:
  planner:
    capabilities: [filesystem_read]
    max_tokens: 8192

  coder:
    capabilities: [filesystem_read, filesystem_write, shell]
    max_tokens: 16384
    allowed_paths:
      - "."
      - "docs/"
      - "tests/"
    denied_paths:
      - "~/.ssh"
      - "~/.aws"
      - "/etc"

  reviewer:
    capabilities: [filesystem_read]
    max_tokens: 8192

  researcher:
    capabilities: [filesystem_read, internet]
    max_tokens: 16384

  git:
    capabilities: [filesystem_read, git]
    allowed_commands:
      - "git add"
      - "git commit"
      - "git push"
      - "git tag"

  tester:
    capabilities: [filesystem_read, shell]
    allowed_paths:
      - "."
      - "tests/"
```

Policy files are loaded from `aios/policies/` in the project directory. The Policy Engine evaluates agent requests against the applicable policy.

#### Capability Manager

Grants and revokes capabilities at runtime. Capabilities are fine-grained:

| Capability | Allows |
|-----------|--------|
| `filesystem_read` | Read files within allowed paths |
| `filesystem_write` | Create and modify files within allowed paths |
| `shell` | Execute shell commands |
| `internet` | Make network requests |
| `git` | Execute git commands |
| `docker` | Execute docker commands |

The Capability Manager evaluates each agent action:

```python
class CapabilityManager:
    async def authorize(self, agent: str, capability: str, resource: str = None) -> bool:
        policy = await self.policy_engine.get_policy(agent)
        if capability not in policy.capabilities:
            await self.audit.denied(agent, capability, resource)
            return False
        if resource and not self._is_allowed_path(policy, resource):
            await self.audit.denied(agent, capability, resource, "path_not_allowed")
            return False
        await self.audit.granted(agent, capability, resource)
        return True
```

#### Secret Manager

Manages secrets without exposing them to agents or prompts:

```python
class SecretManager:
    async def inject_secrets(self, runtime_context: dict) -> dict:
        # Inject secrets into runtime environment, not into prompts
        # Secrets are masked in logs and audit trails
        return {
            **runtime_context,
            "env": {
                "OPENAI_API_KEY": self._load("OPENAI_API_KEY"),
                "GITHUB_TOKEN": self._load("GITHUB_TOKEN"),
            }
        }
```

Secrets are loaded from environment variables or a secure vault. They are never included in prompts, never logged, and never stored in the Memory Engine.

#### Prompt Firewall

Sanitizes prompts before they reach the language model:

```python
class PromptFirewall:
    async def sanitize(self, prompt: str, agent: str) -> str:
        prompt = self._remove_secrets(prompt)        # Strip detected secrets
        prompt = self._block_injection(prompt)       # Detect prompt injection patterns
        prompt = self._enforce_length(prompt, agent) # Truncate to policy max_tokens
        prompt = self._block_dangerous(prompt)       # Block known dangerous instructions
        prompt = self._inject_context(prompt, agent) # Add mandatory safety context
        return prompt
```

The Firewall runs before every agent interaction. It is the last line of defense between an agent and the model.

#### Audit Logger

Records every security-relevant action:

```
[2026-08-02 14:20:01] agent=coder action=start_session status=allowed
[2026-08-02 14:20:05] agent=coder action=filesystem_write path=src/auth.py status=allowed
[2026-08-02 14:20:12] agent=coder action=shell command="ruff check ." status=allowed
[2026-08-02 14:20:15] agent=coder action=git status=denied reason="coder lacks git capability"
[2026-08-02 14:20:20] agent=coder action=filesystem_write path=~/.ssh/config status=denied reason="path_not_allowed"
```

The audit log is append-only and stored locally.

#### Approval Gates

Requires human confirmation for destructive operations:

```python
class ApprovalGate:
    DESTRUCTIVE_COMMANDS = [
        "git push",
        "git push --force",
        "docker rm",
        "docker system prune",
        "rm -rf",
        "DROP TABLE",
        "DELETE FROM",
    ]

    async def check(self, agent: str, action: str, resource: str) -> ApprovalResult:
        if self._is_destructive(action):
            await self.bus.publish("security.approval_requested", {...})
            response = await self._prompt_user(agent, action, resource)
            if response == "approve":
                await self.bus.publish("security.approval_granted", {...})
                return ApprovalResult.APPROVED
            else:
                await self.bus.publish("security.approval_denied", {...})
                return ApprovalResult.DENIED
        return ApprovalResult.NOT_REQUIRED
```

### Event Contract

| Event | Direction | Description |
|-------|-----------|-------------|
| `agent.started` | Consumed | Initialize agent security context |
| `agent.completed` | Consumed | Revoke agent capabilities |
| `security.violation` | Emitted | Capability check failed |
| `security.approval_requested` | Emitted | Destructive action needs confirmation |
| `security.approval_granted` | Emitted | User approved action |
| `security.approval_denied` | Emitted | User denied action |
| `session.start` | Consumed | Initialize security subsystems |
| `session.shutdown` | Consumed | Finalize audit log |

### v0.1 Scope vs Full Implementation

In v0.1, the Security Manager is a **skeleton**: it loads policy files, logs all events, and prepares the infrastructure. Full enforcement is implemented incrementally.

| Component | v0.1 (Foundation) | v0.6 (Full) |
|-----------|-------------------|-------------|
| Policy Engine | Load YAML policies | Evaluate and enforce |
| Capability Manager | Define capability model | Enforce at agent runtime |
| Secret Manager | Define secret model | Inject secrets into runtime env |
| Prompt Firewall | No-op (pass through) | Sanitize all prompts |
| Audit Logger | Log all events | Query and alert on anomalies |
| Approval Gates | No-op (allow all) | Intercept destructive actions |

## Consequences

### Positive

- **Defense in depth**: Multiple layers (policies, capabilities, firewall, ai-jail) protect the system.
- **Auditability**: Every security decision is logged with timestamp and context.
- **Configurable**: Policies are YAML files, not hard-coded rules.
- **Progressive enforcement**: v0.1 establishes the infrastructure. Enforcement tightens over time.

### Negative

- **Performance**: Every prompt passes through the Firewall. Every action passes through the Capability Manager. Adds latency.
- **Complexity**: Five sub-components with interdependent logic.
- **Configuration burden**: Policies must be written and maintained. Default policies cover common cases, but advanced use requires policy editing.

### Neutral

- Security is defense-in-depth. The Security Manager enforces application-level policies. ai-jail enforces OS-level sandboxing. Neither replaces the other.
- Approval Gates require a user interface. CLI prompts are the v0.6 implementation. Future versions may support non-interactive modes with pre-approved actions.

## Implementation Notes

- [ ] Implement `security/policy.py` — Load and parse YAML policy files
- [ ] Implement `security/capabilities.py` — Capability enum, authorization logic
- [ ] Implement `security/secrets.py` — Load secrets from env, inject into runtime
- [ ] Implement `security/firewall.py` — Prompt sanitization pipeline
- [ ] Implement `security/audit.py` — Structured logging to file
- [ ] Default policy (`aios/policies/default.yaml`) must ship with the project
- [ ] Capability check must run before every agent action
- [ ] Audit log must be append-only; directory created if missing
- [ ] Secrets must be masked in logs: `OPENAI_API_KEY=***`
- [ ] Test: coder with no git capability → git action denied
- [ ] Test: coder writes to allowed path → action allowed
- [ ] Test: coder writes to denied path (~/.ssh) → action denied
- [ ] Test: prompt contains a secret → sanitized version has secret removed
- [ ] Test: destructive action triggers approval request
