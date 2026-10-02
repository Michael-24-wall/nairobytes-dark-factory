# Factory Stages

The intended lifecycle is Human Requirement, Architect, Builder, Tester, Breaker, Repair, Retest, Verifier, Evidence, Git, GitHub, Human Approval, and Deployment.

The current live implementation provides a local backend-controlled factory run for a project. It creates architecture artifacts, generates a runnable static website from requirements/design/assets, runs generated-project tests, performs a Breaker inspection, retests, independently verifies, initializes/commits Git, and waits for persistent human approval. GitHub push/PR and deployment remain unconfigured.