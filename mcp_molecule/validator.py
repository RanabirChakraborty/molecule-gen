"""
mcp_molecule/validator.py
Runs yamllint (via Python API) and ansible-lint (via subprocess) on generated
YAML files. Both validators gracefully degrade if not installed.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]


# ---------------------------------------------------------------------------
# yamllint
# ---------------------------------------------------------------------------

def validate_yaml(content: str, filename: str) -> ValidationResult:
    """Lint YAML content using the yamllint Python API (no subprocess, no temp file)."""
    import yamllint.linter
    import yamllint.config

    conf = yamllint.config.YamlLintConfig("extends: relaxed")
    problems = list(yamllint.linter.run(content, conf))
    if not problems:
        return ValidationResult(valid=True, errors=[])

    errors = [
        f"{filename}:{p.line}:{p.column}: [{p.level}] {p.message} ({p.rule})"
        for p in problems
        if p.level == "error"
    ]
    return ValidationResult(valid=not errors, errors=errors)


def is_yamllint_available() -> bool:
    """Check whether the yamllint Python package is importable."""
    try:
        import yamllint  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# ansible-lint
# ---------------------------------------------------------------------------

def run_ansible_lint(scenario_dir: Path) -> ValidationResult:
    """
    Run ansible-lint against a scenario directory.
    Returns ValidationResult with any rule violations found.
    Gracefully degrades if ansible-lint is not installed.
    """
    if not is_ansible_lint_available():
        return ValidationResult(valid=True, errors=[])

    result = subprocess.run(
        ["ansible-lint", "--nocolor", scenario_dir],
        capture_output=True,
        text=True,
        cwd=scenario_dir.parent.parent,  # run from collection root
    )

    if result.returncode == 0:
        return ValidationResult(valid=True, errors=[])

    raw = result.stdout or result.stderr or "Unknown ansible-lint error"
    return ValidationResult(
        valid=False,
        errors=[line for line in raw.splitlines() if line.strip()],
    )


def is_ansible_lint_available() -> bool:
    """Check whether ansible-lint is installed on the system."""
    return shutil.which("ansible-lint") is not None
