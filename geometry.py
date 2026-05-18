from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")

from matplotlib import font_manager, patheffects, pyplot as plt
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

        if self._looks_like_legacy_scene(scene):
            scene = self._normalize_legacy_scene(scene)
        else:
            scene = self._normalize_scene_aliases(scene)

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

    def _normalize_scene_aliases(self, scene: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(scene)
        collection_normalizers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "points": self._normalize_point_aliases,
            "segments": self._normalize_segment_aliases,
            "lines": self._normalize_line_aliases,
            "rays": self._normalize_ray_aliases,
            "circles": self._normalize_circle_aliases,
            "polygons": self._normalize_polygon_aliases,
            "angle_marks": self._normalize_angle_mark_aliases,
            "annotations": self._normalize_annotation_aliases,
        }
        for key, normalizer in collection_normalizers.items():
            value = normalized.get(key)
            if not isinstance(value, list):
                continue
            normalized[key] = [
                normalizer(entry)
                for entry in value
            ]
        self._coerce_misplaced_line_entries(normalized)
        self._maybe_flip_screen_coordinates(normalized)
        self._rebuild_semicircle_geometry(normalized)
        self._infer_compact_circle_types(normalized)
        self._merge_point_label_annotations(normalized)
        return normalized

    def _coerce_misplaced_line_entries(self, scene: dict[str, Any]) -> None:
        lines = scene.get("lines")
        if not isinstance(lines, list):
            return

        segments = scene.get("segments")
        if not isinstance(segments, list):
            segments = []
            scene["segments"] = segments

        kept_lines: list[Any] = []
        moved = 0
        for entry in lines:
            if not isinstance(entry, dict):
                kept_lines.append(entry)
                continue

            through = entry.get("through")
            from_name = self._text_from(entry.get("from"))
            to_name = self._text_from(entry.get("to"))
            if isinstance(through, list):
                kept_lines.append(entry)
                continue
            if not from_name or not to_name:
                kept_lines.append(entry)
                continue

            segments.append(self._normalize_segment_aliases(entry))
            moved += 1

        if moved:
            scene["lines"] = kept_lines
            self._debug("geometry coerced misplaced lines into segments: moved=%s", moved)

    def _label_position_value(self, entry: dict[str, Any]) -> str:
        return (
            self._text_from(entry.get("labelPosition"))
            or self._text_from(entry.get("label_position"))
            or self._text_from(entry.get("label_position_name"))
        )

    def _label_position_key(self, value: Any) -> str:
        return re.sub(r"[^a-z]", "", self._text_from(value).lower())

    def _offset_from_label_position(
        self,
        value: Any,
        *,
        default: tuple[float, float],
    ) -> list[float] | None:
        position = self._label_position_key(value)
        if not position:
            return None

        alias_map = {
            "north": (0, 1),
            "south": (0, -1),
            "east": (1, 0),
            "west": (-1, 0),
            "northeast": (1, 1),
            "northwest": (-1, 1),
            "southeast": (1, -1),
            "southwest": (-1, -1),
            "above": (0, 1),
            "below": (0, -1),
            "left": (-1, 0),
            "right": (1, 0),
            "center": (0, 0),
            "middle": (0, 0),
        }
        direction = alias_map.get(position)
        if direction is None:
            return None

        base = max(abs(default[0]), abs(default[1]), 0.18)
        diagonal_scale = 1.2 if abs(direction[0]) and abs(direction[1]) else 1.0
        return [
            float(direction[0]) * base * diagonal_scale,
            float(direction[1]) * base * diagonal_scale,
        ]

    def _offset_points_from_label_position(self, value: Any, *, distance: float = 8.0) -> list[float] | None:
        position = self._label_position_key(value)
        if not position:
            return None

        alias_map = {
            "north": (0, 1),
            "south": (0, -1),
            "east": (1, 0),
            "west": (-1, 0),
            "northeast": (1, 1),
            "northwest": (-1, 1),
            "southeast": (1, -1),
            "southwest": (-1, -1),
            "above": (0, 1),
            "below": (0, -1),
            "left": (-1, 0),
            "right": (1, 0),
            "center": (0, 0),
            "middle": (0, 0),
        }
        direction = alias_map.get(position)
        if direction is None:
            return None

        diagonal_scale = 0.9 if abs(direction[0]) and abs(direction[1]) else 1.0
        return [
            float(direction[0]) * distance * diagonal_scale,
            float(direction[1]) * distance * diagonal_scale,
        ]

    def _alignment_from_label_position(self, value: Any) -> tuple[str, str] | None:
        position = self._label_position_key(value)
        if not position:
            return None

        alignment_map = {
            "north": ("center", "bottom"),
            "south": ("center", "top"),
            "east": ("left", "center"),
            "west": ("right", "center"),
            "northeast": ("left", "bottom"),
            "northwest": ("right", "bottom"),
            "southeast": ("left", "top"),
            "southwest": ("right", "top"),
            "above": ("center", "bottom"),
            "below": ("center", "top"),
            "left": ("right", "center"),
            "right": ("left", "center"),
            "center": ("center", "center"),
            "middle": ("center", "center"),
        }
        return alignment_map.get(position)

    def _apply_label_position_defaults(
        self,
        normalized: dict[str, Any],
        *,
        distance_points: float,
    ) -> None:
        position = self._label_position_value(normalized)
        if not position:
            return

        if "offset_points" not in normalized:
            offset_points = self._offset_points_from_label_position(position, distance=distance_points)
            if offset_points is not None:
                normalized["offset_points"] = offset_points

        if "ha" not in normalized or "va" not in normalized:
            alignment = self._alignment_from_label_position(position)
            if alignment is not None:
                normalized.setdefault("ha", alignment[0])
                normalized.setdefault("va", alignment[1])

    def _rebuild_semicircle_geometry(self, scene: dict[str, Any]) -> None:
        points = scene.get("points")
        circles = scene.get("circles")
        segments = scene.get("segments")
        if not isinstance(points, list) or not isinstance(circles, list) or not isinstance(segments, list):
            return

        point_entries: dict[str, dict[str, Any]] = {}
        point_coords: dict[str, tuple[float, float]] = {}
        for entry in points:
            if not isinstance(entry, dict):
                continue
            name = self._text_from(entry.get("name"))
            if not name:
                continue
            coords = self._point_coords_from_entry(entry)
            if coords is None:
                continue
            point_entries[name] = entry
            point_coords[name] = coords

        if len(point_coords) < 3:
            return

        adjacency = self._segment_adjacency(segments)
        segment_pairs = {
            frozenset((self._text_from(entry.get("from")), self._text_from(entry.get("to"))))
            for entry in segments
            if isinstance(entry, dict)
            and self._text_from(entry.get("from"))
            and self._text_from(entry.get("to"))
        }

        for circle in circles:
            if not isinstance(circle, dict):
                continue
            orientation_key = self._semicircle_orientation_key(circle)
            if not orientation_key:
                continue
            center_coords = self._point_coords_from_value(circle.get("center"), point_coords)
            if center_coords is None:
                continue

            diameter = self._find_semicircle_diameter(
                center=center_coords,
                orientation_key=orientation_key,
                point_coords=point_coords,
                segment_pairs=segment_pairs,
            )
            if diameter is None:
                continue

            first_name, second_name = diameter
            first = point_coords[first_name]
            second = point_coords[second_name]
            radius = math.hypot(second[0] - first[0], second[1] - first[1]) / 2.0
            if radius <= 1e-6:
                continue

            circle["radius"] = radius
            circle["through"] = first_name
            circle.setdefault("style", "primary")

            center_name = self._name_for_coords(center_coords, point_coords)
            self._project_semicircle_points(
                orientation_key=orientation_key,
                center=center_coords,
                center_name=center_name,
                radius=radius,
                diameter=(first_name, second_name),
                point_entries=point_entries,
                point_coords=point_coords,
                adjacency=adjacency,
            )

    def _find_semicircle_diameter(
        self,
        *,
        center: tuple[float, float],
        orientation_key: str,
        point_coords: dict[str, tuple[float, float]],
        segment_pairs: set[frozenset[str]],
    ) -> tuple[str, str] | None:
        names = list(point_coords.keys())
        if len(names) < 2:
            return None

        xs = [coords[0] for coords in point_coords.values()]
        ys = [coords[1] for coords in point_coords.values()]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        tolerance = max(span * 0.03, 2.0)
        horizontal = orientation_key in {"upper", "lower"}

        best_pair: tuple[str, str] | None = None
        best_score: tuple[int, float] | None = None
        cx, cy = center

        for index, first_name in enumerate(names):
            x1, y1 = point_coords[first_name]
            for second_name in names[index + 1 :]:
                x2, y2 = point_coords[second_name]
                if horizontal:
                    if abs(y1 - cy) > tolerance or abs(y2 - cy) > tolerance:
                        continue
                else:
                    if abs(x1 - cx) > tolerance or abs(x2 - cx) > tolerance:
                        continue
                if abs((x1 + x2) / 2.0 - cx) > tolerance or abs((y1 + y2) / 2.0 - cy) > tolerance:
                    continue

                distance = math.hypot(x2 - x1, y2 - y1)
                has_segment = 1 if frozenset((first_name, second_name)) in segment_pairs else 0
                score = (has_segment, distance)
                if best_score is None or score > best_score:
                    best_score = score
                    best_pair = (first_name, second_name)

        return best_pair

    def _project_semicircle_points(
        self,
        *,
        orientation_key: str,
        center: tuple[float, float],
        center_name: str,
        radius: float,
        diameter: tuple[str, str],
        point_entries: dict[str, dict[str, Any]],
        point_coords: dict[str, tuple[float, float]],
        adjacency: dict[str, set[str]],
    ) -> None:
        horizontal = orientation_key in {"upper", "lower"}
        sign = 1.0 if orientation_key in {"upper", "right"} else -1.0
        first_name, second_name = diameter
        first = point_coords[first_name]
        second = point_coords[second_name]
        cx, cy = center
        tolerance = max(radius * 0.05, 2.0)

        for name, entry in point_entries.items():
            if name in {first_name, second_name, center_name}:
                continue
            coords = point_coords.get(name)
            if coords is None:
                continue
            x, y = coords

            if horizontal:
                if x < min(first[0], second[0]) - tolerance or x > max(first[0], second[0]) + tolerance:
                    continue
                if abs(y - cy) <= tolerance:
                    continue
                inside = radius * radius - (x - cx) * (x - cx)
                if inside < 0:
                    continue
                target_coords = (x, cy + sign * math.sqrt(max(inside, 0.0)))
                on_axis_helper = abs(x - cx) <= tolerance and center_name in adjacency.get(name, set())
                foot_names = [
                    other
                    for other in adjacency.get(name, set())
                    if other in point_coords
                    and abs(point_coords[other][0] - x) <= tolerance
                    and abs(point_coords[other][1] - cy) <= tolerance
                ]
                touches_diameter_ends = first_name in adjacency.get(name, set()) and second_name in adjacency.get(name, set())
                if not (on_axis_helper or foot_names or touches_diameter_ends):
                    continue
                entry["y"] = float(target_coords[1])
                point_coords[name] = target_coords
                if on_axis_helper and not self._text_from(entry.get("label")):
                    entry["show"] = False
                    entry["show_label"] = False
            else:
                if y < min(first[1], second[1]) - tolerance or y > max(first[1], second[1]) + tolerance:
                    continue
                if abs(x - cx) <= tolerance:
                    continue
                inside = radius * radius - (y - cy) * (y - cy)
                if inside < 0:
                    continue
                target_coords = (cx + sign * math.sqrt(max(inside, 0.0)), y)
                on_axis_helper = abs(y - cy) <= tolerance and center_name in adjacency.get(name, set())
                foot_names = [
                    other
                    for other in adjacency.get(name, set())
                    if other in point_coords
                    and abs(point_coords[other][1] - y) <= tolerance
                    and abs(point_coords[other][0] - cx) <= tolerance
                ]
                touches_diameter_ends = first_name in adjacency.get(name, set()) and second_name in adjacency.get(name, set())
                if not (on_axis_helper or foot_names or touches_diameter_ends):
                    continue
                entry["x"] = float(target_coords[0])
                point_coords[name] = target_coords
                if on_axis_helper and not self._text_from(entry.get("label")):
                    entry["show"] = False
                    entry["show_label"] = False

    def _segment_adjacency(self, segments: list[Any]) -> dict[str, set[str]]:
        adjacency: dict[str, set[str]] = {}
        for entry in segments:
            if not isinstance(entry, dict):
                continue
            first = self._text_from(entry.get("from"))
            second = self._text_from(entry.get("to"))
            if not first or not second:
                continue
            adjacency.setdefault(first, set()).add(second)
            adjacency.setdefault(second, set()).add(first)
        return adjacency

    def _semicircle_orientation_key(self, circle: dict[str, Any]) -> str:
        circle_type = self._text_from(circle.get("type")).lower()
        type_map = {
            "semicircle_upper": "upper",
            "semicircle_lower": "lower",
            "semicircle_left": "left",
            "semicircle_right": "right",
        }
        if circle_type in type_map:
            return type_map[circle_type]

        orientation = self._text_from(circle.get("orientation")).lower()
        orientation_map = {
            "up": "upper",
            "upper": "upper",
            "top": "upper",
            "above": "upper",
            "down": "lower",
            "lower": "lower",
            "bottom": "lower",
            "below": "lower",
            "left": "left",
            "right": "right",
        }
        if bool(circle.get("semicircle")):
            return orientation_map.get(orientation, "upper")
        return orientation_map.get(orientation, "")

    def _point_coords_from_entry(self, entry: dict[str, Any]) -> tuple[float, float] | None:
        if "x" not in entry or "y" not in entry:
            return None
        try:
            return (float(entry["x"]), float(entry["y"]))
        except (TypeError, ValueError):
            return None

    def _name_for_coords(
        self,
        coords: tuple[float, float],
        point_coords: dict[str, tuple[float, float]],
    ) -> str:
        cx, cy = coords
        for name, (x, y) in point_coords.items():
            if abs(x - cx) <= 1e-6 and abs(y - cy) <= 1e-6:
                return name
        return ""

    def _maybe_flip_screen_coordinates(self, scene: dict[str, Any]) -> None:
        pivot_y = self._screen_flip_pivot(scene)
        if pivot_y is None:
            return

        for entry in scene.get("points", []):
            if not isinstance(entry, dict) or "y" not in entry:
                continue
            try:
                entry["y"] = pivot_y * 2.0 - float(entry["y"])
            except (TypeError, ValueError):
                continue

        for entry in scene.get("circles", []):
            if not isinstance(entry, dict):
                continue
            center = entry.get("center")
            if isinstance(center, dict) and "y" in center:
                try:
                    center["y"] = pivot_y * 2.0 - float(center["y"])
                except (TypeError, ValueError):
                    pass

        for entry in scene.get("annotations", []):
            if not isinstance(entry, dict) or "y" not in entry:
                continue
            try:
                entry["y"] = pivot_y * 2.0 - float(entry["y"])
            except (TypeError, ValueError):
                continue

    def _screen_flip_pivot(self, scene: dict[str, Any]) -> float | None:
        points = scene.get("points")
        circles = scene.get("circles")
        if not isinstance(points, list) or not isinstance(circles, list):
            return None

        point_map: dict[str, tuple[float, float]] = {}
        for entry in points:
            if not isinstance(entry, dict):
                continue
            name = self._text_from(entry.get("name"))
            if not name:
                continue
            try:
                point_map[name] = (float(entry["x"]), float(entry["y"]))
            except (KeyError, TypeError, ValueError):
                continue

        if not point_map:
            return None

        for circle in circles:
            if not isinstance(circle, dict):
                continue
            orientation = self._text_from(circle.get("orientation")).lower()
            if orientation not in {"up", "down", "top", "bottom"}:
                continue
            center_coords = self._point_coords_from_value(circle.get("center"), point_map)
            if center_coords is None:
                continue
            radius = self._circle_radius_from_entry(circle, point_map, center_coords)
            if radius is None or radius <= 0:
                continue
            cx, cy = center_coords
            tolerance = max(radius * 0.05, 1e-6)
            oriented_points = [
                (x, y)
                for name, (x, y) in point_map.items()
                if not (abs(x - cx) <= tolerance and abs(y - cy) <= tolerance)
                and abs(x - cx) <= radius + tolerance
            ]
            if not oriented_points:
                continue
            above = sum(1 for _, y in oriented_points if y > cy + tolerance)
            below = sum(1 for _, y in oriented_points if y < cy - tolerance)
            if orientation in {"up", "top"} and below > above:
                return cy
            if orientation in {"down", "bottom"} and above > below:
                return cy
        return None

    def _circle_radius_from_entry(
        self,
        entry: dict[str, Any],
        point_map: dict[str, tuple[float, float]],
        center: tuple[float, float],
    ) -> float | None:
        radius_value = entry.get("radius")
        if radius_value is not None:
            try:
                return float(radius_value)
            except (TypeError, ValueError):
                return None

        through_coords = self._point_coords_from_value(entry.get("through"), point_map)
        if through_coords is None:
            return None
        return math.hypot(through_coords[0] - center[0], through_coords[1] - center[1])

    def _point_coords_from_value(
        self,
        value: Any,
        point_map: dict[str, tuple[float, float]],
    ) -> tuple[float, float] | None:
        if isinstance(value, dict) and "x" in value and "y" in value:
            try:
                return (float(value["x"]), float(value["y"]))
            except (TypeError, ValueError):
                return None
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                return (float(value[0]), float(value[1]))
            except (TypeError, ValueError):
                return None
        inline_coords = self._inline_coords_from_text(value)
        if inline_coords is not None:
            return inline_coords
        name = self._text_from(value)
        return point_map.get(name)

    def _infer_compact_circle_types(self, scene: dict[str, Any]) -> None:
        points = scene.get("points")
        circles = scene.get("circles")
        if not isinstance(points, list) or not isinstance(circles, list):
            return

        point_map: dict[str, tuple[float, float]] = {}
        for entry in points:
            if not isinstance(entry, dict):
                continue
            name = self._text_from(entry.get("name"))
            if not name:
                continue
            try:
                point_map[name] = (float(entry["x"]), float(entry["y"]))
            except (KeyError, TypeError, ValueError):
                continue

        if not point_map:
            return

        for entry in circles:
            if not isinstance(entry, dict):
                continue
            if not entry.get("_compact_array") or self._text_from(entry.get("type")):
                continue
            center_name = self._text_from(entry.get("center"))
            if not center_name or center_name not in point_map:
                continue
            try:
                radius = float(entry.get("radius"))
            except (TypeError, ValueError):
                continue
            if radius <= 0:
                continue

            inferred = self._infer_semicircle_type_from_points(center_name, radius, point_map)
            if inferred:
                entry["type"] = inferred
                entry.setdefault("style", "primary")

    def _infer_semicircle_type_from_points(
        self,
        center_name: str,
        radius: float,
        point_map: dict[str, tuple[float, float]],
    ) -> str:
        cx, cy = point_map[center_name]
        tolerance = max(radius * 0.05, 1e-6)
        on_circle: list[tuple[str, float, float]] = []
        for name, (x, y) in point_map.items():
            if name == center_name:
                continue
            distance = math.hypot(x - cx, y - cy)
            if abs(distance - radius) <= tolerance:
                on_circle.append((name, x, y))

        other_points = [
            (name, x, y)
            for name, (x, y) in point_map.items()
            if name != center_name
        ]
        for _, x1, y1 in on_circle:
            for _, x2, y2 in on_circle:
                if x1 == x2 and y1 == y2:
                    continue
                if abs((x1 + x2) / 2.0 - cx) > tolerance or abs((y1 + y2) / 2.0 - cy) > tolerance:
                    continue
                if abs(y1 - cy) <= tolerance and abs(y2 - cy) <= tolerance:
                    above = sum(1 for _, x, y in other_points if y > cy + tolerance)
                    below = sum(1 for _, x, y in other_points if y < cy - tolerance)
                    if above >= below:
                        return "semicircle_upper"
                    return "semicircle_lower"
                if abs(x1 - cx) <= tolerance and abs(x2 - cx) <= tolerance:
                    right = sum(1 for _, x, y in other_points if x > cx + tolerance)
                    left = sum(1 for _, x, y in other_points if x < cx - tolerance)
                    if right >= left:
                        return "semicircle_right"
                    return "semicircle_left"
        return ""

    def _merge_point_label_annotations(self, scene: dict[str, Any]) -> None:
        points = scene.get("points")
        annotations = scene.get("annotations")
        if not isinstance(points, list) or not isinstance(annotations, list):
            return

        point_map: dict[str, dict[str, Any]] = {}
        point_coords: dict[str, tuple[float, float]] = {}
        for entry in points:
            if not isinstance(entry, dict):
                continue
            name = self._text_from(entry.get("name"))
            if name:
                point_map[name] = entry
                try:
                    point_coords[name] = (float(entry["x"]), float(entry["y"]))
                except (KeyError, TypeError, ValueError):
                    pass

        if not point_map:
            return

        remaining_annotations: list[Any] = []
        for entry in annotations:
            if not isinstance(entry, dict):
                remaining_annotations.append(entry)
                continue
            at_name = self._text_from(entry.get("at"))
            text = self._text_from(entry.get("text"))
            if at_name and text and at_name in point_map and not self._text_from(entry.get("color")):
                point_entry = point_map[at_name]
                point_entry["label"] = text
                point_entry["show_label"] = True
                if "offset" in entry:
                    point_entry["offset"] = list(self._pair(entry.get("offset"), default=(0.12, 0.12)))
                continue
            if text and text in point_map and "x" in entry and "y" in entry and not self._text_from(entry.get("color")):
                coords = point_coords.get(text)
                if coords is not None:
                    try:
                        label_x = float(entry.get("x"))
                        label_y = float(entry.get("y"))
                    except (TypeError, ValueError):
                        label_x = coords[0]
                        label_y = coords[1]
                    point_entry = point_map[text]
                    point_entry["label"] = text
                    point_entry["show_label"] = True
                    point_entry["offset"] = [label_x - coords[0], label_y - coords[1]]
                    continue
            remaining_annotations.append(entry)

        scene["annotations"] = remaining_annotations

    def _normalize_point_aliases(self, entry: Any) -> dict[str, Any] | Any:
        if isinstance(entry, (list, tuple)):
            if len(entry) >= 3:
                name = self._text_from(entry[0])
                try:
                    x = float(entry[1])
                    y = float(entry[2])
                except (TypeError, ValueError):
                    return entry
                normalized = {
                    "name": name,
                    "x": x,
                    "y": y,
                }
                if len(entry) >= 4 and self._text_from(entry[3]):
                    normalized["label"] = self._text_from(entry[3])
                return normalized
            return entry
        if not isinstance(entry, dict):
            return entry
        normalized = dict(entry)
        name = self._text_from(normalized.get("name")) or self._text_from(normalized.get("id"))
        if name:
            normalized["name"] = name
        if "show_label" not in normalized and "showLabel" in normalized:
            normalized["show_label"] = bool(normalized.get("showLabel"))
        if "show" not in normalized and "showPoint" in normalized:
            normalized["show"] = bool(normalized.get("showPoint"))
        if bool(normalized.get("highlight")) and not self._text_from(normalized.get("style")):
            normalized["style"] = "highlight"
        if "label" in normalized and not self._text_from(normalized.get("label")) and "show_label" not in normalized:
            normalized["show_label"] = False
        self._apply_label_position_defaults(normalized, distance_points=10.0)
        return normalized

    def _normalize_segment_aliases(self, entry: Any) -> dict[str, Any] | Any:
        if isinstance(entry, (list, tuple)):
            if len(entry) < 2:
                return entry
            normalized: dict[str, Any] = {
                "from": self._text_from(entry[0]),
                "to": self._text_from(entry[1]),
            }
            if len(entry) >= 3:
                third = self._text_from(entry[2])
                style_name = self._text_from(self._normalize_style_alias_value(third)).lower()
                if style_name in {"primary", "auxiliary", "highlight", "subtle"}:
                    normalized["style"] = style_name
                elif third:
                    normalized["label"] = third
            if len(entry) >= 4 and self._text_from(entry[3]):
                normalized["label"] = self._text_from(entry[3])
            return normalized
        if not isinstance(entry, dict):
            return entry
        normalized = dict(entry)
        from_name = (
            self._text_from(normalized.get("from"))
            or self._text_from(normalized.get("start"))
            or self._text_from(normalized.get("p1"))
        )
        to_name = (
            self._text_from(normalized.get("to"))
            or self._text_from(normalized.get("end"))
            or self._text_from(normalized.get("p2"))
        )
        if from_name:
            normalized["from"] = from_name
        if to_name:
            normalized["to"] = to_name
        if "label_pos" not in normalized and "labelPos" in normalized:
            try:
                normalized["label_pos"] = float(normalized.get("labelPos"))
            except (TypeError, ValueError):
                pass
        self._apply_label_position_defaults(normalized, distance_points=7.0)
        normalized["style"] = self._normalize_style_alias_value(normalized.get("style"))
        return normalized

    def _normalize_line_aliases(self, entry: Any) -> dict[str, Any] | Any:
        if isinstance(entry, (list, tuple)):
            if len(entry) < 2:
                return entry
            normalized: dict[str, Any] = {
                "through": [self._text_from(entry[0]), self._text_from(entry[1])],
            }
            if len(entry) >= 3:
                normalized["style"] = self._normalize_style_alias_value(entry[2])
            return normalized
        if not isinstance(entry, dict):
            return entry
        normalized = dict(entry)
        through = normalized.get("through")
        if not isinstance(through, list):
            alt = normalized.get("points")
            if isinstance(alt, list):
                normalized["through"] = alt
        normalized["style"] = self._normalize_style_alias_value(normalized.get("style"))
        return normalized

    def _normalize_ray_aliases(self, entry: Any) -> dict[str, Any] | Any:
        if isinstance(entry, (list, tuple)):
            if len(entry) < 2:
                return entry
            normalized: dict[str, Any] = {
                "from": self._text_from(entry[0]),
                "to": self._text_from(entry[1]),
            }
            if len(entry) >= 3:
                normalized["style"] = self._normalize_style_alias_value(entry[2])
            return normalized
        if not isinstance(entry, dict):
            return entry
        normalized = dict(entry)
        from_name = (
            self._text_from(normalized.get("from"))
            or self._text_from(normalized.get("start"))
            or self._text_from(normalized.get("p1"))
        )
        to_name = (
            self._text_from(normalized.get("to"))
            or self._text_from(normalized.get("through"))
            or self._text_from(normalized.get("p2"))
        )
        if from_name:
            normalized["from"] = from_name
        if to_name:
            normalized["to"] = to_name
        normalized["style"] = self._normalize_style_alias_value(normalized.get("style"))
        return normalized

    def _normalize_circle_aliases(self, entry: Any) -> dict[str, Any] | Any:
        if isinstance(entry, (list, tuple)):
            if len(entry) < 2:
                return entry
            normalized: dict[str, Any] = {
                "center": self._text_from(entry[0]),
                "_compact_array": True,
            }
            second = entry[1]
            if isinstance(second, (int, float)):
                normalized["radius"] = float(second)
            else:
                second_text = self._text_from(second)
                try:
                    normalized["radius"] = float(second_text)
                except (TypeError, ValueError):
                    if second_text:
                        normalized["through"] = second_text
            if len(entry) >= 3 and self._text_from(entry[2]):
                third = self._text_from(entry[2])
                if third.lower().startswith("semicircle"):
                    normalized["type"] = third.lower()
                    normalized["style"] = "primary"
                else:
                    normalized["style"] = self._normalize_style_alias_value(third)
            if len(entry) >= 4 and self._text_from(entry[3]):
                normalized["orientation"] = self._text_from(entry[3])
            entry = normalized
        if not isinstance(entry, dict):
            return entry
        normalized = dict(entry)
        circle_type = self._text_from(normalized.get("type")).lower()
        raw_style = self._text_from(normalized.get("style")).lower()
        if not self._text_from(normalized.get("orientation")):
            alias_orientation = (
                self._text_from(normalized.get("semicircleDirection"))
                or self._text_from(normalized.get("semicircle_direction"))
                or self._text_from(normalized.get("direction"))
            )
            if alias_orientation:
                normalized["orientation"] = alias_orientation
        orientation = self._text_from(normalized.get("orientation")).lower()
        if bool(normalized.get("semicircle")) and not circle_type:
            circle_type = "semicircle"
            normalized["type"] = circle_type
        style_type_map = {
            "semicircle": "semicircle_upper",
            "semicircle_upper": "semicircle_upper",
            "semicircle_lower": "semicircle_lower",
            "semicircle_left": "semicircle_left",
            "semicircle_right": "semicircle_right",
        }
        if not circle_type and raw_style in style_type_map:
            circle_type = style_type_map[raw_style]
            normalized["type"] = circle_type
            normalized["style"] = "primary"
        else:
            normalized["style"] = self._normalize_style_alias_value(normalized.get("style"))

        if circle_type == "semicircle":
            orientation_map = {
                "above": "semicircle_upper",
                "upper": "semicircle_upper",
                "top": "semicircle_upper",
                "up": "semicircle_upper",
                "below": "semicircle_lower",
                "lower": "semicircle_lower",
                "down": "semicircle_lower",
                "bottom": "semicircle_lower",
                "left": "semicircle_left",
                "right": "semicircle_right",
            }
            normalized["type"] = orientation_map.get(orientation, "semicircle_upper")
        return normalized

    def _normalize_polygon_aliases(self, entry: Any) -> dict[str, Any] | Any:
        if isinstance(entry, (list, tuple)) and entry and all(isinstance(item, str) for item in entry):
            return {"points": [self._text_from(item) for item in entry]}
        if not isinstance(entry, dict):
            return entry
        normalized = dict(entry)
        if not isinstance(normalized.get("points"), list):
            vertices = normalized.get("vertices")
            if isinstance(vertices, list):
                normalized["points"] = vertices
        normalized["style"] = self._normalize_style_alias_value(normalized.get("style"))
        return normalized

    def _normalize_angle_mark_aliases(self, entry: Any) -> dict[str, Any] | Any:
        if isinstance(entry, (list, tuple)):
            if len(entry) < 3:
                return entry
            normalized: dict[str, Any] = {
                "vertex": self._text_from(entry[0]),
                "from": self._text_from(entry[1]),
                "to": self._text_from(entry[2]),
            }
            if len(entry) >= 4 and self._text_from(entry[3]):
                normalized["label"] = self._text_from(entry[3])
                if "90" in normalized["label"]:
                    normalized["right_angle"] = True
            return normalized
        if not isinstance(entry, dict):
            return entry
        normalized = dict(entry)
        vertex = self._text_from(normalized.get("vertex")) or self._text_from(normalized.get("at"))
        if vertex:
            normalized["vertex"] = vertex

        from_name = (
            self._text_from(normalized.get("from"))
            or self._text_from(normalized.get("start"))
            or self._text_from(normalized.get("p1"))
        )
        to_name = (
            self._text_from(normalized.get("to"))
            or self._text_from(normalized.get("end"))
            or self._text_from(normalized.get("p2"))
        )
        arms = normalized.get("arms")
        if isinstance(arms, list) and len(arms) >= 2:
            if not from_name:
                from_name = self._arm_point_name(arms[0])
            if not to_name:
                to_name = self._arm_point_name(arms[1])
        if from_name:
            normalized["from"] = from_name
        if to_name:
            normalized["to"] = to_name

        mark = self._text_from(normalized.get("mark"))
        if mark and not self._text_from(normalized.get("label")):
            normalized["label"] = mark
        label = self._text_from(normalized.get("label"))
        if mark and "90" in mark:
            normalized["right_angle"] = True
        if label and "90" in label:
            normalized["right_angle"] = True
        normalized["style"] = self._normalize_style_alias_value(normalized.get("style"))
        return normalized

    def _normalize_annotation_aliases(self, entry: Any) -> dict[str, Any] | Any:
        if isinstance(entry, (list, tuple)):
            if len(entry) >= 3:
                text = self._text_from(entry[0])
                try:
                    x = float(entry[1])
                    y = float(entry[2])
                except (TypeError, ValueError):
                    normalized = {
                        "text": text,
                        "at": self._text_from(entry[1]),
                    }
                    if len(entry) >= 4:
                        normalized["offset"] = list(self._pair(entry[2:4], default=(0.0, 0.0)))
                    return normalized
                return {"text": text, "x": x, "y": y}
            if len(entry) == 2:
                return {
                    "text": self._text_from(entry[0]),
                    "at": self._text_from(entry[1]),
                }
            return entry
        if not isinstance(entry, dict):
            return entry
        normalized = dict(entry)
        if not self._text_from(normalized.get("text")):
            label = self._text_from(normalized.get("label"))
            if label:
                normalized["text"] = label

        at_value = normalized.get("at")
        at_coords = self._point_coords_from_value(at_value, {})
        if at_coords is not None:
            normalized["x"] = at_coords[0]
            normalized["y"] = at_coords[1]
            normalized.pop("at", None)
            return normalized

        at_name = self._text_from(at_value)
        point_value = normalized.get("point")
        if not at_name and isinstance(point_value, str):
            point_coords = self._point_coords_from_value(point_value, {})
            if point_coords is not None:
                normalized["x"] = point_coords[0]
                normalized["y"] = point_coords[1]
                return normalized
            at_name = self._text_from(point_value)
        if at_name:
            normalized["at"] = at_name
        elif isinstance(point_value, (list, tuple)) and len(point_value) == 2:
            try:
                normalized["x"] = float(point_value[0])
                normalized["y"] = float(point_value[1])
            except (TypeError, ValueError):
                pass
        return normalized

    def _arm_point_name(self, value: Any) -> str:
        if isinstance(value, str):
            return self._text_from(value)
        if not isinstance(value, dict):
            return ""
        return (
            self._text_from(value.get("from"))
            or self._text_from(value.get("start"))
            or self._text_from(value.get("to"))
            or self._text_from(value.get("end"))
            or self._text_from(value.get("point"))
            or self._text_from(value.get("name"))
            or self._text_from(value.get("id"))
        )

    def _normalize_style_alias_value(self, value: Any) -> Any:
        candidate = self._text_from(value).lower()
        if not candidate:
            return value
        alias_map = {
            "main": "primary",
            "solid": "primary",
            "normal": "primary",
            "default": "primary",
            "aux": "auxiliary",
            "auxiliary": "auxiliary",
            "dashed": "auxiliary",
            "dash": "auxiliary",
            "helper": "auxiliary",
            "construction": "auxiliary",
            "highlight": "highlight",
            "thick": "highlight",
            "bold": "highlight",
            "focus": "highlight",
            "subtle": "subtle",
            "thin": "subtle",
            "faint": "subtle",
            "light": "subtle",
        }
        return alias_map.get(candidate, value)

    def _looks_like_legacy_scene(self, scene: dict[str, Any]) -> bool:
        return isinstance(scene.get("setup"), list)

    def _normalize_legacy_scene(self, scene: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {
            "caption": self._text_from(scene.get("caption")),
            "viewport": {},
            "points": [],
            "segments": [],
            "lines": [],
            "rays": [],
            "circles": [],
            "polygons": [],
            "angle_marks": [],
            "annotations": [],
        }
        point_entries: dict[str, dict[str, Any]] = {}
        point_order: list[str] = []
        point_objects: dict[str, SymPoint] = {}
        line_defs: dict[str, tuple[str, str]] = {}
        circle_defs: dict[str, SymCircle] = {}
        semicircle_defs: dict[str, dict[str, Any]] = {}

        def store_point(
            name: str,
            point: SymPoint,
            *,
            show: bool = True,
            show_label: bool = True,
            label: str = "",
            offset: tuple[float, float] | None = None,
            style: str = "primary",
        ) -> None:
            point_objects[name] = point
            existing = point_entries.get(name)
            if existing is None:
                existing = {
                    "name": name,
                    "label": label or name,
                    "show": show,
                    "show_label": show_label,
                    "style": style,
                }
                point_entries[name] = existing
                point_order.append(name)
            else:
                existing["label"] = label or existing.get("label") or name
                existing["show"] = bool(existing.get("show", False) or show)
                existing["show_label"] = bool(existing.get("show_label", False) or show_label)
                existing["style"] = style or existing.get("style", "primary")
            existing["x"] = float(point.x)
            existing["y"] = float(point.y)
            if offset is not None:
                existing["offset"] = [float(offset[0]), float(offset[1])]

        for raw_entry in scene.get("setup", []):
            if not isinstance(raw_entry, list) or len(raw_entry) < 2:
                continue
            op_name = self._text_from(raw_entry[0]).lower()
            payload = raw_entry[1]
            try:
                if op_name == "point" and isinstance(payload, list) and len(payload) >= 3:
                    name = self._text_from(payload[0])
                    point = SymPoint(float(payload[1]), float(payload[2]))
                    store_point(name, point)
                    continue

                if op_name == "midpoint" and isinstance(payload, list) and len(payload) >= 3:
                    name = self._text_from(payload[0])
                    p1, p2 = self._legacy_pair_from_names(payload[1], payload[2], point_objects)
                    point = SymSegment(p1, p2).midpoint
                    store_point(name, point)
                    continue

                if op_name == "circle" and isinstance(payload, list) and len(payload) >= 3:
                    circle_name = self._text_from(payload[0])
                    center_name = self._text_from(payload[1])
                    through_name = self._text_from(payload[2])
                    center = self._legacy_point_by_name(center_name, point_objects)
                    through = self._legacy_point_by_name(through_name, point_objects)
                    circle_defs[circle_name] = SymCircle(center, center.distance(through))
                    if not circle_name.lower().startswith("circle"):
                        normalized["circles"].append(
                            {
                                "center": center_name,
                                "through": through_name,
                                "style": "subtle",
                            }
                        )
                    continue

                if op_name == "semicircle" and isinstance(payload, list) and len(payload) >= 3:
                    arc_name = self._text_from(payload[0])
                    start_name = self._text_from(payload[1])
                    end_name = self._text_from(payload[2])
                    orientation = self._text_from(payload[3] if len(payload) >= 4 else "above").lower() or "above"
                    start_point = self._legacy_point_by_name(start_name, point_objects)
                    end_point = self._legacy_point_by_name(end_name, point_objects)
                    center = SymSegment(start_point, end_point).midpoint
                    circle_defs[arc_name] = SymCircle(center, center.distance(start_point))
                    semicircle_defs[arc_name] = {
                        "start": start_name,
                        "end": end_name,
                        "orientation": orientation,
                    }
                    self._legacy_add_semicircle_segments(
                        normalized=normalized,
                        point_objects=point_objects,
                        store_point=store_point,
                        arc_name=arc_name,
                        start_name=start_name,
                        end_name=end_name,
                        orientation=orientation,
                    )
                    continue

                if op_name == "perpendicular" and isinstance(payload, list) and len(payload) >= 3:
                    line_name = self._text_from(payload[0])
                    through_name = self._text_from(payload[1])
                    base_a_name, base_b_name = self._legacy_resolve_pair_ref(payload[2], point_objects)
                    through_point = self._legacy_point_by_name(through_name, point_objects)
                    base_a = self._legacy_point_by_name(base_a_name, point_objects)
                    base_b = self._legacy_point_by_name(base_b_name, point_objects)
                    helper_name = f"__{line_name}_dir"
                    helper_point = self._legacy_make_perpendicular_helper(through_point, base_a, base_b)
                    store_point(helper_name, helper_point, show=False, show_label=False, style="subtle")
                    line_defs[line_name] = (through_name, helper_name)
                    continue

                if op_name == "intersection" and isinstance(payload, list) and len(payload) >= 3:
                    point_name = self._text_from(payload[0])
                    first_ref = payload[1]
                    second_ref = payload[2]
                    try:
                        preferred_index = int(payload[3]) if len(payload) >= 4 else 0
                    except (TypeError, ValueError):
                        preferred_index = 0
                    line_ref = self._legacy_resolve_line_ref(first_ref, point_objects, line_defs)
                    circle_ref = self._legacy_resolve_circle_ref(second_ref, circle_defs)
                    if line_ref is None or circle_ref is None:
                        line_ref = self._legacy_resolve_line_ref(second_ref, point_objects, line_defs)
                        circle_ref = self._legacy_resolve_circle_ref(first_ref, circle_defs)
                    if line_ref is None or circle_ref is None:
                        raise GeometrySceneError("legacy intersection requires one line and one circle/semicircle")
                    p1 = self._legacy_point_by_name(line_ref[0], point_objects)
                    p2 = self._legacy_point_by_name(line_ref[1], point_objects)
                    candidates = [item for item in circle_ref.intersection(SymLine(p1, p2)) if isinstance(item, SymPoint)]
                    if not candidates:
                        raise GeometrySceneError("legacy intersection has no point result")
                    ordered = sorted(candidates, key=lambda item: (float(item.x), float(item.y)))
                    index = max(0, min(preferred_index, len(ordered) - 1))
                    store_point(point_name, ordered[index], style="highlight")
                    continue

                if op_name == "segment" and isinstance(payload, list) and len(payload) >= 3:
                    segment_name = self._text_from(payload[0])
                    from_name = self._text_from(payload[1])
                    to_name = self._text_from(payload[2])
                    normalized["segments"].append(
                        {
                            "from": from_name,
                            "to": to_name,
                            "style": self._legacy_segment_style(segment_name, from_name, to_name),
                        }
                    )
                    continue

                if op_name == "polygon" and isinstance(payload, list) and len(payload) >= 2:
                    point_names = payload[1] if isinstance(payload[1], list) else []
                    if len(point_names) >= 2:
                        normalized["polygons"].append(
                            {
                                "points": [self._text_from(item) for item in point_names],
                                "style": "subtle",
                                "fill": False,
                            }
                        )
                    continue
            except Exception as exc:
                self._debug("legacy geometry item skipped op=%s payload=%r error=%s", op_name, payload, exc)

        self._legacy_apply_measurements(scene, normalized, point_objects)
        self._legacy_apply_right_angles(scene, normalized, point_objects)
        self._legacy_apply_labels(scene, point_entries, point_objects, normalized)
        self._legacy_apply_conclusion(scene, normalized, point_objects)

        normalized["points"] = [point_entries[name] for name in point_order]
        self._debug("legacy geometry normalized summary: %s", self.describe_scene(normalized))
        return normalized

    def _legacy_add_semicircle_segments(
        self,
        *,
        normalized: dict[str, Any],
        point_objects: dict[str, SymPoint],
        store_point: Callable[..., None],
        arc_name: str,
        start_name: str,
        end_name: str,
        orientation: str,
    ) -> None:
        start_point = self._legacy_point_by_name(start_name, point_objects)
        end_point = self._legacy_point_by_name(end_name, point_objects)
        center = SymSegment(start_point, end_point).midpoint
        radius = float(center.distance(start_point))
        if radius <= 1e-9:
            return

        start_angle = math.atan2(float(start_point.y - center.y), float(start_point.x - center.x))
        end_angle_positive = start_angle + math.pi
        end_angle_negative = start_angle - math.pi
        desired_positive = orientation not in {"below", "down", "lower"}

        mid_positive = self._legacy_point_on_circle(center, radius, start_angle + (end_angle_positive - start_angle) / 2.0)
        positive_side = self._legacy_signed_side(start_point, end_point, mid_positive) >= 0.0
        end_angle = end_angle_positive if positive_side == desired_positive else end_angle_negative

        sample_count = 24
        point_chain = [start_name]
        for index in range(1, sample_count):
            angle = start_angle + (end_angle - start_angle) * (index / sample_count)
            arc_point = self._legacy_point_on_circle(center, radius, angle)
            helper_name = f"__{arc_name}_arc_{index}"
            store_point(helper_name, arc_point, show=False, show_label=False, style="subtle")
            point_chain.append(helper_name)
        point_chain.append(end_name)

        for index in range(len(point_chain) - 1):
            normalized["segments"].append(
                {
                    "from": point_chain[index],
                    "to": point_chain[index + 1],
                    "style": "primary",
                }
            )

    def _legacy_apply_measurements(
        self,
        scene: dict[str, Any],
        normalized: dict[str, Any],
        point_objects: dict[str, SymPoint],
    ) -> None:
        for raw_entry in scene.get("measurements", []):
            if not isinstance(raw_entry, list) or len(raw_entry) < 3:
                continue
            op_name = self._text_from(raw_entry[0]).lower()
            if op_name != "distance":
                continue
            pair = raw_entry[1]
            label = self._text_from(raw_entry[2])
            try:
                p1_name, p2_name = self._legacy_resolve_pair_ref(pair, point_objects)
            except Exception:
                continue
            segment = self._legacy_find_segment(normalized.get("segments", []), p1_name, p2_name)
            if segment is not None:
                segment["label"] = label
                segment.setdefault("offset", [0.0, 0.16])
                continue
            p1 = point_objects.get(p1_name)
            p2 = point_objects.get(p2_name)
            if p1 is None or p2 is None or not label:
                continue
            midpoint = SymSegment(p1, p2).midpoint
            normalized["annotations"].append(
                {
                    "text": label,
                    "x": float(midpoint.x),
                    "y": float(midpoint.y),
                    "offset": [0.0, 0.16],
                }
            )

    def _legacy_apply_right_angles(
        self,
        scene: dict[str, Any],
        normalized: dict[str, Any],
        point_objects: dict[str, SymPoint],
    ) -> None:
        raw_value = scene.get("rightAngle") or scene.get("rightAngles")
        if not raw_value:
            return
        vertices = raw_value if isinstance(raw_value, list) else [raw_value]
        for value in vertices:
            vertex_name = self._text_from(value)
            if not vertex_name or vertex_name not in point_objects:
                continue
            pair = self._legacy_pick_right_angle_pair(vertex_name, normalized.get("segments", []), point_objects)
            if pair is None:
                continue
            normalized["angle_marks"].append(
                {
                    "vertex": vertex_name,
                    "from": pair[0],
                    "to": pair[1],
                    "right_angle": True,
                    "style": "highlight",
                }
            )

    def _legacy_apply_labels(
        self,
        scene: dict[str, Any],
        point_entries: dict[str, dict[str, Any]],
        point_objects: dict[str, SymPoint],
        normalized: dict[str, Any],
    ) -> None:
        for raw_entry in scene.get("labels", []):
            if not isinstance(raw_entry, list) or len(raw_entry) < 3:
                continue
            name = self._text_from(raw_entry[0])
            try:
                label_x = float(raw_entry[1])
                label_y = float(raw_entry[2])
            except (TypeError, ValueError):
                continue
            point = point_objects.get(name)
            entry = point_entries.get(name)
            if point is not None and entry is not None:
                entry["offset"] = [label_x - float(point.x), label_y - float(point.y)]
                entry["show_label"] = True
                continue
            normalized["annotations"].append({"text": name, "x": label_x, "y": label_y})

    def _legacy_apply_conclusion(
        self,
        scene: dict[str, Any],
        normalized: dict[str, Any],
        point_objects: dict[str, SymPoint],
    ) -> None:
        conclusion = self._text_from(scene.get("conclusion"))
        if not conclusion or not point_objects:
            return
        xs = [float(point.x) for name, point in point_objects.items() if not name.startswith("__")]
        ys = [float(point.y) for name, point in point_objects.items() if not name.startswith("__")]
        if not xs or not ys:
            return
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        normalized["annotations"].append(
            {
                "text": conclusion,
                "x": (min(xs) + max(xs)) / 2.0,
                "y": min(ys),
                "offset": [0.0, -span * 0.22],
            }
        )

    def _legacy_find_segment(self, segments: list[Any], p1_name: str, p2_name: str) -> dict[str, Any] | None:
        for entry in segments:
            if not isinstance(entry, dict):
                continue
            a = self._text_from(entry.get("from"))
            b = self._text_from(entry.get("to"))
            if {a, b} == {p1_name, p2_name}:
                return entry
        return None

    def _legacy_pick_right_angle_pair(
        self,
        vertex_name: str,
        segments: list[Any],
        point_objects: dict[str, SymPoint],
    ) -> tuple[str, str] | None:
        neighbors: list[str] = []
        for entry in segments:
            if not isinstance(entry, dict):
                continue
            a = self._text_from(entry.get("from"))
            b = self._text_from(entry.get("to"))
            if a == vertex_name and b and b not in neighbors:
                neighbors.append(b)
            if b == vertex_name and a and a not in neighbors:
                neighbors.append(a)
        if len(neighbors) < 2:
            return None

        vertex = point_objects[vertex_name]
        best_pair: tuple[str, str] | None = None
        best_score = float("inf")
        for index in range(len(neighbors)):
            for other_index in range(index + 1, len(neighbors)):
                p1 = point_objects.get(neighbors[index])
                p2 = point_objects.get(neighbors[other_index])
                if p1 is None or p2 is None:
                    continue
                vector1 = (float(p1.x - vertex.x), float(p1.y - vertex.y))
                vector2 = (float(p2.x - vertex.x), float(p2.y - vertex.y))
                length1 = math.hypot(vector1[0], vector1[1])
                length2 = math.hypot(vector2[0], vector2[1])
                if length1 <= 1e-9 or length2 <= 1e-9:
                    continue
                cosine = max(min((vector1[0] * vector2[0] + vector1[1] * vector2[1]) / (length1 * length2), 1.0), -1.0)
                angle = math.degrees(math.acos(cosine))
                score = abs(angle - 90.0)
                if score < best_score:
                    best_score = score
                    best_pair = (neighbors[index], neighbors[other_index])
        return best_pair

    def _legacy_segment_style(self, segment_name: str, from_name: str, to_name: str) -> str:
        lowered = (segment_name or "").lower()
        if any(token in lowered for token in ("aux", "guide", "help", "dash")):
            return "auxiliary"
        if from_name.startswith("__") or to_name.startswith("__"):
            return "subtle"
        return "primary"

    def _legacy_make_perpendicular_helper(self, source: SymPoint, base_a: SymPoint, base_b: SymPoint) -> SymPoint:
        dx = float(base_b.x - base_a.x)
        dy = float(base_b.y - base_a.y)
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return SymPoint(float(source.x), float(source.y) + 1.0)
        scale = max(length * 0.9, 1.0)
        return SymPoint(float(source.x) - dy / length * scale, float(source.y) + dx / length * scale)

    def _legacy_resolve_line_ref(
        self,
        value: Any,
        point_objects: dict[str, SymPoint],
        line_defs: dict[str, tuple[str, str]],
    ) -> tuple[str, str] | None:
        name = self._text_from(value)
        if not name:
            return None
        if name in line_defs:
            return line_defs[name]
        try:
            return self._legacy_resolve_pair_ref(name, point_objects)
        except Exception:
            return None

    def _legacy_resolve_circle_ref(self, value: Any, circle_defs: dict[str, SymCircle]) -> SymCircle | None:
        name = self._text_from(value)
        if not name:
            return None
        return circle_defs.get(name)

    def _legacy_resolve_pair_ref(self, value: Any, point_objects: dict[str, SymPoint]) -> tuple[str, str]:
        if isinstance(value, list) and len(value) == 2:
            left = self._text_from(value[0])
            right = self._text_from(value[1])
            if left in point_objects and right in point_objects:
                return (left, right)
        token = self._text_from(value)
        if not token:
            raise GeometrySceneError("legacy pair reference is empty")
        pieces = [item for item in re.split(r"[\s,;:_-]+", token) if item]
        if len(pieces) == 2 and pieces[0] in point_objects and pieces[1] in point_objects:
            return (pieces[0], pieces[1])
        for left in sorted(point_objects.keys(), key=len, reverse=True):
            if not token.startswith(left):
                continue
            right = token[len(left) :]
            if right in point_objects and right != left:
                return (left, right)
        raise GeometrySceneError(f"legacy pair reference `{token}` could not be resolved")

    def _legacy_pair_from_names(
        self,
        left_name: Any,
        right_name: Any,
        point_objects: dict[str, SymPoint],
    ) -> tuple[SymPoint, SymPoint]:
        return (
            self._legacy_point_by_name(self._text_from(left_name), point_objects),
            self._legacy_point_by_name(self._text_from(right_name), point_objects),
        )

    def _legacy_point_by_name(self, name: str, point_objects: dict[str, SymPoint]) -> SymPoint:
        if not name or name not in point_objects:
            raise GeometrySceneError(f"legacy point `{name}` is undefined")
        return point_objects[name]

    def _legacy_point_on_circle(self, center: SymPoint, radius: float, angle: float) -> SymPoint:
        return SymPoint(float(center.x) + math.cos(angle) * radius, float(center.y) + math.sin(angle) * radius)

    def _legacy_signed_side(self, start: SymPoint, end: SymPoint, point: SymPoint) -> float:
        return (
            float(end.x - start.x) * float(point.y - start.y)
            - float(end.y - start.y) * float(point.x - start.x)
        )

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
                self._debug("geometry point skipped because it is not an object: %r", entry)
                continue
            try:
                name = self._required_text(entry, "name")
                point = self._resolve_point_entry(entry, points)
                has_label_key = "label" in entry
                label_text = self._text_from(entry.get("label"))
                points[name] = point
                point_meta[name] = {
                    "label": label_text if has_label_key else name,
                    "show": bool(entry.get("show", True)),
                    "show_label": bool(entry.get("show_label", False if has_label_key and not label_text else True)),
                    "offset": self._pair(entry.get("offset"), default=(0.12, 0.12)),
                    "offset_points": self._pair(entry.get("offset_points"), default=(0.0, 0.0)),
                    "ha": self._text_from(entry.get("ha")) or "left",
                    "va": self._text_from(entry.get("va")) or "bottom",
                    "style": self._style_name(entry.get("style"), default="primary"),
                }
            except Exception as exc:
                self._debug("geometry point skipped entry=%r error=%s", entry, exc)

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
            return SymCircle(center, center.distance(through))
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
            try:
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
                    has_explicit_label_pos = entry.get("label_pos") is not None
                    try:
                        label_pos = float(entry.get("label_pos", 0.5))
                    except (TypeError, ValueError):
                        label_pos = 0.5
                    label_pos = min(max(label_pos, 0.0), 1.0)
                    if not has_explicit_label_pos:
                        label_pos = self._auto_segment_label_pos(
                            label_pos,
                            p1,
                            p2,
                            points,
                            exclude_names={
                                self._text_from(entry.get("from")),
                                self._text_from(entry.get("to")),
                            },
                        )
                    midpoint = (
                        float(p1.x) + (float(p2.x) - float(p1.x)) * label_pos,
                        float(p1.y) + (float(p2.y) - float(p1.y)) * label_pos,
                    )
                    self._draw_text(
                        ax,
                        label,
                        midpoint[0],
                        midpoint[1],
                        offset=self._pair(entry.get("offset"), default=(0.0, 0.16)),
                        offset_points=self._pair(entry.get("offset_points"), default=(0.0, 0.0)),
                        color=style["color"],
                        font_size=self._int("geometry_annotation_font_size", 11),
                        ha=self._text_from(entry.get("ha")) or "center",
                        va=self._text_from(entry.get("va")) or "center",
                        zorder=8.6,
                    )
            except Exception as exc:
                self._debug("geometry segment skipped entry=%r error=%s", entry, exc)

    def _auto_segment_label_pos(
        self,
        label_pos: float,
        p1: SymPoint,
        p2: SymPoint,
        points: dict[str, SymPoint],
        *,
        exclude_names: set[str],
    ) -> float:
        if abs(label_pos - 0.5) > 1e-9:
            return label_pos

        dx = float(p2.x - p1.x)
        dy = float(p2.y - p1.y)
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return label_pos

        midpoint_x = float(p1.x) + dx * label_pos
        midpoint_y = float(p1.y) + dy * label_pos
        collision_threshold = max(length * 0.045, 0.55)
        for name, point in points.items():
            if name in exclude_names:
                continue
            distance = math.hypot(float(point.x) - midpoint_x, float(point.y) - midpoint_y)
            if distance <= collision_threshold:
                return 0.62
        return label_pos

    def _draw_lines(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint], bounds: tuple[float, float, float, float]) -> None:
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], 1.0) * 2.2
        for entry in scene.get("lines", []):
            if not isinstance(entry, dict):
                continue
            try:
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
            except Exception as exc:
                self._debug("geometry line skipped entry=%r error=%s", entry, exc)

    def _draw_rays(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint], bounds: tuple[float, float, float, float]) -> None:
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], 1.0) * 2.2
        for entry in scene.get("rays", []):
            if not isinstance(entry, dict):
                continue
            try:
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
            except Exception as exc:
                self._debug("geometry ray skipped entry=%r error=%s", entry, exc)

    def _draw_circles(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint]) -> None:
        for entry in scene.get("circles", []):
            if not isinstance(entry, dict):
                continue
            try:
                circle = self._build_circle(entry, points)
                center = circle.center
                radius = float(circle.radius)
                style_name = self._style_name(entry.get("style"), default="primary")
                style = self._style(style_name, override_color=self._text("geometry_circle_color", ""))
                arc_angles = self._circle_arc_angles(entry)
                if arc_angles is None:
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
                    label_anchor = (float(center.x), float(center.y))
                    label_offset = self._pair(entry.get("offset"), default=(radius * 0.55, radius * 0.55))
                else:
                    theta1, theta2 = arc_angles
                    patch = Arc(
                        (float(center.x), float(center.y)),
                        width=radius * 2.0,
                        height=radius * 2.0,
                        theta1=theta1,
                        theta2=theta2,
                        color=style["color"],
                        linewidth=style["line_width"],
                        linestyle=style["line_style"],
                        alpha=style["alpha"],
                        zorder=style["zorder"],
                    )
                    mid_angle = math.radians(self._arc_mid_angle(theta1, theta2))
                    label_anchor = (
                        float(center.x) + math.cos(mid_angle) * radius,
                        float(center.y) + math.sin(mid_angle) * radius,
                    )
                    default_offset = max(radius * 0.08, 0.18)
                    label_offset = self._pair(entry.get("offset"), default=(default_offset, default_offset))
                ax.add_patch(patch)
                label = self._text_from(entry.get("label"))
                if label:
                    self._draw_text(
                        ax,
                        label,
                        label_anchor[0],
                        label_anchor[1],
                        offset=label_offset,
                        offset_points=self._pair(entry.get("offset_points"), default=(0.0, 0.0)),
                        color=style["color"],
                        font_size=self._int("geometry_annotation_font_size", 11),
                        ha=self._text_from(entry.get("ha")) or "left",
                        va=self._text_from(entry.get("va")) or "bottom",
                        zorder=8.6,
                    )
            except Exception as exc:
                self._debug("geometry circle skipped entry=%r error=%s", entry, exc)

    def _draw_polygons(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint]) -> None:
        fill_alpha = max(min(self._float("geometry_fill_alpha", 0.12), 1.0), 0.0)
        fill_color = self._text("geometry_fill_color", "#93C5FD") or "#93C5FD"
        for entry in scene.get("polygons", []):
            if not isinstance(entry, dict):
                continue
            try:
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
            except Exception as exc:
                self._debug("geometry polygon skipped entry=%r error=%s", entry, exc)

    def _draw_angle_marks(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint]) -> None:
        default_radius = max(self._float("geometry_default_angle_radius", 0.42), 0.12)
        radius_step = max(self._float("geometry_angle_radius_step", 0.08), 0.04)
        default_color = self._text("geometry_angle_color", "") or self._text("geometry_highlight_color", "#EA580C") or "#EA580C"
        for entry in scene.get("angle_marks", []):
            if not isinstance(entry, dict):
                continue
            try:
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
                        offset_points=self._pair(entry.get("offset_points"), default=(0.0, 0.0)),
                        color=style["color"],
                        font_size=self._int("geometry_annotation_font_size", 11),
                        ha=self._text_from(entry.get("ha")) or "center",
                        va=self._text_from(entry.get("va")) or "center",
                        zorder=8.8,
                    )
            except Exception as exc:
                self._debug("geometry angle mark skipped entry=%r error=%s", entry, exc)

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
            try:
                style = self._style(meta.get("style"), default="primary", override_color=default_color)
                x = float(point.x)
                y = float(point.y)
                if meta.get("show", True):
                    size = base_size * (1.25 if meta.get("style") == "highlight" else 1.0)
                    ax.scatter([x], [y], s=size, c=style["color"], zorder=style["zorder"] + 2)
                if meta.get("show_label", True):
                    self._draw_text(
                        ax,
                        meta.get("label", name),
                        x,
                        y,
                        offset=self._pair(meta.get("offset"), default=(0.12, 0.12)),
                        offset_points=self._pair(meta.get("offset_points"), default=(0.0, 0.0)),
                        color=self._text("geometry_text_color", "#0F172A") or "#0F172A",
                        font_size=label_size,
                        ha=self._text_from(meta.get("ha")) or "left",
                        va=self._text_from(meta.get("va")) or "bottom",
                        zorder=8.0,
                    )
            except Exception as exc:
                self._debug("geometry point draw skipped name=%s meta=%r error=%s", name, meta, exc)

    def _draw_annotations(self, ax: Any, scene: dict[str, Any], points: dict[str, SymPoint]) -> None:
        font_size = max(self._int("geometry_annotation_font_size", 11), 8)
        default_color = self._text("geometry_text_color", "#0F172A") or "#0F172A"
        for entry in scene.get("annotations", []):
            if not isinstance(entry, dict):
                continue
            try:
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
                    offset_points=self._pair(entry.get("offset_points"), default=(0.0, 0.0)),
                    color=self._text_from(entry.get("color")) or default_color,
                    font_size=font_size,
                    ha=self._text_from(entry.get("ha")) or "left",
                    va=self._text_from(entry.get("va")) or "bottom",
                    zorder=8.7,
                )
            except Exception as exc:
                self._debug("geometry annotation skipped entry=%r error=%s", entry, exc)

    def _draw_text(
        self,
        ax: Any,
        text: str,
        x: float,
        y: float,
        *,
        offset: tuple[float, float],
        offset_points: tuple[float, float],
        color: str,
        font_size: int,
        ha: str,
        va: str,
        zorder: float = 8.0,
    ) -> None:
        label = self._normalize_plot_text(text)
        stroke_width = max(font_size * 0.18, 1.9)
        path_effect_list = [
            patheffects.withStroke(linewidth=stroke_width, foreground=(1, 1, 1, 0.88)),
        ]
        ax.annotate(
            label,
            xy=(x + offset[0], y + offset[1]),
            xytext=offset_points,
            textcoords="offset points",
            fontsize=font_size,
            fontfamily=self._font_families(),
            color=color,
            ha=ha,
            va=va,
            zorder=zorder,
            path_effects=path_effect_list,
            annotation_clip=False,
        )

    def _normalize_plot_text(self, text: str) -> str:
        candidate = (text or "").strip()
        if not candidate:
            return ""
        if "$" in candidate:
            return candidate
        candidate = re.sub(r"√\(([^()]+)\)", r"\\sqrt{\1}", candidate)
        candidate = re.sub(r"√([A-Za-z0-9]+)", r"\\sqrt{\1}", candidate)
        candidate = (
            candidate.replace("≥", r"\geq ")
            .replace("≤", r"\leq ")
            .replace("≠", r"\neq ")
            .replace("≈", r"\approx ")
        ).strip()
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
            arc_angles = self._circle_arc_angles(entry)
            if arc_angles is None:
                xs.extend([float(center.x) - radius, float(center.x) + radius])
                ys.extend([float(center.y) - radius, float(center.y) + radius])
                continue
            for x, y in self._arc_bounds_points(center, radius, arc_angles[0], arc_angles[1]):
                xs.append(x)
                ys.append(y)

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
        candidate = self._text_from(self._normalize_style_alias_value(value)).lower()
        if candidate in {"primary", "auxiliary", "highlight", "subtle"}:
            return candidate
        return default

    def _circle_arc_angles(self, entry: Any) -> tuple[float, float] | None:
        if not isinstance(entry, dict):
            return None
        theta1 = entry.get("theta1")
        theta2 = entry.get("theta2")
        if theta1 is not None and theta2 is not None:
            try:
                return (float(theta1), float(theta2))
            except (TypeError, ValueError):
                return None

        circle_type = self._text_from(entry.get("type")).lower()
        angle_map = {
            "semicircle_upper": (0.0, 180.0),
            "semicircle_lower": (180.0, 360.0),
            "semicircle_left": (90.0, 270.0),
            "semicircle_right": (-90.0, 90.0),
        }
        return angle_map.get(circle_type)

    def _arc_mid_angle(self, theta1: float, theta2: float) -> float:
        start = theta1 % 360.0
        sweep = (theta2 - theta1) % 360.0
        if sweep <= 1e-9 and abs(theta2 - theta1) > 1e-9:
            sweep = 360.0
        return (start + sweep / 2.0) % 360.0

    def _arc_bounds_points(
        self,
        center: SymPoint,
        radius: float,
        theta1: float,
        theta2: float,
    ) -> list[tuple[float, float]]:
        start = theta1 % 360.0
        sweep = (theta2 - theta1) % 360.0
        if sweep <= 1e-9 and abs(theta2 - theta1) > 1e-9:
            sweep = 360.0
        angles = [start, (start + sweep) % 360.0]
        for candidate in (0.0, 90.0, 180.0, 270.0):
            if self._angle_on_arc(candidate, start, sweep):
                angles.append(candidate)
        points: list[tuple[float, float]] = []
        seen: set[tuple[int, int]] = set()
        for angle in angles:
            normalized = angle % 360.0
            key = (int(round(normalized * 1000)), int(round(radius * 1000)))
            if key in seen:
                continue
            seen.add(key)
            radians_value = math.radians(normalized)
            points.append(
                (
                    float(center.x) + math.cos(radians_value) * radius,
                    float(center.y) + math.sin(radians_value) * radius,
                )
            )
        return points

    def _angle_on_arc(self, angle: float, start: float, sweep: float) -> bool:
        if sweep >= 360.0 - 1e-9:
            return True
        relative = (angle - start) % 360.0
        return relative <= sweep + 1e-9

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
        if isinstance(value, dict):
            if "x" in value and "y" in value:
                try:
                    return SymPoint(float(value["x"]), float(value["y"]))
                except (TypeError, ValueError) as exc:
                    raise GeometrySceneError(f"{context} has invalid inline coordinates") from exc
            value = self._text_from(value.get("name")) or self._text_from(value.get("id"))
        elif isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                return SymPoint(float(value[0]), float(value[1]))
            except (TypeError, ValueError):
                pass

        inline_coords = self._inline_coords_from_text(value)
        if inline_coords is not None:
            return SymPoint(inline_coords[0], inline_coords[1])

        name = self._text_from(value)
        if not name:
            raise GeometrySceneError(f"{context} point reference is empty")
        if name not in points:
            raise GeometrySceneError(f"{context} references unknown point `{name}`")
        return points[name]

    def _inline_coords_from_text(self, value: Any) -> tuple[float, float] | None:
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        if not candidate:
            return None
        match = re.fullmatch(
            r"[\(\[]?\s*([-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?)\s*[,，]\s*"
            r"([-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?)\s*[\)\]]?",
            candidate,
        )
        if not match:
            return None
        try:
            return (float(match.group(1)), float(match.group(2)))
        except (TypeError, ValueError):
            return None

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

    def _font_families(self) -> list[str]:
        configured = self._text("geometry_font_family", "")
        defaults = [
            "Noto Sans CJK SC",
            "Microsoft YaHei",
            "PingFang SC",
            "SimHei",
            "WenQuanYi Zen Hei",
            "Source Han Sans SC",
            "Arial Unicode MS",
            "DejaVu Sans",
        ]
        families = [item.strip() for item in configured.split(",") if item.strip()]
        families.extend(defaults)
        available = {item.name.casefold() for item in font_manager.fontManager.ttflist}
        deduped: list[str] = []
        seen: set[str] = set()
        for family in families:
            key = family.casefold()
            if key in seen or key not in available:
                continue
            seen.add(key)
            deduped.append(family)
        return deduped or ["DejaVu Sans"]

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
