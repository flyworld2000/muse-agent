# Muse Agent Security Policy

## Sensitive Files

The following files must never be committed:

- .env
- Private keys
- API tokens
- Password files
- Production SQLite databases
- Database backups containing user data
- Runtime logs containing credentials

## Database Protection

- CI must use temporary test databases.
- Never run migrations against production during CI.
- Back up production databases before schema changes.
- Verify migration version checks and rollback behavior.

## Executor Protection

- All proposed changes must pass approval validation.
- Signature verification must not be bypassed.
- Candidate hashes must be verified.
- File path restrictions must remain enforced.
- Symlink and path traversal protections must remain enabled.

## Code Changes

- Review security-sensitive changes before merging.
- Do not disable tests merely to make CI pass.
- Do not weaken validation without documented justification.
- Do not expose internal credentials in logs.

## Incident Handling

If a credential is accidentally committed:

1. Stop further distribution.
2. Revoke or rotate the exposed credential.
3. Remove the sensitive content from repository history where appropriate.
4. Review access logs for possible misuse.
5. Document the incident and corrective action.
