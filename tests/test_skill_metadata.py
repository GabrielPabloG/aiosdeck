"""Tests for SkillMetadata — frontmatter parsing, validation, schema version."""

import pytest

from aios.skills.metadata import (
    SKILL_SCHEMA_VERSION,
    SkillMetadata,
    SkillMetadataError,
    parse_frontmatter,
)


class TestParseFrontmatter:
    def test_empty_text_returns_empty_dict(self):
        assert parse_frontmatter("") == {}
        assert parse_frontmatter("---\n---\n") == {}

    def test_no_frontmatter_returns_empty_dict(self):
        assert parse_frontmatter("# Hello\n\nno frontmatter here") == {}

    def test_simple_scalar_fields(self):
        text = (
            "---\nname: test-skill\ndescription: A test\npriority: 5\nstatus: active\n---\n# Body"
        )
        result = parse_frontmatter(text)
        assert result["name"] == "test-skill"
        assert result["description"] == "A test"
        assert result["priority"] == "5"
        assert result["status"] == "active"

    def test_list_fields(self):
        text = """---
name: test-skill
description: A test
triggers:
  - react
  - dashboard
  - component
scope:
  - python
  - architecture
---"""
        result = parse_frontmatter(text)
        assert result["triggers"] == ["react", "dashboard", "component"]
        assert result["scope"] == ["python", "architecture"]

    def test_string_values_are_stripped(self):
        text = '---\nname: "test-skill"\ndescription: "A test"\n---'
        result = parse_frontmatter(text)
        assert result["name"] == "test-skill"
        assert result["description"] == "A test"

    def test_version_is_parsed_as_string(self):
        text = "---\nname: s\ndescription: d\nversion: 2.1\n---"
        result = parse_frontmatter(text)
        assert result["version"] == "2.1"


class TestSkillMetadataDefaults:
    def test_defaults(self):
        m = SkillMetadata(name="test", description="A test skill")
        assert m.triggers == []
        assert m.scope == []
        assert m.dependencies == []
        assert m.priority == 0
        assert m.version == "1"
        assert m.owner == ""
        assert m.updated_at == ""
        assert m.status == "active"
        assert m.schema_version == SKILL_SCHEMA_VERSION

    def test_to_dict(self):
        m = SkillMetadata(
            name="test-skill",
            description="A test skill",
            triggers=["react", "frontend"],
            scope=["python"],
            dependencies=["project-dna"],
            priority=8,
            version="2",
            owner="team-a",
            updated_at="2026-01-01",
            status="active",
        )
        d = m.to_dict()
        assert d["name"] == "test-skill"
        assert d["description"] == "A test skill"
        assert d["triggers"] == ["react", "frontend"]
        assert d["scope"] == ["python"]
        assert d["dependencies"] == ["project-dna"]
        assert d["priority"] == 8
        assert d["version"] == "2"
        assert d["owner"] == "team-a"
        assert d["updated_at"] == "2026-01-01"
        assert d["status"] == "active"
        assert d["schema_version"] == SKILL_SCHEMA_VERSION

    def test_from_frontmatter(self):
        text = """---
name: coding-style
description: Conventions for Python
triggers:
  - python
  - style
  - linting
scope:
  - python
dependencies:
  - project-dna
priority: 7
version: "1"
status: active
---
# Content here"""
        m = SkillMetadata.from_frontmatter(text)
        assert m.name == "coding-style"
        assert m.description == "Conventions for Python"
        assert m.triggers == ["python", "style", "linting"]
        assert m.scope == ["python"]
        assert m.dependencies == ["project-dna"]
        assert m.priority == 7
        assert m.schema_version == SKILL_SCHEMA_VERSION

    def test_from_frontmatter_minimal(self):
        text = "---\nname: minimal\ndescription: Just enough\n---"
        m = SkillMetadata.from_frontmatter(text)
        assert m.name == "minimal"
        assert m.description == "Just enough"
        assert m.triggers == []
        assert m.priority == 0

    def test_from_frontmatter_empty_text(self):
        with pytest.raises(SkillMetadataError, match="name"):
            SkillMetadata.from_frontmatter("")

    def test_from_frontmatter_no_frontmatter(self):
        with pytest.raises(SkillMetadataError, match="name"):
            SkillMetadata.from_frontmatter("# Just a markdown file\nno frontmatter")


class TestSkillMetadataValidation:
    def test_valid_minimal(self):
        SkillMetadata(name="test", description="ok").validate()

    def test_missing_name(self):
        with pytest.raises(SkillMetadataError, match="name"):
            SkillMetadata(name="", description="ok").validate()

    def test_name_invalid_slug(self):
        with pytest.raises(SkillMetadataError, match="name"):
            SkillMetadata(name="INVALID NAME", description="ok").validate()

    def test_missing_description(self):
        with pytest.raises(SkillMetadataError, match="description"):
            SkillMetadata(name="test", description="").validate()

    def test_invalid_status(self):
        with pytest.raises(SkillMetadataError, match="status"):
            SkillMetadata(name="test", description="ok", status="unknown").validate()

    def test_valid_status_values(self):
        for s in ("active", "deprecated"):
            m = SkillMetadata(name="test", description="ok", status=s)
            m.validate()

    def test_non_int_priority_raises(self):
        with pytest.raises(SkillMetadataError, match="priority"):
            SkillMetadata(name="test", description="ok", priority=-1).validate()

    def test_empty_trigger_string(self):
        with pytest.raises(SkillMetadataError, match="trigger"):
            SkillMetadata(name="test", description="ok", triggers=["valid", ""]).validate()

    def test_empty_scope_string(self):
        with pytest.raises(SkillMetadataError, match="scope"):
            SkillMetadata(name="test", description="ok", scope=["", "python"]).validate()

    def test_empty_dependency_string(self):
        with pytest.raises(SkillMetadataError, match="dependency"):
            SkillMetadata(
                name="test", description="ok", dependencies=["project-dna", ""]
            ).validate()

    def test_invalid_schema_version(self):
        with pytest.raises(SkillMetadataError, match="unsupported schema version"):
            SkillMetadata(name="test", description="ok", schema_version="2").validate()

    def test_validate_returns_self(self):
        m = SkillMetadata(name="test", description="ok")
        assert m.validate() is m
