"""Collector registry and discovery."""

from aios.context.collectors.javascript import JavaScriptDetector
from aios.context.collectors.python import PythonDetector
from aios.context.collectors.shell import ShellDetector

DETECTORS = [
    PythonDetector,
    JavaScriptDetector,
    ShellDetector,
]
