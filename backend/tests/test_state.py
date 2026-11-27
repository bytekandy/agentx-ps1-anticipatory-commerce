import json
import unittest
from pathlib import Path

from anticipatory.lexicon import Lexicon, load_rows
from anticipatory.state import FilterState, build_snapshot, find_markers
from anticipatory.tokens import tokenize, tokenize_text
from anticipatory.state import build_snapshot, find_markers
from anticipatory.tokens import tokenize_text

DEV_PATH = Path(__file__).resolve().parents[1] / "dev.jsonl"
SLOTS = ("category", "colour", "size", "brand", "max_price")


class StateTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = Lexicon(load_rows())

    def snap(self, text, final=True):
        return build_snapshot(tokenize_text(text), self.lex, final=final)

    def stream(self, text):
        """One snapshot per word, as the agent will see them."""
        state = FilterState(self.lex)
        return [state.push(w) for w in text.split()]


class ReadingTest(StateTestCase):
    def test_a_plain_request(self):
        s = self.snap("show me Tanaro shirt less than 900 in navy blue small please")
        self.assertEqual(s.filters, {"category": "shirts", "colour": "navy", "size": "S",
                                     "brand": "Tanaro", "max_price": 900})
        self.assertTrue(s.settled)

    def test_nothing_heard_yet(self):
        s = self.snap("")
        self.assertEqual(s.words_seen, 0)
        self.assertEqual(s.confidence, 0.0)
        self.assertTrue(all(v is None for v in s.filters.values()))

    def test_confidence_is_the_weakest_slot(self):
        s = self.snap("black slides")           # exact colour 0.95, synonym category 0.85
        self.assertEqual(s.confidence, 0.85)

    def test_min_price_is_reported_only_when_present(self):
        self.assertNotIn("min_price", self.snap("black watch").filters)
        self.assertEqual(self.snap("black watch above 2000").filters["min_price"], 2000)

    def test_weak_guesses_are_left_out(self):
        self.assertIsNone(self.snap("black sandals 9").filters["size"])
        self.assertIsNone(self.snap("need it in 10 days").filters["size"])

    def test_quiet_words_and_clause_end(self):
        s = self.snap("black sandals, please do hurry")
        self.assertEqual(s.quiet_words, 3)
        self.assertFalse(s.at_clause_end)
        s = self.snap("black sandals,")
        self.assertEqual(s.quiet_words, 0)
        self.assertTrue(s.at_clause_end)


class SizeFitTest(StateTestCase):
    def test_size_must_fit_the_category(self):
        self.assertEqual(self.snap("size 32 jeans").filters["size"], "32")
        self.assertIsNone(self.snap("size 9 jeans").filters["size"])
        self.assertEqual(self.snap("size 9 sandals").filters["size"], "9")

    def test_a_later_category_can_cancel_an_earlier_size(self):
        before = self.snap("size M", final=False)
        self.assertEqual(before.filters["size"], "M")
        after = self.snap("size M backpack", final=False)
        self.assertIsNone(after.filters["size"])

    def test_the_fitting_size_wins_over_a_misfit_one(self):
        self.assertEqual(self.snap("size 9 sandals sorry size 32").filters["size"], "9")


