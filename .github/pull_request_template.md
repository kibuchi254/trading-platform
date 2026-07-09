## Description
<!-- A clear and concise description of what this PR does and why -->


## Type of Change
- [ ] 🐛 Bug fix (non-breaking)
- [ ] ✨ New feature (non-breaking)
- [ ] 💥 Breaking change (fix or feature causing existing functionality to break)
- [ ] 🔧 Refactor / code cleanup (no functional changes)
- [ ] 📦 Dependency update
- [ ] 🗄️ Database migration (Alembic)
- [ ] ⚡ Performance improvement
- [ ] 🔒 Security fix
- [ ] 📚 Documentation only

## Changes Made
<!-- List the key changes in this PR. Be specific — what functions/classes/endpoints changed? -->
-
-
-

## Testing
- [ ] Unit tests added / updated and passing locally
- [ ] Integration tests added / updated and passing locally
- [ ] Manual testing performed (describe steps below)

**Manual Testing Steps:**
<!-- How can a reviewer reproduce your manual tests? -->
1.
2.

## Database Migration Notes
- [ ] ✅ No migrations in this PR
- [ ] ✅ Migration is backward-compatible (safe to run before **and** after deploy)
- [ ] ⚠️ Migration requires downtime or is destructive:

  > Explain the impact and rollback strategy:

## Breaking Changes
- [ ] No breaking changes
- [ ] Breaking changes (describe migration path for consumers):

  >

## Observability
- [ ] Structured logging added for new code paths
- [ ] Prometheus metrics / OTel traces added where appropriate
- [ ] No observability changes needed

## Checklist
- [ ] `ruff check` and `black --check` pass locally
- [ ] `mypy` passes locally
- [ ] No hardcoded secrets, credentials, or API keys
- [ ] Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (e.g. `feat:`, `fix:`, `chore:`)
- [ ] Documentation / docstrings updated if needed
- [ ] PR title follows Conventional Commits format (used for release notes)
