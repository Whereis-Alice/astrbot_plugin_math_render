import sys
import tempfile
import unittest
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_math_render.plotting import MathPlotService


class PlottingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir_ctx = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self._temp_dir_ctx.name)

    def tearDown(self) -> None:
        self._temp_dir_ctx.cleanup()

    def test_3d_parametric_curve_uses_t_gradient(self) -> None:
        plotter = MathPlotService(
            {
                "enable_cache": False,
                "plot_dpi": 80,
                "plot_parametric_sample_points": 600,
            },
            self.temp_dir,
        )

        result = plotter.plot_parametric_3d(
            "sin(2*t)",
            "cos(3*t)",
            "t/4",
            t_range="0,4*pi",
            title="3D Parametric Test",
        )

        self.assertTrue(result.path.exists())
        image = mpimg.imread(result.path)
        rgb = image[..., :3]
        if rgb.max() <= 1.0:
            rgb = rgb * 255

        warm_gradient_pixels = (
            (rgb[..., 0] > 180)
            & (rgb[..., 1] > 70)
            & (rgb[..., 2] < 170)
            & (rgb[..., 0] > rgb[..., 2] + 35)
        )
        cool_gradient_pixels = (
            (rgb[..., 2] > 120)
            & (rgb[..., 0] > 40)
            & (rgb[..., 0] < 180)
            & (rgb[..., 2] > rgb[..., 1] + 20)
        )

        self.assertGreater(int(np.count_nonzero(warm_gradient_pixels)), 50)
        self.assertGreater(int(np.count_nonzero(cool_gradient_pixels)), 50)

    def test_extra_3d_plot_modes_render_images(self) -> None:
        plotter = MathPlotService(
            {
                "enable_cache": False,
                "plot_dpi": 70,
                "plot_3d_grid_density": 32,
                "plot_implicit_3d_grid_density": 36,
                "plot_implicit_3d_slices": 18,
            },
            self.temp_dir,
        )

        results = [
            plotter.plot_spherical_3d("1+0.2*sin(3*theta)*cos(2*phi)"),
            plotter.plot_multiple_surfaces("x**2+y**2, sqrt(x**2+y**2)", x_range="-1,1", y_range="-1,1"),
            plotter.plot_implicit_3d("x**2+y**2+z**2=1", x_range="-1.2,1.2", y_range="-1.2,1.2", z_range="-1.2,1.2"),
            plotter.plot_vectors_3d("1,2,3:red:v1; 0,0,0->3,4,1:blue:v2"),
        ]

        for result in results:
            with self.subTest(path=result.path):
                self.assertTrue(result.path.exists())
                self.assertGreater(result.path.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