class RevisionTest(StateTestCase):
    def test_marked_revision(self):
        belief = self.snap("black sorry navy cap").slots["colour"]
        self.assertEqual(belief.value, "navy")
        self.assertEqual(belief.revisions, 1)
        self.assertEqual(belief.history[0][0], "black")
        self.assertTrue(belief.marked)
        self.assertGreaterEqual(belief.confidence, 0.9)

    def test_unmarked_conflict_still_wins_but_is_trusted_less(self):
        belief = self.snap("black cap navy").slots["colour"]
        self.assertEqual(belief.value, "navy")
        self.assertFalse(belief.marked)
        self.assertEqual(belief.confidence, 0.60)

    def test_saying_the_same_thing_again_is_not_a_revision(self):
        belief = self.snap("size M jacket, M size").slots["size"]
        self.assertEqual(belief.revisions, 0)

    def test_two_word_markers(self):
        for text in ("yellow size L make that XXL tee", "red cap make it blue"):
            with self.subTest(text=text):
                markers = find_markers(tokenize_text(text))
                self.assertEqual([m.text for m in markers][-1].split()[0], "make")
                self.assertTrue(any(b.marked for b in self.snap(text).slots.values()))

    def test_make_sure_is_not_a_marker(self):
        self.assertEqual(find_markers(tokenize_text("make sure it is red")), [])

    def test_no_more_than_is_a_price_not_a_correction(self):
        self.assertEqual(find_markers(tokenize_text("watch no more than 1500")), [])
        s = self.snap("watch no more than 1500")
        self.assertFalse(s.correction_pending)
        self.assertEqual(s.filters["max_price"], 1500)

    def test_category_can_be_revised(self):
        s = self.snap("navy shirt size M, no, change that to dress")
        self.assertEqual(s.filters["category"], "dresses")
        self.assertEqual(s.slots["category"].revisions, 1)

    def test_a_correction_may_target_an_earlier_slot(self):
        s = self.snap("white dress large, from Loomsy sorry, I meant size M")
        self.assertEqual(s.filters["size"], "M")
        self.assertEqual(s.filters["brand"], "Loomsy")
        self.assertEqual(s.slots["brand"].revisions, 0)

    def test_hindi_markers(self):
        s = self.snap("dikhao Strydo hoodie in navy, nahi, in olive green")
        self.assertEqual(s.filters["colour"], "olive")
        s = self.snap("Horavo, matlab Tikkra wrist watch")
        self.assertEqual(s.filters["brand"], "Tikkra")


class RestatementTest(StateTestCase):
    def test_bare_number_after_a_marker_restates_the_size(self):
        s = self.snap("olive size eight actually six slides")
        self.assertEqual(s.filters["size"], "6")
        self.assertTrue(s.slots["size"].marked)

    def test_bare_number_after_a_marker_restates_the_price(self):
        s = self.snap("black cap under 800, no, 900")
        self.assertEqual(s.filters["max_price"], 900)

    def test_a_bare_number_without_a_marker_stays_a_weak_guess(self):
        s = self.snap("olive size eight slides 6")
        self.assertEqual(s.filters["size"], "8")

    def test_a_marker_alone_does_not_turn_a_bare_number_into_a_new_size(self):
        s = self.snap("olive slides actually 6")        # no earlier size to restate
        self.assertIsNone(s.filters["size"])


class PendingCorrectionTest(StateTestCase):
    def test_pending_from_the_marker_until_the_replacement(self):
        snaps = self.stream("black cap oops, navy under 500")
        flags = [s.correction_pending for s in snaps]
        self.assertEqual(flags, [False, False, True, False, False, False])

    def test_it_stays_pending_while_the_replacement_is_still_growing(self):
        state = FilterState(self.lex)
        pending = [state.push(w).correction_pending
                   for w in "white cap under 500 no under two thousand five hundred".split()]
        self.assertTrue(pending[4])                        # "no": the replacement is awaited
        self.assertTrue(pending[7])                        # "two thousand": still growing
        self.assertTrue(pending[-1])                       # "hundred": could still grow
        final = state.finish()
        self.assertFalse(final.correction_pending)
        self.assertEqual(final.filters["max_price"], 2500)

    def test_a_marker_with_no_replacement_expires(self):
        snaps = self.stream("black cap sorry about the long wait for the rest of it all now")
        self.assertTrue(snaps[2].correction_pending)
        self.assertFalse(snaps[-1].correction_pending)

    def test_no_pending_without_a_marker(self):
        for s in self.stream("show me black Pacevo sandals size 9 under 1500 for a wedding"):
            self.assertFalse(s.correction_pending)

    def test_settled_needs_no_pending_correction_and_no_growing_number(self):
        self.assertFalse(self.snap("cap under two thousand", final=False).settled)
        self.assertTrue(self.snap("cap under two thousand", final=True).settled)
        self.assertFalse(self.snap("cap oops", final=False).settled)

    def test_confidence_is_halved_while_unsettled(self):
        steady = self.snap("black cap", final=False)
        unsettled = self.snap("black cap oops", final=False)
        self.assertAlmostEqual(unsettled.confidence, steady.confidence * 0.5)


