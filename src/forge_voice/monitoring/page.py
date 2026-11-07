"""Server-rendered dashboard, call detail and weekly review pages."""

from __future__ import annotations

import html
import json
from datetime import datetime
from urllib.parse import quote

from forge_voice.events.models import CallRecord, DashboardToolEvent
from forge_voice.monitoring.alerts import Alert
from forge_voice.monitoring.filters import CallFilters
from forge_voice.policy.state import CallIntent, CallOutcome

OUTCOME_LABELS = {
    "booked": "Booked",
    "rescheduled": "Rescheduled",
    "cancelled": "Cancelled",
    "emergency_ticket": "Emergency ticket",
    "transferred": "Transferred",
    "callback": "Callback",
    "info_only": "Info only",
    "abandoned": "Abandoned",
    "failed": "Failed",
}


def render_dashboard_page(
    *,
    metrics: dict[str, object],
    records: list[CallRecord],
    filters: CallFilters,
    alerts: list[Alert],
    tenant_names: dict[str, str],
    profile: str,
    htmx: bool = True,
) -> str:
    body = render_dashboard_body(
        metrics=metrics,
        records=records,
        filters=filters,
        alerts=alerts,
        tenant_names=tenant_names,
        profile=profile,
        interactive=htmx,
    )
    return _document(
        "Forge Voice monitoring",
        body,
        htmx=htmx,
    )


def render_dashboard_body(
    *,
    metrics: dict[str, object],
    records: list[CallRecord],
    filters: CallFilters,
    alerts: list[Alert],
    tenant_names: dict[str, str],
    profile: str,
    interactive: bool = True,
) -> str:
    values = metrics["metrics"]
    calls = values["calls"]
    latency = values["latency"]
    cost = values["cost"]
    form_attrs = (
        ' hx-get="/dashboard" hx-target="#dashboard-live" hx-select="#dashboard-live"'
        ' hx-swap="outerHTML" hx-push-url="true" hx-trigger="change"'
        if interactive
        else ""
    )
    tenant_options = "".join(
        _option(tenant_id, name, filters.tenant == tenant_id)
        for tenant_id, name in sorted(tenant_names.items())
    )
    outcome_options = "".join(
        _option(outcome.value, OUTCOME_LABELS[outcome.value], filters.outcome is outcome)
        for outcome in CallOutcome
    )
    from_value = _e(filters.from_date.isoformat() if filters.from_date else "")
    to_value = _e(filters.to_date.isoformat() if filters.to_date else "")
    cards = "".join(
        [
            _card("Total calls", str(calls["total"]), f"{profile} profile · last 30 days"),
            _card(
                "Containment",
                _percent(values["containment"]),
                _fraction(values["containment"]),
            ),
            _card(
                "Transfer rate",
                _percent(values["transfer_rate"]),
                _fraction(values["transfer_rate"]),
            ),
            _card(
                "Booking rate",
                _percent(values["booking_rate"]),
                _fraction(values["booking_rate"]),
            ),
            _card(
                "Slot error rate",
                _percent(values["slot_error_rate"]),
                _fraction(values["slot_error_rate"]),
            ),
            _card(
                "p95 first audio",
                f"{round(latency['p95_ms']):,} ms",
                f"p50 {round(latency['p50_ms']):,} ms · {latency['samples']} turns",
            ),
            _card(
                "Tool error rate",
                _percent(values["tool_error_rate"]),
                _fraction(values["tool_error_rate"]),
            ),
            _card(
                "Emergency triage",
                _percent(values["emergency_triage_rate"]),
                _fraction(values["emergency_triage_rate"]),
            ),
            _card(
                "Cost per call",
                f"${cost['per_call_usd']:.4f}",
                f"${cost['total_usd']:.4f} total · demo $0",
            ),
        ]
    )
    rows = "".join(_call_row(record, tenant_names) for record in records)
    if not rows:
        rows = '<tr><td colspan="10" class="empty">No calls match these filters.</td></tr>'
    refresh_alerts = (
        '<form class="alert-refresh" method="post" action="/alerts/refresh">'
        '<button type="submit">Evaluate alerts</button></form>'
        if interactive
        else ""
    )
    return f"""
<div id="dashboard-live">
  {_alert_banner(alerts)}
  {refresh_alerts}
  <form class="filters" method="get" action="/dashboard"{form_attrs}>
    <label>Tenant
      <select name="tenant">
        <option value="">All tenants</option>
        {tenant_options}
      </select>
    </label>
    <label>From
      <input type="date" name="from" value="{from_value}">
    </label>
    <label>To
      <input type="date" name="to" value="{to_value}">
    </label>
    <label>Outcome
      <select name="outcome">
        <option value="">All outcomes</option>
        {outcome_options}
      </select>
    </label>
    <button type="submit">Apply filters</button>
    <a class="reset" href="/dashboard">Reset</a>
  </form>
  <section class="cards" aria-label="Aggregate metrics">{cards}</section>
  <section class="panel">
    <div class="panel-head">
      <h2>Recent calls</h2>
      <span class="muted">{len(records)} shown · newest first</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Started</th><th>Tenant</th><th>Caller</th><th>Call</th><th>Outcome</th>
            <th>Transfer</th><th>Booking / ticket</th><th>p95 first audio</th>
            <th>Cost</th><th>QA flags</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </section>
  <p class="footnote">
    Synthetic data only. Retention is 30 days; recording opt-out is respected.
    Machine-readable aggregate: <a href="/metrics.json">/metrics.json</a>.
    Metrics use the #26 definitions (containment, transfer, booking, slot error, p50/p95,
    tool error, cost, emergency triage).
  </p>
</div>
"""


