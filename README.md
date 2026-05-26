# Quartz

Tournament scouting and draft analysis pipeline for amateur League of Legends tournaments.

Quartz ingests player roster data, enriches it with OP.GG rank history, computes Point Value (PV) scores, and exports a draft pool for Google Sheets. Includes a draft simulator for captain threshold analysis.

## Quickstart

Install uv:

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

Install dependencies and run Quartz from the project environment:

```bash
uv sync --extra dev
uv run quartz --help
```

Create or import a tournament before running pipeline commands:

```bash
uv run quartz tournament create gcs-s4
uv run quartz tournament use gcs-s4
uv run quartz ingest
```

See `CLAUDE.md` for full usage.

## Tournament Config

Quartz stores tournament definitions and active-tournament state in the standard user config/state locations for your OS. Do not edit a repo-root `active_tournament.yaml`; that legacy file is no longer loaded.

Common commands:

```bash
quartz tournament create gcs-s4
quartz tournament import ./old_tournament.yaml --use
quartz tournament list
quartz tournament use gcs-s4
quartz tournament show
quartz tournament path --data
```

For one command without changing the active tournament:

```bash
quartz --tournament gcs-s4 pv
```

Default storage locations:

| OS | Config | Data | State | Cache |
| --- | --- | --- | --- | --- |
| Linux | `$XDG_CONFIG_HOME/quartz` or `~/.config/quartz` | `$XDG_DATA_HOME/quartz` or `~/.local/share/quartz` | `$XDG_STATE_HOME/quartz` or `~/.local/state/quartz` | `$XDG_CACHE_HOME/quartz` or `~/.cache/quartz` |
| macOS | `~/Library/Application Support/quartz` | `~/Library/Application Support/quartz` | `~/Library/Application Support/quartz` | `~/Library/Caches/quartz` |
| Windows | `%APPDATA%\\quartz` | `%LOCALAPPDATA%\\quartz` | `%LOCALAPPDATA%\\quartz` | `%LOCALAPPDATA%\\quartz\\Cache` |

Run `quartz tournament locations` to print the resolved paths on your machine.

If Quartz detects legacy `./active_tournament.yaml` or `./tournaments/*.yaml` files, it prints a migration reminder. Import them explicitly with `quartz tournament import PATH --use`.

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
