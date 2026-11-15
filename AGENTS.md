# Working instructions

For the JOHNY / GitHub Actions integration, the user explicitly performs functional verification.

- Review source code and use static/syntax checks only.
- Do not run market analyses, scoring pipelines, model training, smoke tests, unit tests that exercise analysis, or HTTP integration tests unless the user later explicitly requests them.
- Keep automated JOHNY checks limited to Python compilation and PHP/JavaScript syntax checks.
- Do not trigger the scoring or deployment workflow to verify behavior. Prepare implementation and report remaining activation steps to the user.
