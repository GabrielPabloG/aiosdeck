"""Regression: Kernel.run / WorkflowEngine.execute default params are byte-idéntico.

The new ``commit_factory`` and ``create_branch`` params must NOT change behavior
when not passed (defaults must preserve backward compatibility).
"""

import inspect

from aios.backlog.parser import parse_conventional


def test_kernel_run_defaults_preserved() -> None:
    """Verify ``Kernel.run`` signature hasn't changed its first positional defaults."""
    import inspect

    from aios.core.kernel import Kernel

    sig = inspect.signature(Kernel.run)
    params = sig.parameters

    assert "commit_factory" in params
    assert params["commit_factory"].default is None

    assert "create_branch" in params
    assert params["create_branch"].default is True


def test_workflow_execute_defaults_preserved() -> None:
    """Verify ``WorkflowEngine.execute`` signature hasn't changed its first positional defaults."""
    import inspect

    from aios.workflow.engine import WorkflowEngine

    sig = inspect.signature(WorkflowEngine.execute)
    params = sig.parameters

    assert "commit_factory" in params
    assert params["commit_factory"].default is None

    assert "create_branch" in params
    assert params["create_branch"].default is True


def test_kernel_run_positional_compatible() -> None:
    """Old-style positional calls should still work (mypy-level compatibility test)."""
    from aios.core.kernel import Kernel

    k = Kernel()
    sig = inspect.signature(k.run)
    required = [
        p.name
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty and p.name not in ("self", "args", "kwargs")
    ]
    assert required == ["task", "context"]


def test_commit_factory_derived_from_title() -> None:
    """Backlog runner will derive commit_factory from parsed title."""
    typ, scope, subject, version = parse_conventional("feat(backlog): add task models (v0.9.13)")
    scope_part = f"({scope})" if scope else ""
    version_part = f" ({version})" if version else ""
    message = f"{typ}{scope_part}: {subject}{version_part}"
    assert message == "feat(backlog): add task models (v0.9.13)"

    typ, scope, subject, version = parse_conventional("chore: bump version")
    scope_part = f"({scope})" if scope else ""
    version_part = f" ({version})" if version else ""
    message = f"{typ}{scope_part}: {subject}{version_part}"
    assert message == "chore: bump version"
