# molecule-gen

An MCP (Model Context Protocol) server that scans Ansible Middleware collection
repositories, identifies missing Molecule test scenarios using deterministic gap
analysis, and uses an AI assistant to generate the missing scenario files —
ready to review and merge.

Written in Python. Works with **Bob**, **Claude Desktop**, **Cursor**, **Continue**
— any MCP-compatible AI assistant.

---

## How it works

```
You type:  "scan the collection at /path/to/ansible/collection and generate the missing scenarios"
               ↓
    AI calls  scan_collection()         → reads roles/ + molecule/ from disk
    AI calls  analyze_gaps()            → pure logic, no AI, returns gap manifest
    AI calls  get_generation_prompt()   → returns structured prompts for one gap
    AI generates YAML                   → in its own context window (no extra API key)
    AI calls  write_scenario()          → validates YAML + writes files to disk
               ↓
    molecule/firewalld_standalone/ written
```

The server does **no AI work** — it is pure deterministic Python.
The AI assistant (Bob / Claude / Cursor) does the YAML generation.
You need **no extra API key**.

---

## Quick start

### 1. Prerequisites

```bash
# Python ≥ 3.10
python3 --version
```

### 2. Clone and install

```bash
git clone https://github.com/ansible-middleware/molecule-gen
cd molecule-gen
pip install -e .
```

### 3. Verify it works

Point `smoke_test.py` at the root of a locally cloned Ansible collection repository
(the directory that contains `galaxy.yml`), not the application installation directory:

```bash
python3 smoke_test.py /path/to/ansible/collection
```

Expected output:

```
Collection: middleware_automation.wildfly

Scenario -> roles detected:
   default   -> wildfly_driver, wildfly_install, wildfly_systemd
   ...

Gap manifest (8 gaps):
wildfly_firewalld -> firewalld_standalone  (role_scenario_absent)
   Role 'wildfly_firewalld' is not exercised by any existing molecule scenario.
...
```

### 4. Register in your AI assistant (one-time)

Get the absolute path to the cloned repo:

```bash
echo "$(pwd)"
# e.g. /home/alice/molecule-gen
```

#### Bob

Open Bob → Settings → MCP Servers → Edit `mcp.json`:

```json
{
  "mcpServers": {
    "molecule-gen": {
      "command": "python3",
      "args": ["-m", "mcp_molecule.server"],
      "cwd": "/absolute/path/to/molecule-gen"
    }
  }
}
```

Bob hot-reloads immediately — no restart needed.

#### Claude Desktop

Edit the Claude Desktop config file for your OS:

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

Add the same JSON block above.

#### Cursor / Continue

Add the same JSON block to your MCP configuration file for that tool.

### 5. Use it

Type any of these in your AI chat:

```
Scan the collection at /path/to/ansible/collection and generate the missing molecule scenarios

What molecule coverage is missing from /path/to/ansible/collection?

Generate a molecule scenario for the keycloak_quarkus role
```

---

## Run as a container (alternative)

A `Containerfile` is provided for teams that prefer not to install Python locally.

### Build

```bash
podman build -t molecule-gen:latest -f Containerfile .
# or
docker build -t molecule-gen:latest -f Containerfile .
```

### Register the container in Bob / Claude Desktop

```json
{
  "mcpServers": {
    "molecule-gen": {
      "command": "podman",
      "args": [
        "run", "--rm", "-i",
        "-v", "/path/to/collection:/collections/collection:rw",
        "-e", "MOLECULE_GEN_ALLOW_PATH=/collections",
        "molecule-gen:latest"
      ]
    }
  }
}
```

The MCP client communicates with the container over stdin/stdout — no port mapping needed.
Replace `/path/to/collection` with the absolute path to your collection on disk.

---

## Tools exposed

| Tool | Inputs | What it does |
|---|---|---|
| `scan_collection` | `collection_path` | Reads all `argument_specs.yml` + existing scenarios → structured JSON |
| `analyze_gaps` | `collection_path`, optional `priority_filter` | Compares roles ↔ scenarios → prioritized gap manifest |
| `get_generation_prompt` | `collection_path`, `scenario_name` | Returns system + user prompts for generating one scenario |
| `write_scenario` | `collection_path`, `scenario_name`, `files`, optional `dry_run`, `force` | Validates YAML (yamllint → ansible-lint) + writes files to `molecule/<name>/` |

---

## Gap types detected

| Type | Description |
|---|---|
| `role_scenario_absent` | Role has zero molecule scenarios |
| `flag_never_toggled` | Boolean feature flag never set to non-default in any scenario |
| `multi_instance_missing` | Multi-instance / port-offset deployment never exercised |

---

## write_scenario options

| Option | Type | Description | Default |
|---|---|---|---|
| `dry_run` | boolean | Validate only — do not write to disk | `false` |
| `force` | boolean | Allow overwriting existing scenario files | `false` |

Validation pipeline: **yamllint** (pre-write) → **write files** → **ansible-lint** (post-write).
If yamllint finds errors the files are never written. ansible-lint warnings are
returned in the response but do not block the write.

---

## Security

| Guard | What it prevents |
|---|---|
| `MOLECULE_GEN_ALLOW_PATH` env var | Server only accepts collection paths under this prefix — safe for shared/CI use |
| `scenario_name` validation | `..` traversal and absolute paths in scenario names |
| `ALLOWED_FILES` allowlist | Only `molecule.yml`, `converge.yml`, `verify.yml`, `prepare.yml`, `vars.yml` may be written |
| `force=false` default | Accidental overwrite of existing scenario files |
| Non-root container user | Container runs as UID 1001 |

```bash
# Restrict the server to a specific directory (recommended for CI / shared machines):
export MOLECULE_GEN_ALLOW_PATH=/home/runner/collections
```

---

## Project structure

```
molecule-gen/
├── mcp_molecule/
│   ├── __init__.py
│   ├── server.py       ← MCP server entry point (4 tools)
│   ├── collector.py    ← reads collection from disk → CollectionContext
│   ├── gap_analyzer.py ← pure gap detection logic (no LLM)
│   ├── validator.py    ← yamllint + ansible-lint subprocess wrappers
│   ├── prompts.py      ← generation prompt templates
│   └── types.py        ← shared dataclasses
├── smoke_test.py       ← quick local verification script
├── Containerfile       ← container image (podman / docker)
├── pyproject.toml
├── LICENSE
└── README.md
```

---

## Collections supported

Feature-flag gap detection covers all Ansible Middleware collections out of the box:
`wildfly`, `jws`, `keycloak`, `keycloak_quarkus`, `activemq` (amq), `amq_streams`, `infinispan`.

Role-coverage gap detection (`role_scenario_absent`) works against **any** Ansible collection
that follows the standard layout — no configuration needed.

---

## Author

[Ranabir Chakraborty](https://github.com/RanabirChakraborty)
