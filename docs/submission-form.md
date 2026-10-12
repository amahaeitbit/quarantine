Ready-to-paste answers for the submission form. Fill in the bracketed placeholders.

## Project name

Quarantine

## Tagline

A self-improving agent harness: an MCP gateway whose policy starts empty and is tightened by an Evolver agent after each failed check.

## Elevator pitch

Quarantine is a self-improving harness for an IT-operations agent. Every tool call goes
through one MCP gateway that enforces a policy stored in MongoDB Atlas. The policy starts
empty. After a failed check, an Evolver agent writes the next version, which goes live
only if it is at least as strict and passes an eval on recorded traces.

## What it does

An IT-operations agent triages untrusted helpdesk tickets, saves facts about the
environment to a shared memory, and provisions servers from it. In the demo, ticket 4127
carries one false sentence: corporate DNS resolvers moved to 203.0.113.66. Under the
empty policy v0 the agent saves it, the next session builds web-07 with it, and the
server fails its health check.

Quarantine puts one MCP gateway between the agent and its tools. After the failed check,
an Evolver agent writes policy v1: reading a ticket taints the run, and memory writes
from tainted runs are held. A Guardian agent checks each held write against trusted
memory and flags contradictions, and a person releases or purges it in a Streamlit
console. A second failure, a DNS record change planted in a ticket, produces policy v2,
which keeps v1 and denies such changes from tainted runs. Nobody edits the policy by
hand.

## How it works

A worker agent reaches five tools through one MCP gateway: read_ticket, remember, recall,
provision_server and update_dns_record. Every call goes through policy.enforce, which
marks the run tainted when the tool is a taint source and returns allow, hold or deny.
The policy is a document in MongoDB Atlas; v0 is empty.

A mocked monitor compares each server and DNS record with a baseline document and reports
issue codes such as dns_resolver_untrusted. A failed check triggers the Evolver. It sees
ids, tool names and counts only, never ticket or memory text, and its output is
constrained to a schema derived from the current policy. A proposal must be at least as
strict as the current policy and pass the eval gate: replayed against 32 recorded
tool-call sequences from real runs, it must stop the incident that caused it, block no
clean run and lose no ground on recorded attacks. A failed verdict goes back to the model
for another attempt.

The Guardian reviews each held memory write and reports whether it contradicts trusted
memory. A Streamlit console shows the policy diff, the held queue and the gateway feed.
All agents use claude-haiku-4-5 at temperature 0.

## How it uses MongoDB Atlas

All data lives in the hackathon's Atlas sandbox cluster; a local MongoDB is refused. Eight
collections hold the state: policies (each keeps its incident and its eval), events,
runs, memory_ledger, servers, dns_records, tickets and baseline. Change streams drive the
agents: the Guardian watches memory_ledger and the Evolver watches events, so a held
write is reviewed and a failed check answered within seconds, with no polling loop of
their own. An optional Atlas Vector Search autoEmbed index on memory_ledger.text ranks
memories for recall and the Guardian; the ledger still decides what recall may return. A
run's tool list and taint flag change in one atomic findOneAndUpdate. The 20-ticket
replay runs in a second database on the same cluster.

## How it uses Raindrop

Tracing is one env flag, RAINDROP_ENABLED. All runs since the last reset share one
conversation id, so a demo reads as one conversation. Every worker run is a worker_run
event with the model, policy version, ticket id and incident type. Each gateway decision
is a tool span with its input (free text redacted to its length), the decision and the
taint flag. Each Evolver proposal is a policy_proposal event and each Guardian review a
memory_review event. Signals name the DNS problem class: health_check_failed comes with
the monitor's issue code, such as dns_resolver_untrusted or dns_transport_bypass.

## How it uses MCP

