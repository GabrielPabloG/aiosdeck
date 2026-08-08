---
name: project-dna
description: Project identity, philosophy, architecture, and conventions.
triggers:
  - architecture
  - principles
  - identity
  - design
  - decisions
  - aiosdeck
scope:
  - architecture
  - python
dependencies: []
priority: 10
---

# Identity

AiosDeck is the AI Operating System for Developers — an intelligent orchestration
platform that coordinates specialized AI agents as a collaborative team.

# Principles

Context before Intelligence — better context produces better answers.
Automation over Prompts — detect, never ask.
One Agent. One Responsibility. — every agent has one job.
Events over Function Calls — communication through an event bus.
Humans Own the Architecture — agents execute, humans decide.
Local First. Cloud Optional. — everything runs locally by default.
Memory Is Part of the System — knowledge persists across sessions.
The Runtime Is Replaceable — OpenCode is one runtime, not the runtime.
Security Is Architecture, Not a Feature — zero-trust from day one.
The ProjDesk Contract — ProjDesk manages development, AiosDeck manages intelligence.

# Architecture

Kernel → Event Dispatcher → Scheduler / Memory / Context → Task Queue →
Security Manager → Quality Pipeline → Agents → Runtime Adapter → OpenCode (via ai-jail)
