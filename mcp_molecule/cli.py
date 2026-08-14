#!/usr/bin/env python3
"""
mcp_molecule/cli.py
Headless CLI scanner — no AI, no MCP, no network.

Usage:
    molecule-gen-scan --collection-path /path/to/collection [options]

Exit codes:
    0  no gaps found
    1  one or more gaps found
    2  usage / scan error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .collector import collect_collection
from .gap_analyzer import analyze_gaps


def _format_markdown(gaps: list, collection_label: str) -> str:
    if not gaps:
        return f"**{collection_label}**: no gaps found.\n"

    lines = [
        f"## {collection_label}\n",
        "| Role | Scenario name | Gap type | Reason |",
        "|------|--------------|----------|--------|",
    ]
    for g in gaps:
        lines.append(
            f"| `{g.role}` | `{g.suggested_scenario_name}` "
            f"| {g.type.value} | {g.reason} |"
        )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="molecule-gen-scan",
        description="Scan an Ansible collection for missing molecule scenarios.",
    )
    p.add_argument(
        "--collection-path",
        required=True,
        help="Absolute path to the Ansible collection root (contains galaxy.yml)",
    )
    p.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="text",
        help="Output format (default: text)",
    )
    p.add_argument(
        "--output",
        metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    return p.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        ctx = collect_collection(args.collection_path)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error scanning collection: {exc}", file=sys.stderr)
        return 2

    gaps = analyze_gaps(ctx)
    collection_label = f"{ctx.namespace}.{ctx.collection_name}"

    if args.format == "json":
        output = json.dumps(
            {
                "collection": collection_label,
                "collectionPath": ctx.collection_path,
                "totalGaps": len(gaps),
                "gaps": [g.to_dict() for g in gaps],
            },
            indent=2,
        )
    elif args.format == "markdown":
        output = _format_markdown(gaps, collection_label)
    else:
        if not gaps:
            output = f"{collection_label}: no gaps found."
        else:
            lines = [f"{collection_label}: {len(gaps)} gap(s) found\n"]
            for g in gaps:
                lines.append(
                    f"  {g.role} → {g.suggested_scenario_name}  ({g.type.value})"
                )
                lines.append(f"    {g.reason}")
            output = "\n".join(lines)

    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)

    return 1 if gaps else 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
