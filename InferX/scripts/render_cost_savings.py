#!/usr/bin/env python3
import argparse
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render InferX cost savings from /v1/analytics/cost-savings.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("INFERX_BASE_URL", "http://localhost:8000"),
        help="InferX API base URL.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("INFERX_API_KEY", "inferx-premium-local"),
        help="API key used to read the authenticated usage scope.",
    )
    parser.add_argument(
        "--out",
        default="artifacts/cost-savings.html",
        help="HTML output file for screenshots.",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only include usage records created at or after this ISO-8601 timestamp.",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="Only include usage records created at or before this ISO-8601 timestamp.",
    )
    parser.add_argument(
        "--last-minutes",
        type=float,
        default=None,
        help="Only include usage records from the last N minutes.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Write an empty report instead of failing when no real usage records are found.",
    )
    args = parser.parse_args()

    if args.since and args.last_minutes is not None:
        parser.error("--since and --last-minutes cannot be used together")

    since = args.since
    if args.last_minutes is not None:
        since = isoformat_utc(datetime.now(UTC) - timedelta(minutes=args.last_minutes))

    data = fetch_cost_savings(args.base_url, args.api_key, since=since, until=args.until)
    if data["request_count"] == 0 and not args.allow_empty:
        raise SystemExit(
            "No real usage records matched this session window. "
            "Run authenticated /v1/generate requests first, or pass --allow-empty."
        )

    print_terminal_table(data)

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(data), encoding="utf-8")
    print(f"\nWrote {output}")


