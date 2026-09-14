"""Render a GitHub contribution activity graph as a self-hosted SVG.

Replaces github-readme-activity-graph.vercel.app, which returns
402 DEPLOYMENT_DISABLED. Data comes straight from the GitHub GraphQL API,
so the only thing the README depends on is this repository.
"""

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://api.github.com/graphql"

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

THEMES = {
    "activity-graph.svg": {
        "bg": "#ffffff",
        "grid": "#e2e8f0",
        "axis": "#64748b",
        "title": "#0f172a",
        "line": "#4f46e5",
        "area_from": "#6366f1",
        "area_to": "#a78bfa",
        "point": "#4f46e5",
    },
    "activity-graph-dark.svg": {
        "bg": "#0b1020",
        "grid": "#1e293b",
        "axis": "#94a3b8",
        "title": "#e2e8f0",
        "line": "#67e8f9",
        "area_from": "#22d3ee",
        "area_to": "#6366f1",
        "point": "#67e8f9",
    },
}

W, H = 900, 330
PAD_L, PAD_R, PAD_T, PAD_B = 58, 24, 64, 44
PLOT_W = W - PAD_L - PAD_R
PLOT_H = H - PAD_T - PAD_B


def fetch(login, token, days=365):
    to = datetime.now(timezone.utc).replace(microsecond=0)
    frm = to - timedelta(days=days)
    body = json.dumps(
        {
            "query": QUERY,
            "variables": {
                "login": login,
                "from": frm.isoformat().replace("+00:00", "Z"),
                "to": to.isoformat().replace("+00:00", "Z"),
            },
        }
    ).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "activity-graph-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)

    if payload.get("errors"):
        raise SystemExit(f"GitHub API error: {payload['errors']}")

    calendar = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days_out = [
        (date.fromisoformat(d["date"]), d["contributionCount"])
        for week in calendar["weeks"]
        for d in week["contributionDays"]
    ]
    days_out.sort()
    return days_out, calendar["totalContributions"]


def nice_max(value):
    """Round the axis top up to a readable number."""
    if value <= 5:
        return 5
    step = 10 ** (len(str(value)) - 1)
    for mult in (1, 2, 2.5, 5, 10):
        top = step * mult
        if top >= value:
            return int(top)
    return value


def smooth_path(points):
    """Catmull-Rom through the points, emitted as cubic beziers.

    Control points are clamped to the plot box: a bezier stays inside the
    hull of its control points, so this keeps spikes from overshooting the
    top gridline.
    """
    if len(points) < 2:
        return ""

    def clamp_y(y):
        return min(max(y, PAD_T), PAD_T + PLOT_H)

    d = [f"M {points[0][0]:.2f},{points[0][1]:.2f}"]
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i else points[0]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, clamp_y(p1[1] + (p2[1] - p0[1]) / 6))
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, clamp_y(p2[1] - (p3[1] - p1[1]) / 6))
        d.append(
            f"C {c1[0]:.2f},{c1[1]:.2f} {c2[0]:.2f},{c2[1]:.2f} {p2[0]:.2f},{p2[1]:.2f}"
        )
    return " ".join(d)


def render(login, days, total, theme):
    c = THEMES[theme]
    counts = [n for _, n in days]
    top = nice_max(max(counts) if counts else 0)
    span = max(len(days) - 1, 1)

    pts = [
        (
            PAD_L + PLOT_W * i / span,
            PAD_T + PLOT_H - PLOT_H * (n / top),
        )
        for i, n in enumerate(counts)
    ]

    grid, ticks = [], []
    for step in range(5):
        y = PAD_T + PLOT_H - PLOT_H * step / 4
        grid.append(
            f'<line x1="{PAD_L}" y1="{y:.2f}" x2="{PAD_L + PLOT_W}" y2="{y:.2f}" '
            f'stroke="{c["grid"]}" stroke-width="1" />'
        )
        ticks.append(
            f'<text x="{PAD_L - 12}" y="{y + 4:.2f}" text-anchor="end" '
            f'class="axis">{int(top * step / 4)}</text>'
        )

    months = []
    seen = set()
    for i, (day, _) in enumerate(days):
        key = (day.year, day.month)
        if key in seen or day.day > 7:
            continue
        seen.add(key)
        x = PAD_L + PLOT_W * i / span
        if x < PAD_L + 14 or x > PAD_L + PLOT_W - 14:
            continue
        months.append(
            f'<text x="{x:.2f}" y="{H - PAD_B + 24}" text-anchor="middle" '
            f'class="axis">{day.strftime("%b")}</text>'
        )

    line = smooth_path(pts)
    area = (
        f'{line} L {pts[-1][0]:.2f},{PAD_T + PLOT_H} '
        f'L {pts[0][0]:.2f},{PAD_T + PLOT_H} Z'
    )
    peak = max(counts) if counts else 0
    subtitle = (
        f"{total:,} contributions in the last year · peak {peak} in a day"
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" \
viewBox="0 0 {W} {H}" role="img" aria-label="{login}'s contribution activity graph">
  <title>{login}'s contribution activity graph</title>
  <defs>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{c['area_from']}" stop-opacity="0.55" />
      <stop offset="100%" stop-color="{c['area_to']}" stop-opacity="0.02" />
    </linearGradient>
  </defs>
  <style>
    .title {{ font: 600 17px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: {c['title']}; }}
    .sub   {{ font: 400 12px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: {c['axis']}; }}
    .axis  {{ font: 400 11px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: {c['axis']}; }}
  </style>

  <rect width="{W}" height="{H}" rx="10" fill="{c['bg']}" />
  <text x="{PAD_L - 12}" y="30" class="title">{login}'s contribution graph</text>
  <text x="{PAD_L - 12}" y="48" class="sub">{subtitle}</text>

  {chr(10).join('  ' + g for g in grid)}
  {chr(10).join('  ' + t for t in ticks)}

  <path d="{area}" fill="url(#area)" />
  <path d="{line}" fill="none" stroke="{c['line']}" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round" />
  <circle cx="{pts[-1][0]:.2f}" cy="{pts[-1][1]:.2f}" r="3.5" fill="{c['point']}" />

  {chr(10).join('  ' + m for m in months)}
</svg>
"""


def main():
    login = os.environ.get("GH_LOGIN", "Nardy11")
    token = os.environ.get("GH_TOKEN")
    out_dir = os.environ.get("OUT_DIR", "dist")
    if not token:
        raise SystemExit("GH_TOKEN is required")

    days, total = fetch(login, token)
    if not days:
        raise SystemExit("no contribution data returned")

    os.makedirs(out_dir, exist_ok=True)
    for name in THEMES:
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render(login, days, total, name))
        print(f"wrote {path}")


if __name__ == "__main__":
    sys.exit(main())
