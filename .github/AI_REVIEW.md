# Muse Agent AI Code Review Policy

## 1. Review Objectives

AI review is an advisory security and quality review.
It does not replace human approval.

Review every Pull Request before merging.

## 2. Review Priority

### Critical
- Private key, password, API token or credential exposure.
- Unauthorized execution or privilege escalation.
- Bypass of the Executor approval mechanism.
- Destructive modification of production data.
- Authentication or signature verification bypass.

### High
- SQLite migration can corrupt or lose existing data.
- Path traversal or symlink security vulnerabilities.
- Unsafe file writes or unauthorized file access.

### Medium
- Missing error handling.
- Missing input validation.
- Resource leaks.
- Missing regression tests.

### Low
- Code duplication.
- Naming and readability issues.
- Missing documentation.

## 3. Review Rules

- Never expose secrets in review comments.
- Never automatically approve a Pull Request.
- Never automatically merge a Pull Request.
- Never modify production data.
- Verify findings against actual source code.
- Include file paths and line numbers for findings.
- Distinguish confirmed vulnerabilities from potential risks.

## 4. Executor Security

Pay special attention to:
- Approval workflow integrity.
- Command execution boundaries.
- Shell injection.
- Path traversal.
- Permission checks.
- Audit logging.

## 5. Review Output

Every review should include:

1. Overall assessment.
2. Critical findings.
3. High findings.
4. Medium findings.
5. Low findings.
6. Recommended fixes.
7. Test coverage assessment.

AI review is advisory and must never be represented as an independent GitHub approval.
