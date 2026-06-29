import unittest
from unittest.mock import Mock, patch

import app


class AppHelperTests(unittest.TestCase):
    def test_inverted_index_to_text_orders_words_by_position(self):
        abstract = {"world": [1], "hello": [0], "again": [2]}

        self.assertEqual(app.inverted_index_to_text(abstract), "hello world again")

    def test_parse_openalex_work_keeps_legal_access_links(self):
        work = {
            "display_name": "Accessible Autism Research",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1234/example",
            "cited_by_count": 42,
            "abstract_inverted_index": {"Autism": [0], "research": [1]},
            "authorships": [
                {"author": {"display_name": "Ada Author"}},
                {"author": {"display_name": "Ben Writer"}},
            ],
            "primary_location": {
                "landing_page_url": "https://publisher.example/article",
                "source": {"display_name": "Journal of Examples"},
            },
            "open_access": {"oa_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/"},
        }

        result = app.parse_openalex_work(work, "autism")

        self.assertEqual(result["title"], "Accessible Autism Research")
        self.assertEqual(result["authors"], "Ada Author, Ben Writer")
        self.assertEqual(result["year"], 2024)
        self.assertEqual(result["venue"], "Journal of Examples")
        self.assertEqual(result["citation_count"], 42)
        self.assertEqual(result["abstract"], "Autism research")
        self.assertEqual(result["doi"], "10.1234/example")
        self.assertEqual(result["publisher_url"], "https://publisher.example/article")
        self.assertEqual(result["openalex_oa_url"], "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/")
        self.assertEqual(result["access_status"], "Open access found")
        self.assertEqual(result["best_access_url"], "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/")
        self.assertEqual(result["matched_keyword"], "autism")

    def test_add_access_fields_prefers_unpaywall_then_openalex_then_publisher_then_doi(self):
        rows = [
            {
                "title": "Unpaywall",
                "doi": "10.1/unpaywall",
                "publisher_url": "https://publisher.example/unpaywall",
                "openalex_oa_url": "https://openalex.example/unpaywall",
                "unpaywall_oa_url": "https://unpaywall.example/unpaywall",
            },
            {
                "title": "OpenAlex",
                "doi": "10.1/openalex",
                "publisher_url": "https://publisher.example/openalex",
                "openalex_oa_url": "https://openalex.example/openalex",
                "unpaywall_oa_url": "",
            },
            {
                "title": "Publisher",
                "doi": "10.1/publisher",
                "publisher_url": "https://publisher.example/publisher",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
            },
            {
                "title": "DOI",
                "doi": "10.1/doi",
                "publisher_url": "",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
            },
            {
                "title": "None",
                "doi": "",
                "publisher_url": "",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
            },
        ]

        enriched = [app.add_access_fields(row.copy()) for row in rows]

        self.assertEqual(enriched[0]["access_status"], "Open access found")
        self.assertEqual(enriched[0]["best_access_url"], "https://unpaywall.example/unpaywall")
        self.assertEqual(enriched[1]["access_status"], "Open access found")
        self.assertEqual(enriched[1]["best_access_url"], "https://openalex.example/openalex")
        self.assertEqual(enriched[2]["access_status"], "DOI/publisher only")
        self.assertEqual(enriched[2]["best_access_url"], "https://publisher.example/publisher")
        self.assertEqual(enriched[3]["access_status"], "DOI/publisher only")
        self.assertEqual(enriched[3]["best_access_url"], "https://doi.org/10.1/doi")
        self.assertEqual(enriched[4]["access_status"], "No access link found")
        self.assertEqual(enriched[4]["best_access_url"], "")

    def test_filter_results_applies_year_and_abstract_requirements(self):
        rows = [
            {"title": "Old", "year": 2015, "abstract": "has abstract", "citation_count": 1},
            {"title": "No Abstract", "year": 2022, "abstract": "", "citation_count": 2},
            {"title": "Current", "year": 2023, "abstract": "has abstract", "citation_count": 3},
        ]

        filtered = app.filter_results(rows, minimum_year=2020, maximum_year=2024, require_abstract=True)

        self.assertEqual([row["title"] for row in filtered], ["Current"])

    def test_sort_results_supports_citation_count_and_year(self):
        rows = [
            {"title": "A", "year": 2020, "citation_count": 5, "relevance_score": 1},
            {"title": "B", "year": 2023, "citation_count": 2, "relevance_score": 2},
            {"title": "C", "year": 2021, "citation_count": 9, "relevance_score": 3},
        ]

        by_citations = app.sort_results(rows, "citation count")
        by_year = app.sort_results(rows, "year")

        self.assertEqual([row["title"] for row in by_citations], ["C", "A", "B"])
        self.assertEqual([row["title"] for row in by_year], ["B", "C", "A"])

    def test_results_to_markdown_includes_access_links(self):
        rows = [
            {
                "title": "A Paper",
                "authors": "A. Author",
                "year": 2024,
                "venue": "Example Journal",
                "citation_count": 7,
                "abstract": "Short abstract.",
                "doi": "10.1234/example",
                "publisher_url": "https://publisher.example/article",
                "openalex_oa_url": "https://open.example/full-text",
                "unpaywall_oa_url": "https://oa.example/full-text",
                "matched_keyword": "autism",
            }
        ]

        markdown = app.results_to_markdown(rows)

        self.assertIn("# Literature Finder Results", markdown)
        self.assertIn("https://doi.org/10.1234/example", markdown)
        self.assertIn("https://publisher.example/article", markdown)
        self.assertIn("https://open.example/full-text", markdown)
        self.assertIn("https://oa.example/full-text", markdown)
        self.assertIn("Open access found", markdown)

    def test_display_columns_put_most_useful_fields_first(self):
        self.assertEqual(
            app.display_columns()[:10],
            [
                "title",
                "year",
                "venue",
                "citation_count",
                "access_status",
                "best_access_url",
                "doi",
                "authors",
                "abstract",
                "matched_keyword",
            ],
        )

    def test_ui_guidance_copy_is_available(self):
        self.assertEqual(
            app.SUBTITLE,
            "Find papers, legal access links, and export-ready literature tables.",
        )
        self.assertIn("one search query per line", app.KEYWORD_HELPER_NOTE)
        self.assertIn("connect multiple concepts", app.KEYWORD_HELPER_NOTE)
        self.assertIn("perceived control AND depression AND stress", app.KEYWORD_HELPER_NOTE)
        self.assertIn("perceived control AND depression AND stress", app.EXAMPLE_SEARCHES)
        self.assertIn("autism disclosure employment", app.EXAMPLE_SEARCHES)
        self.assertIn("autistic college students STEM", app.EXAMPLE_SEARCHES)
        self.assertIn("adolescent depression intervention", app.EXAMPLE_SEARCHES)
        self.assertIn("try broader keywords", app.NO_RESULTS_GUIDANCE)
        self.assertIn("remove year filters", app.NO_RESULTS_GUIDANCE)
        self.assertIn("uncheck Require abstract", app.NO_RESULTS_GUIDANCE)
        self.assertIn("search one concept at a time", app.NO_RESULTS_GUIDANCE)
        self.assertIn("best legal access link", app.BEST_ACCESS_URL_EXPLANATION)
        self.assertIn("Open access found", app.ACCESS_STATUS_EXPLANATION)
        self.assertIn("DOI/publisher only", app.ACCESS_STATUS_EXPLANATION)
        self.assertIn("No access link found", app.ACCESS_STATUS_EXPLANATION)
        self.assertIn("light exploratory use", app.PUBLIC_DEMO_NOTE)
        self.assertIn("cleaned literature search table", app.SOFT_CTA)
        self.assertIn("does not scrape Google Scholar", app.LEGAL_ETHICAL_DISCLAIMER)

    def test_public_demo_limits_are_capped(self):
        self.assertEqual(app.DEMO_SEARCH_LIMIT, 5)
        self.assertEqual(app.MAX_KEYWORD_LINES, 5)
        self.assertEqual(app.MAX_RESULTS_PER_KEYWORD, 30)
        self.assertTrue(app.can_run_demo_search(0))
        self.assertTrue(app.can_run_demo_search(4))
        self.assertFalse(app.can_run_demo_search(5))

    def test_parse_keyword_lines_enforces_demo_line_limit(self):
        keywords = app.parse_keyword_lines("a\n\nb\n c ")
        self.assertEqual(keywords, ["a", "b", "c"])
        self.assertTrue(app.is_within_keyword_line_limit(keywords))
        self.assertFalse(app.is_within_keyword_line_limit(["a", "b", "c", "d", "e", "f"]))

    def test_search_literature_does_not_emit_per_paper_status_updates(self):
        status_area = Mock()
        rows = [
            {
                "title": "A",
                "doi": "10.1/a",
                "year": 2024,
                "abstract": "abstract",
                "citation_count": 1,
                "relevance_score": 1,
                "publisher_url": "",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
            },
            {
                "title": "B",
                "doi": "10.1/b",
                "year": 2023,
                "abstract": "abstract",
                "citation_count": 2,
                "relevance_score": 2,
                "publisher_url": "",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
            },
        ]

        with patch.object(app, "search_openalex", return_value=rows), patch.object(
            app, "lookup_unpaywall_oa_url", return_value=""
        ), patch.object(app.time, "sleep"):
            app.search_literature(["autism"], 10, None, None, False, "relevance", status_area)

        status_area.info.assert_not_called()

    def test_get_openalex_api_key_prefers_streamlit_secrets(self):
        with patch.dict("os.environ", {"OPENALEX_API_KEY": "env-key"}):
            self.assertEqual(app.get_openalex_api_key({"OPENALEX_API_KEY": "secret-key"}), "secret-key")

    def test_get_openalex_api_key_falls_back_to_environment(self):
        with patch.dict("os.environ", {"OPENALEX_API_KEY": "env-key"}):
            self.assertEqual(app.get_openalex_api_key({}), "env-key")

    def test_search_openalex_adds_api_key_query_param_when_available(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"results": []}

        with patch.object(app, "get_openalex_api_key", return_value="test-key"), patch.object(
            app.requests, "get", return_value=response
        ) as get:
            app.search_openalex("autism", 10, None, None, "relevance")

        params = get.call_args.kwargs["params"]
        self.assertEqual(params["api_key"], "test-key")

    def test_search_openalex_raises_detailed_error_for_non_200_response(self):
        response = Mock()
        response.status_code = 403
        response.text = "daily usage limit exceeded for this key"

        with patch.object(app.requests, "get", return_value=response):
            with self.assertRaises(app.OpenAlexRequestError) as context:
                app.search_openalex("autism", 10, None, None, "relevance")

        message = str(context.exception)
        self.assertIn("status 403", message)
        self.assertIn("autism", message)
        self.assertIn("daily usage limit exceeded", message)


if __name__ == "__main__":
    unittest.main()
