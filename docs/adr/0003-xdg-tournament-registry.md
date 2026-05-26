# Tournament Config Uses XDG Registry

Quartz no longer loads `active_tournament.yaml` or repo-root `tournaments/*.yaml` files automatically. Tournament definitions are managed by the CLI and stored in the platform config directory; active tournament selection is stored in the platform state directory; tournament data is stored in the platform data directory.

On Linux this follows XDG: `$XDG_CONFIG_HOME/quartz`, `$XDG_DATA_HOME/quartz`, `$XDG_STATE_HOME/quartz`, and `$XDG_CACHE_HOME/quartz`, with normal fallbacks under `~/.config`, `~/.local/share`, `~/.local/state`, and `~/.cache`. macOS and Windows use their conventional application support, local app data, and cache locations.

## Decision

Use `quartz tournament` commands to create, import, list, show, select, rename, remove, and export tournament definitions. Store tournament YAML files under the platform config directory and store `state.yaml` under the platform state directory. Store player JSON, raw inputs, processed outputs, and exports under the platform data directory by default.

Legacy repo-root files are not loaded. If Quartz detects `./active_tournament.yaml` or `./tournaments/*.yaml`, it prints a migration reminder telling the user to run `quartz tournament import PATH --use`.

## Considered Options

- **Repo-root `active_tournament.yaml`** — simple during early development, but it breaks installed CLI usage because packages live in `site-packages`, not the user's working repo.
- **Current working directory fallback** — unblocks installed CLI usage but still makes behavior depend on where the command is invoked.
- **Custom `QUARTZ_HOME` directory** — centralized, but reinvents platform conventions and creates another Quartz-specific concept for users to learn.
- **XDG/platform config registry** — follows OS conventions, works for installed tools, separates config/state/data/cache, and lets the CLI own tournament lifecycle. Chosen.

## Consequences

Users must migrate existing `active_tournament.yaml` or repo-root tournament snapshots with `quartz tournament import`. After migration, commands can be run from any directory and use `quartz tournament use NAME` or `quartz --tournament NAME ...` to select tournament context.
