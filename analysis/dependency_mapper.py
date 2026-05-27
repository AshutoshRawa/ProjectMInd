from __future__ import annotations

from pathlib import Path

from analysis.analysis_types import FileAnalysis


def build_dependency_graph(
    analyses: list[FileAnalysis], *, project_root: Path
) -> dict[str, list[str]]:
    """
    Build a project-local dependency graph from `imports`.

    - Keys are analyzed file paths (string).
    - Values are file paths (string) that appear to be imported locally.

    Heuristic: treat imports as local if their first segment is a directory
    in the project root, or if a corresponding `.py` file exists.
    """
    roots = {p.name for p in project_root.iterdir() if p.is_dir()}
    file_index: dict[str, str] = {}
    for a in analyses:
        p = Path(a.path)
        if p.suffix == ".py":
            module = _path_to_module(p, project_root=project_root)
            file_index[module] = a.path

    graph: dict[str, list[str]] = {}
    for a in analyses:
        deps: list[str] = []
        for imp in a.imports:
            target = _resolve_local_import(
                imp, roots=roots, file_index=file_index, project_root=project_root
            )
            if target is not None and target != a.path:
                deps.append(target)
        graph[a.path] = sorted(set(deps))
    return graph


def _path_to_module(path: Path, *, project_root: Path) -> str:
    rel = path.resolve().relative_to(project_root.resolve())
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join([p for p in parts if p])


def _resolve_local_import(
    imp: str,
    *,
    roots: set[str],
    file_index: dict[str, str],
    project_root: Path,
) -> str | None:
    if not imp:
        return None
    top = imp.split(".", 1)[0]

    # Prefer exact match with an analyzed python module.
    if imp in file_index:
        return file_index[imp]

    # If import starts with a root directory, try resolving.
    if top in roots:
        candidate = project_root / Path(*imp.split("."))
        if (candidate.with_suffix(".py")).exists():
            return str(candidate.with_suffix(".py"))
        if (candidate / "__init__.py").exists():
            return str(candidate / "__init__.py")
    return None
