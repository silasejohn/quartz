# Quartz

Tournament scouting and draft analysis pipeline for amateur League of Legends tournaments.

Quartz ingests player roster data, enriches it with OP.GG rank history and champion pool stats (DPM.lol + OP.GG), computes Point Value (PV) scores, and exports a draft pool for Google Sheets. Includes a draft simulator for captain threshold analysis.

## Quickstart

### Install uv

macOS:

```bash
brew install uv
```

Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows:

```bash
winget install --id astral-sh.uv -e
```

### Development From Source

Clone the repository, install dependencies into uv's managed project environment, and run the CLI through `uv run`:

```bash
git clone <repo-url>
cd quartz
uv sync --extra dev
uv run quartz --help
```

Run Quartz commands with `uv run` so they use the locked project environment:

```bash
uv run quartz ingest
uv run quartz pv
uv run quartz export
```

Run tests the same way:

```bash
uv run pytest tests/ -q
```

### Install As A CLI Tool

To install Quartz as a standalone command from a local checkout:

```bash
uv tool install .
quartz --help
```

To refresh that local tool install after pulling changes:

```bash
uv tool install --reinstall .
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

   Commit messages generally follow `type(scope): summary`, for example:
   ```bash
   feat(docs): add contribution instructions to README.md
   refactor(cli): ensure scripts solo entry point now in the CLI
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
