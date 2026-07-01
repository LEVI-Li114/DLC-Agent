# Core Table Model

Core table judgment must be explainable. The model should never answer only "yes" or "no"; it must return the score and reasons.

## Current v1 scoring

Score threshold:

```text
core table = score >= 60
```

Rules:

- `manual_core_level`: 100 points. Manual business confirmation wins.
- `ads` or `dws` layer: +30. These are closer to BI and reusable domain aggregates.
- Core domain: +25. Current domains: `finance`, `business`, `customer`, `order`, `revenue`.
- Downstream dependencies: +10 per downstream asset, max +25.
- Has quality rules: +20.

## Recommended v2 scoring

Keep the same explainable shape, but split evidence into five dimensions:

```text
core_score =
  business_value * 0.30 +
  lineage_impact * 0.25 +
  usage_heat * 0.20 +
  production_criticality * 0.15 +
  governance_readiness * 0.10
```

Dimensions:

- `business_value`: finance, revenue, customer, order, funnel, operation dashboards, or manually marked business-critical.
- `lineage_impact`: downstream task count, downstream table count, BI/report dependency count, cross-domain reuse.
- `usage_heat`: recent query count, report access count, task read frequency, active users in the last 30 days.
- `production_criticality`: schedule frequency, SLA, recent run stability, whether delayed output blocks ADS/BI.
- `governance_readiness`: owner exists, field descriptions, quality rules, permission owner, lineage completeness.

Interpretation:

- `P0 core`: score >= 85, critical financial/business/customer/order table.
- `P1 core`: score 70-84, important domain table or widely reused aggregate.
- `P2 important`: score 60-69, meaningful but limited impact.
- `non-core`: score < 60.

## Why not use only heat

Heat alone can be misleading:

- A temporary ad hoc table can be hot but not core.
- A monthly finance table can be low-frequency but critical.
- A dimension table can be small but high-impact because many facts depend on it.

Use heat plus lineage plus business value. Manual confirmation remains the override for tables that the model cannot infer.
