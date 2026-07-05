import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_math_render.main import MathRenderPlugin


class PlotToolRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = MathRenderPlugin.__new__(MathRenderPlugin)

    def test_parse_3d_parametric_equations(self) -> None:
        parts = self.plugin._parse_3d_parametric_equations("x=sin(2t), y=cos(3t), z=t/4")

        self.assertEqual(parts, {"x": "sin(2t)", "y": "cos(3t)", "z": "t/4"})

    def test_surface_expression_is_not_parametric_equations(self) -> None:
        parts = self.plugin._parse_3d_parametric_equations("cos(x) * cos(y)")

        self.assertIsNone(parts)

    def test_plot_spec_expression_infers_parametric3d(self) -> None:
        kind = self.plugin._infer_plot_kind({"expression": "x=sin(2t), y=cos(3t), z=t/4"})

        self.assertEqual(kind, "parametric3d")


if __name__ == "__main__":
    unittest.main()
