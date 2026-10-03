# Factory Run Evidence (Tablekeeper)

- Captured: 2026-10-03T12:20:56.057158+00:00
- Project: Tablekeeper Factory Evidence (`3f3267e5-5a22-4311-9326-1f535c19073f`)
- Run: `0ac36242-3504-4cc9-a9ce-ce95995f0fa1`
- Execution mode: `deterministic`
- Final status: `awaiting_approval` (stage `awaiting_approval`)
- Tasks: 6 · Hand-offs: 6 · Events: 17 · Artifacts: 9
- Approval: `PENDING`

## Agent-to-agent hand-offs (persisted)

| # | From | To | Status | Stage | Message |
|---|------|----|--------|-------|---------|
| 1 | architect | builder | COMPLETED | planning | Architect finished and handed off to Builder. The templated plan is ready for implementation. |
| 2 | builder | tester | COMPLETED | building | Builder finished and handed off to Tester. Generated site files are ready for the test gate. |
| 3 | tester | breaker | COMPLETED | testing | Tester finished and handed off to Breaker. The generated suite passed; the breaker now attacks it. |
| 4 | breaker | tester | COMPLETED | breaking | Breaker finished and handed off to Tester. Breaker PASS; handing back to the tester for the retest gate. |
| 5 | tester | verifier | COMPLETED | retesting | Tester finished and handed off to Verifier. The retest gate passed; independent verification begins. |
| 6 | verifier | human | COMPLETED | verifying | Verifier finished and handed off to Human. Independent verification passed; human approval is required. |

## Event stream (persisted)

| Time (UTC) | Type | Source | Destination | Status | Message |
|---|---|---|---|---|---|
| 15:20:43 | run_started |  |  | RUNNING | Factory run started in deterministic mode. |
| 15:20:43 | execution_mode_selected |  |  |  | No reachable agent runtime; running the deterministic template pipeline. Results are templated, not agent-produced. |
| 15:20:43 | stage_started | architect |  |  | Architect produced templated artifacts (no agent runtime). |
| 15:20:43 | handoff | architect | builder | COMPLETED | Architect finished and handed off to Builder. The templated plan is ready for implementation. |
| 15:20:43 | stage_started | builder |  |  | Builder created templated files (no agent runtime). |
| 15:20:43 | handoff | builder | tester | COMPLETED | Builder finished and handed off to Tester. Generated site files are ready for the test gate. |
| 15:20:43 | stage_started | tester |  |  | Tester is executing generated-project checks. |
| 15:20:46 | gate_completed | tester |  |  | tester ran `pytest tests -q` -> passed. |
| 15:20:46 | handoff | tester | breaker | COMPLETED | Tester finished and handed off to Breaker. The generated suite passed; the breaker now attacks it. |
| 15:20:46 | stage_started | breaker |  |  | Breaker inspected generated files (no agent runtime). |
| 15:20:46 | handoff | breaker | tester | COMPLETED | Breaker finished and handed off to Tester. Breaker PASS; handing back to the tester for the retest gate. |
| 15:20:46 | stage_started | tester |  |  | Tester re-confirmed the generated project. |
| 15:20:48 | gate_completed | tester |  |  | tester ran `pytest tests -q` -> passed. |
| 15:20:49 | handoff | tester | verifier | COMPLETED | Tester finished and handed off to Verifier. The retest gate passed; independent verification begins. |
| 15:20:49 | stage_started | verifier |  |  | Verifier recorded templated verification (no agent runtime). |
| 15:20:49 | handoff | verifier | human | COMPLETED | Verifier finished and handed off to Human. Independent verification passed; human approval is required. |
| 15:20:50 | stage_started | human |  |  | Verification passed; human approval is required. |

## Tasks

| # | Role | Type | Status | Verdict | Handed to | Session |
|---|---|---|---|---|---|---|
| 1 | architect | architecture | passed |  | builder |  |
| 2 | builder | generate_project | passed |  | tester |  |
| 3 | tester | generated_tests | passed |  | breaker |  |
| 4 | breaker | generated_project_attack | passed | PASS | tester |  |
| 5 | tester | retest | passed |  | verifier |  |
| 6 | verifier | independent_verification | passed | PASS | human |  |

## Artifacts

- `architecture/architecture.md` (architecture)
- `architecture/project_structure.md` (architecture)
- `architecture/testing_strategy.md` (architecture)
- `index.html` (generated_source)
- `styles.css` (generated_source)
- `README.md` (generated_source)
- `tests/test_generated_site.py` (generated_source)
- `evidence/breaker_report.md` (breaker_report)
- `evidence/verification.md` (verification)

## Factory metrics (database totals)

```json
{
  "runs": 1,
  "live_runs": 0,
  "tasks": 6,
  "artifacts": 9,
  "approvals": 1,
  "approved": 0
}
```
