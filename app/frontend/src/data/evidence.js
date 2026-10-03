import plan from '../../../../evidence/plan.md?raw'
import factoryReport from '../../../../evidence/factory_execution_report.md?raw'
import factoryVerification from '../../../../evidence/factory_final_verification.md?raw'
import concurrency from '../../../../evidence/breaker_concurrency.md?raw'
import idempotency from '../../../../evidence/breaker_idempotency.md?raw'
import timezone from '../../../../evidence/breaker_timezone.md?raw'
import finalTests from '../../../../evidence/final_test_run.txt?raw'
import repair from '../../../../evidence/pg_test_infrastructure_repair.md?raw'
import githubIntegration from '../../../../evidence/github_integration_test.md?raw'
import githubRepositories from '../../../../evidence/github_repository_test.md?raw'
import githubGitFlow from '../../../../evidence/github_git_flow_test.md?raw'
import githubPullRequest from '../../../../evidence/github_pull_request_test.md?raw'
import githubSecurity from '../../../../evidence/github_security_test.md?raw'

export const evidenceItems = [
  { name: 'factory_final_verification.md', type: 'VERIFICATION', status: 'PASS', summary: 'Final factory stage statuses and observed invariant results.', content: factoryVerification },
  { name: 'factory_execution_report.md', type: 'RUN REPORT', status: 'PASS', summary: 'Architect to Verifier execution record.', content: factoryReport },
  { name: 'breaker_concurrency.md', type: 'BREAKER', status: 'PASS', summary: 'Repeated live-server contention tests and deadlock repair.', content: concurrency },
  { name: 'breaker_idempotency.md', type: 'BREAKER', status: 'PASS', summary: 'Replay, mismatch, and unique-key verification.', content: idempotency },
  { name: 'breaker_timezone.md', type: 'BREAKER', status: 'PASS', summary: 'UTC normalization and offset-equivalence attacks.', content: timezone },
  { name: 'final_test_run.txt', type: 'TEST OUTPUT', status: 'PASS', summary: 'Recorded full pytest quiet and verbose output.', content: finalTests },
  { name: 'pg_test_infrastructure_repair.md', type: 'REPAIR', status: 'PASS', summary: 'PostgreSQL test helper and repair evidence.', content: repair },
  { name: 'github_integration_test.md', type: 'INTEGRATION', status: 'PASS', summary: 'GitHub App routes, service contract, and the NOT CONFIGURED live audit.', content: githubIntegration },
  { name: 'github_repository_test.md', type: 'INTEGRATION', status: 'PASS', summary: 'Repository listing, pagination, identity verification, and creation limits.', content: githubRepositories },
  { name: 'github_git_flow_test.md', type: 'GIT FLOW', status: 'PASS', summary: 'Real branch, commit, push, and remote SHA verification against a local bare remote.', content: githubGitFlow },
  { name: 'github_pull_request_test.md', type: 'INTEGRATION', status: 'PASS', summary: 'Pull request creation, state read-back, and webhook updates against mocked GitHub.', content: githubPullRequest },
  { name: 'github_security_test.md', type: 'SECURITY', status: 'PASS', summary: 'Admin gate, credential redaction, webhook HMAC, and input validation.', content: githubSecurity },
  { name: 'plan.md', type: 'ARCHITECT', status: 'RECORDED', summary: 'Requirements, architecture, risks, and acceptance tasks.', content: plan },
]