def render_call_detail_page(
    *,
    record: CallRecord,
    tenant_name: str,
    back_link: str = "/dashboard",
) -> str:
    body = render_call_detail_body(record=record, tenant_name=tenant_name, back_link=back_link)
    return _document(f"Call {record.call_id}", f"<main>{body}</main>", htmx=False)


def render_call_detail_body(
    *,
    record: CallRecord,
    tenant_name: str,
    back_link: str = "/dashboard",
) -> str:
    transcript = _transcript_excerpt(record)
    tools = "".join(_tool_item(event) for event in record.tool_events)
    if not tools:
        tools = '<p class="muted">No tool calls were recorded.</p>'
    qa = (
        "".join(
            f'<span class="chip {"warn" if flag in {"tool_timeout", "handoff_no_answer"} else ""}">'
            f"{_e(flag)}</span>"
            for flag in record.qa_flags
        )
        or '<span class="muted">None recorded.</span>'
    )
    booking = record.booking_id or "—"
    ticket = record.ticket_id or "—"
    caller = record.caller_phone or "—"
    recording = (
        '<p class="callout amber"><strong>Recording opt-out.</strong> '
        "No audio was retained for this call; the transcript is text-only.</p>"
        if record.recording_opt_out
        else f'<p class="muted">Recording reference: <code>{_e(record.recording_ref)}</code></p>'
    )
    transfer = record.transfer_status.value if record.transfer_status else "—"
    waterfall = _waterfall(record)
    back = f'<a class="back" href="{_e(back_link)}">← Back to dashboard</a>' if back_link else ""
    outcome_label = OUTCOME_LABELS[record.outcome.value]
    intent_label = record.intent.value.replace("_", " ") if record.intent else "—"
    recording_label = "Opted out" if record.recording_opt_out else "Text only"
    slot_label = "Error" if record.slot_error else ("OK" if record.slot_checked else "Not checked")
    emergency_panel = (
        f"""
  <section class="panel">
    <h2>Emergency triage</h2>
    <p>Category: <strong>{_e(record.emergency_category or "—")}</strong> ·
    triage {"passed" if record.emergency_triage_ok else "failed"}</p>
    <p class="muted">{_e(record.emergency_safety_script or "No safety script recorded.")}</p>
  </section>
"""
        if record.intent is CallIntent.emergency
        else ""
    )
    return f"""
<div class="detail">
  {back}
  <header class="detail-head">
    <div>
      <h1>{_e(record.call_id)}</h1>
      <p class="sub">{_e(tenant_name)} · {_e(record.profile)} profile ·
        started {_e(_time(record.started_at))} · {record.duration_seconds}s</p>
    </div>
    <span class="badge {_outcome_class(record.outcome)}">{_e(outcome_label)}</span>
  </header>

  <section class="cards">
    {_card("Caller", caller, "synthetic callback number")}
    {_card("Intent", intent_label, "classified intent")}
    {_card("Transfer", transfer, "human handoff status")}
    {_card("Booking ID", booking, "committed write")}
    {_card("Ticket ID", ticket, "emergency or support")}
    {_card("Slot check", slot_label, "service / address / slot audit")}
    {_card("Cost", f"${record.cost_usd:.4f}", "synthetic / demo")}
    {_card("Recording", recording_label, "no audio player")}
  </section>

  {recording}
  {emergency_panel}

  <section class="panel">
    <h2>QA flags</h2>
    <div class="chips">{qa}</div>
  </section>

  <section class="panel">
    <h2>Transcript excerpt</h2>
    <div class="transcript">{transcript}</div>
  </section>

  <section class="panel">
    <h2>Tool timeline</h2>
    <ol class="timeline">{tools}</ol>
  </section>

  <section class="panel">
    <h2>Latency waterfall</h2>
    {waterfall}
  </section>
</div>
"""


