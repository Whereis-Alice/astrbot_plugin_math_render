from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from astrbot.api import html_renderer, logger

from .geometry import DEFAULT_GEOMETRY_LABEL, GeometryRenderer

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
except Exception:  # pragma: no cover
    get_astrbot_data_path = None  # type: ignore[assignment]

try:
    import markdown as markdown_lib
except Exception:  # pragma: no cover
    markdown_lib = None  # type: ignore[assignment]


PLUGIN_NAME = "astrbot_plugin_math_render"
DEFAULT_MATHJAX_CDN = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml-full.js"
DEFAULT_RENDER_TIMEOUT_MS = 45000
DEFAULT_STYLE = "paper"
DEFAULT_FONT_STACK = (
    '"Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC", '
    '"WenQuanYi Micro Hei", "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif'
)

KNOWN_LATEX_COMMANDS = {
    "frac",
    "sqrt",
    "sum",
    "prod",
    "int",
    "lim",
    "sin",
    "cos",
    "tan",
    "log",
    "ln",
    "alpha",
    "beta",
    "gamma",
    "theta",
    "lambda",
    "pi",
    "Delta",
    "delta",
    "cdot",
    "times",
    "leq",
    "geq",
    "neq",
    "approx",
    "pm",
    "mp",
    "to",
    "rightarrow",
    "left",
    "right",
    "overline",
    "underline",
    "vec",
    "bar",
    "hat",
    "angle",
    "triangle",
    "parallel",
    "perp",
    "because",
    "therefore",
    "infty",
    "cdots",
    "ldots",
}


@dataclass(slots=True)
class SolutionCardContent:
    question: str
    answer: str = ""
    title: str = "数学解答"
    summary: str = ""
    steps: list[str] | None = None
    final_answer: str = ""
    key_formula: str = ""
    style_hint: str = ""
    accent_color: str = ""
    layout_mode: str = ""
    markdown_content: str = ""
    geometry_scene: dict[str, Any] | None = None
    geometry_caption: str = ""


@dataclass(frozen=True, slots=True)
class ThemePalette:
    name: str
    background: str
    halo: str
    card_background: str
    border: str
    text: str
    muted: str
    accent: str
    accent_soft: str
    badge_background: str
    formula_background: str
    question_background: str
    final_background: str
    shadow: str


THEMES: dict[str, ThemePalette] = {
    "paper": ThemePalette(
        name="paper",
        background="linear-gradient(180deg, #f7f2e8 0%, #ece2d2 100%)",
        halo="radial-gradient(circle at top right, rgba(195, 122, 54, 0.24), transparent 48%)",
        card_background="rgba(255, 252, 245, 0.96)",
        border="rgba(99, 67, 42, 0.16)",
        text="#2f241b",
        muted="#6b5745",
        accent="#b55d2b",
        accent_soft="rgba(181, 93, 43, 0.12)",
        badge_background="rgba(181, 93, 43, 0.12)",
        formula_background="linear-gradient(180deg, rgba(255, 247, 236, 0.95) 0%, rgba(245, 235, 218, 0.96) 100%)",
        question_background="rgba(120, 83, 52, 0.06)",
        final_background="linear-gradient(135deg, rgba(181, 93, 43, 0.12), rgba(222, 170, 86, 0.20))",
        shadow="0 30px 100px rgba(89, 58, 33, 0.18)",
    ),
    "notebook": ThemePalette(
        name="notebook",
        background="linear-gradient(180deg, #eef5ff 0%, #dfe7f6 100%)",
        halo="radial-gradient(circle at top right, rgba(43, 96, 184, 0.22), transparent 50%)",
        card_background="rgba(253, 254, 255, 0.96)",
        border="rgba(72, 111, 171, 0.16)",
        text="#1d2d44",
        muted="#4b6384",
        accent="#2f68c8",
        accent_soft="rgba(47, 104, 200, 0.13)",
        badge_background="rgba(47, 104, 200, 0.12)",
        formula_background="linear-gradient(180deg, rgba(245, 249, 255, 0.98) 0%, rgba(234, 242, 255, 0.97) 100%)",
        question_background="rgba(47, 104, 200, 0.06)",
        final_background="linear-gradient(135deg, rgba(47, 104, 200, 0.12), rgba(111, 164, 255, 0.22))",
        shadow="0 32px 100px rgba(36, 72, 129, 0.16)",
    ),
    "blackboard": ThemePalette(
        name="blackboard",
        background="linear-gradient(180deg, #102a22 0%, #081712 100%)",
        halo="radial-gradient(circle at top right, rgba(74, 193, 141, 0.16), transparent 52%)",
        card_background="rgba(14, 34, 28, 0.96)",
        border="rgba(134, 215, 184, 0.13)",
        text="#ebfff6",
        muted="#a7d7c4",
        accent="#5dd39e",
        accent_soft="rgba(93, 211, 158, 0.14)",
        badge_background="rgba(93, 211, 158, 0.14)",
        formula_background="linear-gradient(180deg, rgba(20, 52, 42, 0.98) 0%, rgba(15, 39, 32, 0.98) 100%)",
        question_background="rgba(93, 211, 158, 0.08)",
        final_background="linear-gradient(135deg, rgba(93, 211, 158, 0.14), rgba(143, 239, 206, 0.22))",
        shadow="0 28px 90px rgba(0, 0, 0, 0.35)",
    ),
    "aurora": ThemePalette(
        name="aurora",
        background="linear-gradient(180deg, #f2f4ff 0%, #e8f8f6 100%)",
        halo=(
            "radial-gradient(circle at top right, rgba(49, 111, 247, 0.16), transparent 45%), "
            "radial-gradient(circle at bottom left, rgba(24, 185, 148, 0.14), transparent 45%)"
        ),
        card_background="rgba(255, 255, 255, 0.94)",
        border="rgba(73, 110, 173, 0.12)",
        text="#162033",
        muted="#5c6c87",
        accent="#3f6cf4",
        accent_soft="rgba(63, 108, 244, 0.12)",
        badge_background="rgba(63, 108, 244, 0.12)",
        formula_background="linear-gradient(180deg, rgba(244, 247, 255, 0.98) 0%, rgba(236, 252, 248, 0.97) 100%)",
        question_background="rgba(24, 185, 148, 0.07)",
        final_background="linear-gradient(135deg, rgba(63, 108, 244, 0.12), rgba(24, 185, 148, 0.18))",
        shadow="0 35px 110px rgba(59, 83, 150, 0.14)",
    ),
}


