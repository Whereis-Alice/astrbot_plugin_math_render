import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_math_render.solving import build_solver_prompt, parse_solver_response


class PlotSolutionCardTests(unittest.TestCase):
    def test_parse_solver_response_keeps_plot_spec(self) -> None:
        raw = json.dumps(
            {
                "answer": "The vertex is $(2,-1)$.",
                "key_formula": "y=(x-2)^2-1",
                "plot_spec": {
                    "kind": "function",
                    "expression": "x^2-4*x+3",
                    "x_range": "-1,5",
                },
                "plot_caption": "Parabola with vertex at (2,-1).",
                "plot_position": "after_key_formula",
            }
        )

        content = parse_solver_response(raw, "Find the vertex and draw the graph.")

        self.assertEqual(content.plot_spec["kind"], "function")
        self.assertEqual(content.plot_spec["expression"], "x^2-4*x+3")
        self.assertEqual(content.plot_caption, "Parabola with vertex at (2,-1).")
        self.assertEqual(content.plot_position, "after_key_formula")

    def test_solver_prompt_mentions_plot_spec_when_enabled(self) -> None:
        prompt = build_solver_prompt("Draw y=x^2.", plot_enabled=True)

        self.assertIn("plot_spec", prompt)
        self.assertIn("function", prompt)


if __name__ == "__main__":
    unittest.main()
