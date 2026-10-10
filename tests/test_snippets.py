import unittest

from dictate.snippets import expand_snippets

SNIPPETS = (
    {"trigger": "my signature", "text": "Best,\nJordan"},
    {"trigger": "office address", "text": "1 Main St"},
)


class SnippetTests(unittest.TestCase):
    def test_whole_dictation_matches_trigger_ignoring_punctuation(self):
        self.assertEqual(expand_snippets("My signature.", SNIPPETS), "Best,\nJordan")
        self.assertEqual(expand_snippets("  my   SIGNATURE ", SNIPPETS), "Best,\nJordan")

    def test_inline_triggers_expand_within_text(self):
        text = "Send it to the office address and add my signature."
        self.assertEqual(expand_snippets(text, SNIPPETS), "Send it to the 1 Main St and add Best,\nJordan.")

    def test_partial_words_are_not_expanded(self):
        self.assertEqual(expand_snippets("myoffice addresses", SNIPPETS), "myoffice addresses")

    def test_no_snippets_returns_text(self):
        self.assertEqual(expand_snippets("hello there", ()), "hello there")
