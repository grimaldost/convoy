# Documentation

Map of `docs/`, with a suggested reading order for newcomers.

| Where | What | Tracked |
|---|---|---|
| [design/](design/) | Design docs: [00-overview](design/00-overview.md) (architecture, concepts, components), [01-gate](design/01-gate.md) (the quality gate), [02-formats](design/02-formats.md) (series.toml + telemetry formats, exit codes, versioning discipline), [03-serving](design/03-serving.md) (CLI/MCP serving layer, plugin packaging) | yes |
| [adr/](adr/README.md) | Architecture Decision Records — short, four-section records of decisions with lasting consequences | yes |
| [GUARDRAILS.md](GUARDRAILS.md) | Non-negotiable invariants, each naming its mechanical enforcer | yes |
| [backlog.md](backlog.md) | The durable improvement ledger — status-tracked promotions from feedback triage; build from here | yes |
| [plans/](plans/) | Historical build plans (the v1 plan is a completed record, not a roadmap — the live backlog is `backlog.md`) | yes |
| feedback/ | Dogfooding feedback reports and triage passes — session artifacts, deliberately local-only | **no** |

Reading order:

1. The root [README](../README.md) — what convoy is and how to use it.
2. [design/00-overview.md](design/00-overview.md), then 01/02/03 as needed.
3. Contributing (human or agent): [../CONTRIBUTING.md](../CONTRIBUTING.md) and
   [../AGENTS.md](../AGENTS.md), then [GUARDRAILS.md](GUARDRAILS.md).
4. Using convoy from an agent: [../skills/convoy/SKILL.md](../skills/convoy/SKILL.md).
