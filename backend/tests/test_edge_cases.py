"""Hostile, odd and oversized input, and misuse of the agent protocol (Stage 9).

The agent receives whatever a person types. None of this may raise, hang, or end in an early
commit to a product the words do not ask for.
"""
import time
import unittest

from anticipatory.agent import AnticipatoryAgent
from anticipatory.catalog_port import InMemoryCatalog
from anticipatory.config import Config, StateConfig
from anticipatory.lexicon import Lexicon, load_rows
from anticipatory.risk import HybridRisk, LearnedRisk

LOOMSY_BEIGE_10 = "P0081"       # beige Loomsy sneakers, size 10, 2899

NASTY = {
    "devanagari": "मुझे काली जींस चाहिए size 32 under 2000",
    "emoji": "black 👟 sneakers 🔥 size 9 😊 under 2000",
    "mixed scripts": "black シューズ sneakers size 9",
    "control characters": "black\x00 sneakers\x07 size\t9 \x1b[31mred",
    "zero width and rtl marks": "bl​ack sneakers ‏size 9",
    "a 20000 letter word": "a" * 20000 + " black sneakers size 9",
    "a 400 digit number": "black sneakers size 9 under " + "9" * 400,
    "negative, scientific, fractions": "black sneakers size -9 under -500 1e5 1/2 0.0.0 NaN inf",
    "leading zeros": "black sneakers size 009 under 002000",
    "devanagari digits": "black sneakers size ९ under २०००",
    "punctuation only": ". , ; ! ? ... --- ___ ///",
    "only numbers": "1 2 3 4 5 6 7 8 9 10 11 12",
    "k in odd places": "k kk 1kk 2.5.5k k1 1k2",
    "sql-looking": "black'; DROP TABLE products; -- sneakers",
    "combining accents": "café black sneakers",
    "embedded newlines": "black\nsneakers\nsize\n9",
}


class EdgeCaseTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()
        cls.lex = Lexicon(cls.rows)
        cls.ids = {r["product_id"] for r in cls.rows}

    def make_agent(self, config=None):
        config = config or Config()
        return AnticipatoryAgent(InMemoryCatalog(self.rows), config, lexicon=self.lex,
                                 risk_model=HybridRisk(LearnedRisk.from_file(config=config), config))

    def run_words(self, agent, words, request_id="t"):
        agent.start(request_id)
        commits = []
        for i, word in enumerate(words, start=1):
            out = agent.observe(word)
            self.assertTrue(out is None or isinstance(out, dict))
            if out and out.get("commit"):
                commits.append((i, out["commit"]))
        return commits, agent.finish()


class HostileInputTest(EdgeCaseTestCase):
    def test_nothing_raises_and_answers_are_real_products(self):
        agent = self.make_agent()
        for name, text in NASTY.items():
            with self.subTest(case=name):
                commits, final = self.run_words(agent, text.split())
                self.assertTrue(final is None or final in self.ids, final)
                self.assertTrue(all(pid in self.ids for _, pid in commits))

    def test_empty_and_blank_words(self):
        agent = self.make_agent()
        for words in ([], [""], [" "], ["", "", ""], ["\t", "\n"]):
            with self.subTest(words=words):
                commits, final = self.run_words(agent, words)
                self.assertEqual(commits, [])
                self.assertTrue(final is None or final in self.ids)

    def test_letters_the_reader_does_not_know_do_not_confuse_a_clear_request(self):
        agent = self.make_agent()
        _, final = self.run_words(agent, "beige 👟 Loomsy ✨ sneakers size 10 ​ under 3000".split())
        self.assertEqual(final, LOOMSY_BEIGE_10)

    def test_a_noise_word_between_the_words_never_causes_a_wrong_commit(self):
        agent = self.make_agent()
        for noise in ("🔥", "\x00", "???", "9" * 50, "ÄÖÜ", "-"):
            with self.subTest(noise=noise):
                commits, final = self.run_words(
                    agent, f"beige Loomsy sneakers {noise} size 10 {noise} under 3000 please".split())
                self.assertEqual([c for c in commits if c[1] != LOOMSY_BEIGE_10], [])
                self.assertEqual(final, LOOMSY_BEIGE_10)


class LongRequestTest(EdgeCaseTestCase):
    def test_a_very_long_request_is_fast(self):
        agent = self.make_agent()
        words = ("please show me whatever you have in stock today " * 600).split()
        started = time.perf_counter()
        self.run_words(agent, words)
        self.assertLess(time.perf_counter() - started, 3.0)

    def test_a_pin_after_the_live_window_gives_no_early_commit_but_a_right_answer(self):
        agent = self.make_agent()
        words = ("please show me " * 100 + "beige Loomsy sneakers size 10 under 3000").split()
        commits, final = self.run_words(agent, words)
        self.assertGreater(len(words), Config().state.max_live_words)
        self.assertEqual(commits, [])
        self.assertEqual(final, LOOMSY_BEIGE_10)

    def test_a_pin_inside_the_live_window_still_commits_early(self):
        agent = self.make_agent()
        words = ("beige Loomsy sneakers size 10 under 3000 please " + "do hurry " * 300).split()
        commits, final = self.run_words(agent, words)
        self.assertEqual([c[1] for c in commits], [LOOMSY_BEIGE_10])
        self.assertLess(commits[0][0], 12)
        self.assertEqual(final, LOOMSY_BEIGE_10)

    def test_the_window_is_a_setting(self):
        config = Config(state=StateConfig(max_live_words=5))
        agent = self.make_agent(config)
        commits, final = self.run_words(agent, "please show me whatever beige Loomsy sneakers "
                                               "size 10 under 3000 thanks".split())
        self.assertEqual(commits, [])
        self.assertEqual(final, LOOMSY_BEIGE_10)


class ProtocolTest(EdgeCaseTestCase):
    WORDS = "navy Urbanyx hoodie size XS no wait S sorry M".split()

    def test_finish_twice_gives_the_same_answer(self):
        agent = self.make_agent()
        _, first = self.run_words(agent, self.WORDS)
        self.assertEqual(agent.finish(), first)

    def test_words_after_finish_do_not_raise(self):
        agent = self.make_agent()
        self.run_words(agent, self.WORDS)
        agent.observe("extra")
        self.assertTrue(agent.finish() is None or agent.finish() in self.ids)

    def test_start_twice_forgets_the_first_request(self):
        agent = self.make_agent()
        agent.start("a")
        for word in "black watch under 5000".split():
            agent.observe(word)
        self.assertEqual(self.run_words(agent, self.WORDS), self.run_words(self.make_agent(), self.WORDS))

    def test_requests_back_to_back_do_not_leak_into_each_other(self):
        agent = self.make_agent()
        alone = self.run_words(self.make_agent(), self.WORDS)
        for _ in range(3):
            self.run_words(agent, "beige Loomsy sneakers size 10 under 3000".split())
            self.assertEqual(self.run_words(agent, self.WORDS), alone)

    def test_observing_before_start_works(self):
        agent = self.make_agent()
        out = agent.observe("black")
        self.assertEqual(out["filters"]["colour"], "black")

    def test_the_same_words_give_the_same_trace(self):
        a, b = self.make_agent(), self.make_agent()
        self.run_words(a, self.WORDS)
        self.run_words(b, self.WORDS)
        self.assertEqual(a.trace, b.trace)


if __name__ == "__main__":
    unittest.main()
