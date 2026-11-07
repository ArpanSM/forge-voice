"""Static handover export of the dashboard sample.

The export is one self-contained HTML file: no CDN, no htmx, no scripts, no secrets.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from forge_voice.monitoring.alerts import evaluate_alerts
from forge_voice.monitoring.atomic import atomic_write_text
from forge_voice.monitoring.filters import CallFilters
from forge_voice.monitoring.metrics import aggregate_metrics
from forge_voice.monitoring.page import (
    render_call_detail_body,
    render_dashboard_body,
    render_static_export,
)
from forge_voice.monitoring.service import MonitoringService


def export_dashboard(
    service: MonitoringService,
    output: Path | str,
    *,
    generated_at: datetime | None = None,
) -> Path:
    records = [record for record in service.calls() if record.synthetic]
    if not records:
        raise ValueError("no synthetic calls available to export")
    metrics = {"metrics": aggregate_metrics(records)}
    generated = generated_at or datetime.now(UTC)
    alerts = evaluate_alerts(records, profile=service.profile, now=generated)
    dashboard = render_dashboard_body(
        metrics=metrics,
        records=records,
        filters=CallFilters(),
        alerts=alerts,
        tenant_names=service.tenant_options(),
        profile=service.profile,
        interactive=False,
    )
    sample = next(
        (record for record in records if record.booking_id or record.ticket_id),
        records[0],
    )
    detail = render_call_detail_body(
        record=sample,
        tenant_name=service.tenant_name(sample.tenant_id),
        back_link="",
    )
    html = render_static_export(
        dashboard_body=dashboard,
        call_body=detail,
        generated_at=generated,
    )
    html = "\n".join(line.rstrip() for line in html.splitlines()) + "\n"
    return atomic_write_text(output, html)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export a static dashboard sample")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--profile", choices=("local", "hybrid"), default="local")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/samples/dashboard-sample.html"),
    )
    parser.add_argument("--now", help="ISO seed/export timestamp for a reproducible sample")
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else None
    service = MonitoringService(
        data_dir=args.data_dir,
        root=args.root,
        profile=args.profile,
        now=(lambda: now) if now else None,
    )
    path = export_dashboard(service, args.output, generated_at=now)
    print(f"exported {len(service.calls())} calls to {path}")


if __name__ == "__main__":
    main()
