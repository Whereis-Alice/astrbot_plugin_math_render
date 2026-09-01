"""Lightweight geometry prompt/schema constants.

This module deliberately has no SymPy or Matplotlib imports.  It is imported
when building the solver prompt, while the actual geometry renderer remains
lazy-loaded until a diagram is requested.
"""

from __future__ import annotations


SCENE_JSON_GUIDE = """当题目属于几何题、解析几何、圆、三角形、相似全等、辅助线证明，或画图能显著帮助理解时，可以额外返回 `geometry_scene`。

`geometry_scene` 是一个对象，不是字符串。坐标可以是示意图坐标，重点是关系清晰。

推荐结构：
{
  "caption": "可选说明",
  "viewport": {"padding": 0.16},
  "points": [
    {"name": "A", "x": 0, "y": 0},
    {"name": "B", "x": 6, "y": 0},
    {"name": "M", "type": "midpoint", "points": ["A", "B"]}
  ],
  "segments": [{"from": "A", "to": "B", "style": "primary"}],
  "lines": [{"through": ["A", "B"], "style": "auxiliary"}],
  "rays": [{"from": "A", "to": "B", "style": "highlight"}],
  "circles": [{"center": "A", "through": "B", "style": "primary"}],
  "polygons": [{"points": ["A", "B", "C"], "fill": false}],
  "angle_marks": [{"vertex": "A", "from": "B", "to": "C", "label": "α", "radius": 0.45}],
  "annotations": [{"text": "AB = AC", "at": "A", "offset": [0.18, 0.34]}]
}

`style` 使用 `primary`、`auxiliary`、`highlight` 或 `subtle`。先声明直接坐标点，再声明派生点。常用派生点包括 `midpoint`、`perpendicular_foot`、`line_intersection`、`circle_line_intersection`、`circle_circle_intersection`。不需要图时省略 `geometry_scene`。"""


__all__ = ["SCENE_JSON_GUIDE"]
