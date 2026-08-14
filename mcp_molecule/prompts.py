"""
mcp_molecule/prompts.py
System + per-gap user prompt templates for LLM generation.
Returned by the MCP server so the calling AI (Bob/Claude) can use them
as structured generation instructions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .types import CollectionContext, GapItem


@dataclass
class GenerationPrompt:
    system_prompt: str
    user_prompt: str


SYSTEM_PROMPT = """\
You are an expert in Ansible and Molecule testing for the Ansible Middleware
collection family (middleware_automation.*: wildfly, jws, keycloak, activemq, infinispan).

Your job is to generate minimal, idiomatic Molecule test scenarios that match the style
of existing scenarios in the collection.

## Rules
- Output ONLY valid YAML. No markdown code fences, no prose, no comments unless they exist
  in the reference scenario.
- molecule.yml: copy the provisioner/verifier/scenario block from the reference scenario
  exactly. Only change the scenario name.
- converge.yml: use ansible.builtin.include_role unless the reference uses import_playbook.
  Supply ALL required variables. Supply optional variables only if the gap demands them.
- verify.yml: assert observable state — file existence (stat), systemd service state
  (systemd), HTTP endpoint (uri), or CLI query (wildfly_utils jboss_cli). Mirror the
  assertion style of the reference verify.yml.
- prepare.yml: only generate if the scenario needs another role pre-installed before the
  role under test runs (e.g. wildfly_driver, wildfly_app_deploy, keycloak_realm).
- Keep scenarios minimal. Do not add tasks, variables, or assertions beyond what is needed
  to cover the stated gap.
- Variable values must be plausible. Use the defaults from argument_specs as the baseline.
"""


def build_generation_prompt(gap: GapItem, ctx: CollectionContext) -> GenerationPrompt:
    """
    Build a focused generation prompt for one gap.
    Includes the role's argument_specs and a reference scenario for style matching.
    """
    role = next((r for r in ctx.roles if r.name == gap.role), None)
    ref_scenario = (
        next((s for s in ctx.scenarios if s.name == gap.reference_scenario), None)
        if gap.reference_scenario
        else next((s for s in ctx.scenarios if s.name == "default"), None)
    )

    # Serialize only the role variables relevant to this gap
    relevant_vars = []
    if role:
        for v in role.variables:
            if (
                v.required
                or v.name in gap.relevant_vars
                or gap.type == "role_scenario_absent"
            ):
                relevant_vars.append(
                    f"  {v.name}:\n"
                    f"    type: {v.type}\n"
                    f"    required: {v.required}\n"
                    f"    default: {json.dumps(v.default)}\n"
                    f"    description: \"{v.description}\""
                )
    relevant_var_docs = "\n".join(relevant_vars) or "(no variables)"

    user_prompt = f"""\
## Gap to cover
Role: {gap.role}
Gap type: {gap.type}
Priority: {gap.priority}
Reason: {gap.reason}
Scenario name to generate: {gap.suggested_scenario_name}
Variables this scenario must exercise: {", ".join(gap.relevant_vars) or "none specific"}

## Collection
Namespace: {ctx.namespace}
Collection: {ctx.collection_name}

## Role variable spec (relevant variables)
{relevant_var_docs}

## Reference scenario: {ref_scenario.name if ref_scenario else "none"}
### molecule.yml
{ref_scenario.molecule_content if ref_scenario else "(not available)"}

### converge.yml (style reference)
{ref_scenario.converge_content if ref_scenario else "(not available)"}

### verify.yml (style reference)
{ref_scenario.verify_content if ref_scenario else "(not available)"}

## Task
Generate the following files for scenario '{gap.suggested_scenario_name}'.
Return them as a JSON object with keys: "molecule.yml", "converge.yml", "verify.yml".
Only include "prepare.yml" as a key if this scenario genuinely needs a pre-install step.
Each value is the complete file content as a YAML string.

Example response format:
{{
  "molecule.yml": "---\\nprovisioner:\\n  name: ansible\\n...",
  "converge.yml": "---\\n- name: ...\\n",
  "verify.yml": "---\\n- name: ...\\n"
}}"""

    return GenerationPrompt(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)


def build_summary_prompt(ctx: CollectionContext, gaps: list[GapItem]) -> str:
    """Short human-readable summary — used by the analyze_gaps tool response."""
    if gaps:
        gap_lines = "\n".join(
            f"{i + 1}. [{g.priority.upper()}] {g.role} — {g.type}: "
            f"{g.reason} → suggested scenario: '{g.suggested_scenario_name}'"
            for i, g in enumerate(gaps)
        )
    else:
        gap_lines = "No gaps found — full coverage!"

    return (
        f"Collection: {ctx.namespace}.{ctx.collection_name}\n"
        f"Roles: {', '.join(r.name for r in ctx.roles)}\n"
        f"Existing scenarios: {', '.join(s.name for s in ctx.scenarios)}\n\n"
        f"Gap manifest ({len(gaps)} gaps found):\n{gap_lines}"
    )
