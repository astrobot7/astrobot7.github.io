#!/usr/bin/env python3
"""Generate SVG cover images for blog posts.

Usage: python3 scripts/make_covers.py
Writes static/images/covers/<slug>.svg for every entry in POSTS.
To add a cover for a new post, add an entry and rerun.
"""
import math
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1200, 630
OUT = Path(__file__).resolve().parent.parent / "static" / "images" / "covers"

# slug, tag line, title lines, subtitle, accent colour
POSTS = [
    ("kubernetes-the-hard-way-vagrant", "KUBERNETES · NETWORKING",
     ["Kubernetes", "the Hard Way"], "Control planes and pod networking on Vagrant", "#4f8cff"),
    ("localstack-to-floci", "AWS · LOCAL DEV",
     ["LocalStack", "to Floci"], "Am I just saving a quick buck?", "#ff8a3d"),
    ("mimir-migration", "OBSERVABILITY · PROMETHEUS",
     ["Scaling metrics", "with Mimir"], "Past the limits of Prometheus federation", "#a970ff"),
    ("renovate-on-docker-swarm", "HOMELAB · DOCKER SWARM",
     ["Killing :latest"], "Digest-pinned images and self-hosted Renovate", "#3ecf8e"),
    ("running-clickhouse-on-kubernetes", "KUBERNETES · DATABASES",
     ["ClickHouse", "on Kubernetes"], "From zero to a replicated production cluster", "#f5c518"),
    ("sandboxed-alert-triage-agents", "AI AGENTS · SRE",
     ["Sandboxed alert", "triage agents"], "Letting an AI agent near production alerts", "#ff5d73"),
]

SANS = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', SFMono-Regular, Menlo, Consolas, monospace"


def motif(seed: int, accent: str) -> str:
    """A small node graph on the right side, varied per post."""
    cx, cy, r = 975, 315, 165  # keep left edge (~810) clear of the longest text (~770)
    pts = []
    for i in range(7):
        a = (i / 7) * 2 * math.pi + seed * 0.9
        rr = r * (0.55 + 0.45 * ((i * 37 + seed * 11) % 10) / 10)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    pts.append((cx, cy))
    parts = []
    for i, (x, y) in enumerate(pts[:-1]):
        nx, ny = pts[(i + 1) % 7]
        parts.append(f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{nx:.0f}" y2="{ny:.0f}" stroke="{accent}" stroke-opacity="0.35" stroke-width="2"/>')
        parts.append(f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{cx}" y2="{cy}" stroke="{accent}" stroke-opacity="0.2" stroke-width="2"/>')
    for i, (x, y) in enumerate(pts):
        size = 16 if i == len(pts) - 1 else 7 + (i * 5 + seed) % 6
        parts.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{size}" fill="#0f1218" stroke="{accent}" stroke-width="3"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="6" fill="{accent}"/>')
    return "\n    ".join(parts)


def cover(seed, tag, title_lines, subtitle, accent) -> str:
    title_size = 76
    title_y0 = 250 if len(title_lines) == 2 else 290
    titles = "\n    ".join(
        f'<text x="80" y="{title_y0 + i * 88}" font-family="{SANS}" font-size="{title_size}" '
        f'font-weight="800" fill="#f2f4f8">{escape(line)}</text>'
        for i, line in enumerate(title_lines)
    )
    sub_y = title_y0 + (len(title_lines) - 1) * 88 + 64
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <pattern id="dots" width="28" height="28" patternUnits="userSpaceOnUse">
      <circle cx="2" cy="2" r="1.5" fill="#ffffff" fill-opacity="0.06"/>
    </pattern>
    <radialGradient id="glow" cx="78%" cy="50%" r="45%">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="{accent}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="#0f1218"/>
  <rect width="{W}" height="{H}" fill="url(#dots)"/>
  <rect width="{W}" height="{H}" fill="url(#glow)"/>
  <g>
    {motif(seed, accent)}
  </g>
  <rect x="80" y="120" width="56" height="6" rx="3" fill="{accent}"/>
  <text x="80" y="170" font-family="{MONO}" font-size="24" font-weight="600" letter-spacing="3" fill="{accent}">{escape(tag)}</text>
  {titles}
  <text x="80" y="{sub_y}" font-family="{SANS}" font-size="30" fill="#9aa3b2">{escape(subtitle)}</text>
  <text x="80" y="560" font-family="{MONO}" font-size="22" fill="#5d6675">blog.aswinkm.dev</text>
</svg>
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for seed, (slug, tag, lines, sub, accent) in enumerate(POSTS):
        path = OUT / f"{slug}.svg"
        path.write_text(cover(seed, tag, lines, sub, accent))
        print(f"wrote {path.relative_to(OUT.parent.parent.parent)}")


if __name__ == "__main__":
    main()
