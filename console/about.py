"""The About tab: a flow diagram of the parts, where access control and security plug in, and what each tool does.

The diagram is a static SVG built from the constants below; nothing in it is read from the database.
"""
from html import escape

import streamlit as st

from about_text import CONTROLS, MENU, PARTS  # noqa: F401  (app.py reads MENU from here)
from style import heading

INK, INK2, MUTED, HAIR, SURFACE, RAISED, ACCENT, DEEP = ("#ffffff", "#c3c2b7", "#898781", "#3a3a37", "#1a1a19", "#232321",
                                                         "#3987e5", "#16335c")
SANS, MONO = "Helvetica Neue, Helvetica, Arial, sans-serif", "Menlo, ui-monospace, monospace"
NB = "\u00a0\u00a0"  # indent for a wrapped bullet; plain leading spaces collapse in SVG text
# Where each lettered control of about_text.CONTROLS sits: the top right corner of its box.
BADGES = {"A": (220, 128), "B": (510, 128), "C": (840, 128), "D": (1438, 66), "E": (1450, 343), "F": (1450, 473),
          "G": (650, 648), "H": (1050, 648), "I": (1450, 648), "J": (220, 338)}

DEFS = "<defs>" + "".join(
    f'<marker id="head-{kind}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
    f'<path d="M0 0L10 5L0 10z" fill="{color}"/></marker>'
    for kind, color in (("flow", MUTED), ("trace", MUTED), ("loop", ACCENT))) + "</defs>"


def _text(x: float, y: float, text: str, size: float = 15.5, fill: str = INK2, weight: int = 400, font: str = SANS) -> str:
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" font-family="{font}" fill="{fill}">'
            f'{escape(text)}</text>')


def _box(x: int, y: int, w: int, h: int, title: str, lines: list, mono: str = "", fill: str = SURFACE, stroke: str = HAIR) -> str:
    """A titled box. `mono` is an optional line of tool or collection names under the title."""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
           _text(x + 14, y + 27, title, 18, INK, 700)]
    top = y + 52
    if mono:
        out.append(_text(x + 14, top, mono, 14.5, "#9cc4f5", font=MONO))
        top += 22
    return "".join(out + [_text(x + 14, top + 20 * i, line) for i, line in enumerate(lines)])


def _step(x: float, y: float, n: int) -> str:
    return (f'<circle cx="{x}" cy="{y - 5}" r="10.5" fill="{ACCENT}"/><text x="{x}" y="{y}" font-size="13" font-weight="700" '
            f'font-family="{SANS}" fill="{INK}" text-anchor="middle">{n}</text>')


def _badge(x: float, y: float, letter: str) -> str:
    """A lettered square: an access control or security point, explained in the table under the diagram."""
    return (f'<rect x="{x}" y="{y}" width="22" height="22" rx="5" fill="#0d0d0d" stroke="{INK}" stroke-width="1.5"/>'
            f'<text x="{x + 11}" y="{y + 16}" font-size="13" font-weight="700" font-family="{SANS}" fill="{INK}" '
            f'text-anchor="middle">{letter}</text>')


def _arrow(points: list, kind: str = "flow", label: str = "", step: int = 0) -> str:
    """An arrow through `points`. flow: data, grey. loop: the self-improvement loop, blue and numbered. trace: dashed."""
    path = "M" + " L".join(f"{x} {y}" for x, y in points)
    dash = ' stroke-dasharray="5 5"' if kind == "trace" else ""
    out = (f'<path d="{path}" fill="none" stroke="{ACCENT if kind == "loop" else MUTED}" stroke-width="2"{dash} '
           f'marker-end="url(#head-{kind})"/>')
    if label:  # beside the middle of a vertical arrow, centred above a horizontal one
        (x1, y1), (x2, y2) = points[-2], points[-1]
        if y1 == y2:
            return out + _text((x1 + x2) / 2, y1 - 9, label, 14, MUTED).replace("<text ", '<text text-anchor="middle" ')
        x, y = x1 + 12, (y1 + y2) / 2 + 5
        out += (_step(x + 10, y, step) if step else "") + _text(x + (26 if step else 0), y, label, 14, INK2 if step else MUTED)
    return out


