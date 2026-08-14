# ---------------------------------------------------------------------------
# molecule-gen — MCP server container image
#
# Build:
#   podman build -t molecule-gen:latest -f Containerfile .
#   docker build -t molecule-gen:latest -f Containerfile .
#
# Run (stdio transport — used by MCP clients):
#   podman run --rm -i \
#     -v /path/to/collections:/collections:ro \
#     -e MOLECULE_GEN_ALLOW_PATH=/collections \
#     molecule-gen:latest
#
# The container speaks MCP over stdin/stdout.
# Mount your collection(s) read-only under /collections and set
# MOLECULE_GEN_ALLOW_PATH=/collections so the server only scans that tree.
#
# For write_scenario, mount the molecule/ directory read-write:
#   podman run --rm -i \
#     -v /path/to/wildfly-1:/collections/wildfly-1:rw \
#     -e MOLECULE_GEN_ALLOW_PATH=/collections \
#     molecule-gen:latest
# ---------------------------------------------------------------------------

FROM python:3.12-slim

LABEL org.opencontainers.image.title="molecule-gen"
LABEL org.opencontainers.image.description="MCP server — generates missing Molecule scenarios for Ansible Middleware collections"
LABEL org.opencontainers.image.source="https://github.com/ansible-middleware/molecule-gen"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# Install optional lint tools (non-fatal if not used)
RUN pip install --no-cache-dir yamllint ansible-lint

WORKDIR /app

# Copy and install the package
COPY pyproject.toml ./
COPY mcp_molecule/ ./mcp_molecule/

RUN pip install --no-cache-dir -e .

# Security: non-root user
RUN useradd --create-home --uid 1001 moleculegen
USER 1001

# molecule-gen speaks MCP over stdio — no port to expose
ENTRYPOINT ["python3", "-m", "mcp_molecule.server"]
