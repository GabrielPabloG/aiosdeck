"""Unit tests for the reviewer → canonical severity mapper.

The reviewer detectors (aios.agents.detectors) emit ``info`` / ``warning`` /
``error``; the quality pipeline canonical vocabulary is
``low`` / ``medium`` / ``high`` / ``critical``. Every reviewer severity must
map to exactly one canonical value, case-insensitively.
"""

import pytest

from aios.quality.contracts import Severity, severity_mapper


@pytest.mark.parametrize(
    ("reviewer_severity", "expected"),
    [
        ("info", Severity.LOW),
        ("warning", Severity.MEDIUM),
        ("error", Severity.HIGH),
        ("INFO", Severity.LOW),
        ("Warning", Severity.MEDIUM),
        ("ERROR", Severity.HIGH),
    ],
)
def test_severity_mapper_maps_all_reviewer_severities(reviewer_severity, expected):
    assert severity_mapper(reviewer_severity) is expected


def test_severity_mapper_rejects_unknown_severity():
    with pytest.raises(ValueError):
        severity_mapper("fatal")


def test_severity_mapper_never_downgrades_to_critical_without_input():
    assert severity_mapper("error") is Severity.HIGH
