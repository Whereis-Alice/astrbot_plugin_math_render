import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_math_render.rendering import MathRenderService, SolutionCardContent


class SolutionMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MathRenderService(plugin=None, config={})

    def test_free_markdown_strips_trailing_geometry_placeholder(self) -> None:
        content = SolutionCardContent(
            question="",
            layout_mode="free",
            markdown_content="# 证明\n\n已知 D、E 分别是 AB、AC 的中点。\n\n几何示意图：",
            geometry_scene={
                "points": [
                    {"name": "A", "x": 0, "y": 1},
                    {"name": "B", "x": -1, "y": 0},
                    {"name": "C", "x": 1, "y": 0},
                ],
                "segments": [{"from": "A", "to": "B"}, {"from": "A", "to": "C"}],
            },
        )

        markdown = self.service._build_solution_markdown(content)

        self.assertIn("已知 D、E", markdown)
        self.assertNotIn("几何示意图", markdown)

    def test_free_markdown_keeps_placeholder_without_visual_payload(self) -> None:
        content = SolutionCardContent(
            question="",
            layout_mode="free",
            markdown_content="# 证明\n\n几何示意图：",
        )

        markdown = self.service._build_solution_markdown(content)

        self.assertIn("几何示意图", markdown)


if __name__ == "__main__":
    unittest.main()
