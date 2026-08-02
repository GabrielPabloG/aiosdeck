---
name: coding-style
description: Code conventions, naming, and organization standards for this project.
---

# Language

Python 3.12+. Zero external dependencies for core.

# Naming

- Modules: lowercase, no underscores unless necessary (config, context, runtime)
- Classes: PascalCase (ContextEngine, RuntimeAdapter)
- Functions: snake_case (detect_project, load_config)
- Constants: UPPER_SNAKE_CASE

# Organization

- One responsibility per module. Files stay under 200 lines.
- Public API exported via __init__.py.
- No circular imports. Dependency direction: CLI → Kernel → Engines.

# Patterns

- Favor dataclasses over plain dicts for structured data.
- Favor protocols (typing.Protocol) over abstract base classes.
- Use asyncio for I/O-bound operations (subprocess, file reads).
- No global mutable state. Engines are instantiated by the Kernel.
