#!/usr/bin/env python3
"""
Quick smoke test — verify gap detection against a real collection.

Usage:
  python3 smoke_test.py /path/to/collection
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from mcp_molecule.collector import collect_collection
from mcp_molecule.gap_analyzer import analyze_gaps

if len(sys.argv) != 2:
    print("Usage: python3 smoke_test.py /path/to/collection")
    sys.exit(1)

COLLECTION = sys.argv[1]

ctx  = collect_collection(COLLECTION)
gaps = analyze_gaps(ctx)

print(f"\nCollection: {ctx.namespace}.{ctx.collection_name}")
print(f"\nScenario -> roles detected:\n")
for s in ctx.scenarios:
    if s.roles_used:
        print(f"   {s.name:<30} -> {', '.join(s.roles_used)}")

print(f"\nGap manifest ({len(gaps)} gaps):\n")
for g in gaps:
    print(f"{g.role} -> {g.suggested_scenario_name}  ({g.type.value})")
    print(f"   {g.reason}\n")
