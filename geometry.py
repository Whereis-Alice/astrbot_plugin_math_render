from __future__ import annotations

import base64
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt
from matplotlib.patches import Arc, Circle as MplCircle, Polygon as MplPolygon
from sympy.geometry import Circle as SymCircle
from sympy.geometry import Line as SymLine
from sympy.geometry import Point as SymPoint
from sympy.geometry import Segment as SymSegment


DEFAULT_GEOMETRY_LABEL = "几何图"

SCENE_JSON_GUIDE = """当题目属于几何题、解析几何、圆、三角形、相似全等、辅助线证明，或画图能显著帮助理解时，可以额外返回 `geometry_scene`。

`geometry_scene` 是一个对象，不是字符串。它的坐标可以是“示意图坐标”，不要求严格按比例，只要求关系清晰、便于出图。

推荐结构：
{
  "caption": "可选，图的说明文字",
  "viewport": {
    "padding": 0.16
  },
  "points": [
    {"name": "A", "x": 0, "y": 0},
    {"name": "B", "x": 6, "y": 0},
    {"name": "O", "type": "midpoint", "points": ["A", "B"]},
    {"name": "H", "type": "perpendicular_foot", "point": "A", "line": ["B", "C"]}
  ],
  "segments": [
    {"from": "A", "to": "B", "style": "primary"},
    {"from": "C", "to": "H", "style": "auxiliary"}
  ],
  "lines": [
    {"through": ["A", "B"], "style": "auxiliary"}
  ],
  "rays": [
    {"from": "A", "to": "D", "style": "highlight"}
  ],
  "circles": [
    {"center": "O", "through": "A", "style": "primary", "label": "⊙O"}
  ],
  "polygons": [
    {"points": ["A", "B", "C"], "style": "subtle", "fill": false}
  ],
  "angle_marks": [
    {"vertex": "A", "from": "B", "to": "C", "label": "α", "style": "highlight", "radius": 0.45},
    {"vertex": "H", "from": "C", "to": "B", "right_angle": true}
  ],
  "annotations": [
    {"text": "AB = AC", "at": "A", "offset": [0.18, 0.34]}
  ]
}

约定：
1. `style` 可选值建议使用 `primary`、`auxiliary`、`highlight`、`subtle`。
2. `points` 建议先声明直接坐标点，再声明依赖它们的派生点。
3. 派生点目前最稳妥的是：
   - `midpoint`
   - `perpendicular_foot`
   - `line_intersection`
   - `circle_line_intersection`
   - `circle_circle_intersection`
4. 若不需要几何图，直接省略 `geometry_scene`。"""


@dataclass(slots=True)
class GeometryRenderResult:
    path: Path
    data_uri: str
    caption: str
    scene: dict[str, Any]


class GeometrySceneError(ValueError):
    pass


