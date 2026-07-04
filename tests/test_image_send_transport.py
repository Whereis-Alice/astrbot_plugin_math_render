import base64
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot.api.event import MessageEventResult
from astrbot_plugin_math_render.main import MathRenderPlugin


class FakeEvent:
    def make_result(self) -> MessageEventResult:
        return MessageEventResult()

    def plain_result(self, text: str) -> MessageEventResult:
        return MessageEventResult().message(text)


class DictConfig(dict):
    pass


class ImageSendTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir_ctx = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self._temp_dir_ctx.name)
        self.image_path = self.temp_dir / "card.png"
        self.image_path.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            )
        )

    def tearDown(self) -> None:
        self._temp_dir_ctx.cleanup()

    def _plugin(self, **config: object) -> MathRenderPlugin:
        plugin = MathRenderPlugin.__new__(MathRenderPlugin)
        plugin.config = DictConfig(config)
        return plugin

    def test_default_image_transport_uses_file_path_component(self) -> None:
        result = self._plugin()._image_result_for_send(FakeEvent(), self.image_path)

        self.assertEqual(len(result.chain), 1)
        image = result.chain[0]
        self.assertEqual(image.path, str(self.image_path))
        self.assertTrue(image.file.startswith("file:///"))

    def test_base64_image_transport_remains_available(self) -> None:
        result = self._plugin(send_image_transport="base64")._image_result_for_send(FakeEvent(), self.image_path)

        self.assertEqual(len(result.chain), 1)
        image = result.chain[0]
        self.assertTrue(image.file.startswith("base64://"))
        self.assertFalse(getattr(image, "path", ""))


if __name__ == "__main__":
    unittest.main()