The worker agent reaches its five tools, read_ticket, remember, recall, provision_server
and update_dns_record, only through one MCP gateway. Every call passes through
policy.enforce, which returns allow, hold or deny. The worker never chooses its own
run_id. The gateway is the one place where every DNS-affecting action is checked against
the policy and where taint from untrusted input is tracked. In production it would sit in
front of the real helpdesk, memory store and infrastructure automation.

## Results

Measured replay (2026-10-11): 20 tickets, 10 with a false DNS or NTP setting and 10
harmless. Under the empty policy v0, 9 of the 10 poisoned settings reached a server and
no harmless note was held. Under the learned policy v1, 0 of 10 reached a server and all
10 harmless notes were held for review. That is the cost: a rule can test whether a run
is tainted, not whether a note is true, so a person has to release them. The replay
covers the first incident only. On the eval gate's recorded traces, v0 blocks 0 of 12
attacks, v1 10 of 12 and v2 12 of 12, with all 10 clean runs unaffected.

## What is real and what is mocked

Real: all data is in the Atlas sandbox cluster; the MCP gateway and its enforcement; the
worker, Evolver and Guardian are model calls; the learned policy is written by the
Evolver at run time, never loaded from a fixture. Mocked: provisioning writes a document,
and no server exists; the monitor compares a server document's DNS, NTP, transport,
endpoint and DNSSEC settings with a baseline document and probes no resolver; Route 53 is
mocked, so update_dns_record writes a document and no hosted zone changes; tickets are
seed data written for the demo.

## What we learned

- Free-form policy proposals were mostly unusable: across 12 slightly varied incident
  summaries the model produced a usable policy 5 times, and constraining its output to a
  schema derived from the current policy, plus saying in the prompt why writes are held
  rather than denied, gave 12 of 12.
- Structural tightness is not enough: one proposal in 12 was tighter than v0 yet did not
  stop the incident, so an eval on recorded traces now gates activation and feeds its
  verdict back to the model.
- The vector index trails writes, usually by about a second and once by more than five,
  so recall now always reads the five newest eligible memories from the ledger and uses
  vector search only to rank older ones.

## What's next

- Build the Atlas Agent Engine memory mirror (milestone 7), which was not built; the
  memory backend is the ledger only.
- Replace the mocks with real systems: real provisioning in place of a document write,
  the real monitor in place of the baseline comparison, and a Route 53
  ChangeResourceRecordSets call in place of the mocked record update.
- Reduce the review load: the learned policy held all 10 harmless notes in the replay,
  because a rule can test whether a run is tainted, not whether a note is true.

## How to run it

Requires Python 3.10 or later and no Docker. Copy .env.example to .env and set
MONGODB_URI (the hackathon Atlas sandbox cluster; a local MongoDB is refused) and
LLM_API_KEY (an Anthropic API key). RAINDROP_WRITE_KEY is needed only when
RAINDROP_ENABLED=1.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill it in
.venv/bin/python scripts/smoke.py connect    # ping, reset, list seeds, one LLM reply
.venv/bin/python -m pytest                   # policy logic, no database needed
scripts/start_all.sh      # gateway :8000, Guardian, Evolver, console http://localhost:8501
.venv/bin/python scripts/preflight.py
.venv/bin/python scripts/demo.py          # the full demo, as the button runs it
.venv/bin/python scripts/replay.py        # 20 tickets under v0 and under the learned v1
```

preflight.py checks the cluster, the model, the running processes, the replay data and
tracing, and prints READY. In the console at http://localhost:8501, press Run the full
demo: ten stages, about two minutes. demo.py runs the same demo from a terminal.
replay.py needs the learned policy, so run the demo first. Every demo path resets the
shared database.

## Built with

Python, MCP, MongoDB Atlas, Atlas change streams, Atlas Vector Search (autoEmbed index with voyage-4), Anthropic API, claude-haiku-4-5, Raindrop, Streamlit, pytest

## Links

Repository: https://github.com/amahaeitbit/quarantine

Pitch deck: docs/pitch-deck.pdf in the repository

Demo video: [URL, if recorded]
