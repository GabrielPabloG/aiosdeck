"""Learning Engine — event-driven observation capture and candidate extraction.

Subscribes to quality.gate_*, agent.execution.failed, and research.completed
events. Observations are drafts; candidates are scored proposals. Approval and
ingestion are governed separately.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aios.events.events import (
    LEARNING_CANDIDATE_APPROVED,
    LEARNING_CANDIDATE_CREATED,
    LEARNING_CANDIDATE_REJECTED,
    LEARNING_INGESTED,
    LEARNING_OBSERVATION_RECORDED,
    Event,
)
from aios.learning.advisor import RulesAdvisor
from aios.learning.extractor import (
    create_candidate_from_observation,
    extract_from_agent_failure,
    extract_from_quality_event,
    extract_from_research_event,
)
from aios.learning.models import (
    CandidateState,
    LearningCandidate,
    ObservationRecord,
)
from aios.learning.store import LearningStore

if TYPE_CHECKING:
    from aios.memory.engine import MemoryEngine

logger = logging.getLogger("aios.learning")


class LearningEngine:
    name = "learning"

    def __init__(
        self,
        project_path: Path | None = None,
        db_path: str | None = None,
        memory: MemoryEngine | None = None,
    ) -> None:
        self._project_path = project_path or Path.cwd()
        self._project_id = self._project_path.resolve().as_posix()
        self._db_path = Path(db_path) if db_path else self._project_path / ".aios" / "memory.db"
        self._store: LearningStore | None = None
        self._bus = None
        self._memory = memory
        self._confidence_threshold: float = 0.5
        self._min_evidence: int = 1
        self._recurrence_threshold: int = 2
        self._enabled: bool = True
        self._auto_capture: bool = True
        self._error_counts: dict[str, int] = {}
        self._subscribed: bool = False

    def set_event_bus(self, bus) -> None:
        self._bus = bus
        if (
            self._auto_capture
            and bus is not None
            and self._store is not None
            and not self._subscribed
        ):
            self._subscribe_events()

    def initialize(self) -> None:
        try:
            self._store = LearningStore(self._db_path, self._project_id)
            self._store.open()
        except RuntimeError:
            self._store = None
            logger.warning("Learning store initialization failed; learning disabled")

        if self._auto_capture and self._bus is not None:
            self._subscribe_events()

    def health_check(self) -> bool:
        if self._store is None:
            return False
        return self._store.is_open()

    def shutdown(self) -> None:
        if self._store:
            self._store.close()
            self._store = None

    def configure(
        self,
        confidence_threshold: float | None = None,
        min_evidence: int | None = None,
        recurrence_threshold: int | None = None,
        enabled: bool | None = None,
        auto_capture: bool | None = None,
    ) -> None:
        if confidence_threshold is not None:
            self._confidence_threshold = confidence_threshold
        if min_evidence is not None:
            self._min_evidence = min_evidence
        if recurrence_threshold is not None:
            self._recurrence_threshold = recurrence_threshold
        if enabled is not None:
            self._enabled = enabled
        if auto_capture is not None:
            self._auto_capture = auto_capture

    def observe(self, source_event: str, payload: dict) -> list[int]:
        """Capture observations from an event. Returns list of observation IDs."""
        if not self._enabled or self._store is None:
            return []

        payload_with_source = dict(payload)
        payload_with_source["source_event"] = source_event

        observations: list[ObservationRecord] = []

        if source_event.startswith("quality.gate_"):
            observations = extract_from_quality_event(payload_with_source)
        elif source_event == "research.completed":
            observations = extract_from_research_event(payload_with_source)
        elif source_event == "agent.execution.failed":
            observations = self._extract_agent_failures(payload_with_source)

        ids: list[int] = []
        for obs in observations:
            existing = self._store.find_observation_by_source(
                obs.source_execution_id, obs.source_id
            )
            if existing is not None:
                continue
            obs.project_id = self._project_id
            obs_id = self._store.insert_observation(obs)
            if obs_id > 0:
                ids.append(obs_id)
            if self._bus:
                self._bus.publish(
                    LEARNING_OBSERVATION_RECORDED,
                    {"observation_id": obs_id, "source_event": obs.source_event},
                )

        return ids

    def extract(
        self,
        observation_id: int | None = None,
    ) -> list[int]:
        """Extract candidates from observations. Returns list of candidate IDs."""
        if self._store is None:
            return []

        observations = self._get_observations_to_extract(observation_id)
        candidate_ids: list[int] = []

        for obs in observations:
            candidate = create_candidate_from_observation(
                obs, self._confidence_threshold, self._min_evidence
            )
            if candidate is None:
                continue

            existing = self._store.find_candidate_by_hash(candidate.dedupe_hash)
            if existing is not None:
                continue

            candidate_id = self._store.insert_candidate(candidate)
            if candidate_id > 0:
                candidate_ids.append(candidate_id)
            if self._bus:
                self._bus.publish(
                    LEARNING_CANDIDATE_CREATED,
                    {"candidate_id": candidate_id, "type": candidate.suggested_type},
                )

        return candidate_ids

    def approve(self, candidate_id: int, reviewer: str = "human", reason: str = "") -> int:
        """Approve a candidate. Returns review ID."""
        if self._store is None:
            raise RuntimeError("Learning store not available")

        candidate = self._store.get_candidate(candidate_id)
        if candidate is None:
            raise RuntimeError(f"Candidate {candidate_id} not found")
        if candidate.state in ("approved", "rejected", "ingested"):
            raise RuntimeError(f"Cannot approve candidate in state '{candidate.state}'")

        advisor = self._get_advisor()
        decision = advisor.review(candidate)

        self._store.update_candidate_state(candidate_id, "approved")
        review_id = self._store.insert_review(
            candidate_id=candidate_id,
            advisor=advisor.name,
            recommendation=decision.recommendation,
            justification=decision.justification,
            reviewer=reviewer,
            decision="approve",
            reason=reason or decision.justification,
        )

        if self._bus:
            self._bus.publish(
                LEARNING_CANDIDATE_APPROVED,
                {"candidate_id": candidate_id, "type": candidate.suggested_type},
            )

        return review_id

    def reject(self, candidate_id: int, reason: str, reviewer: str = "human") -> int:
        """Reject a candidate. Reason is required."""
        if not reason:
            raise RuntimeError("Reason is required to reject a candidate")
        if self._store is None:
            raise RuntimeError("Learning store not available")

        candidate = self._store.get_candidate(candidate_id)
        if candidate is None:
            raise RuntimeError(f"Candidate {candidate_id} not found")
        if candidate.state in ("approved", "rejected", "ingested"):
            raise RuntimeError(f"Cannot reject candidate in state '{candidate.state}'")

        advisor = self._get_advisor()
        decision = advisor.review(candidate)

        self._store.update_candidate_state(candidate_id, "rejected")
        review_id = self._store.insert_review(
            candidate_id=candidate_id,
            advisor=advisor.name,
            recommendation=decision.recommendation,
            justification=decision.justification,
            reviewer=reviewer,
            decision="reject",
            reason=reason,
        )

        if self._bus:
            self._bus.publish(
                LEARNING_CANDIDATE_REJECTED,
                {"candidate_id": candidate_id, "type": candidate.suggested_type},
            )

        return review_id

    def ingest(self, candidate_id: int) -> int:
        """Ingest an approved candidate into memory. Returns new ingest_version."""
        if self._store is None:
            raise RuntimeError("Learning store not available")

        candidate = self._store.get_candidate(candidate_id)
        if candidate is None:
            raise RuntimeError(f"Candidate {candidate_id} not found")
        if candidate.state != "approved":
            raise RuntimeError(
                f"Candidate {candidate_id} must be approved (current: {candidate.state})"
            )

        if self._memory is None:
            raise RuntimeError("Memory engine not available; cannot ingest")

        memory_id = self._write_to_memory(candidate)
        new_version = candidate.ingest_version + 1

        self._store.update_candidate_state(
            candidate_id,
            "ingested",
            ingest_version=new_version,
            ingested_memory_id=memory_id or "",
        )
        self._store.insert_review(
            candidate_id=candidate_id,
            advisor="engine",
            recommendation="ingest",
            justification=f"Ingested into memory as {memory_id}",
            reviewer="engine",
            decision="ingested",
            reason=f"version {new_version} → {memory_id}",
        )

        if self._bus:
            self._bus.publish(
                LEARNING_INGESTED,
                {
                    "candidate_id": candidate_id,
                    "memory_id": memory_id,
                    "type": candidate.suggested_type,
                },
            )

        return new_version

    def _write_to_memory(self, candidate: LearningCandidate) -> str | None:
        if self._memory is None:
            return None

        content = candidate.content
        kind = candidate.suggested_type
        first_line = content.split("\n")[0].strip()[:100]
        prefix = f"learning:candidate:{candidate.id}"

        memory_id: str | None = None
        try:
            if kind == "convention":
                self._memory.remember_convention(rule=content, category="learning", source=prefix)
                memory_id = f"convention:{first_line[:50]}"
            elif kind == "decision":
                self._memory.remember_decision(title=first_line, context=prefix, decision=content)
                memory_id = f"decision:{first_line[:50]}"
            elif kind == "pattern":
                self._memory.remember_pattern(name=first_line, description=content)
                memory_id = f"pattern:{first_line[:50]}"
            elif kind == "mistake":
                self._memory.remember_mistake(
                    description=content, category="learning", severity=candidate.risk_level
                )
                memory_id = f"mistake:{first_line[:50]}"
            elif kind in ("architecture_note", "dependency-note"):
                self._memory.remember_decision(title=first_line, context=prefix, decision=content)
                memory_id = f"decision:{first_line[:50]}"
            else:
                self._memory.remember_pattern(name=first_line, description=content)
                memory_id = f"pattern:{first_line[:50]}"
        except Exception as exc:
            logger.error("Memory write failed for candidate %d: %s", candidate.id, exc)
            memory_id = f"error:{exc}"

        return memory_id

    def get_reviews(self, candidate_id: int) -> list[dict]:
        if self._store is None:
            return []
        return self._store.get_reviews(candidate_id)

    def get_advisor_recommendation(self, candidate_id: int) -> dict | None:
        if self._store is None:
            return None
        candidate = self._store.get_candidate(candidate_id)
        if candidate is None:
            return None
        advisor = self._get_advisor()
        decision = advisor.review(candidate)
        return {
            "recommendation": decision.recommendation,
            "justification": decision.justification,
            "advisor": decision.advisor,
        }

    def get_candidates(
        self, state: CandidateState | None = None, limit: int = 100
    ) -> list[LearningCandidate]:
        if self._store is None:
            return []
        return self._store.list_candidates(state=state, limit=limit)

    def get_candidate(self, candidate_id: int) -> LearningCandidate | None:
        if self._store is None:
            return None
        return self._store.get_candidate(candidate_id)

    def get_store(self) -> LearningStore | None:
        return self._store

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_advisor(self) -> RulesAdvisor:
        return RulesAdvisor(confidence_threshold=self._confidence_threshold)

    def _extract_agent_failures(self, payload: dict) -> list[ObservationRecord]:
        error_msg = str(payload.get("error", "") or payload.get("errors", ["unknown"])[0])
        hash_key = error_msg
        count = self._error_counts.get(hash_key, 0) + 1
        self._error_counts[hash_key] = count
        return extract_from_agent_failure(payload, count, self._recurrence_threshold)

    def _get_observations_to_extract(self, observation_id: int | None) -> list[ObservationRecord]:
        if self._store is None:
            return []
        if observation_id is not None:
            obs = self._store.get_observation(observation_id)
            return [obs] if obs is not None else []
        return self._store.list_observations_by_state("draft")

    def _subscribe_events(self) -> None:
        if self._bus is None or self._subscribed:
            return

        topics = [
            "quality.gate_failed",
            "quality.gate_blocked",
            "research.completed",
            "agent.execution.failed",
        ]

        def handler(event: Event) -> None:
            payload = event.payload or {}
            payload["correlation_id"] = payload.get("correlation_id", event.correlation_id)
            self.observe(event.topic, payload)

        for topic in topics:
            self._bus.subscribe(topic, handler)

        self._subscribed = True

    def _on_event(self, event: Event) -> None:
        self.observe(event.topic, event.payload or {})
