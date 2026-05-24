# Quartz

Tournament scouting and draft analysis pipeline for amateur League of Legends tournaments.

Quartz ingests player roster data, enriches it with OP.GG rank history, computes Point Value (PV) scores, and exports a draft pool for Google Sheets. Includes a draft simulator for captain threshold analysis.

## Quickstart

```bash
brew install uv
uv venv && source .venv/bin/activate
uv pip install -e .
```

See `CLAUDE.md` for full usage.

## Contributing

1. **Clone the repo and check out `master`**
   ```bash
   git clone <repo-url>
   cd Quartz
   git checkout master
   ```

2. **Create a feature branch off `master`**
   ```bash
   git checkout -b feature/your-feature-name
   ```
   Use a descriptive branch name (`feature/`, `fix/`, `refactor/` prefixes).

3. **Make your changes, then push the branch to remote**
   ```bash
   git push -u origin feature/your-feature-name
   ```

4. **Open a Pull Request targeting `master`**

   GitHub will automatically run the CI pipeline on your PR:
   - **Lint** — `ruff check` (style and correctness)
   - **Tests** — `pytest` with coverage
   - **CodeQL** — static security analysis

   All checks must pass before the PR can be merged.

5. **Request review from @silasjohn**

   The repo owner reviews and approves the PR. Address any feedback on the same branch — CI re-runs on each push.

6. **Merge** — once approved and all checks are green, the PR is merged into `master`.