def render_review_page(
    *,
    records: list[CallRecord],
    marked: dict[str, dict[str, str]],
    candidates: list[str],
    tenant_names: dict[str, str],
) -> str:
    rows = []
    for record in records:
        tenant = tenant_names.get(record.tenant_id, record.tenant_id)
        first_line = next(
            (turn.text for turn in record.transcript if turn.role == "caller"),
            "—",
        )
        reviewed = record.call_id in marked
        mark = (
            '<span class="chip">Reviewed</span>'
            if reviewed
            else f'<form method="post" action="/review/mark?call_id={quote(record.call_id)}">'
            '<button type="submit">Mark reviewed</button></form>'
        )
        rows.append(
            f"<tr><td>{_e(_time(record.started_at))}</td>"
            f"<td>{_e(tenant)}</td>"
            f'<td><a href="/calls/{quote(record.call_id)}">{_e(record.call_id)}</a></td>'
            f"<td>{_e(OUTCOME_LABELS[record.outcome.value])}</td>"
            f'<td class="excerpt">{_e(first_line)}</td>'
            f"<td>{mark}</td>"
            f'<td><form method="post" action="/review/candidate?call_id={quote(record.call_id)}">'
            '<button type="submit">Create scenario candidate</button></form></td></tr>'
        )
    if not rows:
        rows.append('<tr><td colspan="7" class="empty">No calls in the review window.</td></tr>')
    candidate_list = "".join(f"<li><code>{_e(name)}</code></li>" for name in candidates)
    candidate_list = candidate_list or '<li class="muted">None yet.</li>'
    body = f"""
<main>
  <a class="back" href="/dashboard">← Back to dashboard</a>
  <h1>Weekly review</h1>
  <p class="sub">Ten-call sample from the last seven days. Mark failures, turn one into a
  scenario candidate, then run the smoke suite.</p>
  <section class="panel">
    <div class="table-wrap">
      <table>
        <thead><tr><th>Started</th><th>Tenant</th><th>Call</th><th>Outcome</th>
        <th>First caller line</th><th>Review</th><th>Scenario</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
  </section>
  <section class="panel">
    <h2>Run the smoke suite</h2>
    <p>After reviewing the sample and editing any candidate under
    <code>data/monitoring/scenario_candidates/</code>:</p>
    <pre><code>make eval-smoke</code></pre>
    <p class="muted">The web page does not launch the suite from a request. The review
    script can:</p>
    <pre><code>python -m forge_voice.monitoring.review --call-id CALL_ID --run-smoke</code></pre>
  </section>
  <section class="panel">
    <h2>Scenario candidates</h2>
    <ul>{candidate_list}</ul>
    <p class="muted">Candidates are drafts; review the transcript and expected state before
    adding one to the scenario manifest.</p>
  </section>
</main>
"""
    return _document("Forge Voice weekly review", body, htmx=False)


