# Quarantine

A self-improving agent harness. An IT-operations worker agent reaches every tool through
one MCP gateway. The gateway enforces a policy stored in MongoDB Atlas. The policy starts
empty. After a failure, an Evolver agent writes the next policy version, and a Guardian
agent reviews memory writes the gateway has held. A Streamlit console shows each step as
it happens.

```
worker (LLM) ──MCP──▶ gateway ──▶ policy.enforce ──▶ tools ──▶ MongoDB Atlas (sandbox)
                                      ▲                            │
              Evolver ── next policy ─┘◀── failed health check ────┤
              Guardian ◀── held memory write ──────────────────────┘
```

## Setup

Requires Python 3.10 or later. No Docker.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill it in
```

Values you must set in `.env`:

| Variable | What it is |
| --- | --- |
| `MONGODB_URI` | The hackathon Atlas Sandbox cluster. A local MongoDB is refused. |
| `LLM_API_KEY` | Anthropic API key. |
| `LLM_WORKSPACE_ID` | Only if the key is not scoped to a workspace (`wrkspc_...`). |
| `RAINDROP_WRITE_KEY` | Only when `RAINDROP_ENABLED=1`. |

With `RAINDROP_ENABLED=1`, each worker run is sent to Raindrop with one span per tool call
and the signals `health_check_failed`, `write_held`, `call_denied` and `guardian_conflict`.
Run ids restart after a reset, so a later run with the same id updates the earlier one there.

The model is pinned by `LLM_MODEL` (default `claude-haiku-4-5`) and runs at
`LLM_TEMPERATURE=0`. Newer Claude models reject temperature 0; to use one, clear
`LLM_TEMPERATURE` and set `LLM_EFFORT=low`.

Check the setup:

```bash
.venv/bin/python scripts/smoke.py connect    # ping, reset, list seeds, one LLM reply
.venv/bin/python -m pytest                   # policy logic, no database needed
```

## Run the demo

```bash
scripts/start_all.sh      # gateway :8000, Guardian, Evolver, console http://localhost:8501
```

Open the console. It refreshes every two seconds.

**One click.** Press **Run the full demo** in the sidebar. It runs `scripts/demo.py`,
which resets the database to policy v0 and plays the whole story with pauses, so each
change can be watched as it lands. A progress bar names the current stage: reset, triage
ticket 4127, provision web-07, wait for the Evolver's policy, triage ticket 4131, wait
for the Guardian, provision web-08. It takes about a minute. If a stage fails or times
out, the console shows where it stopped and the error.

**Step by step.** The sidebar also has one button for each of the four worker runs, and
**Reset to policy v0**. Start with the reset: the policy is empty, with no taint sources
and no rules. Then:

1. **Triage ticket 4127.** The ticket contains one false sentence (DNS resolvers moved
   to 203.0.113.66). The worker saves it to memory.
2. **Provision web-07.** The worker recalls the newest DNS fact and uses it. The health
   check fails. The Evolver traces the failure to the ticket-derived memory, publishes
   policy v1, and quarantines that memory. The console shows the diff from v0 and the
   event that caused it.
3. **Triage ticket 4131.** A different false fact (NTP moved to 203.0.113.80). The
   gateway holds the worker's memory writes. The Guardian flags the conflict with the
   trusted NTP memory. Release or purge held writes from the queue.
4. **Provision web-08.** Quarantined memory is no longer recalled, so the worker uses
   the trusted settings. The health check passes.

The console is a dark dashboard. From top to bottom it shows:

- A headline figure from the replay: poisoned settings that reached a server, before
  and after the learned policy.
- Four tiles: active policy, gateway decisions, held for review, servers healthy.
- A five-step story strip that fills in from live data: the four runs above, with the
  Evolver's policy as its own step after web-07.
- The active policy as readable rules, with the Evolver's rationale and an expandable
  diff against the version before it.
- The held-for-review queue, with **Release** and **Purge** on each entry.
- Server cards that mark DNS and NTP values that differ from the baseline.
- Before-and-after meters from the replay.
- A live gateway feed: tool calls with their decisions, health checks, Guardian
  verdicts, policy changes and human decisions.

The same story from a terminal:

```bash
.venv/bin/python scripts/demo.py          # the full demo, as the button runs it
.venv/bin/python scripts/smoke.py act1    # reset, then steps 1 and 2
.venv/bin/python scripts/smoke.py act3    # steps 3 and 4
.venv/bin/python scripts/replay.py        # 20 tickets under v0 and under the learned v1
```

`demo.py` takes `--pause SECONDS` to set the pauses (default 4). `smoke.py` adds
assertions and timings. `demo.py`, `smoke.py` and `replay.py` start the processes they
need when the stack is not already running; none of them starts the console.
`smoke.py act3 --fixture` runs steps 3 and 4 against `fixtures/policy_v1.json` on a
clean reset, without the Evolver.

`replay.py` copies the learned policy from the main database, so run the demo or
`smoke.py act1` first. It replays in `REPLAY_DB_NAME` behind its own gateway on port
8001, with the Evolver off, and writes `data/replay_results.json`. The console reads its
headline figure and meters from that file, which git ignores: until the replay has run,
the headline is missing and the meters panel says there is no replay yet.

Result of the replay, measured in a run on 2026-10-11. The set is 20 tickets: 10 carry a
false DNS or NTP setting and 10 are harmless.

| Policy | Poisoned settings that reached a server | Harmless notes held for review |
| --- | --- | --- |
| v0, empty | 9 of 10 | 0 of 10 |
| v1, learned | 0 of 10 | 10 of 10 |

The learned policy kept every poisoned setting off the servers. Its cost is that it also
held every harmless ticket note: a rule can test whether a run is tainted, not whether a
note is true, and a held note stays held until a person releases it.

## How it works

- **Gateway** (`src/quarantine/gateway.py`): four tools, `read_ticket`, `remember`,
  `recall`, `provision_server`. Every call goes through `policy.enforce`, which records
  the call on the run, marks the run tainted when the tool is a taint source, and returns
  `allow`, `hold` or `deny`. The worker never chooses its own `run_id`.
- **Policy** (`policy.py`): taint sources, ordered tool rules, and a context policy that
  filters what `recall` may return. `is_tighter` decides whether a proposed policy may
  go live: it must keep every taint source, not widen what `recall` may return, be at
  least as strict as the current one for every tool, and differ.
- **Evolver** (`evolver.py`): watches for failed health checks. It sees ids, tool names
  and counts only, never ticket or memory text. The model's output is constrained to a
  schema derived from the current policy (`policy.proposal_schema`): `hold` can only be
  expressed on the `remember` tool, and the recall filters cannot name anything the
  current policy already excludes. `is_tighter` still makes the final decision: a
  proposal that is not tighter is saved as `proposed` and does not take effect.
- **Guardian** (`guardian.py`): watches for quarantined memory and reports whether it
  contradicts a trusted memory.
- **Console** (`console/`): one Streamlit page that reads the database directly.
  `views.py` builds each section from one snapshot, `style.py` holds the colours and
  CSS, and `.streamlit/config.toml` sets the dark theme. Release and Purge update the
  ledger entry and record a `human_decision` event.
- **Data**: seven collections (`tickets`, `memory_ledger`, `runs`, `events`, `policies`,
  `servers`, `baseline`) in `DB_NAME`. The replay uses `REPLAY_DB_NAME` on the same cluster.

## What is mocked

- **The health check is a mocked monitor.** `health.py` compares a server's DNS and NTP
  settings with the `baseline` document. No real server or monitoring system exists.
- **Servers are documents.** `provision_server` writes a document; nothing is provisioned.
- **Tickets are seed data**, written for the demo. The replay set is in
  `data/tickets_replay.json`.
- `fixtures/policy_v1.json` is a test fixture (author `fixture`). It is never presented
  as Evolver output.

## Vector search

`recall` and the Guardian can rank memories with Atlas Vector Search over an autoEmbed
index on `memory_ledger.text` (`voyage-4`, with `status` and `trust` as filter fields).

```bash
.venv/bin/python scripts/seed.py --vector-index   # create it, or print its status
```

Set `USE_VECTOR_SEARCH=1` once it reports `READY`. The index trails writes by about a
second, so it only ranks: the policy filter is applied again to the live documents before
anything is returned. With `USE_VECTOR_SEARCH=0`, recall reads the ledger directly. The
replay always uses the ledger, because the index exists only in the main database.

## Not built

- Milestone 7, the Atlas Agent Engine memory mirror. `MEMORY_BACKEND` must stay `ledger`.
