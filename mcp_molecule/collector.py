"""
mcp_molecule/collector.py
Reads an Ansible collection from disk → CollectionContext.
Handles all four role-reference patterns used in Ansible Middleware collections:
  1. include_role / import_role bare name
  2. include_role / import_role fully-qualified name (namespace.collection.role)
  3. roles: block shorthand  (- role: name  or  - name)
  4. ansible.builtin.import_playbook indirection
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from .types import CollectionContext, RoleInfo, RoleVar, ScenarioInfo

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _safe_read(path: Path) -> str:
    """Return file content or empty string if the file does not exist."""
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        log.debug("Could not read %s: %s", path, exc)
        return ""


def _parse_yaml(content: str) -> Any:
    """Parse YAML safely; return empty dict on any error."""
    try:
        return yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        log.debug("Failed to parse YAML content: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Role-reference extraction
# ---------------------------------------------------------------------------

# Patterns compiled once at module load for performance.
_RE_INCLUDE_NAME = re.compile(r"^\s+name:\s+[\"']?([\w.]+)[\"']?", re.MULTILINE)
_RE_ROLE_BLOCK   = re.compile(r"^\s+-\s+role:\s+[\"']?([\w.]+)[\"']?", re.MULTILINE)
_RE_ROLE_LIST    = re.compile(r"^\s+-\s+[\"']?([\w]+)[\"']?\s*$", re.MULTILINE)
_RE_IMPORT_PB    = re.compile(r"import_playbook:\s+[\"']?([\w./\-]+\.ya?ml)[\"']?")
_RE_VARS_INDENT  = re.compile(r"^\s{4,12}([\w]+):\s", re.MULTILINE)
_RE_VARS_TOP     = re.compile(r"^([\w]+):\s", re.MULTILINE)


def _extract_roles_from_text(text: str, known_roles: set[str]) -> list[str]:
    """
    Extract all known role names referenced in a block of YAML text.
    Handles bare names, FQCNs, and roles: block syntax.
    """
    found: list[str] = []

    # Pattern 1 — include_role / import_role  name: <role>
    for m in _RE_INCLUDE_NAME.finditer(text):
        bare = m.group(1).split(".")[-1]
        if bare in known_roles:
            found.append(bare)

    # Pattern 2 — roles: block  - role: <role>
    for m in _RE_ROLE_BLOCK.finditer(text):
        bare = m.group(1).split(".")[-1]
        if bare in known_roles:
            found.append(bare)

    # Pattern 3 — roles: block bare list item  - <role>
    for m in _RE_ROLE_LIST.finditer(text):
        if m.group(1) in known_roles:
            found.append(m.group(1))

    return found


def _resolve_imported_playbooks(
    converge_content: str,
    scenario_dir: Path,
    collection_path: Path,
    known_roles: set[str],
) -> list[str]:
    """
    Follow import_playbook references one level deep and collect roles
    from the imported playbook file.
    """
    found: list[str] = []

    for m in _RE_IMPORT_PB.finditer(converge_content):
        raw_ref = m.group(1)

        # Resolve relative to scenario dir first, then collection root
        candidates = [
            (scenario_dir / raw_ref).resolve(),
            (collection_path / raw_ref).resolve(),
        ]

        for candidate in candidates:
            if candidate.exists():
                content = _safe_read(candidate)
                found.extend(_extract_roles_from_text(content, known_roles))
                break

    return found


# ---------------------------------------------------------------------------
# Role collector
# ---------------------------------------------------------------------------

def _collect_role(roles_dir: Path, role_name: str) -> RoleInfo:
    role_dir   = roles_dir / role_name
    specs_path = role_dir / "meta" / "argument_specs.yml"
    defs_path  = role_dir / "defaults" / "main.yml"
    tasks_dir  = role_dir / "tasks"

    # ── Variables from argument_specs.yml ────────────────────────────────
    variables: list[RoleVar] = []
    specs_raw = _safe_read(specs_path)
    if specs_raw:
        specs = _parse_yaml(specs_raw)
        main_opts: dict[str, Any] = (
            specs.get("argument_specs", {})
                 .get("main", {})
                 .get("options", {})
        )
        for var_name, meta in main_opts.items():
            variables.append(RoleVar(
                name=var_name,
                type=meta.get("type", "str"),
                required=meta.get("required", False) is True,
                default=meta.get("default"),
                description=meta.get("description", ""),
            ))

    # ── Defaults ──────────────────────────────────────────────────────────
    defaults: dict[str, Any] = _parse_yaml(_safe_read(defs_path))

    # ── Task files ────────────────────────────────────────────────────────
    task_files: list[str] = []
    if tasks_dir.exists():
        for root, _, files in os.walk(tasks_dir):
            for f in files:
                if f.endswith((".yml", ".yaml")):
                    task_files.append(
                        str(Path(root, f).relative_to(tasks_dir))
                    )

    return RoleInfo(
        name=role_name,
        variables=variables,
        task_files=task_files,
        defaults=defaults,
    )


# ---------------------------------------------------------------------------
# Scenario collector
# ---------------------------------------------------------------------------

def _collect_scenario(
    molecule_dir: Path,
    scenario_name: str,
    roles: list[RoleInfo],
    collection_path: Path,
) -> ScenarioInfo:
    scenario_dir     = molecule_dir / scenario_name
    converge_content = _safe_read(scenario_dir / "converge.yml")
    verify_content   = _safe_read(scenario_dir / "verify.yml")
    molecule_content = _safe_read(scenario_dir / "molecule.yml")

    known_roles = {r.name for r in roles}

    # ── Roles used: direct references ────────────────────────────────────
    roles_used = _extract_roles_from_text(converge_content, known_roles)

    # ── Roles used: follow import_playbook one level deep ─────────────────
    roles_used.extend(
        _resolve_imported_playbooks(
            converge_content, scenario_dir, collection_path, known_roles
        )
    )

    # ── Variables set: indented vars block in converge.yml ────────────────
    vars_set = [m.group(1) for m in _RE_VARS_INDENT.finditer(converge_content)]

    # ── Variables set: vars.yml top-level keys ───────────────────────────
    vars_content = _safe_read(scenario_dir / "vars.yml")
    vars_set.extend(m.group(1) for m in _RE_VARS_TOP.finditer(vars_content))

    return ScenarioInfo(
        name=scenario_name,
        roles_used=list(dict.fromkeys(roles_used)),   # deduplicate, preserve order
        vars_set=list(dict.fromkeys(vars_set)),
        converge_content=converge_content,
        verify_content=verify_content,
        molecule_content=molecule_content,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def collect_collection(collection_path: Path) -> CollectionContext:
    """Read the Ansible collection at collection_path → CollectionContext."""
    root       = Path(collection_path)
    galaxy_path = root / "galaxy.yml"

    if not galaxy_path.exists():
        raise FileNotFoundError(
            f"galaxy.yml not found at {galaxy_path}. Is this an Ansible collection?"
        )

    galaxy      = _parse_yaml(_safe_read(galaxy_path))
    roles_dir   = root / "roles"
    molecule_dir = root / "molecule"

    roles: list[RoleInfo] = []
    if roles_dir.exists():
        roles = [
            _collect_role(roles_dir, entry.name)
            for entry in sorted(roles_dir.iterdir())
            if entry.is_dir()
        ]

    scenarios: list[ScenarioInfo] = []
    if molecule_dir.exists():
        scenarios = [
            _collect_scenario(molecule_dir, entry.name, roles, root)
            for entry in sorted(molecule_dir.iterdir())
            if entry.is_dir()
        ]

    return CollectionContext(
        namespace=galaxy.get("namespace", "unknown"),
        collection_name=galaxy.get("name", "unknown"),
        collection_path=str(root),
        roles=roles,
        scenarios=scenarios,
    )
