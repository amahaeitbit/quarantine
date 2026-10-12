"""Words for the About tab and the About menu item. Each row describes something the code does today."""

MENU = """**Quarantine** is a self-improving agent harness.

Helpdesk tickets → worker agent → MCP gateway → five tools (memory, web servers, DNS records) → monitor.
A failed check wakes the Evolver through an Atlas change stream. Its next policy goes live only if it passes
an eval, and the gateway enforces it on the next call.

- **MongoDB Atlas**: all state, change streams, Vector Search
- **MCP**: the one gateway in front of the tools
- **Raindrop**: traces and signals
- **Access control**: the gateway decides every call, tainted runs cannot write trusted memory, the Evolver
  never sees text, and only a person releases a held write
- **Mocked**: servers, the monitor and Route 53 are documents

The About tab at the top of the page has the full flow diagram."""

# (part, tool, what it does here)
PARTS = [
    ("State and events", "MongoDB Atlas, sandbox cluster", "Eight collections hold every policy version, run, event, memory, "
     "server and DNS record. Change streams wake the Evolver and the Guardian. A second database holds the replay."),
    ("Search", "Atlas Vector Search", "An autoEmbed index (voyage-4) on memory text ranks memories for recall and for the "
     "Guardian's conflict check. The ledger still decides what recall may return."),
    ("Tool access", "MCP", "One gateway serves the five tools over streamable HTTP. It is the only place where a call is "
     "allowed, held or denied, and where taint from a ticket is tracked."),
    ("Agents", "Claude Haiku 4.5, Anthropic API", "The worker, the Evolver and the Guardian, all at temperature 0."),
    ("Tracing", "Raindrop", "One conversation per demo: each run, a span per gateway decision, each Evolver proposal, each "
     "Guardian review, and a signal with the issue code for each failed check."),
    ("Web", "provision_server (mocked)", "Builds web-07 and web-08 as documents with DNS resolvers, NTP servers, a DoT, DoH "
     "or DoQ endpoint and a DNSSEC setting."),
    ("DNS", "update_dns_record (Route 53, mocked)", "Changes A records in corp.example as documents. The monitor fails a "
     "record that leaves the corporate ranges."),
    ("Evals", "32 recorded traces", "Each proposed policy is replayed on them. It goes live only if it stops its own "
     "incident and blocks no clean run."),
    ("Console", "Streamlit", "This web page: the live state, the policy diff, and the release or purge decision."),
]

# (letter on the diagram, where, control, how it works). The last row has no letter: it is what is missing.
CONTROLS = [
    ("A", "Helpdesk tickets", "Taint tracking", "Reading a ticket marks the run as tainted once the policy names "
     "read_ticket as a taint source. Everything that run does afterwards is judged as coming from untrusted input."),
    ("B", "Worker agent", "An identity the model cannot choose", "The run id is absent from the worker's tool schemas and "
     "is set by the harness on every call, so the model cannot act as another run. It reaches tools only through the gateway."),
    ("C", "MCP gateway", "Enforcement point", "Every call is checked against the active policy and gets allow, hold or "
     "deny; the first matching rule wins. A call from a run the database does not know is denied. The gateway listens on "
     "localhost only."),
    ("D", "Shared memory", "Trust labels", "A held write is stored as quarantined and untrusted. Recall returns only the "
     "statuses and trust levels the policy allows, and that filter is applied again after vector search."),
    ("E", "Monitor", "Independent check", "It compares each result with a baseline that no worker tool can write, and the "
     "worker is not told the outcome."),
    ("F", "MongoDB Atlas", "Credentials and audit trail", "The connection uses a database user over TLS, and the code "
     "refuses a local or placeholder URI. Secrets come from .env only, which git ignores. Every decision is stored as an "
     "event, and each policy version records the incident that caused it."),
    ("G", "Evolver agent", "Text-blind and tighten-only", "It sees ids, tool names and counts, never ticket or memory "
     "text, so planted text cannot reach the rule writer. Its output is limited to a schema. A proposal that is not at "
     "least as strict, or that fails the eval, is saved as proposed and never enforced."),
    ("H", "Guardian agent", "Review without the power to release", "It compares each held write with trusted memory "
     "only and records a conflict with its reason. It cannot change a write's status."),
    ("I", "Console", "Human decision", "Only a person releases or purges a held write, and the decision is stored as an "
     "event. Ticket and memory text is shown escaped, never as Markdown. The console listens on localhost only."),
    ("J", "Raindrop", "Redaction", "Free text in tool arguments is replaced by its length before it is written to events "
     "or sent in traces."),
    ("", "Not built", "User login and roles", "The console has no login and the gateway has no client authentication. "
     "Both can be reached from this machine only."),
]
