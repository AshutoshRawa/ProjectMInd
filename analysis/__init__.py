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

__all__ = ["FileAnalysis", "FunctionInfo", "Module4AnalyzerEngine"]