class GeometryRenderer:
    def __init__(
        self,
        *,
        config: dict[str, Any] | None,
        temp_dir: Path,
        debug: Callable[[str, Any], None] | None = None,
    ) -> None:
        self._config = config or {}
        self._temp_dir = temp_dir
        self._debug_cb = debug

    def render_scene(self, scene_input: str | dict[str, Any]) -> GeometryRenderResult:
        scene = self.parse_scene(scene_input)
        if self._bool("geometry_skip_blank_scene_enabled", True) and not self.has_drawable_content(scene):
            raise GeometrySceneError("geometry scene has no drawable elements")
        cache_key = self._make_cache_key(scene)
        target_path = self._temp_dir / f"geometry_{cache_key}.png"
        if self._bool("enable_cache", True) and target_path.exists():
            target_path.touch()
            return GeometryRenderResult(
                path=target_path,
                data_uri=self._image_to_data_uri(target_path),
                caption=self._scene_caption(scene),
                scene=scene,
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        scene_objects = self._build_scene(scene)
        self._draw_scene(scene, scene_objects, target_path)
        return GeometryRenderResult(
            path=target_path,
            data_uri=self._image_to_data_uri(target_path),
            caption=self._scene_caption(scene),
            scene=scene,
        )

    def parse_scene(self, scene_input: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(scene_input, dict):
            scene = json.loads(json.dumps(scene_input, ensure_ascii=False))
        else:
            raw = self._strip_code_fence(str(scene_input or ""))
            if not raw:
                raise GeometrySceneError("geometry scene is empty")
            try:
                scene = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise GeometrySceneError(f"invalid geometry scene json: {exc}") from exc

        if not isinstance(scene, dict):
            raise GeometrySceneError("geometry scene must be a JSON object")

        normalized = dict(scene)
        for key in ("points", "segments", "lines", "rays", "circles", "polygons", "angle_marks", "annotations"):
            value = normalized.get(key, [])
            if value is None:
                value = []
            if not isinstance(value, list):
                raise GeometrySceneError(f"`{key}` must be an array")
            normalized[key] = value
        viewport = normalized.get("viewport", {})
        if viewport is None:
            viewport = {}
        if not isinstance(viewport, dict):
            raise GeometrySceneError("`viewport` must be an object when provided")
        normalized["viewport"] = viewport
        return normalized

    def has_drawable_content(self, scene_input: str | dict[str, Any]) -> bool:
        summary = self.scene_summary(scene_input)
        return bool(summary["visible_points"] or summary["drawable_objects"])

    def scene_summary(self, scene_input: str | dict[str, Any]) -> dict[str, int]:
        scene = scene_input if isinstance(scene_input, dict) else self.parse_scene(scene_input)
        normalized = self.parse_scene(scene)
        visible_points = 0
        for entry in normalized.get("points", []):
            if not isinstance(entry, dict):
                continue
            if bool(entry.get("show", True)) or bool(entry.get("show_label", True)):
                visible_points += 1

        drawable_objects = sum(
            len(normalized.get(key, []))
            for key in ("segments", "lines", "rays", "circles", "polygons", "angle_marks", "annotations")
        )
        return {
            "points": len(normalized.get("points", [])),
            "visible_points": visible_points,
            "segments": len(normalized.get("segments", [])),
            "lines": len(normalized.get("lines", [])),
            "rays": len(normalized.get("rays", [])),
            "circles": len(normalized.get("circles", [])),
            "polygons": len(normalized.get("polygons", [])),
            "angle_marks": len(normalized.get("angle_marks", [])),
            "annotations": len(normalized.get("annotations", [])),
            "drawable_objects": drawable_objects,
        }

    def describe_scene(self, scene_input: str | dict[str, Any]) -> str:
        summary = self.scene_summary(scene_input)
        return (
            "points={points} visible_points={visible_points} segments={segments} lines={lines} "
            "rays={rays} circles={circles} polygons={polygons} angle_marks={angle_marks} "
            "annotations={annotations} drawable_objects={drawable_objects}"
        ).format(**summary)

    def _build_scene(self, scene: dict[str, Any]) -> dict[str, Any]:
        points: dict[str, SymPoint] = {}
        point_meta: dict[str, dict[str, Any]] = {}
        for entry in scene.get("points", []):
            if not isinstance(entry, dict):
                raise GeometrySceneError("each point must be an object")
            name = self._required_text(entry, "name")
            point = self._resolve_point_entry(entry, points)
            points[name] = point
            point_meta[name] = {
                "label": self._text_from(entry.get("label")) or name,
                "show": bool(entry.get("show", True)),
                "show_label": bool(entry.get("show_label", True)),
                "offset": self._pair(entry.get("offset"), default=(0.12, 0.12)),
                "style": self._style_name(entry.get("style"), default="primary"),
            }

        return {
            "points": points,
            "point_meta": point_meta,
        }

    def _resolve_point_entry(self, entry: dict[str, Any], points: dict[str, SymPoint]) -> SymPoint:
        if "x" in entry and "y" in entry:
            return SymPoint(float(entry["x"]), float(entry["y"]))

        point_type = self._text_from(entry.get("type")).lower()
        if not point_type:
            raise GeometrySceneError(f"point `{entry.get('name', '?')}` is missing coordinates or type")

        if point_type == "midpoint":
            p1, p2 = self._point_pair(entry.get("points"), points, "midpoint")
            return SymSegment(p1, p2).midpoint

        if point_type == "perpendicular_foot":
            source = self._point_ref(entry.get("point"), points, "perpendicular_foot")
            p1, p2 = self._point_pair(entry.get("line"), points, "perpendicular_foot line")
            return SymLine(p1, p2).projection(source)

        if point_type == "line_intersection":
            a1, a2 = self._point_pair(entry.get("line1"), points, "line1")
            b1, b2 = self._point_pair(entry.get("line2"), points, "line2")
            intersections = SymLine(a1, a2).intersection(SymLine(b1, b2))
            return self._pick_intersection(intersections, entry, points, point_type)

        if point_type == "circle_line_intersection":
            circle = self._build_circle(entry, points)
            p1, p2 = self._point_pair(entry.get("line"), points, "circle_line_intersection line")
            intersections = circle.intersection(SymLine(p1, p2))
            return self._pick_intersection(intersections, entry, points, point_type)

        if point_type == "circle_circle_intersection":
            circle1 = self._build_circle(entry.get("circle1"), points)
            circle2 = self._build_circle(entry.get("circle2"), points)
            intersections = circle1.intersection(circle2)
            return self._pick_intersection(intersections, entry, points, point_type)

        raise GeometrySceneError(f"unsupported point type: {point_type}")

    def _build_circle(self, entry: Any, points: dict[str, SymPoint]) -> SymCircle:
        if not isinstance(entry, dict):
            raise GeometrySceneError("circle definition must be an object")
        center = self._point_ref(entry.get("center"), points, "circle center")
        through_name = self._text_from(entry.get("through"))
        radius_value = entry.get("radius")
        if through_name:
            through = self._point_ref(through_name, points, "circle through")
            return SymCircle(center, through)
        if radius_value is None:
            raise GeometrySceneError("circle needs either `through` or `radius`")
        return SymCircle(center, float(radius_value))

    def _pick_intersection(
        self,
        intersections: list[Any],
        entry: dict[str, Any],
        points: dict[str, SymPoint],
        context: str,
    ) -> SymPoint:
        candidates = [item for item in intersections if isinstance(item, SymPoint)]
        if not candidates:
            raise GeometrySceneError(f"{context} has no point intersection")
        if len(candidates) == 1:
            return candidates[0]

        nearest_to = self._text_from(entry.get("nearest_to"))
        if nearest_to:
            ref = self._point_ref(nearest_to, points, f"{context} nearest_to")
            return min(candidates, key=lambda item: float(item.distance(ref)))

        farthest_from = self._text_from(entry.get("farthest_from"))
        if farthest_from:
            ref = self._point_ref(farthest_from, points, f"{context} farthest_from")
            return max(candidates, key=lambda item: float(item.distance(ref)))

        try:
            index = int(entry.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        if index < 0 or index >= len(candidates):
            index = 0
        ordered = sorted(candidates, key=lambda item: (float(item.x), float(item.y)))
        return ordered[index]

    def _draw_scene(self, scene: dict[str, Any], scene_objects: dict[str, Any], target_path: Path) -> None:
        points: dict[str, SymPoint] = scene_objects["points"]
        point_meta: dict[str, dict[str, Any]] = scene_objects["point_meta"]
        bounds = self._compute_bounds(scene, points)

        figure_width = max(self._float("geometry_figure_width_in", 6.8), 3.0)
        figure_height = max(self._float("geometry_figure_height_in", 5.2), 2.6)
        dpi = max(self._int("geometry_dpi", 220), 96)
        transparent = self._bool("geometry_transparent_background", True)
        background = self._text("geometry_background_color", "#FFFFFF") or "#FFFFFF"

        fig, ax = plt.subplots(figsize=(figure_width, figure_height), dpi=dpi)
        try:
            if transparent:
                fig.patch.set_alpha(0)
                ax.set_facecolor((1, 1, 1, 0))
            else:
                fig.patch.set_facecolor(background)
                ax.set_facecolor(background)

            ax.set_aspect("equal", adjustable="box")
            ax.axis("off")
            ax.set_xlim(bounds[0], bounds[1])
            ax.set_ylim(bounds[2], bounds[3])

            self._draw_polygons(ax, scene, points)
            self._draw_circles(ax, scene, points)
            self._draw_lines(ax, scene, points, bounds)
            self._draw_rays(ax, scene, points, bounds)
            self._draw_segments(ax, scene, points)
            self._draw_angle_marks(ax, scene, points)
            self._draw_points(ax, points, point_meta)
            self._draw_annotations(ax, scene, points)

            fig.tight_layout(pad=0.18)
            fig.savefig(
                target_path,
                format="png",
                dpi=dpi,
                bbox_inches="tight",
                transparent=transparent,
                pad_inches=0.08,
            )
        finally:
            plt.close(fig)

    def _draw_segments(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint]) -> None:
        for entry in scene.get("segments", []):
            if not isinstance(entry, dict):
                continue
            p1 = self._point_ref(entry.get("from"), points, "segment from")
            p2 = self._point_ref(entry.get("to"), points, "segment to")
            style = self._style(entry.get("style"))
            ax.plot(
                [float(p1.x), float(p2.x)],
                [float(p1.y), float(p2.y)],
                color=style["color"],
                linewidth=style["line_width"],
                linestyle=style["line_style"],
                alpha=style["alpha"],
                zorder=style["zorder"],
            )
            label = self._text_from(entry.get("label"))
            if label:
                midpoint = ((float(p1.x) + float(p2.x)) / 2.0, (float(p1.y) + float(p2.y)) / 2.0)
                self._draw_text(
                    ax,
                    label,
                    midpoint[0],
                    midpoint[1],
                    offset=self._pair(entry.get("offset"), default=(0.0, 0.16)),
                    color=style["color"],
                    font_size=self._int("geometry_annotation_font_size", 11),
                )

    def _draw_lines(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint], bounds: tuple[float, float, float, float]) -> None:
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], 1.0) * 2.2
        for entry in scene.get("lines", []):
            if not isinstance(entry, dict):
                continue
            p1, p2 = self._point_pair(entry.get("through"), points, "line through")
            dx = float(p2.x - p1.x)
            dy = float(p2.y - p1.y)
            length = math.hypot(dx, dy)
            if length <= 1e-9:
                continue
            ux = dx / length
            uy = dy / length
            style = self._style(entry.get("style"), default="auxiliary")
            start = (float(p1.x) - ux * span, float(p1.y) - uy * span)
            end = (float(p1.x) + ux * span, float(p1.y) + uy * span)
            ax.plot(
                [start[0], end[0]],
                [start[1], end[1]],
                color=style["color"],
                linewidth=style["line_width"],
                linestyle=style["line_style"],
                alpha=style["alpha"],
                zorder=style["zorder"],
            )

    def _draw_rays(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint], bounds: tuple[float, float, float, float]) -> None:
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], 1.0) * 2.2
        for entry in scene.get("rays", []):
            if not isinstance(entry, dict):
                continue
            p1 = self._point_ref(entry.get("from"), points, "ray from")
            p2 = self._point_ref(entry.get("to"), points, "ray to")
            dx = float(p2.x - p1.x)
            dy = float(p2.y - p1.y)
            length = math.hypot(dx, dy)
            if length <= 1e-9:
                continue
            ux = dx / length
            uy = dy / length
            style = self._style(entry.get("style"))
            end = (float(p1.x) + ux * span, float(p1.y) + uy * span)
            ax.plot(
                [float(p1.x), end[0]],
                [float(p1.y), end[1]],
                color=style["color"],
                linewidth=style["line_width"],
                linestyle=style["line_style"],
                alpha=style["alpha"],
                zorder=style["zorder"],
            )

    def _draw_circles(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint]) -> None:
        for entry in scene.get("circles", []):
            if not isinstance(entry, dict):
                continue
            circle = self._build_circle(entry, points)
            center = circle.center
            radius = float(circle.radius)
            style_name = self._style_name(entry.get("style"), default="primary")
            style = self._style(style_name, override_color=self._text("geometry_circle_color", ""))
            patch = MplCircle(
                (float(center.x), float(center.y)),
                radius,
                fill=False,
                linewidth=style["line_width"],
                linestyle=style["line_style"],
                edgecolor=style["color"],
                alpha=style["alpha"],
                zorder=style["zorder"],
            )
            ax.add_patch(patch)
            label = self._text_from(entry.get("label"))
            if label:
                self._draw_text(
                    ax,
                    label,
                    float(center.x),
                    float(center.y),
                    offset=self._pair(entry.get("offset"), default=(radius * 0.55, radius * 0.55)),
                    color=style["color"],
                    font_size=self._int("geometry_annotation_font_size", 11),
                )

    def _draw_polygons(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint]) -> None:
        fill_alpha = max(min(self._float("geometry_fill_alpha", 0.12), 1.0), 0.0)
        fill_color = self._text("geometry_fill_color", "#93C5FD") or "#93C5FD"
        for entry in scene.get("polygons", []):
            if not isinstance(entry, dict):
                continue
            names = entry.get("points")
            if not isinstance(names, list) or len(names) < 2:
                continue
            vertices = []
            for name in names:
                point = self._point_ref(name, points, "polygon point")
                vertices.append((float(point.x), float(point.y)))
            style = self._style(entry.get("style"), default="subtle")
            patch = MplPolygon(
                vertices,
                closed=bool(entry.get("closed", True)),
                fill=bool(entry.get("fill", False)),
                facecolor=fill_color if bool(entry.get("fill", False)) else "none",
                edgecolor=style["color"],
                linewidth=style["line_width"],
                linestyle=style["line_style"],
                alpha=fill_alpha if bool(entry.get("fill", False)) else style["alpha"],
                zorder=max(style["zorder"] - 1, 1),
            )
            ax.add_patch(patch)

    def _draw_angle_marks(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint]) -> None:
        default_radius = max(self._float("geometry_default_angle_radius", 0.42), 0.12)
        radius_step = max(self._float("geometry_angle_radius_step", 0.08), 0.04)
        default_color = self._text("geometry_angle_color", "") or self._text("geometry_highlight_color", "#EA580C") or "#EA580C"
        for entry in scene.get("angle_marks", []):
            if not isinstance(entry, dict):
                continue
            vertex = self._point_ref(entry.get("vertex"), points, "angle vertex")
            from_point = self._point_ref(entry.get("from"), points, "angle from")
            to_point = self._point_ref(entry.get("to"), points, "angle to")
            radius = float(entry.get("radius", default_radius))
            count = max(int(entry.get("count", 1) or 1), 1)
            style = self._style(entry.get("style"), default="highlight", override_color=default_color)

            vx = float(vertex.x)
            vy = float(vertex.y)
            angle1 = math.degrees(math.atan2(float(from_point.y - vertex.y), float(from_point.x - vertex.x)))
            angle2 = math.degrees(math.atan2(float(to_point.y - vertex.y), float(to_point.x - vertex.x)))
            start, sweep = self._normalize_angle_pair(angle1, angle2)

            right_angle = bool(entry.get("right_angle", False)) or abs(sweep - 90.0) <= 3.5
            if right_angle:
                self._draw_right_angle(ax, vertex, from_point, to_point, radius, style)
            else:
                for index in range(count):
                    patch = Arc(
                        (vx, vy),
                        width=(radius + radius_step * index) * 2.0,
                        height=(radius + radius_step * index) * 2.0,
                        theta1=start,
                        theta2=start + sweep,
                        color=style["color"],
                        linewidth=style["line_width"],
                        linestyle=style["line_style"],
                        alpha=style["alpha"],
                        zorder=style["zorder"] + 1,
                    )
                    ax.add_patch(patch)

            label = self._text_from(entry.get("label"))
            if label:
                label_angle = math.radians(start + sweep / 2.0)
                label_radius = radius + radius_step * count + 0.06
                x = vx + math.cos(label_angle) * label_radius
                y = vy + math.sin(label_angle) * label_radius
                self._draw_text(
                    ax,
                    label,
                    x,
                    y,
                    offset=(0.0, 0.0),
                    color=style["color"],
                    font_size=self._int("geometry_annotation_font_size", 11),
                )

    def _draw_right_angle(
        self,
        ax: Any,
        vertex: SymPoint,
        from_point: SymPoint,
        to_point: SymPoint,
        radius: float,
        style: dict[str, Any],
    ) -> None:
        vx = float(vertex.x)
        vy = float(vertex.y)
        ux1, uy1 = self._unit_vector(vertex, from_point)
        ux2, uy2 = self._unit_vector(vertex, to_point)
        p1 = (vx + ux1 * radius, vy + uy1 * radius)
        p2 = (p1[0] + ux2 * radius * 0.72, p1[1] + uy2 * radius * 0.72)
        p3 = (vx + ux2 * radius, vy + uy2 * radius)
        ax.plot(
            [p1[0], p2[0], p3[0]],
            [p1[1], p2[1], p3[1]],
            color=style["color"],
            linewidth=style["line_width"],
            linestyle=style["line_style"],
            alpha=style["alpha"],
            zorder=style["zorder"] + 1,
        )

    def _draw_points(self, ax: Any, points: dict[str, SymPoint], point_meta: dict[str, dict[str, Any]]) -> None:
        base_size = max(self._int("geometry_point_size", 46), 12)
        label_size = max(self._int("geometry_label_font_size", 13), 8)
        default_color = self._text("geometry_point_color", "") or self._text("geometry_primary_color", "#1D4ED8") or "#1D4ED8"
        for name, point in points.items():
            meta = point_meta.get(name, {})
            style = self._style(meta.get("style"), default="primary", override_color=default_color)
            x = float(point.x)
            y = float(point.y)
            if meta.get("show", True):
                size = base_size * (1.25 if meta.get("style") == "highlight" else 1.0)
                ax.scatter([x], [y], s=size, c=style["color"], zorder=style["zorder"] + 2)
            if meta.get("show_label", True):
                self._draw_text(
                    ax,
                    meta.get("label") or name,
                    x,
                    y,
                    offset=self._pair(meta.get("offset"), default=(0.12, 0.12)),
                    color=self._text("geometry_text_color", "#0F172A") or "#0F172A",
                    font_size=label_size,
                )

    def _draw_annotations(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint]) -> None:
        font_size = max(self._int("geometry_annotation_font_size", 11), 8)
        default_color = self._text("geometry_text_color", "#0F172A") or "#0F172A"
        for entry in scene.get("annotations", []):
            if not isinstance(entry, dict):
                continue
            text = self._text_from(entry.get("text"))
            if not text:
                continue
            offset = self._pair(entry.get("offset"), default=(0.0, 0.0))
            if "at" in entry:
                point = self._point_ref(entry.get("at"), points, "annotation at")
                x = float(point.x)
                y = float(point.y)
            else:
                x = float(entry.get("x", 0.0))
                y = float(entry.get("y", 0.0))
            self._draw_text(
                ax,
                text,
                x,
                y,
                offset=offset,
                color=self._text_from(entry.get("color")) or default_color,
                font_size=font_size,
            )

    def _draw_text(
        self,
        ax: Any,
        text: str,
        x: float,
        y: float,
        *,
        offset: tuple[float, float],
        color: str,
        font_size: int,
    ) -> None:
        label = self._normalize_plot_text(text)
        ax.text(
            x + offset[0],
            y + offset[1],
            label,
            fontsize=font_size,
            color=color,
            ha="left",
            va="bottom",
            zorder=8,
            bbox={
                "boxstyle": "round,pad=0.16",
                "fc": (1, 1, 1, 0.64),
                "ec": "none",
            },
        )

    def _normalize_plot_text(self, text: str) -> str:
        candidate = (text or "").strip()
        if not candidate:
            return ""
        if "$" in candidate:
            return candidate
        if any(token in candidate for token in ("\\", "^", "_", "{", "}")):
            return f"${candidate}$"
        return candidate

    def _compute_bounds(self, scene: dict[str, Any], points: dict[str, SymPoint]) -> tuple[float, float, float, float]:
        xs = [float(point.x) for point in points.values()]
        ys = [float(point.y) for point in points.values()]
        for entry in scene.get("circles", []):
            if not isinstance(entry, dict):
                continue
            try:
                circle = self._build_circle(entry, points)
            except Exception:
                continue
            center = circle.center
            radius = float(circle.radius)
            xs.extend([float(center.x) - radius, float(center.x) + radius])
            ys.extend([float(center.y) - radius, float(center.y) + radius])

        if not xs or not ys:
            xs = [0.0, 1.0]
            ys = [0.0, 1.0]

        viewport = scene.get("viewport", {})
        xlim = viewport.get("xlim")
        ylim = viewport.get("ylim")
        if isinstance(xlim, list) and len(xlim) == 2 and isinstance(ylim, list) and len(ylim) == 2:
            return (float(xlim[0]), float(xlim[1]), float(ylim[0]), float(ylim[1]))

        xmin = float(min(xs))
        xmax = float(max(xs))
        ymin = float(min(ys))
        ymax = float(max(ys))
        span_x = xmax - xmin
        span_y = ymax - ymin
        min_span = max(self._float("geometry_min_span", 2.0), 0.5)
        if span_x < min_span:
            center_x = (xmin + xmax) / 2.0
            xmin = center_x - min_span / 2.0
            xmax = center_x + min_span / 2.0
            span_x = min_span
        if span_y < min_span:
            center_y = (ymin + ymax) / 2.0
            ymin = center_y - min_span / 2.0
            ymax = center_y + min_span / 2.0
            span_y = min_span

        padding_ratio = float(viewport.get("padding", self._float("geometry_padding_ratio", 0.16)))
        padding_x = max(span_x * padding_ratio, 0.2)
        padding_y = max(span_y * padding_ratio, 0.2)
        return (xmin - padding_x, xmax + padding_x, ymin - padding_y, ymax + padding_y)

    def _style(self, style_name: Any, *, default: str = "primary", override_color: str = "") -> dict[str, Any]:
        line_width = max(self._float("geometry_line_width", 2.2), 0.6)
        primary = self._text("geometry_primary_color", "#1D4ED8") or "#1D4ED8"
        auxiliary = self._text("geometry_auxiliary_color", "#64748B") or "#64748B"
        highlight = self._text("geometry_highlight_color", "#EA580C") or "#EA580C"
        subtle = self._text("geometry_subtle_color", "#94A3B8") or "#94A3B8"
        name = self._style_name(style_name, default=default)
        style_map = {
            "primary": {
                "color": primary,
                "line_width": line_width,
                "line_style": "-",
                "alpha": 0.96,
                "zorder": 3,
            },
            "auxiliary": {
                "color": auxiliary,
                "line_width": max(line_width * 0.92, 0.6),
                "line_style": "--",
                "alpha": 0.88,
                "zorder": 2,
            },
            "highlight": {
                "color": highlight,
                "line_width": line_width * 1.18,
                "line_style": "-",
                "alpha": 0.98,
                "zorder": 4,
            },
            "subtle": {
                "color": subtle,
                "line_width": max(line_width * 0.84, 0.55),
                "line_style": "-.",
                "alpha": 0.78,
                "zorder": 1,
            },
        }
        style = dict(style_map.get(name, style_map[default]))
        if override_color:
            style["color"] = override_color
        return style

    def _style_name(self, value: Any, *, default: str) -> str:
        candidate = self._text_from(value).lower()
        if candidate in {"primary", "auxiliary", "highlight", "subtle"}:
            return candidate
        return default

    def _normalize_angle_pair(self, angle1: float, angle2: float) -> tuple[float, float]:
        start = angle1 % 360.0
        end = angle2 % 360.0
        sweep = (end - start) % 360.0
        if sweep > 180.0:
            start = end
            sweep = (angle1 - angle2) % 360.0
        return start, sweep

    def _unit_vector(self, source: SymPoint, target: SymPoint) -> tuple[float, float]:
        dx = float(target.x - source.x)
        dy = float(target.y - source.y)
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return (1.0, 0.0)
        return (dx / length, dy / length)

    def _point_pair(
        self,
        value: Any,
        points: dict[str, SymPoint],
        context: str,
    ) -> tuple[SymPoint, SymPoint]:
        if not isinstance(value, list) or len(value) != 2:
            raise GeometrySceneError(f"{context} must contain exactly two point names")
        return (
            self._point_ref(value[0], points, context),
            self._point_ref(value[1], points, context),
        )

    def _point_ref(self, value: Any, points: dict[str, SymPoint], context: str) -> SymPoint:
        name = self._text_from(value)
        if not name:
            raise GeometrySceneError(f"{context} point reference is empty")
        if name not in points:
            raise GeometrySceneError(f"{context} references unknown point `{name}`")
        return points[name]

    def _pair(self, value: Any, *, default: tuple[float, float]) -> tuple[float, float]:
        if isinstance(value, list) and len(value) == 2:
            try:
                return (float(value[0]), float(value[1]))
            except (TypeError, ValueError):
                return default
        if isinstance(value, tuple) and len(value) == 2:
            try:
                return (float(value[0]), float(value[1]))
            except (TypeError, ValueError):
                return default
        return default

    def _scene_caption(self, scene: dict[str, Any]) -> str:
        return self._text_from(scene.get("caption")) or self._text("geometry_section_default_caption", "按题意生成的几何关系图")

    def _required_text(self, payload: dict[str, Any], key: str) -> str:
        value = self._text_from(payload.get(key))
        if not value:
            raise GeometrySceneError(f"`{key}` is required")
        return value

    def _strip_code_fence(self, text: str) -> str:
        candidate = (text or "").strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            if "\n" in candidate:
                _, rest = candidate.split("\n", 1)
                candidate = rest
            if candidate.endswith("```"):
                candidate = candidate[:-3]
        return candidate.strip()

    def _image_to_data_uri(self, path: Path) -> str:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _make_cache_key(self, scene: dict[str, Any]) -> str:
        raw = json.dumps(scene, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

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

    def _text_from(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _debug(self, message: str, *args: Any) -> None:
        if self._debug_cb:
            self._debug_cb(message, *args)


__all__ = [
    "DEFAULT_GEOMETRY_LABEL",
    "GeometryRenderResult",
    "GeometryRenderer",
    "GeometrySceneError",
    "SCENE_JSON_GUIDE",
]