FORMULA_CARD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    * { box-sizing: border-box; }
    :root {
      --page-padding: {{ page_padding }}px;
      --card-radius: {{ card_radius }}px;
      --section-radius: {{ section_radius }}px;
      --body-font-size: {{ body_font_size }}px;
      --body-line-height: {{ body_line_height }};
      --title-font-size: {{ title_font_size }}px;
      --subtitle-font-size: {{ subtitle_font_size }}px;
      --formula-font-scale: {{ formula_font_scale }};
      --content-max-width: {{ content_max_width }}px;
    }
    body {
      margin: 0;
      padding: var(--page-padding);
      min-height: 100vh;
      font-family: {{ font_stack }};
      background: {{ background }};
      color: {{ text }};
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background: {{ halo }};
      pointer-events: none;
    }
    .math-root {
      width: min(var(--content-max-width), calc(100vw - var(--page-padding) * 2));
      opacity: 0;
      transition: opacity 160ms ease;
    }
    .math-root.ready {
      opacity: 1;
    }
    .card {
      position: relative;
      overflow: hidden;
      border-radius: var(--card-radius);
      border: 1px solid {{ border }};
      background: {{ card_background }};
      box-shadow: {{ shadow }};
      backdrop-filter: blur(10px);
    }
    .card::before {
      content: "";
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(90deg, transparent 0, transparent 24px, rgba(255,255,255,0.06) 24px, rgba(255,255,255,0.06) 25px),
        linear-gradient(0deg, transparent 0, transparent 24px, rgba(255,255,255,0.06) 24px, rgba(255,255,255,0.06) 25px);
      opacity: 0.14;
      pointer-events: none;
    }
    .header {
      position: relative;
      padding: 28px 32px 0;
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-start;
    }
    .badge {
      display: inline-flex;
      padding: 7px 14px;
      border-radius: 999px;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: {{ accent }};
      background: {{ badge_background }};
    }
    .title {
      margin: 14px 0 0;
      font-size: var(--title-font-size);
      font-weight: 800;
      line-height: 1.16;
      color: {{ text }};
      word-break: break-word;
      overflow-wrap: anywhere;
    }
    .subtitle {
      margin: 12px 0 0;
      max-width: 820px;
      font-size: var(--subtitle-font-size);
      line-height: var(--body-line-height);
      color: {{ muted }};
      word-break: break-word;
      overflow-wrap: anywhere;
    }
    .accent-dot {
      width: 16px;
      height: 16px;
      flex: 0 0 16px;
      border-radius: 50%;
      margin-top: 10px;
      background: {{ accent }};
      box-shadow: 0 0 30px {{ accent_soft }};
    }
    .formula-shell,
    .formula-free {
      position: relative;
      margin: 24px 32px 22px;
      border-radius: var(--section-radius);
      background: {{ formula_background }};
      overflow-wrap: anywhere;
      word-break: break-word;
      white-space: normal;
    }
    .formula-shell {
      padding: 30px 34px;
    }
    .formula-free {
      padding: 28px 32px;
      font-size: var(--body-font-size);
      line-height: var(--body-line-height);
      color: {{ text }};
    }
    .formula-free :is(p, ul, ol, li, blockquote, pre, code, table, h1, h2, h3, h4) {
      max-width: 100%;
    }
    .formula-free p { margin: 0 0 12px; }
    .formula-free p:last-child { margin-bottom: 0; }
    .formula-free h1,
    .formula-free h2,
    .formula-free h3,
    .formula-free h4 {
      margin: 0 0 12px;
      line-height: 1.3;
    }
    .formula-free h1 { font-size: calc(var(--body-font-size) * 1.4); }
    .formula-free h2 { font-size: calc(var(--body-font-size) * 1.25); }
    .formula-free h3 { font-size: calc(var(--body-font-size) * 1.12); }
    .formula-free ul,
    .formula-free ol {
      margin: 0 0 12px;
      padding-left: 1.5em;
      display: grid;
      gap: 8px;
    }
    .formula-free blockquote {
      margin: 0 0 14px;
      padding: 10px 14px;
      border-left: 4px solid {{ accent }};
      background: {{ accent_soft }};
      border-radius: 0 14px 14px 0;
    }
    .formula-free pre {
      margin: 0 0 12px;
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(20, 20, 20, 0.08);
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .formula-free code {
      padding: 0.12em 0.38em;
      border-radius: 8px;
      background: rgba(20, 20, 20, 0.08);
      font-size: 0.94em;
    }
    .formula-free pre code {
      padding: 0;
      background: transparent;
      font-size: 0.92em;
    }
    .formula-free table {
      width: 100%;
      border-collapse: collapse;
      margin: 0 0 14px;
      display: block;
      overflow-x: auto;
    }
    .formula-free th,
    .formula-free td {
      border: 1px solid {{ border }};
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }
    .formula-shell .mjx-container,
    .formula-free .mjx-container {
      font-size: calc(100% * var(--formula-font-scale)) !important;
      max-width: 100%;
      overflow-x: auto;
      overflow-y: hidden;
    }
    .footer {
      position: relative;
      padding: 0 32px 30px;
      font-size: calc(var(--body-font-size) - 1px);
      line-height: var(--body-line-height);
      color: {{ muted }};
      word-break: break-word;
      overflow-wrap: anywhere;
    }
    .footer p { margin: 0; }
  </style>
  <script>
    function markReady(state) {
      const root = document.getElementById("capture-root");
      if (!root) {
        return;
      }
      root.dataset.ready = state;
      root.classList.add("ready");
    }

    window.MathJax = {
      tex: {
        inlineMath: [["$", "$"], ["\\\\(", "\\\\)"]],
        displayMath: [["$$", "$$"], ["\\\\[", "\\\\]"]]
      },
      chtml: {
        matchFontHeight: false,
        scale: 1.02,
        mtextInheritFont: true
      },
      startup: {
        ready: () => {
          MathJax.startup.defaultReady();
          MathJax.startup.promise
            .then(() => markReady("done"))
            .catch(() => markReady("fallback"));
        }
      }
    };

    window.setTimeout(() => markReady("timeout"), 12000);
  </script>
  <script defer src="{{ mathjax_cdn_url }}"></script>
</head>
<body>
  <main id="capture-root" class="math-root">
    <section class="card">
      <div class="header">
        <div>
          <div class="badge">LaTeX Render</div>
          <h1 class="title">{{ title }}</h1>
          {% if subtitle_html %}
          <div class="subtitle">{{ subtitle_html | safe }}</div>
          {% endif %}
        </div>
        <div class="accent-dot"></div>
      </div>
      {% if formula_is_markdown and formula_markdown_html %}
      <div class="formula-free">{{ formula_markdown_html | safe }}</div>
      {% else %}
      <div class="formula-shell">
        \\[
        {{ formula }}
        \\]
      </div>
      {% endif %}
      {% if note_html %}
      <div class="footer">{{ note_html | safe }}</div>
      {% endif %}
    </section>
  </main>
</body>
</html>
"""


SOLUTION_CARD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    * { box-sizing: border-box; }
    :root {
      --page-padding: {{ page_padding }}px;
      --card-radius: {{ card_radius }}px;
      --section-radius: {{ section_radius }}px;
      --body-font-size: {{ body_font_size }}px;
      --body-line-height: {{ body_line_height }};
      --title-font-size: {{ title_font_size }}px;
      --summary-font-size: {{ subtitle_font_size }}px;
      --formula-font-scale: {{ formula_font_scale }};
      --content-max-width: {{ content_max_width }}px;
      --section-gap: {{ section_gap }}px;
    }
    body {
      margin: 0;
      padding: var(--page-padding);
      min-height: 100vh;
      font-family: {{ font_stack }};
      background: {{ background }};
      color: {{ text }};
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background: {{ halo }};
      pointer-events: none;
    }
    .math-root {
      width: min(var(--content-max-width), calc(100vw - var(--page-padding) * 2));
      opacity: 0;
      transition: opacity 160ms ease;
    }
    .math-root.ready {
      opacity: 1;
    }
    .card {
      position: relative;
      overflow: hidden;
      border-radius: var(--card-radius);
      border: 1px solid {{ border }};
      background: {{ card_background }};
      box-shadow: {{ shadow }};
      backdrop-filter: blur(10px);
    }
    .card::before {
      content: "";
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(90deg, transparent 0, transparent 28px, rgba(255, 255, 255, 0.05) 28px, rgba(255, 255, 255, 0.05) 29px),
        linear-gradient(0deg, transparent 0, transparent 28px, rgba(255, 255, 255, 0.05) 28px, rgba(255, 255, 255, 0.05) 29px);
      opacity: 0.12;
      pointer-events: none;
    }
    .hero {
      position: relative;
      padding: 30px 34px 26px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 24px;
      align-items: start;
    }
    .badge {
      display: inline-flex;
      padding: 8px 14px;
      border-radius: 999px;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: {{ accent }};
      background: {{ badge_background }};
    }
    .title {
      margin: 14px 0 0;
      font-size: var(--title-font-size);
      font-weight: 800;
      line-height: 1.15;
      color: {{ text }};
      word-break: break-word;
      overflow-wrap: anywhere;
    }
    .summary {
      margin: 14px 0 0;
      max-width: 880px;
      font-size: var(--summary-font-size);
      line-height: var(--body-line-height);
      color: {{ muted }};
      word-break: break-word;
      overflow-wrap: anywhere;
    }
    .summary p { margin: 0; }
    .accent-pill {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 16px;
      border-radius: 999px;
      background: {{ accent_soft }};
      color: {{ accent }};
      font-size: 15px;
      font-weight: 700;
      white-space: nowrap;
    }
    .accent-pill::before {
      content: "";
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: {{ accent }};
      box-shadow: 0 0 24px {{ accent_soft }};
    }
    .section-grid {
      position: relative;
      display: grid;
      gap: var(--section-gap);
      padding: 0 34px 34px;
    }
    .section {
      position: relative;
      border-radius: var(--section-radius);
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(255, 255, 255, 0.02);
      padding: 22px 24px;
      overflow: hidden;
    }
    .question {
      background: {{ question_background }};
    }
    .formula {
      background: {{ formula_background }};
    }
    .final {
      background: {{ final_background }};
    }
    .geometry {
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.42), rgba(255, 255, 255, 0.18));
    }
    .label {
      margin: 0 0 14px;
      font-size: 15px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: {{ accent }};
    }
    .body,
    .free-layout-body,
    .geometry-caption {
      font-size: var(--body-font-size);
      line-height: var(--body-line-height);
      color: {{ text }};
      word-break: break-word;
      overflow-wrap: anywhere;
      white-space: normal;
    }
    .geometry-caption {
      font-size: calc(var(--body-font-size) - 1px);
      color: {{ muted }};
    }
    .body :is(p, ul, ol, li, blockquote, pre, code, table, h1, h2, h3, h4),
    .free-layout-body :is(p, ul, ol, li, blockquote, pre, code, table, h1, h2, h3, h4) {
      max-width: 100%;
    }
    .body p,
    .free-layout-body p { margin: 0 0 12px; }
    .body p:last-child,
    .free-layout-body p:last-child { margin-bottom: 0; }
    .body h1,
    .body h2,
    .body h3,
    .body h4,
    .free-layout-body h1,
    .free-layout-body h2,
    .free-layout-body h3,
    .free-layout-body h4 {
      margin: 0 0 14px;
      line-height: 1.3;
    }
    .body h1,
    .free-layout-body h1 { font-size: calc(var(--body-font-size) * 1.48); }
    .body h2,
    .free-layout-body h2 { font-size: calc(var(--body-font-size) * 1.34); }
    .body h3,
    .free-layout-body h3 { font-size: calc(var(--body-font-size) * 1.2); }
    .body h4,
    .free-layout-body h4 { font-size: calc(var(--body-font-size) * 1.08); }
    .body ul,
    .body ol,
    .free-layout-body ul,
    .free-layout-body ol {
      margin: 0 0 12px;
      padding-left: 1.5em;
      display: grid;
      gap: 8px;
    }
    .body blockquote,
    .free-layout-body blockquote {
      margin: 0 0 14px;
      padding: 10px 14px;
      border-left: 4px solid {{ accent }};
      background: {{ accent_soft }};
      border-radius: 0 14px 14px 0;
    }
    .body pre,
    .free-layout-body pre {
      margin: 0 0 12px;
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(20, 20, 20, 0.08);
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .body code,
    .free-layout-body code {
      padding: 0.12em 0.38em;
      border-radius: 8px;
      background: rgba(20, 20, 20, 0.08);
      font-size: 0.94em;
    }
    .body pre code,
    .free-layout-body pre code {
      padding: 0;
      background: transparent;
      font-size: 0.92em;
    }
    .body table,
    .free-layout-body table {
      width: 100%;
      border-collapse: collapse;
      margin: 0 0 14px;
      display: block;
      overflow-x: auto;
    }
    .body th,
    .body td,
    .free-layout-body th,
    .free-layout-body td {
      border: 1px solid {{ border }};
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }
    .body hr,
    .free-layout-body hr {
      border: 0;
      height: 1px;
      margin: 16px 0;
      background: {{ border }};
    }
    .steps {
      margin: 0;
      padding-left: 24px;
      display: grid;
      gap: 12px;
    }
    .steps li {
      padding-left: 6px;
      font-size: var(--body-font-size);
      line-height: var(--body-line-height);
      word-break: break-word;
      overflow-wrap: anywhere;
    }
    .formula .mjx-container,
    .final .mjx-container,
    .steps .mjx-container,
    .body .mjx-container,
    .free-layout-body .mjx-container {
      font-size: calc(100% * var(--formula-font-scale)) !important;
      max-width: 100%;
      overflow-x: auto;
      overflow-y: hidden;
    }
    .formula-math {
      overflow-wrap: anywhere;
      word-break: break-word;
      white-space: normal;
    }
    .free-layout {
      display: grid;
      gap: var(--section-gap);
      background: {{ formula_background }};
    }
    .geometry-shell {
      display: grid;
      gap: 14px;
    }
    .geometry-media {
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 14px;
      border-radius: calc(var(--section-radius) - 8px);
      background: rgba(255, 255, 255, 0.52);
      overflow: hidden;
    }
    .geometry-media img {
      display: block;
      max-width: 100%;
      height: auto;
      object-fit: contain;
    }
  </style>
  <script>
    function markReady(state) {
      const root = document.getElementById("capture-root");
      if (!root) {
        return;
      }
      root.dataset.ready = state;
      root.classList.add("ready");
    }

    window.MathJax = {
      tex: {
        inlineMath: [["$", "$"], ["\\\\(", "\\\\)"]],
        displayMath: [["$$", "$$"], ["\\\\[", "\\\\]"]]
      },
      chtml: {
        matchFontHeight: false,
        scale: 1.0,
        mtextInheritFont: true
      },
      startup: {
        ready: () => {
          MathJax.startup.defaultReady();
          MathJax.startup.promise
            .then(() => markReady("done"))
            .catch(() => markReady("fallback"));
        }
      }
    };

    window.setTimeout(() => markReady("timeout"), 12000);
  </script>
  <script defer src="{{ mathjax_cdn_url }}"></script>
</head>
<body>
  <main id="capture-root" class="math-root">
    <section class="card">
      <div class="hero">
        <div>
          <div class="badge">Math Solution</div>
          <h1 class="title">{{ title }}</h1>
          {% if summary_html %}
          <div class="summary">{{ summary_html | safe }}</div>
          {% endif %}
        </div>
        <div class="accent-pill">{{ theme_name }}</div>
      </div>
      <div class="section-grid">
        {% if free_layout_html %}
          {% if geometry_image_data_uri and geometry_position == "before_answer" %}
          <section class="section geometry">
            <div class="label">{{ geometry_label }}</div>
            <div class="geometry-shell">
              <div class="geometry-media">
                <img src="{{ geometry_image_data_uri }}" alt="geometry diagram" />
              </div>
              {% if geometry_caption_html %}
              <div class="geometry-caption">{{ geometry_caption_html | safe }}</div>
              {% endif %}
            </div>
          </section>
          {% endif %}
          <section class="section free-layout">
            <div class="label">内容</div>
            <div class="free-layout-body">{{ free_layout_html | safe }}</div>
          </section>
          {% if geometry_image_data_uri and geometry_position != "before_answer" %}
          <section class="section geometry">
            <div class="label">{{ geometry_label }}</div>
            <div class="geometry-shell">
              <div class="geometry-media">
                <img src="{{ geometry_image_data_uri }}" alt="geometry diagram" />
              </div>
              {% if geometry_caption_html %}
              <div class="geometry-caption">{{ geometry_caption_html | safe }}</div>
              {% endif %}
            </div>
          </section>
          {% endif %}
        {% else %}
          {% if question_html %}
          <section class="section question">
            <div class="label">题目</div>
            <div class="body">{{ question_html | safe }}</div>
          </section>
          {% endif %}
          {% if key_formula %}
          <section class="section formula">
            <div class="label">关键公式</div>
            <div class="formula-math">
              \\[
              {{ key_formula }}
              \\]
            </div>
          </section>
          {% endif %}
          {% if geometry_image_data_uri and geometry_position == "before_answer" %}
          <section class="section geometry">
            <div class="label">{{ geometry_label }}</div>
            <div class="geometry-shell">
              <div class="geometry-media">
                <img src="{{ geometry_image_data_uri }}" alt="geometry diagram" />
              </div>
              {% if geometry_caption_html %}
              <div class="geometry-caption">{{ geometry_caption_html | safe }}</div>
              {% endif %}
            </div>
          </section>
          {% endif %}
          {% if answer_html %}
          <section class="section">
            <div class="label">解答</div>
            <div class="body">{{ answer_html | safe }}</div>
          </section>
          {% endif %}
          {% if steps_html %}
          <section class="section">
            <div class="label">步骤</div>
            <ol class="steps">
              {% for step_html in steps_html %}
              <li>{{ step_html | safe }}</li>
              {% endfor %}
            </ol>
          </section>
          {% endif %}
          {% if final_answer_html %}
          <section class="section final">
            <div class="label">最终答案</div>
            <div class="body">{{ final_answer_html | safe }}</div>
          </section>
          {% endif %}
          {% if geometry_image_data_uri and geometry_position != "before_answer" %}
          <section class="section geometry">
            <div class="label">{{ geometry_label }}</div>
            <div class="geometry-shell">
              <div class="geometry-media">
                <img src="{{ geometry_image_data_uri }}" alt="geometry diagram" />
              </div>
              {% if geometry_caption_html %}
              <div class="geometry-caption">{{ geometry_caption_html | safe }}</div>
              {% endif %}
            </div>
          </section>
          {% endif %}
        {% endif %}
      </div>
    </section>
  </main>
</body>
</html>
"""


class MathRenderService:
    def __init__(self, plugin: Any, config: dict[str, Any] | None, plugin_name: str = PLUGIN_NAME) -> None:
        self._plugin = plugin
        self._config = config or {}
        self._plugin_name = plugin_name
        self._init_lock = asyncio.Lock()
        self._renderer_ready = False
        self._temp_dir = self._resolve_temp_dir()
        self._geometry_renderer = GeometryRenderer(
            config=self._config,
            temp_dir=self._temp_dir,
            debug=self._debug,
        )

    @property
    def temp_dir(self) -> Path:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        return self._temp_dir

    async def prepare(self) -> None:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        if self._bool("cleanup_on_initialize", True):
            removed = await self.cleanup_temp_files()
            if removed:
                logger.info("math_render plugin cleaned %s expired temp files on init.", removed)
            self._debug("prepare cleanup_on_initialize removed=%s", removed)

        if self._text("render_backend", "auto").lower() == "local":
            self._debug("prepare skipped remote prewarm because backend=local")
            return
        if not self._bool("prewarm_renderer", True):
            self._debug("prepare skipped remote prewarm because prewarm_renderer=false")
            return

        async with self._init_lock:
            if self._renderer_ready:
                self._debug("prepare skipped because renderer already ready")
                return
            try:
                await html_renderer.initialize()
                self._renderer_ready = True
                self._debug("remote html renderer prewarmed successfully")
            except Exception as exc:  # pragma: no cover
                logger.warning("math_render plugin failed to prewarm html renderer: %s", exc)
                self._debug("remote html renderer prewarm failed: %s", exc)

    async def cleanup_temp_files(self, purge_all: bool = False) -> int:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        ttl_hours = self._int("temp_retention_hours", 24)
        if not purge_all and ttl_hours <= 0:
            return 0

        now = time.time()
        cutoff = now - max(ttl_hours, 0) * 3600
        removed = 0
        for path in self.temp_dir.glob("*"):
            if not path.is_file():
                continue
            try:
                if purge_all or path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except FileNotFoundError:
                continue
        self._debug("cleanup_temp_files purge_all=%s removed=%s", purge_all, removed)
        return removed

    async def render_formula_card(
        self,
        *,
        formula: str,
        title: str = "LaTeX 公式渲染",
        note: str = "",
        style_hint: str = "",
        accent_color: str = "",
    ) -> Path:
        await self._before_render()
        raw_formula = (formula or "").strip()
        clean_formula = self._strip_formula_wrappers(raw_formula)
        theme = self._resolve_theme(style_hint, accent_color)
        render_as_markdown = self._should_render_formula_as_markdown(raw_formula, clean_formula)
        render_key = self._make_cache_key(
            "formula",
            {
                "formula": clean_formula,
                "raw_formula": raw_formula if render_as_markdown else "",
                "title": title,
                "note": note,
                "style": theme.name,
                "accent": theme.accent,
                "render_as_markdown": render_as_markdown,
            },
        )
        target_path = self.temp_dir / f"formula_{render_key}.png"
        if self._bool("enable_cache", True) and target_path.exists():
            target_path.touch()
            return target_path

        payload = self._theme_context(theme)
        payload.update(self._render_settings_context())
        payload.update(
            {
                "title": title.strip() or "LaTeX 公式渲染",
                "subtitle_html": self._rich_text_to_html("高质量数学公式图卡", prefer_markdown=True),
                "formula": clean_formula if not render_as_markdown else self._fallback_formula_placeholder(),
                "formula_is_markdown": render_as_markdown,
                "formula_markdown_html": self._rich_text_to_html(raw_formula, prefer_markdown=True) if render_as_markdown else "",
                "note_html": self._rich_text_to_html(note, prefer_markdown=True),
                "mathjax_cdn_url": self._text("mathjax_cdn_url", DEFAULT_MATHJAX_CDN),
            }
        )
        return await self._render_to_png(FORMULA_CARD_TEMPLATE, payload, target_path)

    async def render_solution_card(self, content: SolutionCardContent) -> Path:
        await self._before_render()
        theme = self._resolve_theme(content.style_hint, content.accent_color)
        steps = [step.strip() for step in (content.steps or []) if step and step.strip()]
        geometry_payload = self._prepare_geometry_payload(content)
        render_key = self._make_cache_key(
            "solution",
            {
                "question": content.question,
                "answer": content.answer,
                "title": content.title,
                "summary": content.summary,
                "steps": steps,
                "final_answer": content.final_answer,
                "key_formula": content.key_formula,
                "style": theme.name,
                "accent": theme.accent,
                "layout_mode": content.layout_mode,
                "markdown_content": content.markdown_content,
                "geometry_scene": content.geometry_scene,
                "geometry_caption": content.geometry_caption,
                "geometry_position": geometry_payload.get("geometry_position", ""),
            },
        )
        target_path = self.temp_dir / f"solution_{render_key}.png"
        if self._bool("enable_cache", True) and target_path.exists():
            target_path.touch()
            return target_path

        free_layout_markdown = self._build_solution_markdown(content)
        payload = self._theme_context(theme)
        payload.update(self._render_settings_context())
        payload.update(
            {
                "title": content.title.strip() or "数学解答",
                "theme_name": self._display_theme_name(theme.name),
                "question_html": self._rich_text_to_html(content.question, prefer_markdown=True),
                "summary_html": self._rich_text_to_html(content.summary, prefer_markdown=True),
                "answer_html": self._rich_text_to_html(content.answer, prefer_markdown=True),
                "steps_html": [self._rich_text_to_html(step, prefer_markdown=True) for step in steps],
                "final_answer_html": self._rich_text_to_html(content.final_answer, prefer_markdown=True),
                "key_formula": self._strip_formula_wrappers(content.key_formula),
                "free_layout_html": self._rich_text_to_html(free_layout_markdown, prefer_markdown=True)
                if self._resolve_layout_mode(content) == "free"
                else "",
                "mathjax_cdn_url": self._text("mathjax_cdn_url", DEFAULT_MATHJAX_CDN),
            }
        )
        payload.update(geometry_payload)
        return await self._render_to_png(SOLUTION_CARD_TEMPLATE, payload, target_path)

    def _prepare_geometry_payload(self, content: SolutionCardContent) -> dict[str, Any]:
        if not self._bool("geometry_render_enabled", True):
            return {
                "geometry_image_data_uri": "",
                "geometry_caption_html": "",
                "geometry_label": self._text("geometry_section_label", DEFAULT_GEOMETRY_LABEL),
                "geometry_position": self._geometry_position(),
            }
        if not self._bool("geometry_section_enabled", True):
            return {
                "geometry_image_data_uri": "",
                "geometry_caption_html": "",
                "geometry_label": self._text("geometry_section_label", DEFAULT_GEOMETRY_LABEL),
                "geometry_position": self._geometry_position(),
            }

        scene = content.geometry_scene
        if not scene:
            return {
                "geometry_image_data_uri": "",
                "geometry_caption_html": "",
                "geometry_label": self._text("geometry_section_label", DEFAULT_GEOMETRY_LABEL),
                "geometry_position": self._geometry_position(),
            }

        try:
            geometry_result = self._geometry_renderer.render_scene(scene)
            caption = (content.geometry_caption or "").strip() or geometry_result.caption
            return {
                "geometry_image_data_uri": geometry_result.data_uri,
                "geometry_caption_html": self._rich_text_to_html(caption, prefer_markdown=True)
                if self._bool("geometry_caption_enabled", True)
                else "",
                "geometry_label": self._text("geometry_section_label", DEFAULT_GEOMETRY_LABEL),
                "geometry_position": self._geometry_position(),
            }
        except Exception as exc:
            logger.warning("math_render geometry render failed: %s", exc)
            self._debug("geometry render failed: %s", exc)
            return {
                "geometry_image_data_uri": "",
                "geometry_caption_html": "",
                "geometry_label": self._text("geometry_section_label", DEFAULT_GEOMETRY_LABEL),
                "geometry_position": self._geometry_position(),
            }

    def _geometry_position(self) -> str:
        return "before_answer" if self._text("geometry_section_position", "before_answer").lower() == "before_answer" else "after_answer"

    async def _before_render(self) -> None:
        if self._bool("cleanup_before_render", True):
            await self.cleanup_temp_files()
        if not self._renderer_ready:
            await self.prepare()
        self._debug("before_render complete renderer_ready=%s", self._renderer_ready)

    async def _render_to_png(self, template: str, payload: dict[str, Any], target_path: Path) -> Path:
        backend = self._text("render_backend", "auto").lower()
        if backend not in {"auto", "local", "remote"}:
            backend = "auto"
        self._debug("render_to_png backend=%s target=%s", backend, target_path)

        errors: list[str] = []
        if backend in {"auto", "local"}:
            try:
                return await self._render_with_local_browser(template, payload, target_path)
            except Exception as exc:
                errors.append(f"local browser backend failed: {exc}")
                logger.warning("math_render local backend failed: %s", exc)
                self._debug("local render backend failed: %s", exc)

        if backend in {"auto", "remote"}:
            try:
                return await self._render_with_remote_html(template, payload, target_path)
            except Exception as exc:
                errors.append(f"remote html_render backend failed: {exc}")
                logger.warning("math_render remote backend failed: %s", exc)
                self._debug("remote render backend failed: %s", exc)

        raise RuntimeError("; ".join(errors) if errors else "No render backend is available.")

    async def _render_with_local_browser(self, template: str, payload: dict[str, Any], target_path: Path) -> Path:
        try:
            from jinja2 import Template
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("local browser dependencies are unavailable") from exc

        rendered_html = Template(template).render(**payload)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            target_path.unlink(missing_ok=True)

        executable = self._resolve_local_browser_executable()
        viewport = {
            "width": self._int("viewport_width", 1280),
            "height": self._int("viewport_height", 2200),
        }
        timeout = self._int("render_timeout_ms", DEFAULT_RENDER_TIMEOUT_MS)
        base_scale = max(self._float("device_scale_factor", 2.0), 1.0)
        dpi_scale = max(self._float("render_dpi_scale", 1.0), 0.5)
        device_scale_factor = max(base_scale * dpi_scale, 1.0)
        selector = "#capture-root[data-ready]"

        launch_kwargs: dict[str, Any] = {"headless": True}
        if executable:
            launch_kwargs["executable_path"] = str(executable)
        browser_args = self._resolve_local_browser_launch_args()
        if browser_args:
            launch_kwargs["args"] = browser_args

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch_kwargs)
            try:
                page = await browser.new_page(viewport=viewport, device_scale_factor=device_scale_factor)
                await page.set_content(rendered_html, wait_until="networkidle")
                locator = page.locator(selector)
                await locator.wait_for(timeout=timeout)
                await locator.screenshot(path=str(target_path), type="png")
            finally:
                await browser.close()
        return target_path

    async def _render_with_remote_html(self, template: str, payload: dict[str, Any], target_path: Path) -> Path:
        options = {
            "viewport": {
                "width": self._int("viewport_width", 1280),
                "height": self._int("viewport_height", 2200),
            },
            "selector": "#capture-root[data-ready]",
            "wait_until": "networkidle",
            "timeout": self._int("render_timeout_ms", DEFAULT_RENDER_TIMEOUT_MS),
            "type": "png",
            "full_page": False,
            "animations": "disabled",
            "scale": "device",
        }
        source_path = await self._plugin.html_render(template, payload, return_url=False, options=options)
        if not source_path:
            raise RuntimeError("HTML render returned an empty result.")
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Rendered file not found: {source}")
        return self._persist_png(source, target_path)

    def _persist_png(self, source: Path, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink(missing_ok=True)
        try:
            with PILImage.open(source) as image:
                image.save(target, format="PNG")
        except UnidentifiedImageError as exc:
            try:
                preview = source.read_text(encoding="utf-8", errors="replace")[:240].strip()
            except Exception:
                preview = ""
            message = "remote renderer returned a non-image response"
            if preview:
                message += f": {preview}"
            raise RuntimeError(message) from exc
        finally:
            source.unlink(missing_ok=True)
        return target

    def _theme_context(self, theme: ThemePalette) -> dict[str, str]:
        return {
            "background": self._text("render_page_background_css", "") or theme.background,
            "halo": theme.halo,
            "card_background": self._text("render_card_background_css", "") or theme.card_background,
            "border": theme.border,
            "text": self._text("render_text_color", "") or theme.text,
            "muted": self._text("render_muted_text_color", "") or theme.muted,
            "accent": theme.accent,
            "accent_soft": theme.accent_soft,
            "badge_background": theme.badge_background,
            "formula_background": theme.formula_background,
            "question_background": theme.question_background,
            "final_background": theme.final_background,
            "shadow": theme.shadow,
            "font_stack": DEFAULT_FONT_STACK,
        }

    def _resolve_theme(self, style_hint: str, accent_color: str) -> ThemePalette:
        hint = (style_hint or self._text("default_style", DEFAULT_STYLE)).strip().lower()
        theme_key = DEFAULT_STYLE
        if any(token in hint for token in ("chalk", "blackboard", "黑板", "课堂")):
            theme_key = "blackboard"
        elif any(token in hint for token in ("note", "notebook", "paper line", "草稿", "笔记")):
            theme_key = "notebook"
        elif any(token in hint for token in ("aurora", "modern", "vivid", "future", "科技", "流光", "清爽")):
            theme_key = "aurora"
        elif any(token in hint for token in ("paper", "exam", "elegant", "试卷", "纸张", "简洁")):
            theme_key = "paper"
        elif hint in THEMES:
            theme_key = hint

        theme = THEMES.get(theme_key, THEMES[DEFAULT_STYLE])
        custom_accent = self._normalize_hex_color(accent_color or self._text("default_accent_color", ""))
        if not custom_accent:
            return theme
        return ThemePalette(
            name=theme.name,
            background=theme.background,
            halo=theme.halo,
            card_background=theme.card_background,
            border=theme.border,
            text=theme.text,
            muted=theme.muted,
            accent=custom_accent,
            accent_soft=self._hex_to_rgba(custom_accent, 0.14),
            badge_background=self._hex_to_rgba(custom_accent, 0.12),
            formula_background=theme.formula_background,
            question_background=theme.question_background,
            final_background=theme.final_background,
            shadow=theme.shadow,
        )

    def _resolve_temp_dir(self) -> Path:
        if get_astrbot_data_path:
            try:
                base = Path(get_astrbot_data_path())
                return base / "plugins" / self._plugin_name / "temp"
            except Exception as exc:  # pragma: no cover
                logger.warning("math_render plugin failed to resolve AstrBot data path: %s", exc)
        return Path(__file__).resolve().parent / ".tmp"

    def _resolve_local_browser_executable(self) -> Path | None:
        configured = self._text("local_browser_executable", "")
        if configured:
            candidate = Path(configured).expanduser()
            if candidate.exists():
                return candidate
            discovered = shutil.which(configured)
            if discovered:
                return Path(discovered)

        for command_name in (
            "microsoft-edge",
            "microsoft-edge-stable",
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        ):
            discovered = shutil.which(command_name)
            if discovered:
                return Path(discovered)

        candidates = [
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path("/usr/bin/microsoft-edge"),
            Path("/usr/bin/microsoft-edge-stable"),
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/snap/bin/chromium"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _resolve_local_browser_launch_args(self) -> list[str]:
        if os.name != "posix":
            return []
        args: list[str] = ["--disable-dev-shm-usage"]
        if self._bool("linux_disable_browser_sandbox", True) and self._is_running_as_root():
            args.extend(["--no-sandbox", "--disable-setuid-sandbox"])
        return args

    def _is_running_as_root(self) -> bool:
        geteuid = getattr(os, "geteuid", None)
        if geteuid is None:
            return False
        try:
            return geteuid() == 0
        except Exception:
            return False

    def _make_cache_key(self, prefix: str, payload: dict[str, Any]) -> str:
        raw = json.dumps({"prefix": prefix, "payload": payload}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    def _rich_text_to_html(self, text: str, *, prefer_markdown: bool = False) -> str:
        clean = self._normalize_rich_text(text)
        if not clean:
            return ""
        if prefer_markdown:
            markdown_html = self._markdown_to_html(clean)
            if markdown_html:
                return markdown_html
        paragraphs = re.split(r"\n\s*\n", clean)
        html_parts: list[str] = []
        for paragraph in paragraphs:
            escaped = html.escape(paragraph.strip()).replace("\n", "<br>")
            if escaped:
                html_parts.append(f"<p>{escaped}</p>")
        return "".join(html_parts)

    def _markdown_to_html(self, text: str) -> str:
        clean = self._normalize_rich_text(text)
        if not clean:
            return ""
        protected, math_tokens = self._protect_math_blocks(clean)
        rendered = ""
        if markdown_lib is not None:
            try:
                rendered = markdown_lib.markdown(
                    protected,
                    extensions=["extra", "tables", "fenced_code", "sane_lists", "nl2br"],
                    output_format="html5",
                )
            except Exception as exc:
                self._debug("markdown render failed: %s", exc)
                rendered = ""
        if not rendered:
            rendered = self._basic_markdown_to_html(protected)
        return self._restore_math_blocks(rendered.strip(), math_tokens)

    def _basic_markdown_to_html(self, text: str) -> str:
        blocks = re.split(r"\n\s*\n", (text or "").strip())
        html_blocks: list[str] = []
        for block in blocks:
            lines = [line.rstrip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            if len(lines) == 1:
                heading = re.match(r"^(#{1,4})\s+(.*)$", lines[0])
                if heading:
                    level = min(len(heading.group(1)), 4)
                    content = self._render_inline_markdown(heading.group(2))
                    html_blocks.append(f"<h{level}>{content}</h{level}>")
                    continue
            if all(re.match(r"^\s*[-*+]\s+.+$", line) for line in lines):
                items = "".join(
                    f"<li>{self._render_inline_markdown(re.sub(r'^\s*[-*+]\s+', '', line))}</li>"
                    for line in lines
                )
                html_blocks.append(f"<ul>{items}</ul>")
                continue
            if all(re.match(r"^\s*\d+\.\s+.+$", line) for line in lines):
                items = "".join(
                    f"<li>{self._render_inline_markdown(re.sub(r'^\s*\d+\.\s+', '', line))}</li>"
                    for line in lines
                )
                html_blocks.append(f"<ol>{items}</ol>")
                continue
            if all(line.lstrip().startswith(">") for line in lines):
                quote_lines = [re.sub(r"^\s*>\s?", "", line) for line in lines]
                quote_html = "<br>".join(self._render_inline_markdown(line) for line in quote_lines)
                html_blocks.append(f"<blockquote><p>{quote_html}</p></blockquote>")
                continue
            paragraph = "<br>".join(self._render_inline_markdown(line) for line in lines)
            html_blocks.append(f"<p>{paragraph}</p>")
        return "".join(html_blocks)

    def _render_inline_markdown(self, text: str) -> str:
        escaped = html.escape(text or "")
        code_tokens: list[str] = []

        def take_code(match: re.Match[str]) -> str:
            code_tokens.append(f"<code>{html.escape(match.group(1))}</code>")
            return f"@@MATHRENDERCODE{len(code_tokens) - 1}@@"

        escaped = re.sub(r"`([^`]+)`", take_code, escaped)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", escaped)
        escaped = re.sub(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", r"<em>\1</em>", escaped)
        for index, token in enumerate(code_tokens):
            escaped = escaped.replace(f"@@MATHRENDERCODE{index}@@", token)
        return escaped

    def _protect_math_blocks(self, text: str) -> tuple[str, list[str]]:
        pattern = re.compile(r"(\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<!\$)\$(?:\\.|[^$\n])+\$)", re.DOTALL)
        math_tokens: list[str] = []

        def replace(match: re.Match[str]) -> str:
            math_tokens.append(match.group(0))
            return f"@@MATHRENDERTOKEN{len(math_tokens) - 1}@@"

        return pattern.sub(replace, text), math_tokens

    def _restore_math_blocks(self, text: str, math_tokens: list[str]) -> str:
        restored = text
        for index, token in enumerate(math_tokens):
            restored = restored.replace(f"@@MATHRENDERTOKEN{index}@@", token)
        return restored

    def _normalize_rich_text(self, text: str) -> str:
        clean = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not clean:
            return ""
        if self._bool("normalize_escaped_newlines_enabled", True):
            clean = self._normalize_escaped_newlines(clean)
        if self._bool("auto_wrap_bare_latex_enabled", True):
            clean = self._wrap_bare_latex_fragments(clean)
        return clean.strip()

    def _normalize_escaped_newlines(self, text: str) -> str:
        normalized = text.replace("\\r\\n", "\n").replace("\\n\\n", "\n\n")
        normalized = re.sub(r"\\n(?=[^A-Za-z]|$)", "\n", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized

    def _wrap_bare_latex_fragments(self, text: str) -> str:
        protected, math_tokens = self._protect_math_blocks(text)
        wrapped_lines: list[str] = []
        for line in protected.splitlines():
            updated = self._wrap_math_command_fragments(line)
            updated = self._wrap_inline_formula_runs(updated)
            wrapped_lines.append(updated)
        return self._restore_math_blocks("\n".join(wrapped_lines), math_tokens)

    def _wrap_math_command_fragments(self, line: str) -> str:
        if not line or "$" in line:
            return line
        result: list[str] = []
        i = 0
        while i < len(line):
            if line[i] == "\\" and self._starts_known_latex_command(line, i):
                start = i
                i += 1
                while i < len(line) and line[i].isalpha():
                    i += 1
                depth = 0
                while i < len(line):
                    char = line[i]
                    if char in "{[(":
                        depth += 1
                    elif char in "}])" and depth > 0:
                        depth -= 1
                    if depth == 0 and self._is_formula_boundary(char):
                        break
                    i += 1
                fragment = line[start:i].strip()
                if fragment:
                    result.append(f"${fragment}$")
                continue
            result.append(line[i])
            i += 1
        return "".join(result)

    def _wrap_inline_formula_runs(self, line: str) -> str:
        if not line or "$" in line:
            return line
        stripped = line.strip()
        if stripped and not re.search(r"[\u4e00-\u9fff]", stripped):
            if re.search(r"[_^]", stripped) or stripped.count("=") >= 1:
                if re.search(r"[A-Za-z0-9]", stripped):
                    return f"${stripped}$"
        pattern = re.compile(r"([A-Za-z0-9][A-Za-z0-9_{}^()+\-*/=<>., ]{2,}[=_^][A-Za-z0-9_{}^()+\-*/=<>., ]*)")

        def replace(match: re.Match[str]) -> str:
            fragment = match.group(1).strip()
            if "$" in fragment or re.search(r"[\u4e00-\u9fff]", fragment):
                return match.group(1)
            if fragment.count(" ") > 6:
                return match.group(1)
            return f"${fragment}$"

        return pattern.sub(replace, line)

    def _starts_known_latex_command(self, text: str, index: int) -> bool:
        match = re.match(r"\\([A-Za-z]+)", text[index:])
        if not match:
            return False
        return match.group(1) in KNOWN_LATEX_COMMANDS

    def _is_formula_boundary(self, char: str) -> bool:
        if char in "，。；：！？、<>《》“”‘’":
            return True
        if char in "（【":
            return True
        return bool(re.match(r"[\u4e00-\u9fff]", char))

    def _build_solution_markdown(self, content: SolutionCardContent) -> str:
        custom = self._normalize_rich_text(content.markdown_content)
        if custom:
            return custom

        blocks: list[str] = []
        if content.question.strip():
            blocks.append("## 题目\n\n" + self._normalize_rich_text(content.question))
        if content.summary.strip():
            blocks.append("## 概述\n\n" + self._normalize_rich_text(content.summary))
        if content.key_formula.strip():
            blocks.append("## 关键公式\n\n$$\n" + self._strip_formula_wrappers(content.key_formula) + "\n$$")
        if content.answer.strip():
            blocks.append("## 解答\n\n" + self._normalize_rich_text(content.answer))
        steps = [self._normalize_rich_text(step) for step in (content.steps or []) if step and step.strip()]
        if steps:
            step_lines = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
            blocks.append("## 步骤\n\n" + step_lines)
        if content.final_answer.strip():
            blocks.append("## 最终答案\n\n" + self._normalize_rich_text(content.final_answer))
        if content.geometry_scene and self._bool("geometry_section_enabled", True):
            caption = (content.geometry_caption or "").strip() or self._text("geometry_section_default_caption", "按题意生成的几何关系图")
            blocks.append(f"> {caption}")
        return "\n\n".join(blocks)

    def _resolve_layout_mode(self, content: SolutionCardContent) -> str:
        configured = self._text("llm_render_layout_mode", "auto").lower()
        requested = (content.layout_mode or "").strip().lower()
        if requested in {"structured", "free"}:
            return requested
        if configured in {"structured", "free"}:
            return configured
        return "free" if (content.markdown_content or "").strip() else "structured"

    def _render_settings_context(self) -> dict[str, Any]:
        body_font_size = max(self._int("body_font_size_px", 18), 12)
        title_font_size = max(self._int("title_font_size_px", 36), body_font_size + 8)
        subtitle_font_size = max(self._int("subtitle_font_size_px", 18), 12)
        return {
            "body_font_size": body_font_size,
            "body_line_height": self._float("body_line_height", 1.74),
            "title_font_size": title_font_size,
            "subtitle_font_size": subtitle_font_size,
            "formula_font_scale": self._float("formula_font_scale", 1.16),
            "page_padding": max(self._int("page_padding_px", 42), 12),
            "card_radius": max(self._int("card_radius_px", 36), 8),
            "section_radius": max(self._int("section_radius_px", 28), 6),
            "content_max_width": max(self._int("content_max_width_px", 1180), 640),
            "section_gap": max(self._int("section_gap_px", 18), 8),
        }

    def _strip_formula_wrappers(self, formula: str) -> str:
        clean = (formula or "").strip()
        patterns = [
            r"^\$\$(?P<body>.*)\$\$$",
            r"^\\\[(?P<body>.*)\\\]$",
            r"^\\begin\{equation\*?\}(?P<body>.*)\\end\{equation\*?\}$",
        ]
        for pattern in patterns:
            match = re.match(pattern, clean, re.DOTALL)
            if match:
                return match.group("body").strip()
        return clean

    def _should_render_formula_as_markdown(self, raw_formula: str, clean_formula: str) -> bool:
        if self._bool("formula_tool_supports_markdown_content", True):
            if self._looks_like_markdown_block(raw_formula):
                return True
            if self._looks_like_long_plain_paragraph(raw_formula) and not self._looks_like_formula_expression(clean_formula):
                return True
        return False

    def _fallback_formula_placeholder(self) -> str:
        return r"\text{Markdown\ Content}"

    def _looks_like_markdown_block(self, text: str) -> bool:
        candidate = (text or "").strip()
        if not candidate:
            return False
        if re.search(r"(^|\n)\s{0,3}#{1,6}\s+\S", candidate):
            return True
        if re.search(r"(^|\n)\s*[-*+]\s+\S", candidate):
            return True
        if re.search(r"(^|\n)\s*\d+\.\s+\S", candidate):
            return True
        if "```" in candidate:
            return True
        if "|" in candidate and "\n" in candidate:
            return True
        if re.search(r"\*\*[^*]+\*\*|__[^_]+__|`[^`]+`", candidate):
            return True
        return False

    def _looks_like_long_plain_paragraph(self, text: str) -> bool:
        candidate = (text or "").strip()
        return len(candidate) >= 60 and (" " in candidate or "\n" in candidate)

    def _looks_like_formula_expression(self, text: str) -> bool:
        candidate = (text or "").strip()
        if not candidate:
            return False
        math_signals = ("\\", "^", "_", "=", "+", "-", "*", "/", "×", "÷", "(", ")", "{", "}", "$")
        if any(token in candidate for token in math_signals):
            return True
        return bool(re.fullmatch(r"[A-Za-z0-9\s.,:;!?，。；：！？\"'-]+", candidate)) is False

    def _display_theme_name(self, theme_name: str) -> str:
        mapping = {
            "paper": "Paper",
            "notebook": "Notebook",
            "blackboard": "Blackboard",
            "aurora": "Aurora",
        }
        return mapping.get(theme_name, theme_name.title())

    def _normalize_hex_color(self, value: str) -> str:
        candidate = (value or "").strip()
        if not candidate:
            return ""
        if re.fullmatch(r"#?[0-9a-fA-F]{6}", candidate):
            return candidate if candidate.startswith("#") else f"#{candidate}"
        return ""

    def _hex_to_rgba(self, value: str, alpha: float) -> str:
        hex_value = value.lstrip("#")
        if len(hex_value) != 6:
            return value
        red = int(hex_value[0:2], 16)
        green = int(hex_value[2:4], 16)
        blue = int(hex_value[4:6], 16)
        return f"rgba({red}, {green}, {blue}, {alpha:.2f})"

    def _text(self, key: str, default: str) -> str:
        value = self._config.get(key, default)
        return str(value).strip() if value is not None else default

    def _int(self, key: str, default: int) -> int:
        value = self._config.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _float(self, key: str, default: float) -> float:
        value = self._config.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _bool(self, key: str, default: bool) -> bool:
        value = self._config.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _debug(self, message: str, *args: Any) -> None:
        if self._bool("debug_logging_enabled", False):
            logger.debug("[math_render] " + message, *args)


__all__ = [
    "DEFAULT_STYLE",
    "MathRenderService",
    "PLUGIN_NAME",
    "SolutionCardContent",
]
