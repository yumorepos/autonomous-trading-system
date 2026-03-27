# Workspace Runtime Directory

This directory is the default runtime workspace used by `config/runtime.py`.

It is intentionally separate from source code so that generated state and operator controls are easy to inspect or replace.

## Expected contents

- `data/` — generated datasets and intermediate artifacts
- `logs/` — append-only trade logs, state files, incident logs, and generated reports
- `operator_control.json` — human override inputs
- `system_status.json` — latest health and trading-permission snapshot

Set `OPENCLAW_WORKSPACE` to point the system at another runtime directory if desired.
