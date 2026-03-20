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

FirePilot runs entirely without live infrastructure. Set `FIREPILOT_ENV=demo` and every MCP tool returns realistic fixture data instead of calling external APIs.

```bash
# Clone the repository
git clone https://github.com/your-org/firepilot.git
cd firepilot

# Run CI validation locally
cd ci && make check-deps && make validate

# Run OPA policy tests
cd ci && make test-policies
```

The demo fixtures represent a small enterprise environment with a four-tier network segmentation model (untrust → web → app → db), pre-configured security zones, address objects, and a baseline rulebase.

---

## 🛠️ Technology Stack

| Component | Technology | Role |
|-----------|-----------|------|
| Orchestration | Claude API (Anthropic) | Intent parsing, config generation |
| Integration | Model Context Protocol (MCP) | Decoupled tool interface |
| Firewall API | Palo Alto Strata Cloud Manager | Target platform |
| Policy Engine | Open Policy Agent (OPA) + Rego | CI/CD validation |
| Config Format | YAML + JSON Schema | Declarative firewall rules |
| CI/CD | GitHub Actions | Pipeline runtime |
| Change Management | GitHub Issues | Request intake + audit trail |
| Language | Python 3.12+ | MCP servers, scripts |

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
