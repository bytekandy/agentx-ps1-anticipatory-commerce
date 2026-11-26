"""The typed models must describe exactly what the service sends: a field added to an event but
not to its model would be silently dropped from responses, so this test fails first."""
import unittest

from tests._server_fixture import require_extras

require_extras()

from server import models  # noqa: E402
from server.service import StreamService  # noqa: E402

SERVICE = StreamService()
WORDS = "beige Loomsy sneakers size 10 under 3000 please".split()


def fields(model):
    return set(model.model_fields)


class ModelsMatchTheServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = SERVICE.run(WORDS)
        cls.start, cls.words, cls.final = cls.events[0], cls.events[1:-1], cls.events[-1]
        cls.replayed_final = list(SERVICE.replay(example="dev-0004"))[-1]

    def check(self, model, payload, name):
        self.assertEqual(set(payload), fields(model), name)
        model.model_validate(payload)

    def test_events(self):
        self.check(models.StartEvent, self.start, "start")
        for event in self.words:
            self.check(models.WordEvent, event, "word")
            self.check(models.Trace, event["trace"], "trace")
        self.check(models.FinalEvent, self.final, "final")
        self.check(models.Evaluation, self.replayed_final["evaluation"], "evaluation")
        models.FinalEvent.model_validate(self.replayed_final)

    def test_commit_and_product(self):
        commit = self.words[7]["commit"]
        self.check(models.Commit, commit, "commit")
        self.check(models.Product, commit["product"], "product")
        self.assertEqual(self.words[7]["committed"], commit)

    def test_the_other_responses(self):
        info = SERVICE.info()
        self.assertEqual(set(info) - {"auth_required"}, fields(models.Info) - {"auth_required"})
        self.check(models.Limits, info["limits"], "limits")
        page = SERVICE.examples("dev", limit=2)
        self.check(models.ExamplesPage, page, "examples")
        self.check(models.ExampleItem, page["items"][0], "example item")
        self.check(models.ExampleDetail, SERVICE.example_detail("dev-0004"), "detail")
        results = SERVICE.results("dev_extra")
        self.check(models.Results, results, "results")
        self.check(models.Summary, results["summary"], "summary")
        self.check(models.ResultRow, results["requests"][0], "row")

    def test_the_request_model_rejects_bad_agents(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            models.RunRequest(words=["x"], agent="gpt")
        self.assertEqual(models.RunRequest(words=["x"]).agent, "hybrid")


if __name__ == "__main__":
    unittest.main()
