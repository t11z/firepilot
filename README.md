# 🔥 FirePilot

**AI-driven firewall rule management through natural language, GitOps, and the Model Context Protocol.**

FirePilot lets business units describe network security requirements in plain language. Claude parses the intent, generates declarative firewall configuration, validates it through Policy-as-Code, and deploys it to Palo Alto Networks Strata Cloud Manager — with a complete audit trail in GitHub Issues.

> 🚨 **This is a demonstration project.** See [Disclaimer](#-disclaimer) below.

---

## 🧭 Why FirePilot?

Firewall rule changes in enterprises are slow, error-prone, and buried in ticket queues. The typical workflow — business unit fills out a form, security team interprets it, engineer implements it, change board approves it — takes days to weeks for a single rule.

FirePilot compresses this into minutes by making the firewall configuration **declarative**, **version-controlled**, and **AI-assisted** — while keeping humans in the loop where it matters.

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────────┐
│  GitHub Issue    │────▶│  GitHub Actions   │────▶│  Claude API             │
│  (Change Request)│     │  (Orchestration)  │     │  (Intent → Config)      │
└─────────────────┘     └──────────────────┘     └──────────┬──────────────┘
                                                            │
                                 ┌──────────────────────────┼──────────────────┐
                                 │              MCP Protocol │                  │
                                 ▼                          ▼                  ▼
                        ┌────────────────┐   ┌──────────────────┐   ┌─────────────┐
                        │ mcp-strata-    │   │ mcp-itsm         │   │ Git Repo    │
                        │ cloud-manager  │   │ (GitHub Issues)  │   │ (YAML +     │
                        │ (SCM API)      │   │                  │   │  OPA + CI)  │
                        └────────────────┘   └──────────────────┘   └─────────────┘
```

For C4 diagrams, data model, and component details, see [docs/architecture.md](docs/architecture.md).

### Constraint Layers (Defense in Depth)

FirePilot validates at every boundary — no single layer is trusted:

| Layer | Where | What |
|-------|-------|------|
| **1 — Input** | GitHub Issue Template | Structured fields, required sections |
| **2 — AI** | Claude system prompt | Security policy rules, forbidden patterns |
| **3 — CI/CD** | OPA + JSON Schema | Policy-as-Code before merge |
| **4 — API** | MCP server | Backend validation at the integration boundary |

---

## 📁 Repository Structure

```
firepilot/
├── CLAUDE.md                           # Agent configuration and conventions
├── docs/
│   └── adr/                            # Architecture Decision Records
├── mcp-servers/
│   ├── mcp-strata-cloud-manager/       # Palo Alto SCM API integration
│   └── mcp-itsm/                       # Change management (GitHub Issues)
├── firewall-configs/                   # Declarative YAML firewall rules
│   └── shared/pre/                     # Folder/position directory layout
├── ci/
│   ├── policies/                       # OPA/Rego security policies
│   ├── schemas/                        # JSON Schemas for config validation
│   └── scripts/                        # Pipeline gate scripts
├── prompts/                            # Claude system prompts, versioned
├── .github/
│   ├── ISSUE_TEMPLATE/                 # Firewall change request template
│   ├── workflows/                      # CI/CD pipelines
│   └── scripts/                        # Workflow orchestration scripts
└── demo/                               # Mock layer and local demo setup
```

---

## 🔄 How It Works

**1. Request** — A business unit opens a GitHub Issue using the firewall change request template. They describe what they need ("Allow HTTPS from web-zone to app-zone for the new payment service") and attach supporting documentation.

**2. Analyse** — GitHub Actions triggers automatically. The workflow extracts the request, downloads any PDF attachments, and calls the Claude API with the full context.

**3. Generate** — Claude parses the intent, queries the current firewall state via `mcp-strata-cloud-manager`, and generates declarative YAML configuration aligned with the existing rulebase.

**4. Validate** — The CI pipeline runs three gates: JSON Schema validation (structural correctness), OPA policy evaluation (security semantics), and a dry-run against the SCM API.

**5. Review** — Claude posts its analysis, the proposed configuration, and the validation results as an issue comment. A human approver reviews and sets the approval label.

**6. Deploy** — On approval, the configuration is pushed to Strata Cloud Manager via MCP, and the deployment result is recorded on the issue.

---

## 🧪 Demo Mode

FirePilot runs entirely without live infrastructure. Every MCP tool returns realistic fixture data when `FIREPILOT_ENV=demo` — no credentials, no external APIs.

### Stufe 1 — Quick Start (no API key required)

```bash
git clone https://github.com/tsprock/firepilot.git
cd firepilot
make demo
```

This runs all four CI/CD validation gates against the existing firewall configuration fixtures in demo mode:

- **Gate 1** — JSON Schema validation (structural correctness of YAML files)
- **Gate 2** — OPA policy evaluation (security semantics via Rego)
- **Gate 3** — Dry-run validation against the mock SCM API
- **Gate 4** — Simulated deployment (demo mode)

Docker is used if available (`docker compose`). If Docker is not installed, native execution is used instead — requires Python 3.12+, `opa`, and `check-jsonschema` on `PATH`. Run `make check-deps` first to verify.

### Stufe 2 — AI-Powered Analysis (requires Anthropic API key)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
make demo-orchestrator
```

This sends the example firewall change request (`demo/example-issue.md`) through the full Claude agentic loop. Claude connects to both MCP servers in demo mode, queries the mock firewall state (`list_security_zones`, `list_security_rules`, `list_addresses`), and generates a YAML configuration proposal validated against the security policies. The complete analysis is printed to stdout.

This demonstrates the core AI workflow without any live infrastructure or production credentials.

Docker is used if available. Without Docker, `ci/scripts/process-issue.py` is invoked directly (requires the MCP servers to be installed: `pip install ./mcp-servers/mcp-strata-cloud-manager ./mcp-servers/mcp-itsm`).

### Stufe 3 — Full GitHub Actions Flow (production narrative)

The full production workflow operates entirely within GitHub:

1. **Issue created** — A business unit opens a GitHub Issue using the `firewall-change-request` template. The template automatically applies the `firepilot:pending` label.
2. **Workflow triggers** — The `firepilot:pending` label triggers `.github/workflows/process-firewall-request.yml`.
3. **Claude analyses** — The workflow extracts the issue body and any PDF attachments, then invokes the Claude API (`ci/scripts/process-issue.py`). Claude queries the live SCM API via `mcp-strata-cloud-manager` and the ITSM state via `mcp-itsm`.
4. **Comment posted** — Claude posts its analysis, proposed YAML configuration, and validation summary as an issue comment.
5. **Human approves** — A security approver reviews the comment and sets the `firepilot:approved` label on the issue.
6. **Config committed** — The approved YAML is committed to a feature branch and a PR is opened against `main`.
7. **PR validation** — `.github/workflows/validate.yml` runs Gates 1–3 on the PR.
8. **Merge → deploy** — After PR merge, `.github/workflows/deploy.yml` re-runs Gates 1–3 then executes Gate 4: pushing the configuration to Strata Cloud Manager via `mcp-strata-cloud-manager` and recording the deployment result via `mcp-itsm`.

The demo fixtures represent a four-tier network segmentation model (untrust → web → app → db), pre-configured security zones, address objects, and a baseline rulebase.

---

## 🛠️ Technology Stack

See [Technology Stack](docs/architecture.md#10--technology-stack) in the architecture document for the full stack with rationale.

---

## 📐 Architecture Decisions

Every significant design choice is documented as an Architecture Decision Record:

| ADR | Decision |
|-----|----------|
| [ADR-0000](docs/adr/0000-adr-format-and-process-definition.md) | ADR format and process |
| [ADR-0001](docs/adr/0001-git-as-single-source-of-truth-for-firewall-configuration.md) | Git as single source of truth |
| [ADR-0002](docs/adr/0002-mcp-over-direct-api.md) | MCP over direct API integration |
| [ADR-0003](docs/adr/0003-cicd-pipeline-design-and-policy-validation-toolchain.md) | CI/CD pipeline and OPA validation |
| [ADR-0004](docs/adr/0004-mcp-strata-cloud-manager-tool-interface-design.md) | SCM MCP server tool interface |
| [ADR-0005](docs/adr/0005-mcp-itsm-tool-interface-design.md) | ITSM MCP server tool interface |
| [ADR-0006](docs/adr/0006-mcp-server-authentication-and-credential-management.md) | Authentication and credential management |
| [ADR-0007](docs/adr/0007-declarative-firewall-configuration-yaml-schema.md) | Declarative YAML configuration schema |
| [ADR-0008](docs/adr/0008-zone-topology-aware-policy-validation.md) | Zone topology-aware policy validation |
| [ADR-0009](docs/adr/0009-github-issues-as-primary-firewall-change-request-interface.md) | GitHub Issues as change request interface |

---

## ⚠️ Disclaimer

**FirePilot is a demonstration and architectural exploration project. It is not intended for production use.**

- This software is provided **"as is"**, without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement.
- In no event shall the authors be liable for any claim, damages, or other liability arising from, out of, or in connection with the software or its use.
- FirePilot is **not affiliated with, endorsed by, or supported by** Palo Alto Networks, Anthropic, or any other vendor referenced in this repository. All product names, trademarks, and registered trademarks are the property of their respective owners.
- The firewall configurations, security policies, and MCP server implementations in this repository are **illustrative examples only**. They do not represent security best practices and must not be used to protect real network infrastructure.
- **Do not deploy FirePilot against production firewall management systems.** The demo mode exists precisely so that the architecture can be explored without risk.

---

## 📄 License

[MIT](LICENSE)
