"""Committed names and searches share normal Unicode field editing."""

import unittest

from roads_beneath_shadow.text_input import TextEntry


class TextEntryTests(unittest.TestCase):
    def test_insert_at_caret_and_delete_preserve_surrounding_words(self):
        entry = TextEntry("silver star")
        entry.home()
        self.assertTrue(entry.insert("the "))
        self.assertEqual(entry.text, "the silver star")
        entry.home()
        self.assertTrue(entry.delete(word=True))
        self.assertEqual(entry.text, "silver star")
        entry.end()
        self.assertTrue(entry.backspace(word=True))
        self.assertEqual(entry.text, "silver ")

    def test_shift_selection_replacement_and_collapse_do_not_remove_other_text(self):
        entry = TextEntry("silver star")
        entry.navigate(-1, select=True, word=True)
        self.assertEqual(entry.selection, (7, 11))
        entry.insert("moon")
        self.assertEqual(entry.text, "silver moon")
        entry.home(select=True)
        entry.navigate(1)
        self.assertEqual(entry.cursor, len(entry.text))
        self.assertFalse(entry.has_selection)

    def test_name_limit_counts_committed_source_and_allows_selected_replacement(self):
        source = "ÉowenÁlfrúnÞórhildurÖrnß"
        entry = TextEntry(source, max_length=24)
        self.assertEqual(entry.text, source)
        self.assertFalse(entry.insert("overflow"))
        entry.select_all()
        self.assertTrue(entry.insert("Míra"))
        self.assertEqual(entry.text, "Míra")
        self.assertEqual(entry.cursor, 4)

    def test_decomposed_accents_move_and_erase_together_without_normalizing_source(self):
        entry = TextEntry("E\u0301owen")
        entry.home()
        entry.navigate(1)
        self.assertEqual(entry.cursor, 2)
        self.assertEqual(entry.text, "E\u0301owen")
        entry.backspace()
        self.assertEqual(entry.text, "owen")
        entry.insert("E\u0301")
        entry.home()
        entry.delete()
        self.assertEqual(entry.text, "owen")

    def test_line_breaks_in_a_pasted_phrase_keep_words_separate(self):
        entry = TextEntry()
        entry.insert("silver\nstar\tremembers")
        self.assertEqual(entry.text, "silver star remembers")
        self.assertFalse(entry.insert("\x00"))

    def test_empty_edges_and_combining_mouse_positions_stay_in_bounds(self):
        entry = TextEntry()
        self.assertFalse(entry.backspace())
        self.assertFalse(entry.delete())
        entry.navigate(-1)
        entry.navigate(1)
        self.assertEqual(entry.cursor, 0)
        entry.set_text("E\u0301owen")
        entry.move_to(1)
        self.assertEqual(entry.cursor, 0)
        entry.move_to(999)
        self.assertEqual(entry.cursor, len(entry.text))


if __name__ == "__main__":
    unittest.main()
