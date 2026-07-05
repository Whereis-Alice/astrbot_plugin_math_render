import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_math_render.main import MathRenderPlugin
from astrbot_plugin_math_render.plotting import PlotResult


class FakePlotter:
    def __init__(self) -> None:
        self.calls = []

    def plot_multiple_surfaces(self, expressions: str, **kwargs):
        self.calls.append(("plot_multiple_surfaces", expressions, kwargs))
        return PlotResult(Path("multiple.png"), "multiple")

    def plot_spherical_3d(self, expression: str, **kwargs):
        self.calls.append(("plot_spherical_3d", expression, kwargs))
        return PlotResult(Path("spherical.png"), "spherical")

    def plot_implicit_3d(self, equation: str, **kwargs):
        self.calls.append(("plot_implicit_3d", equation, kwargs))
        return PlotResult(Path("implicit3d.png"), "implicit3d")

    def plot_vectors_3d(self, vectors: str, **kwargs):
        self.calls.append(("plot_vectors_3d", vectors, kwargs))
        return PlotResult(Path("vectors.png"), "vectors")


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

    def test_plot_spec_expression_infers_implicit3d(self) -> None:
        kind = self.plugin._infer_plot_kind({"expression": "x^2+y^2+z^2=1"})

        self.assertEqual(kind, "implicit3d")

    def test_plot_spec_phi_infers_spherical(self) -> None:
        kind = self.plugin._infer_plot_kind({"expression": "1+0.2*sin(theta)*cos(phi)"})

        self.assertEqual(kind, "spherical")

    def test_plot_spec_vectors_infers_vector3d(self) -> None:
        kind = self.plugin._infer_plot_kind({"vectors": "1,2,3:red:v1"})

        self.assertEqual(kind, "vector3d")

    def test_new_plot_spec_kinds_route_to_plotter(self) -> None:
        fake = FakePlotter()
        self.plugin.plotter = fake

        specs = [
            {"kind": "multiple_surfaces", "expressions": ["x^2+y^2", "sqrt(x^2+y^2)"]},
            {"kind": "spherical", "expression": "1+sin(theta)*cos(phi)"},
            {"kind": "implicit3d", "expression": "x^2+y^2+z^2=1"},
            {"kind": "vector3d", "vectors": "1,2,3:red:v1"},
        ]
        for spec in specs:
            self.plugin._render_plot_spec(spec)

        self.assertEqual(
            [name for name, _payload, _kwargs in fake.calls],
            ["plot_multiple_surfaces", "plot_spherical_3d", "plot_implicit_3d", "plot_vectors_3d"],
        )


if __name__ == "__main__":
    unittest.main()
