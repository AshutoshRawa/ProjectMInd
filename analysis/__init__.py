"""
analysis/
=========
Module 4 — Code & Architecture Analysis.

This package implements :class:`core.interfaces.Analyzer` as a long-lived
service that subscribes to :class:`core.EventBus` watcher events and turns
them into structured AI-generated findings.
"""

from analysis.analysis_types import FileAnalysis, FunctionInfo
from analysis.analyzer_engine import Module4AnalyzerEngine
from analysis.ast_analyzer import analyze_python, analyze_python_file
from analysis.complexity import cyclomatic_complexity, file_complexity_score
from analysis.dependency_mapper import build_dependency_graph, resolve_local_import

__all__ = [
    "FileAnalysis",
    "FunctionInfo",
    "Module4AnalyzerEngine",
    "analyze_python",
    "analyze_python_file",
    "build_dependency_graph",
    "cyclomatic_complexity",
    "file_complexity_score",
    "resolve_local_import",
]
