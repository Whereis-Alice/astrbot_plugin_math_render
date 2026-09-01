import asyncio
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARENT_ROOT = PROJECT_ROOT.parent
if str(PARENT_ROOT) not in sys.path:
    sys.path.insert(0, str(PARENT_ROOT))

from astrbot_plugin_math_render.main import MathRenderPlugin
from astrbot_plugin_math_render.plotting import MathPlotService
from astrbot_plugin_math_render.config_utils import get_config_value


class PlotOptimizationTests(unittest.TestCase):
    def test_main_import_does_not_load_heavy_plotting_backend(self) -> None:
        script = """
import json
import sys
sys.path.insert(0, r'{root}')
import astrbot_plugin_math_render.main
print(json.dumps({{name: any(item == name or item.startswith(name + '.') for item in sys.modules) for name in ('matplotlib', 'sympy', 'mpl_toolkits')}}))
""".format(root=str(PARENT_ROOT).replace("\\", "\\\\"))
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        marker = next(line for line in reversed(completed.stdout.splitlines()) if line.startswith("{"))
        loaded = json.loads(marker)
        self.assertEqual(loaded, {"matplotlib": False, "sympy": False, "mpl_toolkits": False})

    def test_plot_cache_key_changes_when_sampling_config_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = MathPlotService({"plot_sample_points": 500}, Path(directory))
            second = MathPlotService({"plot_sample_points": 501}, Path(directory))
            self.assertNotEqual(first._cache_key("function", "sin(x)"), second._cache_key("function", "sin(x)"))

    def test_cache_trim_respects_file_limit_and_protected_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = MathPlotService(
                {"plot_cache_max_files": 2, "plot_cache_max_bytes": 1_048_576},
                root,
            )
            old = root / "plot_old.png"
            middle = root / "plot_middle.png"
            protected = root / "plot_new.png"
            old.write_bytes(b"0")
            middle.write_bytes(b"1")
            protected.write_bytes(b"2")
            old.touch()
            middle.touch()
            protected.touch()

            service._trim_cache(protected=protected)

            files = sorted(root.glob("plot_*.png"))
            self.assertLessEqual(len(files), 2)
            self.assertTrue(protected.exists())

    def test_expression_and_range_limits_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = MathPlotService(
                {
                    "plot_max_expression_length": 64,
                    "plot_max_range_span": 5,
                },
                Path(directory),
            )
            with self.assertRaises(ValueError):
                service._parse_expr("x" * 65, variables=("x",))
            with self.assertRaises(ValueError):
                service._parse_range("0,6", "0,1")

    def test_common_labelled_expression_forms_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = MathPlotService({"enable_cache": False, "plot_sample_points": 128}, Path(directory))
            function_result = service.plot_function("y=sin(x)", x_range="-1,1")
            polar_result = service.plot_polar("r=sin(theta)", theta_range="0,pi")
            self.assertTrue(function_result.path.exists())
            self.assertTrue(polar_result.path.exists())
            service.release()

    def test_plotter_runs_in_worker_thread_and_serializes_calls(self) -> None:
        class FakePlotter:
            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self.thread_ids: list[int] = []

            def render(self, value: int) -> int:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.thread_ids.append(threading.get_ident())
                import time

                time.sleep(0.02)
                self.active -= 1
                return value * 2

        plugin = MathRenderPlugin.__new__(MathRenderPlugin)
        plugin.plotter = FakePlotter()
        plugin._plot_lock = None

        async def run() -> list[int]:
            return await asyncio.gather(plugin._run_plotter("render", 2), plugin._run_plotter("render", 3))

        results = asyncio.run(run())
        self.assertEqual(results, [4, 6])
        self.assertEqual(plugin.plotter.max_active, 1)
        self.assertTrue(all(thread_id != threading.get_ident() for thread_id in plugin.plotter.thread_ids))

    def test_logo_is_dashboard_ready_png(self) -> None:
        logo = PROJECT_ROOT / "logo.png"
        self.assertTrue(logo.exists())
        with Image.open(logo) as image:
            self.assertEqual(image.size, (512, 512))
            self.assertEqual(image.format, "PNG")

    def test_new_nested_plot_settings_are_read(self) -> None:
        config = {
            "plot_settings": {
                "plot_implicit_3d_slices": 12,
                "plot_max_vectors": 8,
            }
        }
        self.assertEqual(get_config_value(config, "plot_implicit_3d_slices", 48), 12)
        self.assertEqual(get_config_value(config, "plot_max_vectors", 16), 8)


if __name__ == "__main__":
    unittest.main()
