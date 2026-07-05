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


if __name__ == "__main__":
    unittest.main()