def fetch_cost_savings(
    base_url: str,
    api_key: str,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/v1/analytics/cost-savings"
    query = {
        key: value
        for key, value in {
            "since": since,
            "until": until,
        }.items()
        if value
    }
    if query:
        endpoint += "?" + urllib.parse.urlencode(query)

    request = urllib.request.Request(
        endpoint,
        method="GET",
        headers={
            "Accept": "application/json",
            "X-API-Key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Cost analytics request failed: HTTP {exc.code} {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach InferX at {endpoint}: {exc}") from exc


def print_terminal_table(data: dict[str, Any]) -> None:
    headers = [
        "Provider",
        "Model",
        "Tier",
        "Reqs",
        "Prompt",
        "Output",
        "Total",
        "Input $/1M",
        "Output $/1M",
        "Spend USD",
    ]
    rows = []
    for row in data["model_breakdown"]:
        rows.append(
            [
                row["provider"],
                row["model"],
                row["cache_tier"],
                str(row["request_count"]),
                str(row["prompt_tokens"]),
                str(row["completion_tokens"]),
                str(row["total_tokens"]),
                rate(row["input_price_per_million_tokens_usd"]),
                rate(row["output_price_per_million_tokens_usd"]),
                money(row["spend_usd"]),
            ]
        )

    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows)) if rows else len(header)
        for index, header in enumerate(headers)
    ]
    print(" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(value.ljust(widths[index]) for index, value in enumerate(row)))

    savings = data["savings_usd"]
    savings_percent = data["savings_percent"]
    savings_text = "unavailable"
    if savings is not None and savings_percent is not None:
        savings_text = f"{money(savings)} ({savings_percent:.2f}%)"

    print()
    print(f"Window:              {window_label(data)}")
    print(f"Actual spend:        {money(data['actual_spend_usd'])}")
    print(
        "Counterfactual spend: "
        f"{money(data['counterfactual_spend_usd'])} "
        f"if all requests used {data['counterfactual_provider']}/{data['counterfactual_model']}"
    )
    print(f"Savings:             {savings_text}")
    if not rows:
        print("No usage records found for this API key.")


def render_html(data: dict[str, Any]) -> str:
    actual = parse_decimal(data["actual_spend_usd"])
    counterfactual = parse_decimal(data["counterfactual_spend_usd"])
    max_spend = max(actual, counterfactual, Decimal("0.000000001"))
    actual_width = percent_width(actual, max_spend)
    counterfactual_width = percent_width(counterfactual, max_spend)
    savings = data["savings_usd"]
    savings_percent = data["savings_percent"]
    savings_text = "Unavailable: pricing incomplete"
    if savings is not None and savings_percent is not None:
        savings_text = f"{money(savings)} saved ({savings_percent:.2f}%)"

    model_rows = "\n".join(render_model_row(row) for row in data["model_breakdown"])
    if not model_rows:
        model_rows = '<tr><td colspan="10" class="empty">No usage records matched.</td></tr>'

    notes = "\n".join(f"<li>{escape(note)}</li>" for note in data["notes"])
    generated_at = escape(data["generated_at"])
    scope = escape(data["scope"])
    window = escape(window_label(data))
    counterfactual_label = escape(
        f"{data['counterfactual_provider']}/{data['counterfactual_model']}"
    )
    source_url = data["counterfactual_pricing_source_url"]
    source_link = ""
    if source_url:
        source_link = (
            f'<a href="{escape(source_url)}">{escape(data["counterfactual_pricing_source"])}</a>'
        )
    font_stack = (
        'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    )
    actual_spend = money(data["actual_spend_usd"])
    counterfactual_spend = money(data["counterfactual_spend_usd"])
    counterfactual_rates = escape(
        f"{rate(data['counterfactual_input_price_per_million_tokens_usd'])} input / "
        f"{rate(data['counterfactual_output_price_per_million_tokens_usd'])} output"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InferX Cost Savings</title>
  <style>
    body {{
      margin: 0;
      background: #0b1020;
      color: #e5e7eb;
      font-family: {font_stack};
    }}
    .card {{
      width: min(1040px, calc(100vw - 48px));
      margin: 32px auto;
      background: #111827;
      border: 1px solid #263244;
      border-radius: 24px;
      box-shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
      overflow: hidden;
    }}
    .hero {{
      padding: 28px 32px;
      border-bottom: 1px solid #263244;
      background: linear-gradient(135deg, rgba(59,130,246,0.18), rgba(16,185,129,0.10));
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 32px;
      letter-spacing: -0.04em;
    }}
    .meta {{
      color: #94a3b8;
      font-size: 14px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
      padding: 24px 32px;
    }}
    .metric {{
      background: #0f172a;
      border: 1px solid #263244;
      border-radius: 16px;
      padding: 16px;
    }}
    .label {{
      color: #94a3b8;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .value {{
      margin-top: 8px;
      font-size: 22px;
      font-weight: 700;
    }}
    .section {{
      padding: 0 32px 28px;
    }}
    .bars {{
      display: grid;
      gap: 14px;
      background: #0f172a;
      border: 1px solid #263244;
      border-radius: 18px;
      padding: 18px;
    }}
    .bar-label {{
      display: flex;
      justify-content: space-between;
      color: #cbd5e1;
      margin-bottom: 6px;
      font-size: 14px;
    }}
    .track {{
      height: 18px;
      background: #1f2937;
      border-radius: 999px;
      overflow: hidden;
    }}
    .fill {{
      height: 100%;
      border-radius: 999px;
    }}
    .actual {{ background: #10b981; width: {actual_width}%; }}
    .counterfactual {{ background: #f97316; width: {counterfactual_width}%; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #0f172a;
      border: 1px solid #263244;
      border-radius: 18px;
      overflow: hidden;
    }}
    th, td {{
      padding: 13px 14px;
      text-align: left;
      border-bottom: 1px solid #1f2937;
      font-size: 14px;
    }}
    .nowrap {{ white-space: nowrap; }}
    th {{
      color: #94a3b8;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    tr:last-child td {{ border-bottom: none; }}
    .empty {{ color: #94a3b8; text-align: center; }}
    .notes {{
      color: #94a3b8;
      font-size: 13px;
      line-height: 1.6;
    }}
    a {{ color: #93c5fd; }}
  </style>
</head>
<body>
  <main class="card">
    <section class="hero">
      <h1>InferX Cost Savings</h1>
      <div class="meta">Scope: {scope} · Window: {window} · Generated: {generated_at}</div>
    </section>
    <section class="grid">
      <div class="metric">
        <div class="label">Actual Spend</div>
        <div class="value">{actual_spend}</div>
      </div>
      <div class="metric">
        <div class="label">Counterfactual</div>
        <div class="value">{counterfactual_spend}</div>
      </div>
      <div class="metric">
        <div class="label">Savings</div>
        <div class="value">{escape(savings_text)}</div>
      </div>
      <div class="metric">
        <div class="label">Requests / Cache Hits</div>
        <div class="value">{data["request_count"]} / {data["cache_hit_count"]}</div>
      </div>
    </section>
    <section class="section">
      <div class="bars">
        <div>
          <div class="bar-label"><span>Actual InferX spend</span><span>{actual_spend}</span></div>
          <div class="track"><div class="fill actual"></div></div>
        </div>
        <div>
          <div class="bar-label">
            <span>All requests on {counterfactual_label}</span>
            <span>{counterfactual_spend}</span>
          </div>
          <div class="track"><div class="fill counterfactual"></div></div>
        </div>
      </div>
    </section>
    <section class="section">
      <table>
        <thead>
          <tr>
            <th>Provider</th>
            <th>Model</th>
            <th>Tier</th>
            <th>Requests</th>
            <th>Prompt</th>
            <th>Output</th>
            <th>Total</th>
            <th>Input $/1M</th>
            <th>Output $/1M</th>
            <th>Spend</th>
          </tr>
        </thead>
        <tbody>
          {model_rows}
        </tbody>
      </table>
    </section>
    <section class="section notes">
      <p>Counterfactual source: {source_link} · Rates: {counterfactual_rates}</p>
      <ul>{notes}</ul>
    </section>
  </main>
</body>
</html>
"""


def render_model_row(row: dict[str, Any]) -> str:
    return f"""<tr>
  <td>{escape(row["provider"])}</td>
  <td>{escape(row["model"])}</td>
  <td>{escape(row["cache_tier"])}</td>
  <td>{row["request_count"]}</td>
  <td>{row["prompt_tokens"]}</td>
  <td>{row["completion_tokens"]}</td>
  <td>{row["total_tokens"]}</td>
  <td class="nowrap">{rate(row["input_price_per_million_tokens_usd"])}</td>
  <td class="nowrap">{rate(row["output_price_per_million_tokens_usd"])}</td>
  <td class="nowrap">{money(row["spend_usd"])}</td>
</tr>"""


def parse_decimal(value: str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(value)


def percent_width(value: Decimal, maximum: Decimal) -> str:
    width = (value / maximum) * Decimal("100")
    return f"{width.quantize(Decimal('0.1'))}"


def money(value: str | None) -> str:
    return f"${parse_decimal(value):,.9f}"


def rate(value: str | None) -> str:
    if value is None:
        return "unpriced"
    formatted = f"{parse_decimal(value):,.6f}".rstrip("0").rstrip(".")
    return f"${formatted}/1M"


def window_label(data: dict[str, Any]) -> str:
    start = data.get("window_start")
    end = data.get("window_end")
    if start is None and end is None:
        return "all logged records"
    return f"{start or 'beginning'} to {end or 'now'}"


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


if __name__ == "__main__":
    main()
