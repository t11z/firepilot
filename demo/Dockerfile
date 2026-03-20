FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Install OPA (linux amd64 static binary)
RUN curl -fsSL -o /usr/local/bin/opa \
    https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static \
    && chmod +x /usr/local/bin/opa

# Install Python tooling
RUN pip install --no-cache-dir check-jsonschema

# Copy repository
COPY . /app

WORKDIR /app

# Install MCP servers from local paths
RUN pip install --no-cache-dir \
    ./mcp-servers/mcp-strata-cloud-manager \
    ./mcp-servers/mcp-itsm

# Install orchestrator dependencies
RUN pip install --no-cache-dir requests anthropic

# Demo mode by default — no live credentials required
ENV FIREPILOT_ENV=demo