def render_static_export(
    *,
    dashboard_body: str,
    call_body: str,
    generated_at: datetime,
) -> str:
    body = f"""
<main>
  <h1>Static dashboard export</h1>
  <p class="sub">Sample synthetic run for handover · generated
  {_e(generated_at.isoformat())} · no credentials, no live services.</p>
  {dashboard_body}
  <hr>
  <h1>Sample call detail</h1>
  {call_body}
</main>
"""
    return _document("Forge Voice static dashboard export", body, htmx=False)


def _alert_banner(alerts: list[Alert]) -> str:
    if not alerts:
        return (
            '<section class="banner ok"><strong>No active alerts.</strong> '
            "All monitored thresholds are inside the active profile budget.</section>"
        )
    items = "".join(
        f'<li><span class="badge {alert.severity}">{_e(alert.severity)}</span> '
        f"<strong>{_e(alert.title)}</strong> — {_e(alert.message)}</li>"
        for alert in alerts
    )
    return (
        f'<section class="banner alert"><strong>{len(alerts)} active alert'
        f"{'s' if len(alerts) != 1 else ''}</strong>"
        f"<ul>{items}</ul></section>"
    )


def _call_row(record: CallRecord, tenant_names: dict[str, str]) -> str:
    booking = record.booking_id or record.ticket_id or "—"
    latency = record.first_audio_p95_ms
    latency_text = f"{latency:,} ms" if latency is not None else "not measured"
    flags = ", ".join(record.qa_flags) if record.qa_flags else "—"
    transfer = record.transfer_status.value if record.transfer_status else "—"
    return (
        "<tr>"
        f"<td>{_e(_time(record.started_at))}</td>"
        f"<td>{_e(tenant_names.get(record.tenant_id, record.tenant_id))}</td>"
        f"<td>{_e(record.caller_phone or '—')}</td>"
        f'<td><a href="/calls/{quote(record.call_id)}">{_e(record.call_id)}</a></td>'
        f'<td><span class="badge {_outcome_class(record.outcome)}">'
        f"{_e(OUTCOME_LABELS[record.outcome.value])}</span></td>"
        f"<td>{_e(transfer)}</td>"
        f"<td>{_e(booking)}</td>"
        f"<td>{_e(latency_text)}</td>"
        f"<td>${record.cost_usd:.4f}</td>"
        f'<td class="flags">{_e(flags)}</td>'
        "</tr>"
    )


def _transcript_excerpt(record: CallRecord) -> str:
    turns = record.transcript
    shown = [*turns[:8], None, *turns[-5:]] if len(turns) > 14 else turns
    if not shown:
        return '<p class="muted">Transcript not available.</p>'
    lines = []
    for turn in shown:
        if turn is None:
            lines.append(f'<p class="muted">… {len(turns) - 13} turns omitted …</p>')
            continue
        role = "caller" if turn.role == "caller" else "agent"
        lines.append(f'<p class="{role}"><strong>{_e(turn.role)}</strong>: {_e(turn.text)}</p>')
    return "".join(lines)


def _tool_item(event: DashboardToolEvent) -> str:
    status = "ok" if event.ok else f"error {event.error_code or ''}".strip()
    args = json.dumps(event.args, sort_keys=True, default=str)
    if len(args) > 240:
        args = args[:237] + "…"
    return (
        f'<li><span class="tool-name">{_e(event.name)}</span> '
        f'<span class="badge {"ok" if event.ok else "critical"}">{_e(status)}</span> '
        f'<span class="muted">{event.latency_ms} ms · {_e(_time(event.at))}</span>'
        f'<pre class="args">{_e(args)}</pre></li>'
    )


