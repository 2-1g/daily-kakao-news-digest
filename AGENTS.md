# Repository Safety Rules

This is a public, vibe-coding repository. Treat every tracked file and the full
Git history as publicly visible.

- Never commit credentials, API keys, OAuth codes or tokens, cookies, private
  keys, personal identifiers, private URLs, billing data, or production logs.
- Store runtime secrets only in the approved secret manager or an untracked
  local `.env`; keep examples empty or obviously synthetic.
- Before every commit and push, inspect staged changes and scan both filenames
  and content for secrets. Stop the push if a value is uncertain.
- Redact sensitive values from tests, fixtures, documentation, screenshots,
  command output, issue text, and commit messages.
- Do not weaken `.gitignore` secret protections. If a secret is ever committed,
  rotate it first and then remove it from the complete Git history.
- Avoid adding generated artifacts, local state, IDE metadata, or user-specific
  absolute paths unless they are intentionally required and non-sensitive.
