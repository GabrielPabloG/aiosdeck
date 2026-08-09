# ADR-0002 — ai-jail as Security Sandbox

**Status**: Implemented
**Level**: Architecture
**Review date**: 2026-08-09
**Date**: 2026-08-02

## Context

AiosDeck agents execute code, access files, run shell commands, and interact with models. Without a sandbox, a misconfigured agent or a prompt injection attack could compromise the developer's machine.

We evaluated four approaches:

| Option | Description |
|--------|-------------|
| **No sandbox** | Rely on the Security Manager's capability checks alone |
| **ai-jail** | Lightweight sandbox: process isolation, filesystem masks, secret masking, per-project policies |
| **Docker containers** | Full container isolation for every agent run |
| **Custom sandbox** | Build our own process isolation and filesystem restriction layer |

## Decision

**Use ai-jail as the security sandbox.** The Runtime Adapter always invokes OpenCode through ai-jail (`ai-jail opencode`). If ai-jail is not installed, the system degrades gracefully with a warning — but the intended path always includes sandbox isolation.

ai-jail provides OS-level security: process isolation, controlled filesystem mounts, secret masking, and resource limits. The AiosDeck Security Manager provides application-level security: capability checks, policy enforcement, prompt sanitization, and audit logging. Together they form **defense in depth**.

## Consequences

### Positive

- **Defense in depth**: Application-level (AiosDeck Security Manager) + OS-level (ai-jail) security. Neither layer trusts the other.
- **Proven isolation model**: Process isolation and filesystem masking are well-understood security primitives.
- **Alignment**: ai-jail was designed for exactly this use case — sandboxing AI agent tool execution.
- **Gradual adoption**: System works without ai-jail (with warning). Teams can install ai-jail when ready for production security.

### Negative

- **Dependency**: ai-jail is an external project. Breaking changes or abandonment would require a new sandbox or degradation to direct execution.
- **Startup overhead**: Each agent invocation adds process startup latency through the sandbox.
- **Configuration complexity**: ai-jail policies and AiosDeck policies must be kept consistent. Two policy files per project.

### Neutral

- ai-jail is an implementation of the zero-trust principle. If it is replaced, the principle remains — only the tool changes.
- The Runtime Adapter abstracts the sandbox invocation. No other component knows ai-jail is the sandbox.
