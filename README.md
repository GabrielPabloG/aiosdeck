# AiosDeck

The AI Operating System for Developers — an intelligent orchestration platform
that coordinates specialized AI agents as a collaborative team.

Instead of talking to a single language model, you work with a coordinated team
of specialized agents — each with one responsibility, governed by a kernel that
manages context, memory, scheduling, workflows, and security.

- **Status**: Implemented — core orchestration, agents, workflows, security,
  and telemetry are shipped and tested (1400+ tests). The routing engine
  supports a configurable fallback chain (`routing.fallback_providers`), and
  the benchmark suite is operational with a versioned v1.1.1 baseline
  (full + bare); see [docs/README.md](docs/README.md) and
  [.aios/benchmarks/README.md](.aios/benchmarks/README.md).
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

Requirements: an agent runtime (currently **OpenCode**) and **ai-jail** (security sandbox).
[ProjDesk](docs/integrations/projdesk.md) is optional but recommended.

## Documentation

Full documentation lives in [docs/README.md](docs/README.md).

- [Vision](docs/vision.md) — where AiosDeck is going
- [Roadmap](docs/roadmap.md) — milestones M1–M8 + design track (status legend inside)
- [Philosophy](docs/philosophy.md) — the ten principles
- [Architecture](docs/architecture.md) — system design
- [Design](docs/design/README.md) — control-room identity, tokens, Penpot artifacts
- [Decisions](docs/decisions/) — architecture decision records (ADRs)
- [Agents](docs/agents/) — agent ecosystem
- [Internals](docs/internals/) — component specifications

## License

[MIT](LICENSE) © Gabriel Pablo Garcia