def diagram() -> str:
    parts = [DEFS, _text(20, 38, "The self-improvement loop", 17, INK, 700)]
    x = 20
    for n, label in enumerate(("a check fails", "a change stream wakes the Evolver", "its policy passes the eval",
                               "the gateway enforces it"), start=1):
        parts += [_step(x + 10, 68, n), _text(x + 27, 68, label, 14.5)]
        x += 48 + 7.3 * len(label)
    parts += [f'<path d="M20 92 L60 92" stroke="{MUTED}" stroke-width="2"/>', _text(68, 97, "data flow", 14, MUTED),
              f'<path d="M160 92 L200 92" stroke="{MUTED}" stroke-width="2" stroke-dasharray="5 5"/>',
              _text(208, 97, "traces to Raindrop", 14, MUTED), _badge(372, 81, "A"),
              _text(402, 97, "to J: access control and security, listed under the diagram", 14, MUTED)]
    parts += [
        _box(20, 120, 230, 160, "Helpdesk tickets", ["Untrusted input from", "employees and vendors,",
                                                     "by web portal and email.", "Any line may be planted."]),
        _box(310, 120, 230, 160, "Worker agent", ["Claude Haiku 4.5 through", "the Anthropic API,", "temperature 0. Reaches",
                                                  "its tools only through", "the gateway."]),
        _box(600, 120, 270, 160, "MCP gateway", ["MCP server, streamable HTTP.", "Every call passes policy.enforce:",
                                                 "allow, hold or deny, by the", "policy stored in Atlas. Reading",
                                                 "a ticket taints the run."], fill=DEEP, stroke=ACCENT),
        f'<rect x="950" y="20" width="530" height="285" rx="10" fill="{SURFACE}" stroke="{HAIR}" stroke-width="1.5"/>',
        _text(964, 47, "Five MCP tools behind the gateway", 18, INK, 700),
        _box(962, 58, 247, 108, "Helpdesk", ["Reads one ticket. It is the", "taint source."], "read_ticket", RAISED),
        _box(1221, 58, 247, 108, "Shared memory", ["Writes from a tainted run", "are held for review."],
             "remember · recall", RAISED),
        _box(962, 180, 247, 108, "Web servers (mocked)", ["DNS resolvers, NTP, DoT /", "DoH / DoQ endpoint, DNSSEC."],
             "provision_server", RAISED),
        _box(1221, 180, 247, 108, "DNS records (mocked)", ["Route 53 A records in the", "corp.example zone."],
             "update_dns_record", RAISED),
        _box(950, 335, 530, 86, "Monitor (mocked health check)", [
            "Compares every server and record with the baseline document.",
            "Issue codes: resolvers, NTP, DNS transport, DNSSEC, ranges."]),
        _box(310, 465, 1170, 112, "MongoDB Atlas · the hackathon's sandbox cluster", [
            "Change streams wake the Evolver and the Guardian. Vector Search (autoEmbed, voyage-4) ranks memories for "
            "recall and review.",
            "An atomic findOneAndUpdate keeps each run's taint flag. A second database on the same cluster holds the "
            "20-ticket replay."],
            "policies · events · runs · memory_ledger · servers · dns_records · tickets · baseline"),
        _box(310, 640, 370, 150, "Evolver agent", ["Wakes when a check fails. Writes the next", "policy from ids, tool names "
                                                   "and counts,", "never ticket or memory text. It goes live",
                                                   "only if it is at least as strict and passes", "the eval on 32 recorded "
                                                   "traces."]),
        _box(710, 640, 370, 150, "Guardian agent", ["Wakes when a memory write is held.", "Compares it with trusted memory, "
                                                    "found", "through Vector Search, and records any",
                                                    "conflict with its reason."]),
        _box(1110, 640, 370, 150, "Console (Streamlit web app)", ["This page. Shows the policy, its diff and",
                                                                  "eval scores, the servers, the DNS records",
                                                                  "and the gateway feed. A person releases or",
                                                                  "purges each held write here."]),
        _box(20, 330, 230, 460, "Raindrop", ["Traces and signals, one", "conversation per demo:", "", "• worker_run per session",
                                             "• tool span per gateway", NB + "decision", "• policy_proposal per",
                                             NB + "Evolver attempt", "• memory_review per", NB + "Guardian verdict",
                                             "• signal with the issue", NB + "code on a failed check", "",
                                             "Switched on by one flag,", "RAINDROP_ENABLED."]),
    ]
    parts += [
        _arrow([(250, 200), (310, 200)]), _arrow([(540, 200), (600, 200)]),
        _arrow([(870, 200), (950, 200)], label="if allowed"),
        _arrow([(1215, 305), (1215, 335)], label="every result is checked"),
        _arrow([(1215, 421), (1215, 465)], "loop", "a check fails", 1),
        _arrow([(650, 280), (650, 465)], label="runs, events"),
        _arrow([(790, 465), (790, 280)], "loop", "active policy", 4),
        _arrow([(420, 577), (420, 640)], "loop", "wakes it", 2), _arrow([(540, 640), (540, 577)], "loop", "next policy", 3),
        _arrow([(820, 577), (820, 640)], label="held write"), _arrow([(940, 640), (940, 577)], label="verdict"),
        _arrow([(1220, 577), (1220, 640)], label="live data"), _arrow([(1340, 640), (1340, 577)], label="release / purge"),
        _arrow([(425, 280), (425, 400), (250, 400)], "trace"), _arrow([(620, 280), (620, 425), (250, 425)], "trace"),
        _arrow([(310, 715), (250, 715)], "trace"),
    ]
    parts += [_badge(x, y, letter) for letter, (x, y) in BADGES.items()]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="805" viewBox="0 0 1500 805" '
            f'font-family="{SANS}">{"".join(parts)}</svg>')


def render() -> None:
    st.markdown(heading("How the pieces fit"), unsafe_allow_html=True)
    st.image(diagram(), width="stretch", alt="Flow diagram: tickets, worker agent, MCP gateway, five tools, monitor, "
             "MongoDB Atlas, Evolver, Guardian, console and Raindrop. The tables below say the same in text.")
    controls = "".join(f'<div class="q-arow"><b>{escape(f"{letter} · {where}" if letter else where)}</b>'
                       f'<span class="tool">{escape(control)}</span><span>{escape(how)}</span></div>'
                       for letter, where, control, how in CONTROLS)
    st.markdown(heading("Where access control and security plug in") + f'<div class="q-card">{controls}</div>',
                unsafe_allow_html=True)
    rows = "".join(f'<div class="q-arow"><b>{escape(part)}</b><span class="tool">{escape(tool)}</span>'
                   f'<span>{escape(use)}</span></div>' for part, tool, use in PARTS)
    st.markdown(heading("What each tool does here") + f'<div class="q-card">{rows}</div>', unsafe_allow_html=True)
