from __future__ import annotations

import json
import re
from typing import Any

from .geometry import SCENE_JSON_GUIDE
from .rendering import DEFAULT_STYLE, SolutionCardContent


SOLVER_SYSTEM_PROMPT = """你是一名专门把数学解答整理成高质量图片卡片数据的助手。
你的唯一任务是返回一个合法 JSON，不要输出 JSON 以外的任何文字。

返回结构必须符合下面的对象格式：
{
  "title": "短标题",
  "summary": "1-3 句概述，可含 $...$ 行内公式",
  "answer": "完整正文，可含 Markdown 和 $...$ / $$...$$ 数学公式",
  "steps": ["步骤 1", "步骤 2"],
  "final_answer": "最终答案，可含 $...$ 行内公式",
  "key_formula": "最值得高亮展示的一条公式，不要带 $$",
  "style_hint": "paper | notebook | blackboard | aurora",
  "accent_color": "#RRGGBB 或空字符串",
  "layout_mode": "structured | free",
  "markdown_content": "当你希望整张图自由排版时填写，可写 Markdown，并允许夹带 $...$ 或 $$...$$",
  "geometry_caption": "可选，几何图说明文字",
  "geometry_position": "before_content | after_question | after_key_formula | before_answer | after_answer | after_steps | after_final_answer | after_content",
  "geometry_scene": { }
}

额外规则：
1. 只返回合法 JSON。
2. 如果题目不需要复杂步骤，`steps` 可以为空数组。
3. `key_formula` 可以为空字符串。
4. `style_hint` 只能从 `paper`、`notebook`、`blackboard`、`aurora` 中选择。
5. 如果不是几何题，直接省略 `geometry_scene`，不要硬画图。
6. 如果正文里出现公式，优先使用 `$...$` 或 `$$...$$` 包起来，避免裸写 LaTeX 命令。
7. 如果需要自由排版，请把主要内容写进 `markdown_content`，并把 `layout_mode` 设为 `free`。
8. 默认使用简体中文。"""


def build_solver_prompt(
    question: str,
    *,
    default_style: str = DEFAULT_STYLE,
    max_steps: int = 5,
    layout_mode: str = "auto",
    geometry_enabled: bool = False,
    geometry_prompt: str = "",
) -> str:
    parts = [
        "请解答下面的数学题，并按要求整理成 JSON。",
        f"默认视觉风格优先使用 {default_style}。",
        f"步骤数量尽量不超过 {max_steps} 条。",
        f"默认布局模式偏好：{layout_mode}。",
        "正文中的数学公式请尽量使用 `$...$` 或 `$$...$$` 明确包裹。",
    ]
    if geometry_enabled:
        parts.append((geometry_prompt or SCENE_JSON_GUIDE).strip())
        parts.append(
            "如果你返回 `geometry_scene`，请确保其中至少包含一个可见的点、线、圆、角标或注释，不要返回只有 caption 或 viewport 的空场景。"
            "需要时可以额外返回 `geometry_position`，可选值为 before_content、after_question、after_key_formula、before_answer、after_answer、after_steps、after_final_answer、after_content。"
            "如果是自由排版，优先使用 before_content 或 after_content。"
        )
    parts.append(f"题目：{question.strip()}")
    return "\n\n".join(part for part in parts if part.strip())


def parse_solver_response(raw_text: str, question: str, *, default_style: str = DEFAULT_STYLE) -> SolutionCardContent:
    data = _extract_json_object(raw_text)
    if not data:
        return SolutionCardContent(
            question=question,
            answer=(raw_text or "").strip(),
            title="数学解答",
            style_hint=default_style,
        )

    steps = _normalize_steps(data.get("steps"))
    summary = _clean_text(data.get("summary"))
    final_answer = _clean_text(data.get("final_answer"))
    answer = _clean_text(data.get("answer"))
    if not answer:
        answer = "\n\n".join(part for part in [summary, final_answer] if part)

    geometry_scene = _normalize_geometry_scene(data.get("geometry_scene") or data.get("geometry_scene_json"))
    geometry_caption = _clean_text(data.get("geometry_caption"))
    geometry_position = _clean_geometry_position(data.get("geometry_position"))

    return SolutionCardContent(
        question=question,
        answer=answer,
        title=_clean_text(data.get("title")) or "数学解答",
        summary=summary,
        steps=steps,
        final_answer=final_answer,
        key_formula=_clean_formula(data.get("key_formula")),
        style_hint=_clean_style_hint(data.get("style_hint")) or default_style,
        accent_color=_clean_text(data.get("accent_color")),
        layout_mode=_clean_layout_mode(data.get("layout_mode")),
        markdown_content=_clean_text(data.get("markdown_content")),
        geometry_scene=geometry_scene,
        geometry_caption=geometry_caption,
        geometry_position=geometry_position,
    )


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    text = (raw_text or "").strip()
    if not text:
        return None

    candidates: list[str] = []
    fenced = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    candidates.extend(fenced)

    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}")
        if start < end:
            candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def _normalize_steps(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    steps: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text:
            steps.append(text)
    return steps


def _normalize_geometry_scene(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    if isinstance(value, dict):
        return json.loads(json.dumps(value, ensure_ascii=False))
    text = _clean_text(value)
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _clean_formula(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    patterns = [
        r"^\$\$(?P<body>.*)\$\$$",
        r"^\\\[(?P<body>.*)\\\]$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.DOTALL)
        if match:
            return match.group("body").strip()
    return text


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_layout_mode(value: Any) -> str:
    text = _clean_text(value).lower()
    if text in {"structured", "free"}:
        return text
    return ""


def _clean_geometry_position(value: Any) -> str:
    text = _clean_text(value).lower()
    aliases = {
        "top": "before_content",
        "bottom": "after_content",
        "after_problem": "after_question",
        "after_formula": "after_key_formula",
        "before_solution": "before_answer",
        "after_solution": "after_answer",
        "after_final": "after_final_answer",
    }
    normalized = aliases.get(text, text)
    if normalized in {
        "before_content",
        "after_question",
        "after_key_formula",
        "before_answer",
        "after_answer",
        "after_steps",
        "after_final_answer",
        "after_content",
    }:
        return normalized
    return ""


def _clean_style_hint(value: Any) -> str:
    text = _clean_text(value).lower()
    if text in {"paper", "notebook", "blackboard", "aurora"}:
        return text
    return ""
