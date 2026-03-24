# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repo has two primary runtimes:
- **FastAPI webhook service** in `main.py` that reviews GitHub PR diffs with Gemini and posts PR comments.
- **Click-based CLI** in `reviewer.py` (installed as `reviewer`) for server setup and model management.

## Common Development Commands

### Local setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### Run the API service locally
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Run with Docker
```bash
docker-compose up -d
docker-compose restart
```

### CLI workflows
```bash
reviewer setup-server
reviewer init --url http://localhost:8000 --token <WEBHOOK_SECRET>
reviewer status
reviewer list
reviewer set <model_id>
reviewer health
reviewer test-webhook
```

### Build distributable CLI binary
```bash
# Windows PowerShell
./build.ps1

# Direct command used by CI/build script
pyinstaller --onefile --name reviewer --clean reviewer.py
```

### Release pipeline trigger
```bash
git tag v1.2.3
git push origin v1.2.3
```
(Tagged `v*` pushes trigger `.github/workflows/release.yml` to build cross-platform binaries and create a GitHub Release.)

## Testing and Linting Status

- No dedicated lint or automated test config is currently checked in (no `tests/`, `pytest.ini`, or lint tool config).
- Practical smoke checks used in this codebase:
```bash
python -m py_compile main.py reviewer.py
reviewer status
reviewer test-webhook
```
- If pytest tests are added, run a single test with:
```bash
pytest path/to/test_file.py::test_name
```

## High-Level Architecture

### Server flow (`main.py`)
1. Load `.env`; fail startup if `WEBHOOK_SECRET` is missing.
2. `POST /webhook` verifies `X-Hub-Signature-256` HMAC.
3. For PR actions (`opened`, `synchronize`, `reopened`):
   - Build GitHub client (GitHub App preferred; PAT fallback).
   - Download PR diff via GitHub API (`application/vnd.github.v3.diff`).
   - Count tokens and generate review with configured Gemini model.
   - Post formatted/truncated PR comment to GitHub.
4. Admin endpoints (`/api/models`, `/api/models/active`) are protected by `X-Admin-Token`.

### CLI flow (`reviewer.py`)
- Stores client connection config in `~/.code_reviewer/config.json`.
- `setup-server` creates/updates `.env` (secrets + provider credentials).
- `init` stores server URL/admin token and optional auto-restart behavior.
- Model commands call the server admin endpoints over HTTP.
- `restart_server()` assumes current directory contains `docker-compose.yml`.

### Configuration and state
- Server runtime secrets/config: `.env`
- Server-selected active model persistence: `config.json` (repo root)
- CLI client config: `~/.code_reviewer/config.json`

## Important Implementation Conventions

- Keep webhook verification and admin-token protection intact when changing auth logic.
- Preserve retry behavior (`tenacity`) and thread offloading (`anyio.to_thread.run_sync`) around blocking network/API calls.
- Respect hard limits already encoded in `main.py` (`MAX_TOKENS`, GitHub comment size safety margin).

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **code-reviewer** (182 symbols, 319 relationships, 5 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## When Debugging

1. `gitnexus_query({query: "<error or symptom>"})` — find execution flows related to the issue
2. `gitnexus_context({name: "<suspect function>"})` — see all callers, callees, and process participation
3. `READ gitnexus://repo/code-reviewer/process/{processName}` — trace the full execution flow step by step
4. For regressions: `gitnexus_detect_changes({scope: "compare", base_ref: "main"})` — see what your branch changed

## When Refactoring

- **Renaming**: MUST use `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` first. Review the preview — graph edits are safe, text_search edits need manual review. Then run with `dry_run: false`.
- **Extracting/Splitting**: MUST run `gitnexus_context({name: "target"})` to see all incoming/outgoing refs, then `gitnexus_impact({target: "target", direction: "upstream"})` to find all external callers before moving code.
- After any refactor: run `gitnexus_detect_changes({scope: "all"})` to verify only expected files changed.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Tools Quick Reference

| Tool | When to use | Command |
|------|-------------|---------|
| `query` | Find code by concept | `gitnexus_query({query: "auth validation"})` |
| `context` | 360-degree view of one symbol | `gitnexus_context({name: "validateUser"})` |
| `impact` | Blast radius before editing | `gitnexus_impact({target: "X", direction: "upstream"})` |
| `detect_changes` | Pre-commit scope check | `gitnexus_detect_changes({scope: "staged"})` |
| `rename` | Safe multi-file rename | `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` |
| `cypher` | Custom graph queries | `gitnexus_cypher({query: "MATCH ..."})` |

## Impact Risk Levels

| Depth | Meaning | Action |
|-------|---------|--------|
| d=1 | WILL BREAK — direct callers/importers | MUST update these |
| d=2 | LIKELY AFFECTED — indirect deps | Should test |
| d=3 | MAY NEED TESTING — transitive | Test if critical path |

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/code-reviewer/context` | Codebase overview, check index freshness |
| `gitnexus://repo/code-reviewer/clusters` | All functional areas |
| `gitnexus://repo/code-reviewer/processes` | All execution flows |
| `gitnexus://repo/code-reviewer/process/{name}` | Step-by-step execution trace |

## Self-Check Before Finishing

Before completing any code modification task, verify:
1. `gitnexus_impact` was run for all modified symbols
2. No HIGH/CRITICAL risk warnings were ignored
3. `gitnexus_detect_changes()` confirms changes match expected scope
4. All d=1 (WILL BREAK) dependents were updated

## Keeping the Index Fresh

After committing code changes, the GitNexus index becomes stale. Re-run analyze to update it:

```bash
npx gitnexus analyze
```

If the index previously included embeddings, preserve them by adding `--embeddings`:

```bash
npx gitnexus analyze --embeddings
```

To check whether embeddings exist, inspect `.gitnexus/meta.json` — the `stats.embeddings` field shows the count (0 means no embeddings). **Running analyze without `--embeddings` will delete any previously generated embeddings.**

> Claude Code users: A PostToolUse hook handles this automatically after `git commit` and `git merge`.

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
