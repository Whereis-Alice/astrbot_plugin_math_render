import tempfile
import unittest
from pathlib import Path

from geometry import GeometryRenderer


class GeometryAliasCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir_ctx = tempfile.TemporaryDirectory()
        self.renderer = GeometryRenderer(
            config={},
            temp_dir=Path(self._temp_dir_ctx.name),
        )

    def tearDown(self) -> None:
        self._temp_dir_ctx.cleanup()

    def test_angle_mark_start_end_aliases_render(self) -> None:
        scene = {
            "points": [
                {"id": "A", "x": -50, "y": 0, "label": "A", "labelPosition": "southWest"},
                {"id": "B", "x": 50, "y": 0, "label": "B", "labelPosition": "southEast"},
                {"id": "O", "x": 0, "y": 0, "label": "O", "labelPosition": "south"},
                {"id": "C", "x": -15, "y": 0, "label": "C", "labelPosition": "south"},
                {"id": "D", "x": -15, "y": 35, "label": "D", "labelPosition": "north"},
            ],
            "segments": [
                {"from": "A", "to": "B", "label": "a+b", "labelPosition": "south", "style": "thick"},
                {"from": "A", "to": "C", "label": "a", "labelPosition": "southEast"},
                {"from": "C", "to": "B", "label": "b", "labelPosition": "southWest"},
                {"from": "C", "to": "D", "label": "√ab", "labelPosition": "east", "style": "dashed"},
                {"from": "O", "to": "D", "label": "(a+b)/2", "labelPosition": "northWest", "style": "thick"},
                {"from": "A", "to": "D", "style": "thin"},
                {"from": "B", "to": "D", "style": "thin"},
            ],
            "circles": [
                {"center": "O", "radius": 50, "semicircle": True, "semicircleDirection": "up", "style": "thick"}
            ],
            "angle_marks": [
                {"vertex": "D", "start": "A", "end": "B", "label": "90°", "radius": 8}
            ],
        }

        normalized = self.renderer.parse_scene(scene)

        self.assertEqual(normalized["angle_marks"][0]["from"], "A")
        self.assertEqual(normalized["angle_marks"][0]["to"], "B")
        self.assertEqual(normalized["circles"][0]["type"], "semicircle_upper")
        self.assertTrue(normalized["angle_marks"][0]["right_angle"])

        result = self.renderer.render_scene(scene)
        self.assertTrue(result.path.exists())
        self.assertGreater(result.path.stat().st_size, 0)

    def test_inline_circle_center_object_and_semicircle_render(self) -> None:
        scene = {
            "points": [
                {"id": "A", "x": 100, "y": 200, "label": "A"},
                {"id": "B", "x": 500, "y": 200, "label": "B"},
                {"id": "C", "x": 280, "y": 200, "label": "C", "highlight": True},
                {"id": "O", "x": 300, "y": 200, "label": "O"},
                {"id": "D", "x": 280, "y": 95, "label": "D", "highlight": True},
                {"id": "E_top", "x": 300, "y": 90, "label": ""},
            ],
            "segments": [
                {"from": "A", "to": "B", "style": "solid"},
                {"from": "C", "to": "D", "style": "solid", "label": "CD = √ab"},
                {"from": "O", "to": "E_top", "style": "dashed", "label": "OD = (a+b)/2"},
                {"from": "A", "to": "D", "style": "solid"},
                {"from": "D", "to": "B", "style": "solid"},
            ],
            "circles": [
                {
                    "center": {"x": 300, "y": 200},
                    "radius": 110,
                    "semicircle": True,
                    "orientation": "up",
                    "label": "",
                }
            ],
            "annotations": [
                {"text": "AC = a", "x": 190, "y": 225},
                {"text": "CB = b", "x": 390, "y": 225},
            ],
        }

        result = self.renderer.render_scene(scene)
        self.assertTrue(result.path.exists())
        self.assertGreater(result.path.stat().st_size, 0)

    def test_label_position_aliases_produce_offsets(self) -> None:
        scene = {
            "points": [
                {"id": "A", "x": 0, "y": 0, "label": "A", "labelPosition": "southWest"},
                {"id": "B", "x": 4, "y": 0, "label": "B", "labelPosition": "southEast"},
            ],
            "segments": [
                {"from": "A", "to": "B", "label": "AB", "labelPosition": "north"},
            ],
        }

        normalized = self.renderer.parse_scene(scene)
        point_offsets = [entry.get("offset") for entry in normalized["points"]]

        self.assertTrue(all(offset for offset in point_offsets))
        self.assertEqual(normalized["segments"][0]["offset"][1] > 0, True)


if __name__ == "__main__":
    unittest.main()
