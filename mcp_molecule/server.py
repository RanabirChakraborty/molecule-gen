#!/usr/bin/env python3
"""
mcp_molecule/server.py
MCP Server entry point — exposes 4 tools to any MCP-compatible AI assistant.

Tools:
  1. scan_collection        → CollectionContext summary (roles + scenarios)
  2. analyze_gaps           → prioritized gap manifest
  3. get_generation_prompt  → structured prompts for one gap (AI generates YAML)
  4. write_scenario         → validates + writes files to molecule/<scenario>/

Security
--------
* ``_ALLOW_PATH``:  When set (env var ``MOLECULE_GEN_ALLOW_PATH``), every
  ``collection_path`` argument must be a subdirectory of that prefix.  This
  prevents the MCP server from scanning or writing to arbitrary paths on disk
  when running in a shared / multi-tenant environment.
* ``scenario_name`` is validated to be a plain directory name (no ``..``, no
  absolute path) before it is joined onto the molecule/ directory.
* Only filenames in ``ALLOWED_FILES`` may be written; no arbitrary file
  creation is permitted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from .collector import collect_collection
from .gap_analyzer import analyze_gaps
from .prompts import build_generation_prompt, build_summary_prompt
from .validator import (
    is_ansible_lint_available,
    is_yamllint_available,
    run_ansible_lint,
    validate_yaml,
)

# ---------------------------------------------------------------------------
# Security: optional path allowlist
# ---------------------------------------------------------------------------
# Set MOLECULE_GEN_ALLOW_PATH to restrict which collection roots are accepted.
# e.g.  export MOLECULE_GEN_ALLOW_PATH=/home/runner/collections
_ALLOW_PATH: Path | None = (
    Path(os.environ["MOLECULE_GEN_ALLOW_PATH"]).resolve()
    if "MOLECULE_GEN_ALLOW_PATH" in os.environ
    else None
)


def _assert_allowed_path(collection_path: Path) -> None:
    """Raise ValueError if collection_path is outside the configured allowlist."""
    if _ALLOW_PATH is None:
        return
    resolved = Path(collection_path).resolve()
    try:
        resolved.relative_to(_ALLOW_PATH)
    except ValueError:
        raise ValueError(
            f"collection_path '{collection_path}' is not under the allowed prefix "
            f"'{_ALLOW_PATH}'.  Set MOLECULE_GEN_ALLOW_PATH to change this."
        )


# ---------------------------------------------------------------------------
ALLOWED_FILES = {"molecule.yml", "converge.yml", "verify.yml", "prepare.yml", "vars.yml"}

server = Server("molecule-gen")


# ---------------------------------------------------------------------------
# Tool 1 — scan_collection
# ---------------------------------------------------------------------------
@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="scan_collection",
            description=(
                "Scan an Ansible collection directory and return a structured context: "
                "every role with its argument_specs variables, and every existing molecule "
                "scenario with the roles it exercises. "
                "Call this first when you want to understand what is already covered."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "collection_path": {
                        "type": "string",
                        "description": (
                            "Absolute path to the root of the Ansible collection "
                            "(the directory that contains galaxy.yml)"
                        ),
                    }
                },
                "required": ["collection_path"],
            },
        ),
        types.Tool(
            name="analyze_gaps",
            description=(
                "Analyze an Ansible collection for missing molecule test scenarios. "
                "Returns a prioritized gap manifest. Each gap has: role, type, reason, "
                "priority (high/medium/low), suggestedScenarioName, and relevantVars. "
                "No AI is involved — this is pure deterministic analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "collection_path": {
                        "type": "string",
                        "description": "Absolute path to the root of the Ansible collection",
                    },
                },
                "required": ["collection_path"],
            },
        ),
        types.Tool(
            name="get_generation_prompt",
            description=(
                "Returns a structured system prompt + user prompt for generating molecule "
                "scenario files for a specific gap. Includes the role's argument_specs and "
                "the reference scenario content for style matching. "
                "Use these prompts to generate molecule.yml, converge.yml, verify.yml, "
                "then pass the result to write_scenario."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "collection_path": {
                        "type": "string",
                        "description": "Absolute path to the root of the Ansible collection",
                    },
                    "scenario_name": {
                        "type": "string",
                        "description": (
                            "The suggestedScenarioName from analyze_gaps output "
                            "(e.g. 'driver_standalone')"
                        ),
                    },
                },
                "required": ["collection_path", "scenario_name"],
            },
        ),
        types.Tool(
            name="write_scenario",
            description=(
                "Write a new molecule scenario to the collection's molecule/ directory. "
                "Validates each file with yamllint then ansible-lint before writing. "
                "On success returns the list of files written. "
                "On validation failure returns the errors so you can fix the YAML and retry. "
                "Set dry_run: true to validate without writing to disk. "
                "Set force: true to overwrite existing files (off by default)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "collection_path": {
                        "type": "string",
                        "description": "Absolute path to the root of the Ansible collection",
                    },
                    "scenario_name": {
                        "type": "string",
                        "description": "Name for the new molecule scenario directory",
                    },
                    "files": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": (
                            "Map of filename → YAML content. "
                            "Required keys: molecule.yml, converge.yml, verify.yml. "
                            "Optional: prepare.yml, vars.yml"
                        ),
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, validate only — do not write to disk. Defaults to false.",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "If true, allow overwriting existing files. Defaults to false.",
                    },
                },
                "required": ["collection_path", "scenario_name", "files"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------
@server.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[types.TextContent]:

    def ok(data: object) -> list[types.TextContent]:
        text = data if isinstance(data, str) else json.dumps(data, indent=2)
        return [types.TextContent(type="text", text=text)]

    def err(msg: str) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=f"Error: {msg}")]

    try:
        collection_path = Path(arguments["collection_path"])
        _assert_allowed_path(collection_path)
    except (KeyError, ValueError) as exc:
        return err(str(exc))

    # ── Tool 1 ──────────────────────────────────────────────────────────
    if name == "scan_collection":
        try:
            ctx = collect_collection(collection_path)
            summary = {
                "namespace": ctx.namespace,
                "collectionName": ctx.collection_name,
                "collectionPath": ctx.collection_path,
                "roles": [
                    {
                        "name": r.name,
                        "variableCount": len(r.variables),
                        "requiredVars": [v.name for v in r.variables if v.required],
                        "taskFiles": r.task_files,
                    }
                    for r in ctx.roles
                ],
                "scenarios": [
                    {
                        "name": s.name,
                        "rolesUsed": s.roles_used,
                        "varsSet": s.vars_set[:20],  # trim for readability
                    }
                    for s in ctx.scenarios
                ],
            }
            return ok(summary)
        except Exception as exc:
            return err(f"scanning collection: {exc}")

    # ── Tool 2 ──────────────────────────────────────────────────────────
    if name == "analyze_gaps":
        try:
            ctx  = collect_collection(collection_path)
            gaps = analyze_gaps(ctx)

            summary = build_summary_prompt(ctx, gaps)
            full_manifest = json.dumps([g.to_dict() for g in gaps], indent=2)
            return ok(f"{summary}\n\n---\n\nFull gap manifest (JSON):\n{full_manifest}")
        except Exception as exc:
            return err(f"analyzing gaps: {exc}")

    # ── Tool 3 ──────────────────────────────────────────────────────────
    if name == "get_generation_prompt":
        try:
            scenario_name = arguments["scenario_name"]
            ctx  = collect_collection(collection_path)
            gaps = analyze_gaps(ctx)
            gap  = next(
                (g for g in gaps if g.suggested_scenario_name == scenario_name), None
            )

            if gap is None:
                available = ", ".join(g.suggested_scenario_name for g in gaps)
                return err(
                    f"No gap found with scenario name '{scenario_name}'. "
                    f"Available gaps: {available or 'none'}"
                )

            prompt = build_generation_prompt(gap, ctx)
            return ok(
                f"## System prompt\n{prompt.system_prompt}\n\n"
                f"## User prompt\n{prompt.user_prompt}\n\n"
                "---\n"
                "Generate the scenario files now using the above prompts. "
                "Return a JSON object with keys molecule.yml, converge.yml, verify.yml "
                "(and optionally prepare.yml). Then call write_scenario with the result."
            )
        except Exception as exc:
            return err(f"building prompt: {exc}")

    # ── Tool 4 ──────────────────────────────────────────────────────────
    if name == "write_scenario":
        try:
            scenario_name: str = arguments["scenario_name"]
            files: dict[str, str] = arguments["files"]
            dry_run: bool = arguments.get("dry_run", False)
            force: bool = arguments.get("force", False)

            # Guard: required files present
            required = {"molecule.yml", "converge.yml", "verify.yml"}
            missing  = required - files.keys()
            if missing:
                return err(
                    f"Missing required files: {', '.join(sorted(missing))}. "
                    "Please provide all three."
                )

            # Guard: no path traversal in scenario_name
            if ".." in scenario_name or os.path.isabs(scenario_name):
                return err(
                    "scenario_name must be a plain directory name, not a path."
                )

            # Guard: only known filenames allowed
            unknown_files = set(files.keys()) - ALLOWED_FILES
            if unknown_files:
                return err(
                    f"Disallowed filenames: {', '.join(sorted(unknown_files))}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_FILES))}"
                )

            scenario_dir = Path(collection_path) / "molecule" / scenario_name

            # Guard: do not overwrite unless force=true
            if not dry_run and not force:
                # Directory-level check
                if scenario_dir.exists():
                    return err(
                        f"Scenario '{scenario_name}' already exists at {scenario_dir}. "
                        "Use force=true to overwrite, or choose a different name."
                    )
                # Per-file check (handles partial directories)
                existing_files = [
                    filename for filename in files
                    if (scenario_dir / filename).exists()
                ]
                if existing_files:
                    return err(
                        f"Files already exist: {', '.join(existing_files)}. "
                        "Use force=true to overwrite, or use dry_run to preview."
                    )

            # ── Step 1: yamllint ─────────────────────────────────────────
            if not is_yamllint_available():
                return err(
                    "yamllint is required but not installed. "
                    "Run: pip install molecule-gen"
                )

            validation_errors: dict[str, list[str]] = {}
            for filename, content in files.items():
                result = validate_yaml(content, filename)
                if not result.valid:
                    validation_errors[filename] = result.errors

            if validation_errors:
                detail = "\n".join(
                    f"{filename}:\n" + "\n".join(f"  - {e}" for e in errors)
                    for filename, errors in validation_errors.items()
                )
                return err(
                    f"yamllint validation failed. Fix the errors below and retry "
                    f"write_scenario:\n\n{detail}"
                )

            # Dry run — stop after yamllint (ansible-lint needs files on disk)
            if dry_run:
                return ok({
                    "status": "dry_run_ok",
                    "yamllintChecked": True,
                    "ansibleLintChecked": False,
                    "note": "ansible-lint requires files on disk and is skipped during dry_run. Write with force=false (default) to avoid overwriting existing files with unvalidated YAML.",
                    "scenarioDir": str(scenario_dir),
                    "files": list(files.keys()),
                })

            # ── Step 2: write files to disk ──────────────────────────────
            scenario_dir.mkdir(parents=True, exist_ok=True)
            written: list[str] = []
            for filename, content in files.items():
                full_path = scenario_dir / filename
                full_path.write_text(content, encoding="utf-8")
                written.append(str(full_path))

            # ── Step 3: ansible-lint (local, post-write) ─────────────────
            ansible_lint_result = run_ansible_lint(scenario_dir)
            ansible_lint_warnings = ansible_lint_result.errors if not ansible_lint_result.valid else []

            return ok({
                "status": "written",
                "scenarioDir": str(scenario_dir),
                "filesWritten": written,
                "ansibleLintPassed": ansible_lint_result.valid,
                "ansibleLintWarnings": ansible_lint_warnings,
                "nextStep": (
                    f"Review the generated files, then run: "
                    f"cd {collection_path} && molecule test -s {scenario_name}"
                ),
            })

        except Exception as exc:
            return err(f"writing scenario: {exc}")

    return err(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    import asyncio
    import sys

    async def _run() -> None:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    print("molecule-gen MCP server v1.0.0 running on stdio", file=sys.stderr)
    print(
        "Tools: scan_collection | analyze_gaps | get_generation_prompt | write_scenario",
        file=sys.stderr,
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
