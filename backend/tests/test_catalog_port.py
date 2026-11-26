import unittest

from anticipatory.catalog_port import InMemoryCatalog, ToolsCatalog, clean_filters

ROWS = [
    {"product_id": "P1", "title": "Pacevo Court Sneakers, Black", "brand": "Pacevo",
     "category": "sneakers", "colour": "black", "size": "9", "price": "2500", "description": ""},
    {"product_id": "P2", "title": "Pacevo Court Sneakers, Black", "brand": "Pacevo",
     "category": "sneakers", "colour": "black", "size": "10", "price": "2500", "description": ""},
    {"product_id": "P3", "title": "Kudova Flex Sneakers, Black", "brand": "Kudova",
     "category": "sneakers", "colour": "black", "size": "9", "price": "1800", "description": ""},
]


class InMemoryCatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = InMemoryCatalog(ROWS)

    def ids(self, filters, query="", k=10):
        return [p["product_id"] for p in self.catalog.find(filters, query, k)]

    def test_exact_filters_are_case_insensitive(self):
        self.assertEqual(self.ids({"brand": "pacevo", "size": "9"}), ["P1"])

    def test_price_bounds(self):
        self.assertEqual(self.ids({"max_price": 2000}), ["P3"])
        self.assertEqual(self.ids({"min_price": 2000}), ["P1", "P2"])

    def test_cheaper_first_on_a_tie_and_query_overlap_first(self):
        self.assertEqual(self.ids({"size": "9"}), ["P3", "P1"])
        self.assertEqual(self.ids({"size": "9"}, "pacevo"), ["P1", "P3"])

    def test_k_limits_the_results_and_every_call_is_counted(self):
        self.assertEqual(len(self.ids({}, k=2)), 2)
        self.assertEqual(self.catalog.searches, 1)
        self.ids({})
        self.assertEqual(self.catalog.searches, 2)

    def test_none_filters_are_ignored(self):
        self.assertEqual(len(self.ids({"brand": None, "size": None})), 3)


class ToolsCatalogTest(unittest.TestCase):
    def test_forwards_to_the_counted_tools_search(self):
        calls = []

        class FakeTools:
            def search(self, query="", filters=None, k=10):
                calls.append((query, filters, k))
                return [{"product_id": "P9"}]

        hits = ToolsCatalog(FakeTools()).find({"colour": "black", "size": None}, "black", 5)
        self.assertEqual(hits, [{"product_id": "P9"}])
        self.assertEqual(calls, [("black", {"colour": "black"}, 5)])

    def test_clean_filters(self):
        self.assertEqual(clean_filters({"a": 1, "b": None}), {"a": 1})
        self.assertEqual(clean_filters(None), {})


if __name__ == "__main__":
    unittest.main()
