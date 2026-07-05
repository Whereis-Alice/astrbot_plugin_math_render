import base64
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot.api.event import MessageEventResult
from astrbot_plugin_math_render.main import MathRenderPlugin


class FakeEvent:
    unified_msg_origin = "default:GroupMessage:10000"

    def __init__(self, *, raise_error: Exception | None = None) -> None:
        self.sent_chains = []
        self.raise_error = raise_error

    def make_result(self) -> MessageEventResult:
        return MessageEventResult()

    def plain_result(self, text: str) -> MessageEventResult:
        return MessageEventResult().message(text)

    def chain_result(self, chain) -> MessageEventResult:
        result = MessageEventResult()
        result.chain = chain
        return result

    async def send(self, chain) -> None:
        if self.raise_error:
            raise self.raise_error
        self.sent_chains.append(chain)


class FakeContext:
    def __init__(self, *, result: object = True, raise_error: Exception | None = None) -> None:
        self.result = result
        self.raise_error = raise_error
        self.calls = []

    async def send_message(self, session, chain) -> object:
        self.calls.append((session, chain))
        if self.raise_error:
            raise self.raise_error
        return self.result


class FakeAmbiguousTimeout(Exception):
    def __init__(self) -> None:
        self.result = {
            "retcode": 1200,
            "message": "Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg",
            "wording": "Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg",
        }
        super().__init__(
            "<ActionFailed status='failed', retcode=1200, "
            "message='Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg'>"
        )


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
        plugin.context = FakeContext()
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

    def test_tool_image_send_uses_context_send_message(self) -> None:
        plugin = self._plugin()
        event = FakeEvent()

        fallback = asyncio.run(plugin._send_image_from_tool(event, self.image_path))

        self.assertIsNone(fallback)
        self.assertEqual(len(plugin.context.calls), 1)
        session, chain = plugin.context.calls[0]
        self.assertEqual(session, event.unified_msg_origin)
        self.assertEqual(chain.chain[0].path, str(self.image_path))
        self.assertEqual(event.sent_chains, [])

    def test_tool_image_send_treats_context_none_return_as_success(self) -> None:
        plugin = self._plugin()
        plugin.context = FakeContext(result=None)
        event = FakeEvent()

        fallback = asyncio.run(plugin._send_image_from_tool(event, self.image_path))

        self.assertIsNone(fallback)
        self.assertEqual(len(plugin.context.calls), 1)
        self.assertEqual(event.sent_chains, [])

    def test_tool_image_send_falls_back_to_event_send(self) -> None:
        plugin = self._plugin()
        plugin.context = FakeContext(result=False)
        event = FakeEvent()

        fallback = asyncio.run(plugin._send_image_from_tool(event, self.image_path))

        self.assertIsNone(fallback)
        self.assertEqual(len(plugin.context.calls), 1)
        self.assertEqual(len(event.sent_chains), 1)
        self.assertEqual(event.sent_chains[0].chain[0].path, str(self.image_path))

    def test_tool_image_send_skips_event_fallback_on_ambiguous_context_timeout(self) -> None:
        plugin = self._plugin()
        plugin.context = FakeContext(raise_error=FakeAmbiguousTimeout())
        event = FakeEvent()

        fallback = asyncio.run(plugin._send_image_from_tool(event, self.image_path))

        self.assertIsNone(fallback)
        self.assertEqual(len(plugin.context.calls), 1)
        self.assertEqual(event.sent_chains, [])

    def test_tool_image_send_failure_returns_builtin_tool_instruction(self) -> None:
        plugin = self._plugin()
        plugin.context = FakeContext(raise_error=RuntimeError("boom"))
        event = FakeEvent(raise_error=RuntimeError("event boom"))

        fallback = asyncio.run(plugin._send_image_from_tool(event, self.image_path, "plot ready"))

        self.assertIsNotNone(fallback)
        self.assertIn("send_message_to_user", fallback)
        self.assertIn(str(self.image_path), fallback)
        self.assertIn("context.send_message failed", fallback)
        self.assertIn("event.send failed", fallback)
        self.assertIn("plot ready", fallback)

    def test_tool_direct_send_result_keeps_agent_loop_alive(self) -> None:
        result = self._plugin()._tool_direct_send_result("plot ready")

        self.assertIn("sent directly to the user", result)
        self.assertIn("Reply with one short natural follow-up", result)
        self.assertIn("plot ready", result)
        self.assertNotEqual(result, "")


if __name__ == "__main__":
    unittest.main()
