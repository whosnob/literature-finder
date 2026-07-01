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
                "authors",
                "abstract",
                "citation_count",
                "doi",
                "access_status",
                "best_access_url",
                "matched_keyword",
            ],
        )

    def test_export_columns_include_screening_fields(self):
        columns = app.export_columns()

        for column in [
            "screening_decision",
            "reason_for_exclusion",
            "notes",
            "theme",
            "priority",
        ]:
            self.assertIn(column, columns)

    def test_results_to_csv_includes_blank_screening_columns(self):
        csv_data = app.results_to_csv([{"title": "A Paper"}])

        self.assertIn("screening_decision", csv_data.splitlines()[0])
        self.assertIn("reason_for_exclusion", csv_data.splitlines()[0])
        self.assertIn("A Paper", csv_data)

    def test_results_to_markdown_includes_screening_fields(self):
        markdown = app.results_to_markdown([{"title": "A Paper"}])

        self.assertIn("- **Screening decision:**", markdown)
        self.assertIn("- **Reason for exclusion:**", markdown)
        self.assertIn("- **Notes:**", markdown)
        self.assertIn("- **Theme:**", markdown)
        self.assertIn("- **Priority:**", markdown)

    def test_search_mode_configs_set_defaults_and_caps(self):
        quick = app.search_mode_config(app.QUICK_SEARCH_MODE, trusted=False)
        research_public = app.search_mode_config(app.RESEARCH_SEARCH_MODE, trusted=False)
        research_trusted = app.search_mode_config(app.RESEARCH_SEARCH_MODE, trusted=True)

        self.assertEqual(quick.default_results, 5)
        self.assertEqual(quick.max_results_cap, 10)
        self.assertFalse(quick.default_require_abstract)
        self.assertEqual(research_public.max_results_cap, 10)
        self.assertEqual(research_trusted.default_results, 10)
        self.assertEqual(research_trusted.max_results_cap, 50)
        self.assertTrue(research_trusted.allow_require_abstract)
        self.assertTrue(research_trusted.allow_year_filters)

    def test_trusted_research_code_prefers_secrets_then_environment(self):
        with patch.dict("os.environ", {"TRUSTED_RESEARCH_CODE": "env-code"}):
            self.assertEqual(app.get_trusted_research_code({"TRUSTED_RESEARCH_CODE": "secret-code"}), "secret-code")
            self.assertEqual(app.get_trusted_research_code({}), "env-code")

    def test_trusted_research_mode_requires_configured_matching_code(self):
        self.assertTrue(app.is_trusted_research_enabled("  secret-code ", {"TRUSTED_RESEARCH_CODE": "secret-code"}))
        self.assertFalse(app.is_trusted_research_enabled("wrong", {"TRUSTED_RESEARCH_CODE": "secret-code"}))
        self.assertFalse(app.is_trusted_research_enabled("anything", {}))
        self.assertFalse(app.is_trusted_research_enabled("", {"TRUSTED_RESEARCH_CODE": "secret-code"}))

    def test_ui_guidance_copy_is_available(self):
        self.assertEqual(
            app.SUBTITLE,
            "Find papers, legal access links, and export-ready literature tables.",
        )
        self.assertIn("one search query per line", app.KEYWORD_HELPER_NOTE)
        self.assertIn("connect multiple concepts", app.KEYWORD_HELPER_NOTE)
        self.assertIn("perceived control AND depression AND stress", app.KEYWORD_HELPER_NOTE)
        self.assertIn("Very broad terms such as 'Participatory Study'", app.KEYWORD_HELPER_NOTE)
        self.assertIn("For best stability, start with 10 results per keyword", app.RESEARCH_STABILITY_HELPER_TEXT)
        self.assertIn("perceived control AND depression AND stress", app.EXAMPLE_SEARCHES)
        self.assertIn("autism disclosure employment", app.EXAMPLE_SEARCHES)
        self.assertIn("autistic college students STEM", app.EXAMPLE_SEARCHES)
        self.assertIn("adolescent depression intervention", app.EXAMPLE_SEARCHES)
        self.assertIn("try broader keywords", app.NO_RESULTS_GUIDANCE)
        self.assertIn("remove year filters", app.NO_RESULTS_GUIDANCE)
        self.assertIn("uncheck Require abstract", app.NO_RESULTS_GUIDANCE)
        self.assertIn("search one concept at a time", app.NO_RESULTS_GUIDANCE)
        self.assertIn("Research workflow tip", app.RESEARCH_WORKFLOW_TIP)
        self.assertIn("best legal access link", app.BEST_ACCESS_URL_EXPLANATION)
        self.assertIn("Open access found", app.ACCESS_STATUS_EXPLANATION)
        self.assertIn("DOI/publisher only", app.ACCESS_STATUS_EXPLANATION)
        self.assertIn("No access link found", app.ACCESS_STATUS_EXPLANATION)
        self.assertIn("light exploratory use", app.PUBLIC_DEMO_NOTE)
        self.assertIn("cleaned literature search table", app.SOFT_CTA)
        self.assertIn("does not scrape Google Scholar", app.LEGAL_ETHICAL_DISCLAIMER)

    def test_public_demo_limits_are_capped(self):
        self.assertEqual(app.DEMO_SEARCH_LIMIT, 5)
        self.assertEqual(app.PUBLIC_MAX_KEYWORD_LINES, 5)
        self.assertEqual(app.TRUSTED_MAX_KEYWORD_LINES, 10)
        self.assertEqual(app.QUICK_MAX_RESULTS_PER_KEYWORD, 10)
        self.assertEqual(app.RESEARCH_MAX_RESULTS_PER_KEYWORD, 50)
        self.assertTrue(app.can_run_demo_search(0))
        self.assertTrue(app.can_run_demo_search(4))
        self.assertFalse(app.can_run_demo_search(5))

    def test_parse_keyword_lines_enforces_demo_line_limit(self):
        keywords = app.parse_keyword_lines("a\n\nb\n c ")
        self.assertEqual(keywords, ["a", "b", "c"])
        self.assertTrue(app.is_within_keyword_line_limit(keywords, trusted=False))
        self.assertFalse(app.is_within_keyword_line_limit(["a", "b", "c", "d", "e", "f"], trusted=False))
        self.assertTrue(app.is_within_keyword_line_limit(["a", "b", "c", "d", "e", "f"], trusted=True))

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

    def test_search_literature_suppresses_unpaywall_lookup_errors_and_falls_back_to_doi(self):
        status_area = Mock()
        rows = [
            {
                "title": "Fallback",
                "doi": "10.1/fallback",
                "year": 2024,
                "abstract": "abstract",
                "citation_count": 1,
                "relevance_score": 1,
                "publisher_url": "",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
            }
        ]

        with patch.object(app, "search_openalex", return_value=rows), patch.object(
            app, "lookup_unpaywall_oa_url", side_effect=app.requests.HTTPError("422 Client Error for url")
        ), patch.object(app.time, "sleep"):
            result = app.search_literature(["autism"], 10, None, None, False, "relevance", status_area)

        self.assertEqual(result[0]["unpaywall_oa_url"], "")
        self.assertEqual(result[0]["access_status"], "DOI/publisher only")
        self.assertEqual(result[0]["best_access_url"], "https://doi.org/10.1/fallback")
        status_area.warning.assert_not_called()
        status_area.error.assert_not_called()

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

    def test_search_openalex_retries_once_for_504_timeout(self):
        timeout_response = Mock()
        timeout_response.status_code = 504
        timeout_response.text = '{"reason":"query_timeout"}'
        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {"results": []}

        with patch.object(app.requests, "get", side_effect=[timeout_response, success_response]) as get, patch.object(
            app.time, "sleep"
        ) as sleep:
            rows = app.search_openalex("autistic college students STEM", 10, None, None, "relevance")

        self.assertEqual(rows, [])
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once()

    def test_search_openalex_raises_friendly_timeout_error_after_retry(self):
        timeout_response = Mock()
        timeout_response.status_code = 400
        timeout_response.text = '{"reason":"query_timeout"}'

        with patch.object(app.requests, "get", return_value=timeout_response) as get, patch.object(app.time, "sleep"):
            with self.assertRaises(app.OpenAlexRequestError) as context:
                app.search_openalex("Inclusive Data Analysis", 10, None, None, "relevance")

        self.assertEqual(get.call_count, 2)
        self.assertTrue(context.exception.is_timeout)
        self.assertEqual(str(context.exception), app.OPENALEX_TIMEOUT_MESSAGE)
        self.assertNotIn("Gateway timeout", str(context.exception))
        self.assertNotIn("query_timeout", str(context.exception))

    def test_search_literature_continues_after_keyword_non_timeout_openalex_error(self):
        status_area = Mock()
        rows = [
            {
                "title": "Recovered",
                "doi": "",
                "year": 2024,
                "abstract": "abstract",
                "citation_count": 1,
                "relevance_score": 1,
                "publisher_url": "",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
                "matched_keyword": "second keyword",
            }
        ]

        with patch.object(
            app,
            "search_openalex",
            side_effect=[
                app.OpenAlexRequestError("first keyword", 403, "daily usage limit exceeded"),
                rows,
            ],
        ), patch.object(app.time, "sleep"):
            result = app.search_literature(
                ["first keyword", "second keyword"], 10, None, None, False, "relevance", status_area
            )

        self.assertEqual([row["title"] for row in result], ["Recovered"])
        status_area.warning.assert_called_once()
        warning = status_area.warning.call_args.args[0]
        self.assertIn("first keyword", warning)
        self.assertIn("status 403", warning)
        self.assertNotIn("query_timeout", warning)

    def test_search_literature_uses_lighter_fallback_after_timeout(self):
        status_area = Mock()
        fallback_rows = [
            {
                "title": "Fallback",
                "doi": "",
                "year": 2024,
                "abstract": "",
                "citation_count": 1,
                "relevance_score": 1,
                "publisher_url": "",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
                "matched_keyword": "broad keyword",
            }
        ]

        with patch.object(
            app,
            "search_openalex",
            side_effect=[
                app.OpenAlexRequestError("broad keyword", 504, '{"reason":"query_timeout"}'),
                fallback_rows,
            ],
        ) as search, patch.object(app.time, "sleep"):
            outcome = app.search_literature_with_status(
                ["broad keyword"], 40, 2020, 2024, True, "relevance", status_area
            )

        self.assertEqual([row["title"] for row in outcome.rows], ["Fallback"])
        self.assertTrue(outcome.used_timeout_fallback)
        self.assertFalse(outcome.all_keywords_timed_out)
        self.assertEqual(search.call_args_list[1].args, ("broad keyword", 10, 2020, 2024, "relevance"))
        info = status_area.info.call_args.args[0]
        self.assertIn("lighter fallback search was used", info)

    def test_research_mode_starts_with_lightweight_discovery_before_expansion(self):
        status_area = Mock()
        discovery_rows = [
            {
                "title": "Discovery",
                "doi": "",
                "year": 2024,
                "abstract": "",
                "citation_count": 1,
                "relevance_score": 1,
                "publisher_url": "",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
                "matched_keyword": "Participatory Study",
            }
        ]
        expanded_rows = discovery_rows + [
            {
                "title": "Expansion",
                "doi": "",
                "year": 2023,
                "abstract": "abstract",
                "citation_count": 2,
                "relevance_score": 2,
                "publisher_url": "",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
                "matched_keyword": "Participatory Study",
            }
        ]

        with patch.object(app, "search_openalex", side_effect=[discovery_rows, expanded_rows]) as search, patch.object(
            app.time, "sleep"
        ):
            outcome = app.search_literature_with_status(
                ["Participatory Study"], 10, 2020, 2024, True, "year", status_area, mode=app.RESEARCH_SEARCH_MODE
            )

        self.assertEqual([row["title"] for row in outcome.rows], ["Discovery", "Expansion"])
        self.assertEqual(search.call_args_list[0].args, ("Participatory Study", 5, None, None, "relevance"))
        self.assertEqual(search.call_args_list[1].args, ("Participatory Study", 10, 2020, 2024, "year"))

    def test_research_mode_keeps_discovery_results_after_expansion_timeout(self):
        status_area = Mock()
        discovery_rows = [
            {
                "title": "Discovery",
                "doi": "",
                "year": 2024,
                "abstract": "",
                "citation_count": 1,
                "relevance_score": 1,
                "publisher_url": "",
                "openalex_oa_url": "",
                "unpaywall_oa_url": "",
                "matched_keyword": "autism disclosure employment",
            }
        ]

        with patch.object(
            app,
            "search_openalex",
            side_effect=[
                discovery_rows,
                app.OpenAlexRequestError("autism disclosure employment", 504, '{"reason":"query_timeout"}'),
            ],
        ), patch.object(app.time, "sleep"):
            outcome = app.search_literature_with_status(
                ["autism disclosure employment"], 20, None, None, True, "relevance", status_area, mode=app.RESEARCH_SEARCH_MODE
            )

        self.assertEqual([row["title"] for row in outcome.rows], ["Discovery"])
        self.assertTrue(outcome.had_timeout)
        self.assertFalse(outcome.all_keywords_timed_out)
        status_area.warning.assert_not_called()
        note = status_area.info.call_args.args[0]
        self.assertEqual(
            note,
            "Partial results shown for 'autism disclosure employment' because OpenAlex timed out while expanding the search.",
        )
        self.assertNotIn("query_timeout", note)
        self.assertNotIn("{", note)

    def test_research_mode_full_timeout_warning_only_when_zero_keyword_results(self):
        status_area = Mock()

        with patch.object(
            app,
            "search_openalex",
            side_effect=app.OpenAlexRequestError("Inclusive Data Analysis Qualitative Coding", 504, '{"reason":"query_timeout"}'),
        ), patch.object(app.time, "sleep"):
            outcome = app.search_literature_with_status(
                ["Inclusive Data Analysis Qualitative Coding"], 20, None, None, False, "relevance", status_area, mode=app.RESEARCH_SEARCH_MODE
            )

        self.assertEqual(outcome.rows, [])
        self.assertTrue(outcome.all_keywords_timed_out)
        warning = status_area.warning.call_args.args[0]
        self.assertIn("OpenAlex timed out for 'Inclusive Data Analysis Qualitative Coding'", warning)
        self.assertNotIn("query_timeout", warning)
        self.assertNotIn("{", warning)

    def test_search_literature_reports_all_timeout_without_raw_json(self):
        status_area = Mock()

        with patch.object(
            app,
            "search_openalex",
            side_effect=app.OpenAlexRequestError("broad keyword", 400, '{"reason":"query_timeout"}'),
        ), patch.object(app.time, "sleep"):
            outcome = app.search_literature_with_status(
                ["broad keyword"], 40, None, None, True, "relevance", status_area
            )

        self.assertEqual(outcome.rows, [])
        self.assertTrue(outcome.all_keywords_timed_out)
        self.assertTrue(outcome.had_timeout)
        warning = status_area.warning.call_args.args[0]
        self.assertIn("OpenAlex timed out for 'broad keyword'", warning)
        self.assertNotIn("query_timeout", warning)
        self.assertNotIn("{", warning)

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
