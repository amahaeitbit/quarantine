"""Look and feel of the console: colour roles, CSS, and small HTML builders.

Status is always an icon plus a label, never colour alone. All dynamic text is escaped,
because memory and ticket text is untrusted content.
"""
from html import escape

CSS = """<style>
:root { --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a;
  --hair:rgba(255,255,255,.10); --accent:#3987e5; --track:#16335c;
  --good:#0ca30c; --warn:#fab219; --crit:#d03b3b; }
.block-container { padding-top: 2.2rem; max-width: 1500px; }
.q-head { display:flex; justify-content:space-between; align-items:flex-end; gap:32px; margin-bottom:18px; }
.q-title { font-size:40px; font-weight:700; line-height:1.1; color:var(--ink); }
.q-tag { color:var(--ink2); font-size:16px; max-width:640px; margin-top:6px; }
.q-hero { text-align:right; }
.q-hero .num { font-size:56px; font-weight:650; line-height:1; color:var(--ink); white-space:nowrap; }
.q-hero .cap { color:var(--ink2); font-size:13.5px; margin-top:6px; }
.q-card, .q-tile, .q-step { background:var(--surface); border:1px solid var(--hair); border-radius:12px; }
.q-card { padding:16px 18px; margin-bottom:12px; }
.q-h { font-size:20px; font-weight:650; color:var(--ink); margin:22px 0 10px; }
.q-tiles { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.q-tile { padding:14px 18px; }
.q-tile .label, .q-k { color:var(--ink2); font-size:13px; }
.q-tile .value { font-size:30px; font-weight:600; color:var(--ink); line-height:1.25; }
.q-tile .sub, .q-dim { color:var(--muted); font-size:13px; }
.q-steps { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; margin-top:12px; }
.q-step { padding:12px 14px; border-top:3px solid var(--grid); }
.q-step.good { border-top-color:var(--good); } .q-step.warn { border-top-color:var(--warn); }
.q-step.crit { border-top-color:var(--crit); } .q-step.run { border-top-color:var(--accent); }
.q-step .n { color:var(--muted); font-size:12px; letter-spacing:.04em; }
.q-step .t { color:var(--ink); font-weight:600; font-size:15px; margin:2px 0 8px; }
.q-step .d { color:var(--ink2); font-size:13px; margin-top:8px; min-height:36px; }
.q-badge { display:inline-flex; align-items:center; gap:6px; padding:1px 10px 1px 8px; border-radius:999px;
  border:1px solid var(--hair); background:rgba(255,255,255,.05); color:var(--ink); font-size:12.5px; white-space:nowrap; }
.q-badge b { font-weight:700; } .q-badge.good b { color:var(--good); } .q-badge.warn b { color:var(--warn); }
.q-badge.crit b { color:var(--crit); } .q-badge.info b, .q-badge.run b { color:var(--accent); }
.q-chip { display:inline-block; padding:1px 9px; border-radius:6px; background:rgba(57,135,229,.16); color:var(--ink);
  font-size:12.5px; font-family:ui-monospace,Menlo,monospace; margin:0 4px 4px 0; }
.q-chip.bad { background:rgba(208,59,59,.22); }
.q-rule { display:grid; grid-template-columns:150px 1fr auto; gap:10px; align-items:center; padding:6px 0;
  border-top:1px solid var(--grid); font-size:13.5px; color:var(--ink); }
.q-rule.dim { color:var(--muted); } .q-mono { font-family:ui-monospace,Menlo,monospace; }
.q-quote { border-left:3px solid var(--accent); padding:2px 0 2px 12px; color:var(--ink2); font-size:13.5px; margin-top:12px; }
.q-meter { height:10px; background:var(--track); border-radius:4px; overflow:hidden; }
.q-meter span { display:block; height:100%; background:var(--accent); border-radius:0 4px 4px 0; }
.q-mrow { display:grid; grid-template-columns:34px 1fr 190px; gap:12px; align-items:center; margin:8px 0; color:var(--ink2); font-size:13px; }
.q-feed { max-height:430px; overflow:auto; padding:4px 18px; }
.q-ev { display:grid; grid-template-columns:70px 1fr auto; gap:12px; align-items:center; padding:7px 0;
  border-top:1px solid var(--grid); font-size:13.5px; color:var(--ink); }
.q-ev:first-child, .q-rule:first-of-type { border-top:none; }
.q-warnbox { border:1px solid rgba(208,59,59,.55); background:rgba(208,59,59,.10); border-radius:8px; padding:8px 10px;
  color:var(--ink); font-size:13px; margin-top:8px; }
</style>"""

ICON = {"good": "✓", "warn": "!", "crit": "✕", "info": "•", "run": "…"}
DECISION_ROLE = {"allow": "good", "hold": "warn", "deny": "crit", "pass": "good", "fail": "crit"}


def badge(label: str, role: str = "info") -> str:
    return f'<span class="q-badge {role}"><b>{ICON[role]}</b>{escape(str(label))}</span>'


def decision(value: str) -> str:
    return badge(value, DECISION_ROLE.get(value, "info"))


def chip(text: str, bad: bool = False) -> str:
    return f'<span class="q-chip{" bad" if bad else ""}">{escape(str(text))}</span>'


def tile(label: str, value, sub: str = "") -> str:
    return (f'<div class="q-tile"><div class="label">{escape(label)}</div>'
            f'<div class="value">{escape(str(value))}</div><div class="sub">{escape(sub)}</div></div>')


def heading(text: str) -> str:
    return f'<div class="q-h">{escape(text)}</div>'


def meter_row(name: str, value: int, total: int, note: str) -> str:
    """One labelled meter. The value is written out beside it, and repeated as a hover title."""
    width = 100 * value / total if total else 0
    title = escape(f"{name}: {value} of {total}")
    return (f'<div class="q-mrow" title="{title}"><span class="q-mono">{escape(name)}</span>'
            f'<div class="q-meter"><span style="width:{width:.0f}%"></span></div><span>{note}</span></div>')
