"""Tests for research and learning event topics."""

from aios.events.events import (
    ALL_TOPICS,
    LEARNING_CANDIDATE_APPROVED,
    LEARNING_CANDIDATE_CREATED,
    LEARNING_CANDIDATE_REJECTED,
    LEARNING_INGESTED,
    LEARNING_OBSERVATION_RECORDED,
    LEARNING_TOPICS,
    RESEARCH_COMPLETED,
    RESEARCH_TOPICS,
    Event,
)


class TestResearchTopics:
    def test_research_completed_in_topics(self) -> None:
        assert "research.completed" in RESEARCH_TOPICS
        assert RESEARCH_COMPLETED == "research.completed"

    def test_research_topics_in_all(self) -> None:
        for topic in RESEARCH_TOPICS:
            assert topic in ALL_TOPICS


class TestLearningTopics:
    def test_learning_topics_defined(self) -> None:
        expected = {
            "learning.observation_recorded",
            "learning.candidate.created",
            "learning.candidate.approved",
            "learning.candidate.rejected",
            "learning.ingested",
        }
        assert set(LEARNING_TOPICS) == expected

    def test_learning_topic_constants(self) -> None:
        assert LEARNING_OBSERVATION_RECORDED == "learning.observation_recorded"
        assert LEARNING_CANDIDATE_CREATED == "learning.candidate.created"
        assert LEARNING_CANDIDATE_APPROVED == "learning.candidate.approved"
        assert LEARNING_CANDIDATE_REJECTED == "learning.candidate.rejected"
        assert LEARNING_INGESTED == "learning.ingested"

    def test_learning_topics_in_all(self) -> None:
        for topic in LEARNING_TOPICS:
            assert topic in ALL_TOPICS


class TestEventBusAcceptsNewTopics:
    def test_research_event_published(self) -> None:
        event = Event(
            topic=RESEARCH_COMPLETED,
            payload={
                "correlation_id": "run-1",
                "memory_candidates": [],
                "findings": 3,
                "sources": 2,
            },
        )
        assert event.topic == "research.completed"
        assert event.payload["findings"] == 3

    def test_learning_observation_event(self) -> None:
        event = Event(
            topic=LEARNING_OBSERVATION_RECORDED,
            payload={"observation_id": 1, "source_event": "quality.gate_failed"},
        )
        assert event.topic == "learning.observation_recorded"

    def test_all_topics_count(self) -> None:
        assert len(ALL_TOPICS) == 57