def _waterfall(record: CallRecord) -> str:
    if not record.turn_latencies:
        return (
            '<p class="muted">No measured first-audio stages for this trace. '
            "The live trace records tool calls and outcomes, not caller-perceived audio timing.</p>"
        )
    turn = max(record.turn_latencies, key=lambda item: item.total_ms)
    total = max(turn.total_ms, 1)
    stages = [
        ("STT / endpointing", turn.stt_endpointing_ms, "stt"),
        ("LLM TTFT", turn.llm_ttft_ms, "llm"),
        ("Tool", turn.tool_ms, "tool"),
        ("TTS TTFB", turn.tts_ttfb_ms, "tts"),
    ]
    rows = "".join(
        f'<div class="wf-row"><span class="wf-label">{_e(label)}</span>'
        f'<div class="wf-track"><div class="wf-bar {css}" style="width:'
        f'{max(1, round(100 * value / total))}%"></div></div>'
        f'<span class="wf-value">{value:,} ms</span></div>'
        for label, value, css in stages
    )
    totals = ", ".join(
        f"{index + 1}: {item.total_ms:,} ms" for index, item in enumerate(record.turn_latencies)
    )
    return f"""
    <p class="muted">Slowest measured turn. Caller-perceived first audio is the sum of the
    four stages.</p>
    <div class="waterfall">{rows}</div>
    <p class="total">First audio: <strong>{turn.total_ms:,} ms</strong></p>
    <p class="muted">Turn totals: {_e(totals)}</p>
"""


def _card(label: str, value: str, note: str) -> str:
    return (
        f'<div class="card"><span class="card-label">{_e(label)}</span>'
        f'<strong class="card-value">{_e(value)}</strong>'
        f'<span class="card-note">{_e(note)}</span></div>'
    )


def _option(value: str, label: str, selected: bool) -> str:
    mark = " selected" if selected else ""
    return f'<option value="{_e(value)}"{mark}>{_e(label)}</option>'


def _percent(metric: dict[str, object]) -> str:
    return f"{metric['percent']:.1f}%"


def _fraction(metric: dict[str, object]) -> str:
    return f"{metric['numerator']} / {metric['denominator']}"


def _outcome_class(outcome: CallOutcome) -> str:
    if outcome in {CallOutcome.booked, CallOutcome.rescheduled, CallOutcome.cancelled}:
        return "ok"
    if outcome in {CallOutcome.failed, CallOutcome.emergency_ticket}:
        return "critical"
    return "neutral"


def _time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _document(title: str, body: str, *, htmx: bool) -> str:
    script = '<script src="/static/htmx.min.js"></script>' if htmx else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(title)}</title>
  <link rel="icon" href="data:,">
  {script}
  <style>{_STYLE}</style>
</head>
<body>
<header class="site-head">
  <a class="brand" href="/dashboard">Forge Voice monitoring</a>
  <nav><a href="/dashboard">Dashboard</a><a href="/review">Weekly review</a>
  <a href="/metrics.json">metrics.json</a><a href="/">Browser demo</a></nav>
