"""Kernel factory — assembles all engines and agents from domain building blocks.

Every domain knows how to register itself into the Kernel. This module is
the single place where engines, agents, and cross-cutting dependencies
(executor, skills, context) are wired together. The CLI imports only this
module; all agent/engine imports live here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from aios.agents import AgentExecutor
from aios.agents.developer import DeveloperAgent
from aios.agents.documentation import DocumentationAgent
from aios.agents.git import GitAgent
from aios.agents.planner import PlannerAgent
from aios.agents.research import ResearchAgent
from aios.agents.reviewer import ReviewerAgent
from aios.agents.tester import TesterAgent
from aios.config import ConfigEngine
from aios.config.loader import ConfigLoader
from aios.context import ContextAssembler, ContextEngine
from aios.core import Kernel
from aios.events import EventsEngine
from aios.knowledge import KnowledgeEngine
from aios.learning import LearningEngine
from aios.memory import MemoryEngine
from aios.retrieval.providers import OllamaEmbeddingProvider
from aios.retrieval.selector import ContextBudget
from aios.routing.engine import RuleBasedRouter
from aios.runtime import RuntimeEngine
from aios.runtime.ollama import OllamaAdapter
from aios.runtime.opencode import OpenCodeAdapter
from aios.scheduler import KanbanEngine
from aios.security import SecurityEngine
from aios.skills.assembler import SkillAssembler
from aios.skills.discovery import SkillDiscoveryService
from aios.skills.registry import SkillRegistry
from aios.skills.retrieval import SkillRetrievalService
from aios.skills.telemetry import SkillUsageRecorder
from aios.storage.pool import ConnectionPool
from aios.telemetry import TelemetryEngine
from aios.workflow import WorkflowEngine

logger = logging.getLogger("aios.core.factory")


def create_kernel(project_path: Path) -> Kernel:
    """Build a fully-wired Kernel with all engines and agents registered."""
    kernel = Kernel(project_path=str(project_path))
    pool = ConnectionPool()
    kernel.set_storage_pool(pool)
    kernel.register(ConfigEngine(project_path=project_path))
    kernel.register(ContextEngine(project_path=project_path))
    kernel.register(MemoryEngine(project_path=project_path, connection_pool=pool))
    kernel.register(
        LearningEngine(
            project_path=project_path,
            memory=kernel.get_engine("memory"),
            connection_pool=pool,
        )
    )
    kernel.register(KanbanEngine(project_path=project_path, connection_pool=pool))
    events = EventsEngine()
    kernel.register(events)
    kernel.register(TelemetryEngine(project_path=project_path, connection_pool=pool))
    embedding_host = os.environ.get("AIOS_OLLAMA_HOST", "http://localhost:11434")
    embedding_model = os.environ.get("AIOS_EMBEDDING_MODEL", "nomic-embed-text")
    embedding_provider = OllamaEmbeddingProvider(model=embedding_model, host=embedding_host)
    kernel.register(
        KnowledgeEngine(
            project_path=project_path,
            embedding_provider=embedding_provider,
            connection_pool=pool,
        )
    )
    security = SecurityEngine(project_path=project_path)
    kernel.register(security)
    executor = AgentExecutor(capabilities_enforcer=security._enforcer)
    executor.set_event_bus(events.bus)
    kernel.set_executor(executor)

    config = ConfigLoader(project_path=project_path).load()
    routing_config = config.routing
    router = None
    if routing_config and routing_config.enabled:
        router = RuleBasedRouter(routing_config)

    adapter = OllamaAdapter() if config.runtime.adapter == "ollama" else OpenCodeAdapter()
    runtime = RuntimeEngine(adapter=adapter, router=router, config=config)
    kernel.register(runtime)

    assembler = _build_skill_assembler(project_path, kernel)
    context_assembler = _build_context_assembler(project_path, kernel)
    developer = DeveloperAgent(runtime, skills=assembler, assembler=context_assembler)
    planner = PlannerAgent(runtime, skills=assembler, assembler=context_assembler)
    reviewer = ReviewerAgent()
    research_agent = ResearchAgent()
    kernel.register(developer)
    kernel.register(planner)
    kernel.register(reviewer)
    kernel.register(research_agent)
    git = GitAgent(repository=project_path) if (project_path / ".git").exists() else None
    kernel.register(
        WorkflowEngine(
            planner=planner,
            scheduler=kernel.get_engine("scheduler"),
            developer=developer,
            reviewer=reviewer,
            researcher=research_agent,
            tester=TesterAgent(),
            documentation=DocumentationAgent(docs_dir=str(project_path / "docs")),
            git=git,
            project_path=project_path,
            executor=executor,
        )
    )
    return kernel


def _build_skill_assembler(project_path: Path, kernel: Kernel):
    try:
        registry = SkillRegistry(project_path)
        discovery = SkillDiscoveryService(registry)
        knowledge = kernel.get_engine("knowledge")
        telemetry = kernel.get_engine("telemetry")
        if knowledge is not None:
            retrieval = SkillRetrievalService(knowledge)
            recorder = SkillUsageRecorder(telemetry)
            return SkillAssembler(discovery=discovery, retrieval=retrieval, recorder=recorder)
    except Exception:
        logger.warning(
            "Failed to build skill assembler (skills will be unavailable)", exc_info=True
        )
        pass
    return SkillAssembler()


def _build_context_assembler(project_path: Path, kernel: Kernel):
    try:
        knowledge = kernel.get_engine("knowledge")
        return ContextAssembler(knowledge=knowledge, budget=ContextBudget())
    except Exception:
        logger.warning("Failed to build context assembler (context will be limited)", exc_info=True)
        pass
    return ContextAssembler(knowledge=None)
