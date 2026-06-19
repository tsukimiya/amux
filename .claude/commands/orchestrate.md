---
description: Scaffold a closed orchestrator loop — creates the mission note, state/constraints notes, and a scheduler entry from the v2 template.
allowed-tools: Bash, Read, Write
argument-hint: -g "goal description" -s "session-a, session-b, ..."
---

# /orchestrate — Scaffold a closed orchestrator loop

Parse the arguments, generate a filled-in orchestrator loop note from the v2 template, create companion notes, and wire up a scheduler entry.

## Arguments

- `-g "<text>"` — The mission goal(s). Can be a sentence or a paragraph. Required.
- `-s "<list>"` — Comma-separated list of authorized session names. Required.
- `--schedule "<expr>"` — When to run. Optional. Default: `every 2h`
- `--slug "<name>"` — Note slug to use. Optional. Default: derived from the goal (kebab-case, ≤30 chars)
- `--no-schedule` — Create the note but skip the scheduler entry (useful for manual/one-shot loops)

## Procedure

### 1. Parse arguments

Extract `-g`, `-s`, `--schedule`, `--slug`, `--no-schedule` from the skill arguments. If `-g` or `-s` is missing, stop and ask the user before proceeding.

Derive a slug if not provided: lowercase the goal, strip punctuation, replace spaces with `-`, truncate to 30 chars. Example: "Make MVS robust end to end" → `mvs-robust-end-to-end`.

### 2. Infer session lanes

For each session in `-s`, derive its likely lane and issue prefix using this mapping. If a session isn't listed, use its name as the lane description and leave the prefix blank.

| Session name contains | Issue prefix | Lane |
|---|---|---|
| `mvs-infra` | `MI-` | shard, partition, scroll, scale |
| `mvs-build` | `MB-` | topology, image builds, cutover |
| `backend` | `BACKE-` | write pipeline, celery, analytics |
| `ts-gke` | `TG-` | TubeScience, GKE experiments |
| `observability` | `MO-` | metrics, alerts, dashboards |
| `studio` | `MS-` | UI, golden path, E2E |
| `orchestrator` | `AMUX-` | cross-cutting, escalations |
| `general` | `MG-` | diagnosis, root cause, unowned |

### 3. Build the mission note

Fetch the v2 template:
```bash
curl -sk $AMUX_URL/api/notes/orchestrator-loop-v2 | python3 -c "import json,sys; print(json.load(sys.stdin).get('content',''))"
```

Fill in the template with:

- **Loop slug**: derived in step 1
- **Issue prefixes**: from step 2, space-separated
- **Schedule**: from `--schedule` or default `every 2h`
- **Goal**: the `-g` text verbatim as the **Goal** line
- **Scope in / Scope out / Done when**: leave as `[...]` — the orchestrator will fill these in on first tick based on context
- **Critical path**: leave as `[Item 1]`, `[Item 2]`, `[Item 3]` placeholders — the orchestrator derives this from the goal on first tick
- **Session access control table**: one row per session from `-s`, all with `✓ ✓ ✓` permissions and their inferred lane. Add a final row for `mixpeek-orchestrator` with `AMUX-` prefix (always present).
- **State note slug**: `<slug>-state`
- **Constraints note slug**: `<slug>-constraints`

Save the filled note:
```bash
curl -sk -X POST -H 'Content-Type: application/json' \
  -d "{\"content\": \"<filled content>\"}" \
  $AMUX_URL/api/notes/<slug>
```

### 4. Create companion notes

**State note** (blank initial state):
```bash
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"content": "## Status\n\nNot yet run. Orchestrator will populate on first tick."}' \
  $AMUX_URL/api/notes/<slug>-state
```

**Constraints note** (seed with one standing rule):
```bash
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"content": "# Constraints — <slug>\n\nAppend-only. Never edit existing lines.\n\n```\n[YYYY-MM-DD] — stage explicit git paths only, never git add -A. Reason: 5407ac1473 swept another session'\''s deletions into wrong commit (AMUX-1315).\n```\n"}' \
  $AMUX_URL/api/notes/<slug>-constraints
```

### 5. Create the scheduler entry (skip if --no-schedule)

```bash
curl -sk -X POST -H 'Content-Type: application/json' \
  -d "{
    \"title\": \"Orchestrator loop: <slug>\",
    \"session\": \"mixpeek-orchestrator\",
    \"command\": \"Load note <slug> and run your orchestration loop. Apply constraints from <slug>-constraints. Write state to <slug>-state.\",
    \"schedule_expr\": \"<schedule>\"
  }" \
  $AMUX_URL/api/schedules
```

Capture the returned schedule ID.

### 6. Report back to the user

Print a summary:

```
✓ Loop created: <slug>

Notes:
  Mission:     $AMUX_URL → Notes → <slug>
  State:       <slug>-state  (updated each tick)
  Constraints: <slug>-constraints  (append-only skill library)

Sessions: <list from -s>
Schedule: <expr>  [Schedule ID: <id>]

Scheduler prompt (sent each tick):
  "Load note <slug> and run your orchestration loop.
   Apply constraints from <slug>-constraints.
   Write state to <slug>-state."

Next steps:
  1. Open the mission note and fill in Critical Path if you know it now
     (or leave it — the orchestrator derives it from the goal on first tick)
  2. Run the loop manually once to validate: send the prompt above to mixpeek-orchestrator
  3. The scheduler fires automatically on: <expr>
```

If `--no-schedule` was set, omit the schedule line and say "No scheduler entry created — run manually or add one later with /schedule."

## Edge cases

- If a note slug already exists, stop and ask: overwrite, pick a new slug, or abort.
- If `$AMUX_URL` is not set, stop and tell the user to check their environment.
- If the v2 template note doesn't exist (`orchestrator-loop-v2`), stop and tell the user to run the template setup first.
- Session names with spaces or special characters: quote them in the access control table, use as-is.