</header>
{body}
<footer class="site-foot">Local-only, read-only, synthetic data · 30-day retention ·
recording opt-out respected · no public exposure</footer>
</body>
</html>
"""


_STYLE = """
:root { color-scheme: light dark; font-family: system-ui, -apple-system, Segoe UI, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; line-height: 1.5; background: Canvas; color: CanvasText; }
a { color: #2f7ed8; }
.site-head { display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline;
  justify-content: space-between; padding: 18px 28px; border-bottom: 1px solid #8884; }
.site-head .brand { font-weight: 700; font-size: 1.1rem; text-decoration: none; color: inherit; }
.site-head nav { display: flex; flex-wrap: wrap; gap: 16px; font-size: .94rem; }
main, #dashboard-live { display: block; max-width: 1180px; margin: 0 auto; padding: 0 28px; }
main { padding-bottom: 24px; }
h1 { margin: 22px 0 4px; font-size: 1.7rem; }
h2 { font-size: 1.05rem; margin: 0 0 12px; }
.sub { margin: 0 0 16px; color: #777; }
.filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; margin: 20px 0;
  padding: 14px 16px; border: 1px solid #8884; border-radius: 12px; }
.filters label { display: grid; gap: 4px; font-size: .82rem; font-weight: 600; }
.filters select, .filters input, .filters button { padding: 8px 10px; font: inherit;
  border-radius: 7px; border: 1px solid #8886; background: Canvas; color: CanvasText; }
.filters button, button { cursor: pointer; padding: 8px 12px; font: inherit; border-radius: 7px;
  border: 1px solid #8886; background: #2f7ed8; color: white; }
.filters .reset { align-self: center; font-size: .9rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px; margin: 14px 0 20px; }
.card { border: 1px solid #8884; border-radius: 12px; padding: 12px 14px;
  display: grid; gap: 2px; }
.card-label { font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; color: #777; }
.card-value { font-size: 1.35rem; }
.card-note { font-size: .78rem; color: #777; }
.banner { margin-top: 18px; padding: 12px 16px; border-radius: 12px; border: 1px solid; }
.banner.ok { border-color: #2c9a5e66; background: #2c9a5e12; }
.banner.alert { border-color: #d6454566; background: #d6454512; }
.banner ul { margin: 8px 0 0; padding-left: 20px; }
.panel { border: 1px solid #8884; border-radius: 12px; padding: 16px; margin: 16px 0; }
.panel-head { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .88rem; }
th, td { text-align: left; padding: 8px 9px; border-bottom: 1px solid #8883; vertical-align: top; }
th { font-size: .75rem; text-transform: uppercase; letter-spacing: .03em; color: #777; }
td.flags { max-width: 230px; }
.muted { color: #777; }
.footnote { font-size: .82rem; color: #777; margin: 18px 0 28px; }
.badge { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: .74rem;
  font-weight: 700; background: #8882; }
.badge.ok, .badge.success { background: #2c9a5e22; color: #237a4a; }
.badge.critical, .badge.error { background: #d6454522; color: #b52f2f; }
.badge.warning { background: #d99a1e22; color: #8a5c00; }
.badge.neutral { background: #8882; }
.chip { display: inline-block; margin: 2px 4px 2px 0; padding: 2px 8px; border-radius: 999px;
  background: #8882; font-size: .8rem; }
.chip.warn { background: #d99a1e22; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.detail-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.back { display: inline-block; margin-top: 18px; font-size: .9rem; text-decoration: none; }
.transcript { max-height: 430px; overflow-y: auto; padding-right: 8px; }
.transcript p { margin: 6px 0; }
.transcript .caller strong { color: #2f7ed8; }
.transcript .agent strong { color: #2c9a5e; }
.timeline { margin: 0; padding-left: 22px; }
.timeline li { margin: 10px 0; }
.tool-name { font-weight: 700; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
pre.args { margin: 4px 0; white-space: pre-wrap; word-break: break-word; font-size: .78rem;
  color: #666; }
pre { background: #8881; padding: 10px 12px; border-radius: 8px; overflow-x: auto; }
.waterfall { display: grid; gap: 8px; margin: 14px 0; }
.wf-row { display: grid; grid-template-columns: 150px 1fr 90px; gap: 10px; align-items: center;
  font-size: .86rem; }
.wf-label { color: #666; }
.wf-track { height: 16px; background: #8881; border-radius: 999px; overflow: hidden; }
.wf-bar { height: 100%; }
.wf-bar.stt { background: #2f7ed8; }
.wf-bar.llm { background: #7d5bd6; }
.wf-bar.tool { background: #d99a1e; }
.wf-bar.tts { background: #2c9a5e; }
.wf-value { text-align: right; font-variant-numeric: tabular-nums; }
.total { margin: 10px 0 2px; }
.callout { padding: 10px 12px; border-radius: 10px; border: 1px solid #8884; }
.callout.amber { background: #d99a1e12; border-color: #d99a1e66; }
.excerpt { max-width: 320px; }
.empty { text-align: center; color: #777; padding: 22px; }
.site-foot { padding: 20px 28px; border-top: 1px solid #8884; color: #777; font-size: .8rem; }
form { margin: 0; }
td form button { padding: 4px 8px; font-size: .78rem; }
@media (max-width: 640px) {
  main, #dashboard-live { padding: 0 14px; }
  .site-head { padding: 14px; }
  .wf-row { grid-template-columns: 110px 1fr 80px; }
  .detail-head { display: block; }
}
"""
