from __future__ import annotations

import sys
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
HERMES_SOURCE = REPO_ROOT.parent / "hermes-agent-upstream"
sys.path.insert(0, str(REPO_ROOT))
if str(HERMES_SOURCE) not in sys.path:
    sys.path.insert(0, str(HERMES_SOURCE))

from hermes_chathub_connector import register


class FakeContext:
    def __init__(self) -> None:
        self.registered = []

    def register_tool(self, **kwargs) -> None:
        self.registered.append(kwargs)


class RegisterTests(unittest.TestCase):
    def test_registers_both_chathub_tools(self) -> None:
        ctx = FakeContext()

        register(ctx)

        self.assertEqual(
            {item["name"] for item in ctx.registered},
            {"list_chathub_tools", "exec_chathub_tools"},
        )
        self.assertEqual(len(ctx.registered), 2)
        for item in ctx.registered:
            self.assertEqual(item["toolset"], "chathub")
            self.assertEqual(item["schema"]["name"], item["name"])
            self.assertIsInstance(item["schema"], dict)
            self.assertTrue(callable(item["handler"]))


if __name__ == "__main__":
    unittest.main()
