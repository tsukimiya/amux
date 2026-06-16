"""Unit tests for board auto-completion gating helpers.

These tests load the real amux-server.py via importlib (the __main__ guard
prevents the HTTP server from starting) and exercise the helper that decides
whether an idle pane is truly complete or just waiting for human input.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SERVER_PATH = REPO_ROOT / "amux-server.py"


def _load_server():
    spec = importlib.util.spec_from_file_location("amux_server", SERVER_PATH)
    assert spec is not None and spec.loader is not None, f"could not load {SERVER_PATH}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["amux_server"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestPaneHasPendingQuestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_server()

    def test_free_form_question_at_end(self):
        raw = "Some output here\nShould I run the tests now?"
        self.assertTrue(self.mod._pane_has_pending_question(raw))

    def test_full_width_question(self):
        raw = "Some output here\nWhat should I do next？"
        self.assertTrue(self.mod._pane_has_pending_question(raw))

    def test_question_with_ansi_codes(self):
        raw = "\x1b[32mSome output\x1b[0m\n\x1b[1mShould I continue?\x1b[0m"
        self.assertTrue(self.mod._pane_has_pending_question(raw))

    def test_completed_spinner_no_question(self):
        raw = "Working...\n✻ Brewed for 1m 8s"
        self.assertFalse(self.mod._pane_has_pending_question(raw))

    def test_active_spinner_no_question(self):
        raw = "✻ Beaming… (1m 3s)"
        self.assertFalse(self.mod._pane_has_pending_question(raw))

    def test_status_bar_only(self):
        raw = "Some earlier content\n⏵⏵  ·  bash  ·  0 tools"
        self.assertFalse(self.mod._pane_has_pending_question(raw))

    def test_input_box_prompt(self):
        raw = (
            "╭──────────────────────────────╮\n"
            "│ How would you like to proceed? │\n"
            "╰──────────────────────────────╯\n"
            "❯ Continue"
        )
        self.assertFalse(self.mod._pane_has_pending_question(raw))

    def test_selector_prompt(self):
        raw = "Do you want to proceed?\n❯ 1. Yes\n  2. No"
        self.assertFalse(self.mod._pane_has_pending_question(raw))

    def test_code_with_question_not_at_end(self):
        raw = "x = input('name?')\nprint('done')"
        self.assertFalse(self.mod._pane_has_pending_question(raw))

    def test_empty_pane(self):
        self.assertFalse(self.mod._pane_has_pending_question(""))

    def test_whitespace_only_pane(self):
        self.assertFalse(self.mod._pane_has_pending_question("   \n  \n "))


class TestDetectClaudeStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_server()

    def test_pager_screen(self):
        raw = (
            "commit abc123\n"
            "Author: User <user@example.com>\n"
            "Date:   Mon Jan 1 00:00:00 2024\n"
            "\n"
            "    Some commit message\n"
            "\n"
            "diff --git a/file b/file\n"
            "..."
        )
        self.assertEqual(self.mod._detect_claude_status(raw), "")

    def test_completed_spinner(self):
        raw = "✻ Brewed for 1m 8s"
        self.assertEqual(self.mod._detect_claude_status(raw), "idle")

    def test_active_spinner(self):
        raw = "✻ Beaming… (1m 3s)"
        self.assertEqual(self.mod._detect_claude_status(raw), "active")

    def test_waiting_selector(self):
        raw = "Do you want to proceed?\n❯ 1. Yes\n  2. No"
        self.assertEqual(self.mod._detect_claude_status(raw), "waiting")


if __name__ == "__main__":
    unittest.main()
