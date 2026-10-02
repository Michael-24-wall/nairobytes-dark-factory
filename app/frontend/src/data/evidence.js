import plan from '../../../../evidence/plan.md?raw'
import factoryReport from '../../../../evidence/factory_execution_report.md?raw'
import factoryVerification from '../../../../evidence/factory_final_verification.md?raw'
import concurrency from '../../../../evidence/breaker_concurrency.md?raw'
import idempotency from '../../../../evidence/breaker_idempotency.md?raw'
import timezone from '../../../../evidence/breaker_timezone.md?raw'
import finalTests from '../../../../evidence/final_test_run.txt?raw'
import repair from '../../../../evidence/pg_test_infrastructure_repair.md?raw'

export const evidenceItems = [
  { name: 'factory_final_verification.md', type: 'VERIFICATION', status: 'PASS', summary: 'Final factory stage statuses and observed invariant results.', content: factoryVerification },
  { name: 'factory_execution_report.md', type: 'RUN REPORT', status: 'PASS', summary: 'Architect to Verifier execution record.', content: factoryReport },
  { name: 'breaker_concurrency.md', type: 'BREAKER', status: 'PASS', summary: 'Repeated live-server contention tests and deadlock repair.', content: concurrency },
  { name: 'breaker_idempotency.md', type: 'BREAKER', status: 'PASS', summary: 'Replay, mismatch, and unique-key verification.', content: idempotency },
  { name: 'breaker_timezone.md', type: 'BREAKER', status: 'PASS', summary: 'UTC normalization and offset-equivalence attacks.', content: timezone },
  { name: 'final_test_run.txt', type: 'TEST OUTPUT', status: 'PASS', summary: 'Recorded full pytest quiet and verbose output.', content: finalTests },
  { name: 'pg_test_infrastructure_repair.md', type: 'REPAIR', status: 'PASS', summary: 'PostgreSQL test helper and repair evidence.', content: repair },
  { name: 'plan.md', type: 'ARCHITECT', status: 'RECORDED', summary: 'Requirements, architecture, risks, and acceptance tasks.', content: plan },
]