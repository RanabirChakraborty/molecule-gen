"""
mcp_molecule/types.py
Shared dataclasses for molecule-gen — mirrors types.ts exactly.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Collection model
# ---------------------------------------------------------------------------

@dataclass
class RoleVar:
    """A single variable declared in a role's argument_specs.yml."""
    name: str                      # variable name as declared in argument_specs
    type: str                      # ansible type string (str, bool, int, list, …)
    required: bool                 # whether the variable must be supplied by the caller
    default: Any                   # default value from argument_specs (None if absent)
    description: str               # human-readable description from argument_specs


@dataclass
class RoleInfo:
    """Everything we know about one role in the collection."""
    name: str                      # role directory name under roles/
    variables: list[RoleVar]       # variables declared in meta/argument_specs.yml
    task_files: list[str]          # relative paths under roles/<name>/tasks/
    defaults: dict[str, Any]       # raw defaults/main.yml key→value map


@dataclass
class ScenarioInfo:
    """Everything we know about one existing molecule scenario."""
    name: str                      # scenario directory name under molecule/
    roles_used: list[str]          # role names referenced in converge.yml
    vars_set: list[str]            # variable names set in converge.yml / vars files
    converge_content: str          # raw converge.yml — used as style reference
    verify_content: str            # raw verify.yml
    molecule_content: str          # raw molecule.yml


@dataclass
class CollectionContext:
    """Top-level context object produced by the Collector."""
    namespace: str                 # galaxy.yml namespace field
    collection_name: str           # galaxy.yml name field
    collection_path: str           # absolute path to the collection root
    roles: list[RoleInfo]          # all roles found under roles/
    scenarios: list[ScenarioInfo]  # all scenarios found under molecule/


# ---------------------------------------------------------------------------
# Gap model
# ---------------------------------------------------------------------------

class GapType(str, Enum):
    ROLE_SCENARIO_ABSENT  = "role_scenario_absent"   # role has zero scenarios
    FLAG_NEVER_TOGGLED    = "flag_never_toggled"      # a boolean feature flag is never set non-default
    MULTI_INSTANCE_MISSING  = "multi_instance_missing" # multi-instance (port offset) never exercised


@dataclass
class GapItem:
    """One entry in the gap manifest."""
    role: str                                  # role name the gap belongs to
    type: GapType                              # category of the gap
    reason: str                                # human-readable explanation
    suggested_scenario_name: str               # becomes the molecule/ directory name
    relevant_vars: list[str]                   # variables the generated scenario must exercise
    reference_scenario: Optional[str] = None   # closest existing scenario for style

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "type": self.type,
            "reason": self.reason,
            "suggestedScenarioName": self.suggested_scenario_name,
            "relevantVars": self.relevant_vars,
            "referenceScenario": self.reference_scenario,
        }