class CuePendingTest(StateTestCase):
    def pending(self, text):
        return self.snap(text, final=False).cue_pending

    def test_a_cue_waiting_for_its_number_is_pending(self):
        for text in ("black cap within Rs.", "black cap up to", "black cap budget of",
                     "black cap under", "sandals size", "jeans waist"):
            with self.subTest(text=text):
                self.assertTrue(self.pending(text))
                self.assertFalse(self.snap(text, final=False).settled)

    def test_the_number_arriving_clears_it(self):
        self.assertFalse(self.pending("black cap under 500"))
        self.assertFalse(self.pending("sandals size 9"))

    def test_make_is_pending_because_it_may_become_make_that(self):
        self.assertTrue(self.pending("black cap make"))
        self.assertFalse(self.pending("black cap make that"))
        self.assertFalse(self.pending("black cap make sure"))

    def test_make_alone_is_not_a_correction_alarm(self):
        self.assertFalse(self.snap("black cap make", final=False).correction_pending)

    def test_a_cue_followed_by_a_pause_is_not_pending(self):
        self.assertFalse(self.pending("black cap under, hmm"))

    def test_plain_words_are_not_pending(self):
        self.assertFalse(self.pending("black cap please"))


class ConnectorPendingTest(CuePendingTest):
    def test_a_connector_announces_a_value(self):
        for text in ("grey Pacevo sneakers size 8 in", "Loomsy shirt XXL, and",
                     "Loomsy shirt XXL, and I'd", "the same but", "white cap aur"):
            with self.subTest(text=text):
                self.assertTrue(self.pending(text))
                self.assertFalse(self.snap(text, final=False).settled)

    def test_the_value_or_a_pause_or_two_words_close_it(self):
        for text in ("Loomsy shirt in white", "Loomsy shirt XXL, and, hmm",
                     "Loomsy shirt XXL, and thanks a lot", "black cap and."):
            with self.subTest(text=text):
                self.assertFalse(self.pending(text))
        self.assertFalse(self.pending(""))


class NumberGrowthTest(StateTestCase):
    def test_a_growing_price_is_pending_and_not_yet_read(self):
        s = self.snap("shirt under two thousand", final=False)
        self.assertEqual(s.pending_slots, ("max_price",))
        self.assertIsNone(s.filters["max_price"])

    def test_the_next_word_or_the_end_settles_it(self):
        self.assertEqual(self.snap("shirt under two thousand please",
                                   final=False).filters["max_price"], 2000)
        self.assertEqual(self.snap("shirt under two thousand", final=True).filters["max_price"],
                         2000)

    def test_it_grows_into_a_bigger_price(self):
        snaps = self.stream("shirt under two thousand five hundred please")
        # "five" and "hundred" may still grow, so the price shows up when "please" arrives
        self.assertEqual([s.filters["max_price"] for s in snaps[-3:]], [None, None, 2500])


class LateConstraintTest(StateTestCase):
    def test_afterthoughts_are_flagged(self):
        s = self.snap("black cap, and from Pacevo")
        self.assertTrue(s.slots["brand"].late)
        self.assertFalse(s.slots["colour"].late)
        s = self.snap("I'd like black joggers size S, not more than 1k. oh, and from Pacevo")
        self.assertTrue(s.slots["brand"].late)
        self.assertEqual(s.filters["max_price"], 1000)

    def test_a_late_constraint_does_not_disturb_earlier_slots(self):
        s = self.snap("Strydo runners size 11 UK, and in blue")
        self.assertEqual(s.filters, {"category": "running shoes", "colour": "blue",
                                     "size": "11", "brand": "Strydo", "max_price": None})
        self.assertTrue(s.slots["colour"].late)

    def test_hindi_afterthought(self):
        s = self.snap("mere liye dress small, Mehrin wala, ek aur baat, in navy blue chahiye")
        self.assertTrue(s.slots["colour"].late)


class StreamingTest(StateTestCase):
    def test_push_matches_the_pure_function(self):
        text = "get me white dress large, from Loomsy sorry, I meant size M"
        state = FilterState(self.lex)
        for i, word in enumerate(text.split(), start=1):
            got = state.push(word)
            want = build_snapshot(tokenize(text.split()[:i]), self.lex)
            self.assertEqual(got, want)

    def test_reset_starts_a_new_request(self):
        state = FilterState(self.lex)
        for w in "black cap oops".split():
            state.push(w)
        state.reset()
        self.assertEqual(state.snapshot.words_seen, 0)
        self.assertEqual(state.push("red").filters["colour"], "red")

    def test_finish_settles_a_trailing_number(self):
        state = FilterState(self.lex)
        for w in "shirt under two thousand".split():
            state.push(w)
        self.assertIsNone(state.snapshot.filters["max_price"])
        self.assertEqual(state.finish().filters["max_price"], 2000)

    def test_the_same_words_give_the_same_snapshot(self):
        a = self.stream("black slides size nine under Rs.1,500 oops white")
        b = self.stream("black slides size nine under Rs.1,500 oops white")
        self.assertEqual(a, b)


