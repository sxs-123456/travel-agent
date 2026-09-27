# Agent Benchmark Report

This report is generated from `evals/cases.json` against a running API. The runner does not invent missing values: failed cases stay in the report, unavailable token accounting remains unavailable, and cost is only calculated when model prices are configured.

## Stateful workflow benchmark

The production benchmark for this revision must be written by the following command after deployment:

```bash
python evals/run_evaluation.py --base-url https://travel-agent-production-fbc9.up.railway.app
```

The resulting source of truth is `evals/results/latest.json`. Reported fields are Task Success Rate, Grounded POI Rate, Constraint Satisfaction Rate, Tool Call Success Rate, Duplicate Rate, Hallucination Rate, Retry/Fallback Rate, P50/P95 latency, token usage and configured cost.

No result is recorded in this section until that command has completed against the Stateful Agent build. This prevents the previous architecture's numbers from being presented as results for the new workflow.

## Test benchmark

The test suite exercises model validation, provider parsing, source-ID restoration, retry, timeout, fallback, deterministic constraints, API integration, MCP adapters and evaluation aggregation. Its exact count and elapsed time should be copied from the current CI or local `pytest -q` run; it is validation evidence, not a substitute for the live agent benchmark.

