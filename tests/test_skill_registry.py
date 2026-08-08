"""Tests for SkillRegistry — filesystem scan + validation filtering."""

from pathlib import Path

from aios.skills.registry import SkillRegistry


def _write_skill_file(directory: Path, name: str, content: str) -> Path:
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    return skill_file


def _build_skill_text(
    name: str,
    description: str = "A test skill",
    triggers: list[str] | None = None,
    scope: list[str] | None = None,
    priority: int = 0,
) -> str:
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if triggers:
        lines.append("triggers:")
        for t in triggers:
            lines.append(f"  - {t}")
    if scope:
        lines.append("scope:")
        for s in scope:
            lines.append(f"  - {s}")
    lines.append(f"priority: {priority}")
    lines.append("---")
    lines.append("")
    lines.append("# Content")
    return "\n".join(lines)


class TestSkillRegistryLoad:
    def test_empty_directory(self, tmp_path):
        registry = SkillRegistry(tmp_path)
        assert registry.load() == []

    def test_single_valid_skill(self, tmp_path):
        _write_skill_file(
            tmp_path / ".opencode" / "skills",
            "test-skill",
            _build_skill_text("test-skill", "A test skill", triggers=["python"]),
        )
        registry = SkillRegistry(tmp_path)
        skills = registry.load()
        assert len(skills) == 1
        assert skills[0].name == "test-skill"
        assert skills[0].triggers == ["python"]

    def test_multiple_skills_sorted(self, tmp_path):
        skills_dir = tmp_path / ".opencode" / "skills"
        _write_skill_file(skills_dir, "z-skill", _build_skill_text("z-skill", "Z"))
        _write_skill_file(skills_dir, "a-skill", _build_skill_text("a-skill", "A", triggers=["go"]))
        _write_skill_file(skills_dir, "m-skill", _build_skill_text("m-skill", "M"))

        registry = SkillRegistry(tmp_path)
        skills = registry.load()
        assert [s.name for s in skills] == ["a-skill", "m-skill", "z-skill"]

    def test_no_skills_directory(self, tmp_path):
        registry = SkillRegistry(tmp_path)
        assert registry.load() == []

    def test_no_opencode_directory(self, tmp_path):
        registry = SkillRegistry(tmp_path)
        assert registry.load() == []

    def test_directory_not_a_skill(self, tmp_path):
        skills_dir = tmp_path / ".opencode" / "skills" / "just-a-dir"
        skills_dir.mkdir(parents=True)
        (skills_dir / "notes.txt").write_text("not a skill")

        registry = SkillRegistry(tmp_path)
        assert registry.load() == []

    def test_missing_skuill_md_file(self, tmp_path):
        skill_dir = tmp_path / ".opencode" / "skills" / "no-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "other.md").write_text("not SKILL.md")

        registry = SkillRegistry(tmp_path)
        assert registry.load() == []

    def test_invalid_skill_skipped_with_warning(self, tmp_path, caplog):
        _write_skill_file(
            tmp_path / ".opencode" / "skills",
            "valid-skill",
            _build_skill_text("valid-skill", "Valid", triggers=["python"]),
        )
        _write_skill_file(
            tmp_path / ".opencode" / "skills",
            "bad-skill",
            "no frontmatter here",
        )

        registry = SkillRegistry(tmp_path)
        skills = registry.load()
        assert len(skills) == 1
        assert skills[0].name == "valid-skill"

    def test_validate_raises_on_corrupt(self, tmp_path):
        _write_skill_file(
            tmp_path / ".opencode" / "skills",
            "bad",
            "---\nname: bad\ndescription: ok\nstatus: invalid-value\n---\n",
        )
        registry = SkillRegistry(tmp_path)
        skills = registry.load()
        assert len(skills) == 0

    def test_supplementary_md_files(self, tmp_path):
        skills_dir = tmp_path / ".opencode" / "skills"
        _write_skill_file(skills_dir, "main-skill", _build_skill_text("main-skill", "Main"))
        sub = skills_dir / "main-skill" / "sub"
        sub.mkdir(parents=True)
        (sub / "extra.md").write_text("# Extra doc")

        registry = SkillRegistry(tmp_path)
        skills = registry.load()
        assert len(skills) == 1
        assert skills[0].name == "main-skill"

    def test_get_by_name(self, tmp_path):
        skills_dir = tmp_path / ".opencode" / "skills"
        _write_skill_file(
            skills_dir, "my-skill", _build_skill_text("my-skill", "My skill", priority=5)
        )
        _write_skill_file(skills_dir, "other", _build_skill_text("other", "Other"))

        registry = SkillRegistry(tmp_path)
        registry.load()
        assert registry.get("my-skill").name == "my-skill"
        assert registry.get("my-skill").priority == 5
        assert registry.get("nonexistent") is None


class TestSkillRegistryWithFullMetadata:
    def test_all_fields_parsed(self, tmp_path):
        text = """---
name: full-skill
description: Full metadata test
triggers:
  - react
  - frontend
scope:
  - javascript
  - architecture
dependencies:
  - project-dna
  - coding-style
priority: 8
version: "2.1"
owner: team-frontend
updated_at: "2026-01-15"
status: active
---
# Full skill body"""
        _write_skill_file(tmp_path / ".opencode" / "skills", "full-skill", text)

        registry = SkillRegistry(tmp_path)
        skills = registry.load()
        assert len(skills) == 1
        s = skills[0]
        assert s.name == "full-skill"
        assert s.description == "Full metadata test"
        assert s.triggers == ["react", "frontend"]
        assert s.scope == ["javascript", "architecture"]
        assert s.dependencies == ["project-dna", "coding-style"]
        assert s.priority == 8
        assert s.version == "2.1"
        assert s.owner == "team-frontend"
        assert s.updated_at == "2026-01-15"
        assert s.status == "active"

    def test_deprecated_status(self, tmp_path):
        _write_skill_file(
            tmp_path / ".opencode" / "skills",
            "old-skill",
            "---\nname: old-skill\ndescription: Deprecated\nstatus: deprecated\n---\n",
        )
        registry = SkillRegistry(tmp_path)
        skills = registry.load()
        assert len(skills) == 0  # deprecated skills filtered by default

    def test_include_deprecated(self, tmp_path):
        _write_skill_file(
            tmp_path / ".opencode" / "skills",
            "old-skill",
            "---\nname: old-skill\ndescription: Deprecated\nstatus: deprecated\n---\n",
        )
        registry = SkillRegistry(tmp_path)
        skills = registry.load(include_deprecated=True)
        assert len(skills) == 1
        assert skills[0].status == "deprecated"