class DevReplayTest(unittest.TestCase):
    """Replays dev.jsonl word by word. This is a test only: the agent never reads it."""

    @classmethod
    def setUpClass(cls):
        cls.lex = Lexicon(load_rows())
        with open(DEV_PATH, encoding="utf-8") as fh:
            cls.rows = [json.loads(line) for line in fh if line.strip()]

    def replay(self, row):
        state = FilterState(self.lex)
        snapshots = [state.push(w) for w in row["words"]]
        return snapshots, state.finish()

    def test_plain_and_correction_requests_are_read_right_at_the_last_word(self):
        rows = [r for r in self.rows if not r["tags"] or "correction" in r["tags"]]
        right = 0
        for row in rows:
            _, final = self.replay(row)
            right += all(final.filters[s] == row["filters"][s] for s in SLOTS)
        self.assertGreaterEqual(right / len(rows), 0.95, f"{right}/{len(rows)}")

    def test_every_request_is_read_right(self):
        wrong = []
        for row in self.rows:
            _, final = self.replay(row)
            if any(final.filters[s] != row["filters"][s] for s in SLOTS):
                wrong.append(row["id"])
        self.assertEqual(wrong, [])

    def test_no_false_correction_alarm_without_a_correction(self):
        alarms = []
        for row in self.rows:
            if "correction" in row["tags"]:
                continue
            snapshots, _ = self.replay(row)
            alarms += [(row["id"], i) for i, s in enumerate(snapshots) if s.correction_pending]
        self.assertEqual(alarms, [])

    def test_only_corrected_requests_have_revisions_and_all_are_marked(self):
        bad = []
        for row in self.rows:
            _, final = self.replay(row)
            revised = [b for b in final.slots.values() if b.revisions]
            if "correction" in row["tags"]:
                if not revised or not all(b.marked for b in revised):
                    bad.append(row["id"])
            elif revised:
                bad.append(row["id"])
        self.assertEqual(bad, [])

    def test_every_marker_raises_the_flag_on_the_word_that_carries_it(self):
        missed = []
        for row in self.rows:
            if "correction" not in row["tags"]:
                continue
            snapshots, final = self.replay(row)
            for marker in final.markers:
                if not snapshots[marker.end - 1].correction_pending:
                    # an earlier marker's replacement may already have answered it; the flag
                    # only has to be up when nothing has answered yet, i.e. for the first one
                    if marker is final.markers[0]:
                        missed.append((row["id"], marker.text))
        self.assertEqual(missed, [])


LEX = Lexicon(load_rows())


def filters(text):
    return build_snapshot(tokenize_text(text), LEX, final=True).filters


class CommaInsidePhraseTest(unittest.TestCase):
    def test_commas_inside_phrases_change_nothing(self):
        for plain, commas in (("navy blue t shirt size M", "navy, blue t, shirt size M"),
                              ("black shirt extra large", "black shirt extra, large")):
            self.assertEqual(filters(plain), filters(commas), commas)

    def test_a_comma_between_two_values_still_separates_them(self):
        self.assertEqual(filters("shirt, size M, in black")["colour"], "black")


class CueTypoTest(unittest.TestCase):
    def test_typos_in_size_and_price_cues_are_read(self):
        for plain, typo in (("black shoes size 9", "black shoes sise 9"),
                            ("black shoes size 9", "black shoes saiz 9"),
                            ("black shoes under 2000", "black shoes unedr 2000"),
                            ("black shoes budget 2000", "black shoes budgte 2000")):
            self.assertEqual(filters(plain), filters(typo), typo)

    def test_a_typo_in_a_correction_marker_is_still_a_marker(self):
        words = tokenize_text("black shoes sorey I meant white")
        self.assertGreaterEqual(len(find_markers(words)), 1)
        self.assertEqual(filters("black shoes sorey I meant white")["colour"], "white")

    def test_ordinary_words_are_not_pulled_into_cues(self):
        for word in ("sized", "shirt", "short", "wait", "want", "number"):
            self.assertNotIn(LEX.corrector.correct(word), ("size", "under", "sorry"), word)


if __name__ == "__main__":
    unittest.main()
