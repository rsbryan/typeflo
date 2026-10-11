import unittest

from dictate.context import fit_to_context


class FitToContextTests(unittest.TestCase):
    def test_unknown_context_leaves_text_alone(self):
        self.assertEqual(fit_to_context("Hello there.", None, None), "Hello there.")
        self.assertEqual(fit_to_context("Hello there.", "", ""), "Hello there.")

    def test_word_inserted_mid_sentence(self):
        self.assertEqual(fit_to_context("Simply.", "the word would ", "be uppercase"), "simply ")
        self.assertEqual(fit_to_context("Rather.", "at the end,", "than being"), " rather ")

    def test_continuing_an_unfinished_sentence(self):
        self.assertEqual(fit_to_context("This is great.", "I think", ""), " this is great.")
        self.assertEqual(fit_to_context("This is great.", "I think ", ""), "this is great.")

    def test_new_sentence_after_period_or_newline(self):
        self.assertEqual(fit_to_context("Second thought.", "First thought.", "Third thought."), " Second thought. ")
        self.assertEqual(fit_to_context("Second thought.", "First thought.\n", ""), "Second thought.")
        self.assertEqual(fit_to_context("Hello.", "", "Next line"), "Hello. ")

    def test_before_existing_punctuation(self):
        self.assertEqual(fit_to_context("Really.", "I mean ", "."), "really")
        self.assertEqual(fit_to_context("Really.", "I mean ", ", anyway"), "really")
        self.assertEqual(fit_to_context("Hello.", "(", ")"), "hello")

    def test_keeps_proper_nouns_and_i(self):
        self.assertEqual(fit_to_context("I think so.", "and then ", ""), "I think so.")
        self.assertEqual(fit_to_context("I'm sure.", "and then ", ""), "I'm sure.")
        self.assertEqual(fit_to_context("Typeflo works.", "and ", "", ("Typeflo",)), "Typeflo works.")
        self.assertEqual(fit_to_context("iPhone works.", "and ", ""), "iPhone works.")
        self.assertEqual(fit_to_context("Hello world.", "and ", ""), "hello world.")
