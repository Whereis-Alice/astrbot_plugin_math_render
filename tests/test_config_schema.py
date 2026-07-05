import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_math_render.config_utils import get_config_value


class ConfigSchemaTests(unittest.TestCase):
    def test_nested_config_value_is_read(self) -> None:
        config = {
            "image_delivery_settings": {
                "send_image_transport": "base64",
            }
        }

        self.assertEqual(get_config_value(config, "send_image_transport", "file"), "base64")

    def test_legacy_custom_value_beats_nested_default(self) -> None:
        config = {
            "send_image_max_side": 2048,
            "image_delivery_settings": {
                "send_image_max_side": 4096,
            },
        }

        self.assertEqual(get_config_value(config, "send_image_max_side", 4096), 2048)

    def test_schema_is_grouped_and_plot_text_is_chinese(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(schema["plot_settings"]["type"], "object")
        self.assertEqual(schema["plot_settings"]["description"], "函数绘图")
        self.assertTrue(schema["plot_tool_prompt_enabled"]["invisible"])
        plot_item = schema["plot_settings"]["items"]["plot_tool_prompt_enabled"]
        self.assertEqual(plot_item["description"], "启用 LLM 绘图工具提示注入")
        self.assertNotIn("Enable LLM", plot_item["description"])
        prompt = schema["plot_settings"]["items"]["plot_tool_awareness_prompt"]["default"]
        self.assertIn("plot_3d_spherical", prompt)
        self.assertIn("plot_implicit_3d", prompt)


if __name__ == "__main__":
    unittest.main()
