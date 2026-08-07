# AiosDeck

The AI Operating System for Developers — an intelligent orchestration platform
that coordinates specialized AI agents as a collaborative team.

Instead of talking to a single language model, you work with a coordinated team
of specialized agents — each with one responsibility, governed by a kernel that
manages context, memory, scheduling, workflows, and security.

- **Status**: alpha
- **Platform**: Linux
- **Language**: Python 3.12+ (zero runtime dependencies)

## Quick Start

```bash
git clone <repository-url> && cd aiosdeck
python -m venv .venv && source .venv/bin/activate
pip install -e .
aios                                # Show dashboard
aios doctor                         # Run diagnostics
aios memory add convention "Use snake_case"
aios plan "add OAuth2 login" --run  # Plan and run the central workflow pipeline
```

Requirements: **OpenCode** (agent runtime) and **ai-jail** (security sandbox).
[ProjDesk](docs/integrations/projdesk.md) is optional but recommended.

## Documentation

Full documentation lives in [docs/README.md](docs/README.md).

- [Vision](docs/vision.md) — where AiosDeck is going
- [Philosophy](docs/philosophy.md) — the ten principles
- [Architecture](docs/architecture.md) — system design
- [Decisions](docs/decisions/) — architecture decision records (ADRs)
- [Agents](docs/agents/) — agent ecosystem
- [Internals](docs/internals/) — component specifications

## License

[MIT](LICENSE) © Gabriel Pablo Garcia
