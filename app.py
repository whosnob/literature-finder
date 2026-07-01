import csv
import io
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import requests


logger = logging.getLogger(__name__)

OPENALEX_URL = "https://api.openalex.org/works"
UNPAYWALL_URL_TEMPLATE = "https://api.unpaywall.org/v2/{doi}"
DEFAULT_PAUSE_SECONDS = 0.2
OPENALEX_ERROR_SNIPPET_LENGTH = 500
OPENALEX_TIMEOUT_MESSAGE = (
    "OpenAlex timed out on this search. This can happen when a query is broad or the API is "
    "temporarily slow. Try a more specific phrase, fewer concepts at once, or add a year filter."
)
OPENALEX_RETRY_DELAY_SECONDS = 0.5
OPENALEX_USER_ERROR_DETAIL_LENGTH = 180
DEMO_SEARCH_LIMIT = 5
PUBLIC_MAX_KEYWORD_LINES = 5
TRUSTED_MAX_KEYWORD_LINES = 10
QUICK_SEARCH_MODE = "Quick search"
RESEARCH_SEARCH_MODE = "Research mode"
QUICK_DEFAULT_RESULTS_PER_KEYWORD = 5
QUICK_MAX_RESULTS_PER_KEYWORD = 10
RESEARCH_DEFAULT_RESULTS_PER_KEYWORD = 10
RESEARCH_MAX_RESULTS_PER_KEYWORD = 50
FALLBACK_MAX_RESULTS_PER_KEYWORD = 10
RESEARCH_DISCOVERY_RESULTS_PER_KEYWORD = 5
RESEARCH_EXPANSION_BATCH_SIZE = 5
MAX_KEYWORD_LINES = PUBLIC_MAX_KEYWORD_LINES
MAX_RESULTS_PER_KEYWORD = RESEARCH_MAX_RESULTS_PER_KEYWORD
SUBTITLE = "Find papers, legal access links, and export-ready literature tables."
EXAMPLE_SEARCHES = [
    "perceived control AND depression AND stress",
    "autism disclosure employment",
    "autistic college students STEM",
    "adolescent depression intervention",
]
KEYWORD_HELPER_NOTE = "\n".join(
    [
        "Enter one search query per line. Each line is searched separately.",
        "",
        "Tip: If you want papers that connect multiple concepts, put them in the same line with AND.",
        "Example: perceived control AND depression AND stress",
        "",
        "Very broad terms such as 'Participatory Study' may time out or return mixed results. "
        "Add context such as autism, employment, education, qualitative methods, or STEM.",
        "",
        "For broader searches, use separate lines:",
        "perceived control",
        "depression",
        "stress",
    ]
)
NO_RESULTS_GUIDANCE = "\n".join(
    [
        "No results matched the current keywords and filters.",
        "",
        "Suggestions:",
        "- try broader keywords",
        "- remove year filters",
        "- uncheck Require abstract",
        "- search one concept at a time",
    ]
)
BEST_ACCESS_URL_EXPLANATION = (
    "best_access_url is the best legal access link found by the tool. It may be an open-access "
    "full text, repository copy, publisher page, or DOI page."
)
ACCESS_STATUS_EXPLANATION = "\n".join(
    [
        "- Open access found: a legal access link was found",
        "- DOI/publisher only: no OA full-text link was found, but DOI or publisher page is available",
        "- No access link found: no reliable access link was found",
    ]
)
PUBLIC_DEMO_NOTE = (
    "This public demo is intended for light exploratory use. For larger searches, run the "
    "open-source version locally with your own OpenAlex API key."
)
DEMO_LIMIT_MESSAGE = (
    "You have reached the demo search limit for this session. For larger searches, please run the "
    "open-source version locally with your own OpenAlex API key or contact me for a cleaned "
    "literature search package."
)
SOFT_CTA = "\n".join(
    [
        "Need a cleaned literature search table?",
        "",
        "For beta literature search packages, contact me through the platform where you found this tool.",
    ]
)
LEGAL_ETHICAL_DISCLAIMER = (
    "This tool supports exploratory literature discovery. It does not replace a systematic review "
    "or librarian-assisted database search. It does not scrape Google Scholar, bypass paywalls, or "
    "download copyrighted PDFs."
)
HOW_TO_USE_RESULTS = [
    "Use CSV for screening and sorting",
    "Use Markdown for notes or drafting",
    "Start from best_access_url for legal access",
    "Treat results as exploratory, not exhaustive",
]
RESEARCH_WORKFLOW_TIP = (
    "Research workflow tip:\n"
    "Start with Quick search to test keywords. Then use Research mode to build a larger source table. "
    "If a query times out, run fewer keyword lines at a time or reduce filters."
)
RESEARCH_STABILITY_HELPER_TEXT = "For best stability, start with 10 results per keyword, then increase if needed."
TIMEOUT_NO_RESULTS_GUIDANCE = (
    "No results were returned because OpenAlex timed out before completing the discovery search. "
    "This does not necessarily mean no papers exist. Try narrower keywords or run one keyword at a time."
)


@dataclass(frozen=True)
class SearchModeConfig:
    name: str
    default_results: int
    max_results_cap: int
    default_require_abstract: bool
    allow_require_abstract: bool
    allow_year_filters: bool


@dataclass
class LiteratureSearchOutcome:
    rows: List[Dict[str, Any]]
    had_timeout: bool = False
    all_keywords_timed_out: bool = False
    used_timeout_fallback: bool = False


class OpenAlexRequestError(requests.RequestException):
    def __init__(self, keyword: str, status_code: int, response_text: str):
        self.keyword = keyword
        self.status_code = status_code
        self.response_text = (response_text or "")[:OPENALEX_ERROR_SNIPPET_LENGTH]
        self.is_timeout = is_openalex_timeout_response(status_code, self.response_text)
        if self.is_timeout:
            message = OPENALEX_TIMEOUT_MESSAGE
        else:
            detail = friendly_openalex_error_detail(self.response_text)
            message = f"OpenAlex search failed for '{keyword}' with status {status_code}. {detail}"
        super().__init__(message)


def is_openalex_timeout_response(status_code: int, response_text: str) -> bool:
    return status_code == 504 or "query_timeout" in (response_text or "").lower()


def friendly_openalex_error_detail(response_text: str) -> str:
    if not response_text:
        return "No response detail was provided."

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        detail = response_text
    else:
        detail_parts = [
            str(data.get(key)).strip()
            for key in ("message", "error", "reason")
            if data.get(key)
        ]
        detail = " ".join(detail_parts) or response_text

    if len(detail) > OPENALEX_USER_ERROR_DETAIL_LENGTH:
        return detail[:OPENALEX_USER_ERROR_DETAIL_LENGTH].rstrip() + "..."
    return detail


def get_openalex_api_key(secrets: Optional[Mapping[str, Any]] = None) -> str:
    if secrets is None:
        try:
            import streamlit as st

            secrets = st.secrets
        except Exception:
            secrets = None

    if secrets is not None:
        try:
            api_key = secrets.get("OPENALEX_API_KEY")
        except Exception:
            api_key = None
        if api_key:
            return str(api_key).strip()

    return (os.getenv("OPENALEX_API_KEY") or "").strip()


def get_trusted_research_code(secrets: Optional[Mapping[str, Any]] = None) -> str:
    if secrets is None:
        try:
            import streamlit as st

            secrets = st.secrets
        except Exception:
            secrets = None

    if secrets is not None:
        try:
            access_code = secrets.get("TRUSTED_RESEARCH_CODE")
        except Exception:
            access_code = None
        if access_code:
            return str(access_code).strip()

    return (os.getenv("TRUSTED_RESEARCH_CODE") or "").strip()


def is_trusted_research_enabled(access_code: str, secrets: Optional[Mapping[str, Any]] = None) -> bool:
    configured_code = get_trusted_research_code(secrets)
    return bool(configured_code and access_code.strip() == configured_code)


def search_mode_config(mode: str, trusted: bool) -> SearchModeConfig:
    if mode == RESEARCH_SEARCH_MODE and trusted:
        return SearchModeConfig(
            name=RESEARCH_SEARCH_MODE,
            default_results=RESEARCH_DEFAULT_RESULTS_PER_KEYWORD,
            max_results_cap=RESEARCH_MAX_RESULTS_PER_KEYWORD,
            default_require_abstract=False,
            allow_require_abstract=True,
            allow_year_filters=True,
        )

    return SearchModeConfig(
        name=QUICK_SEARCH_MODE if mode != RESEARCH_SEARCH_MODE else RESEARCH_SEARCH_MODE,
        default_results=QUICK_DEFAULT_RESULTS_PER_KEYWORD,
        max_results_cap=QUICK_MAX_RESULTS_PER_KEYWORD,
        default_require_abstract=False,
        allow_require_abstract=mode == RESEARCH_SEARCH_MODE and trusted,
        allow_year_filters=mode == RESEARCH_SEARCH_MODE and trusted,
    )


def keyword_line_limit(trusted: bool) -> int:
    return TRUSTED_MAX_KEYWORD_LINES if trusted else PUBLIC_MAX_KEYWORD_LINES


def normalize_doi(doi: str) -> str:
    cleaned = (doi or "").strip().lower()
    cleaned = cleaned.replace("https://doi.org/", "")
    cleaned = cleaned.replace("http://doi.org/", "")
    cleaned = cleaned.replace("doi:", "")
    return cleaned.strip()


def doi_url(doi: str) -> str:
    cleaned = normalize_doi(doi)
    if not cleaned:
        return ""
    return f"https://doi.org/{cleaned}"


def add_access_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    openalex_oa_url = row.get("openalex_oa_url") or ""
    unpaywall_oa_url = row.get("unpaywall_oa_url") or ""
    publisher_url = row.get("publisher_url") or ""
    doi_link = doi_url(row.get("doi") or "")

    if openalex_oa_url or unpaywall_oa_url:
        row["access_status"] = "Open access found"
    elif doi_link or publisher_url:
        row["access_status"] = "DOI/publisher only"
    else:
        row["access_status"] = "No access link found"

    row["best_access_url"] = unpaywall_oa_url or openalex_oa_url or publisher_url or doi_link
    return row


def inverted_index_to_text(index: Optional[Dict[str, List[int]]]) -> str:
    if not index:
        return ""

    positioned_words = []
    for word, positions in index.items():
        for position in positions:
            positioned_words.append((position, word))
    positioned_words.sort()
    return " ".join(word for _, word in positioned_words)


def relevance_score(row: Dict[str, Any], keyword: str) -> int:
    words = [word.lower() for word in keyword.replace("-", " ").split() if len(word) > 2]
    title = (row.get("title") or "").lower()
    abstract = (row.get("abstract") or "").lower()
    score = 0
    for word in words:
        if word in title:
            score += 4
        if word in abstract:
            score += 1
    if row.get("abstract"):
        score += 5
    return score


def parse_openalex_work(work: Dict[str, Any], keyword: str) -> Dict[str, Any]:
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    open_access = work.get("open_access") or {}
    doi = normalize_doi(work.get("doi") or "")

    authors = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        if author.get("display_name"):
            authors.append(author["display_name"])

    row = {
        "openalex_id": work.get("id") or "",
        "title": (work.get("title") or work.get("display_name") or "").strip(),
        "authors": ", ".join(authors),
        "year": work.get("publication_year"),
        "venue": source.get("display_name") or "",
        "publication_type": work.get("type") or "",
        "citation_count": int(work.get("cited_by_count") or 0),
        "abstract": inverted_index_to_text(work.get("abstract_inverted_index")),
        "doi": doi,
        "landing_page_url": primary_location.get("landing_page_url") or "",
        "publisher_url": primary_location.get("landing_page_url") or doi_url(doi),
        "openalex_oa_url": open_access.get("oa_url") or "",
        "unpaywall_oa_url": "",
        "matched_keyword": keyword,
        "relevance_score": 0,
    }
    row["relevance_score"] = relevance_score(row, keyword)
    return add_access_fields(row)


def search_openalex(
    keyword: str,
    max_results: int,
    minimum_year: Optional[int],
    maximum_year: Optional[int],
    sort_by: str,
) -> List[Dict[str, Any]]:
    filters = []
    if minimum_year:
        filters.append(f"from_publication_date:{minimum_year}-01-01")
    if maximum_year:
        filters.append(f"to_publication_date:{maximum_year}-12-31")

    params = {
        "search": keyword,
        "per-page": max_results,
        "select": (
            "id,title,display_name,type,authorships,publication_year,primary_location,"
            "doi,cited_by_count,abstract_inverted_index,open_access"
        ),
    }
    if filters:
        params["filter"] = ",".join(filters)
    if sort_by == "citation count":
        params["sort"] = "cited_by_count:desc"
    elif sort_by == "year":
        params["sort"] = "publication_year:desc"

    mailto = os.getenv("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto

    api_key = get_openalex_api_key()
    if api_key:
        params["api_key"] = api_key

    response = None
    for attempt in range(2):
        response = requests.get(OPENALEX_URL, params=params, timeout=30)
        response_text = response.text if isinstance(response.text, str) else ""
        if response.status_code == 200:
            break
        if is_openalex_timeout_response(response.status_code, response_text) and attempt == 0:
            time.sleep(OPENALEX_RETRY_DELAY_SECONDS)
            continue
        raise OpenAlexRequestError(keyword, response.status_code, response_text)

    if response is None:
        return []
    data = response.json()

    rows = []
    for work in data.get("results", []):
        row = parse_openalex_work(work, keyword)
        if row["title"]:
            rows.append(row)
    return rows


def lookup_unpaywall_oa_url(doi: str) -> str:
    cleaned_doi = normalize_doi(doi)
    if not cleaned_doi:
        return ""

    email = os.getenv("UNPAYWALL_EMAIL") or os.getenv("OPENALEX_MAILTO") or "literature-finder@example.com"
    response = requests.get(
        UNPAYWALL_URL_TEMPLATE.format(doi=cleaned_doi),
        params={"email": email},
        timeout=30,
    )
    if response.status_code == 404:
        return ""
    response.raise_for_status()
    data = response.json()
    best_location = data.get("best_oa_location") or {}
    return best_location.get("url_for_landing_page") or best_location.get("url") or ""


def filter_results(
    rows: List[Dict[str, Any]],
    minimum_year: Optional[int],
    maximum_year: Optional[int],
    require_abstract: bool,
) -> List[Dict[str, Any]]:
    filtered = []
    for row in rows:
        year = row.get("year")
        if minimum_year and year and year < minimum_year:
            continue
        if maximum_year and year and year > maximum_year:
            continue
        if require_abstract and not row.get("abstract"):
            continue
        filtered.append(row)
    return filtered


def sort_results(rows: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
    if sort_by == "citation count":
        return sorted(rows, key=lambda row: row.get("citation_count") or 0, reverse=True)
    if sort_by == "year":
        return sorted(rows, key=lambda row: row.get("year") or 0, reverse=True)
    return sorted(rows, key=lambda row: row.get("relevance_score") or 0, reverse=True)


def parse_keyword_lines(keywords_text: str) -> List[str]:
    return [line.strip() for line in keywords_text.splitlines() if line.strip()]


def is_within_keyword_line_limit(keywords: List[str], trusted: bool = False) -> bool:
    return len(keywords) <= keyword_line_limit(trusted)


def can_run_demo_search(searches_used: int) -> bool:
    return searches_used < DEMO_SEARCH_LIMIT


def deduplicate_results(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique_rows = []
    for row in rows:
        key = row.get("doi") or (row.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def timeout_fallback_max_results(max_results: int) -> int:
    return min(max_results, FALLBACK_MAX_RESULTS_PER_KEYWORD)


def research_expansion_result_counts(max_results: int) -> List[int]:
    if max_results <= RESEARCH_DISCOVERY_RESULTS_PER_KEYWORD:
        return []

    result_counts = []
    next_count = RESEARCH_DISCOVERY_RESULTS_PER_KEYWORD + RESEARCH_EXPANSION_BATCH_SIZE
    while next_count < max_results:
        result_counts.append(next_count)
        next_count += RESEARCH_EXPANSION_BATCH_SIZE
    result_counts.append(max_results)
    return result_counts


def results_to_csv(rows: List[Dict[str, Any]]) -> str:
    output = io.StringIO()
    columns = export_columns()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        enriched_row = add_access_fields(row.copy())
        writer.writerow({column: enriched_row.get(column, "") for column in columns})
    return output.getvalue()


def results_to_markdown(rows: List[Dict[str, Any]]) -> str:
    lines = ["# Literature Finder Results", ""]
    for index, original_row in enumerate(rows, start=1):
        row = add_access_fields(original_row.copy())
        doi_link = doi_url(row.get("doi", ""))
        lines.extend(
            [
                f"## {index}. {row.get('title') or 'Untitled'}",
                "",
                f"- **Authors:** {row.get('authors') or 'Not listed'}",
                f"- **Year:** {row.get('year') or 'Not listed'}",
                f"- **Venue:** {row.get('venue') or 'Not listed'}",
                f"- **Citation count:** {row.get('citation_count') or 0}",
                f"- **DOI:** {doi_link or row.get('doi') or 'Not listed'}",
                f"- **Access status:** {row.get('access_status') or 'Not listed'}",
                f"- **Best access URL:** {row.get('best_access_url') or 'Not listed'}",
                f"- **Publisher URL:** {row.get('publisher_url') or 'Not listed'}",
                f"- **OpenAlex OA URL:** {row.get('openalex_oa_url') or 'Not listed'}",
                f"- **Unpaywall OA URL:** {row.get('unpaywall_oa_url') or 'Not listed'}",
                f"- **Publication type:** {row.get('publication_type') or 'Not listed'}",
                f"- **OpenAlex ID:** {row.get('openalex_id') or 'Not listed'}",
                f"- **Landing page URL:** {row.get('landing_page_url') or 'Not listed'}",
                f"- **Matched keyword:** {row.get('matched_keyword') or 'Not listed'}",
                f"- **Screening decision:** {row.get('screening_decision') or ''}",
                f"- **Reason for exclusion:** {row.get('reason_for_exclusion') or ''}",
                f"- **Notes:** {row.get('notes') or ''}",
                f"- **Theme:** {row.get('theme') or ''}",
                f"- **Priority:** {row.get('priority') or ''}",
                "",
                f"**Abstract:** {row.get('abstract') or 'No abstract available from API results.'}",
                "",
            ]
        )
    return "\n".join(lines)


def display_columns() -> List[str]:
    return [
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
        "publication_type",
        "openalex_id",
        "landing_page_url",
        "publisher_url",
        "openalex_oa_url",
        "unpaywall_oa_url",
    ]


def screening_columns() -> List[str]:
    return [
        "screening_decision",
        "reason_for_exclusion",
        "notes",
        "theme",
        "priority",
    ]


def export_columns() -> List[str]:
    return display_columns() + screening_columns()


def search_literature(
    keywords: List[str],
    max_results: int,
    minimum_year: Optional[int],
    maximum_year: Optional[int],
    require_abstract: bool,
    sort_by: str,
    status_area: Any,
    mode: str = QUICK_SEARCH_MODE,
) -> List[Dict[str, Any]]:
    return search_literature_with_status(
        keywords,
        max_results,
        minimum_year,
        maximum_year,
        require_abstract,
        sort_by,
        status_area,
        mode,
    ).rows


def search_research_keyword_stable_first(
    keyword: str,
    max_results: int,
    minimum_year: Optional[int],
    maximum_year: Optional[int],
    sort_by: str,
    status_area: Any,
) -> LiteratureSearchOutcome:
    had_timeout = False
    discovery_count = min(max_results, RESEARCH_DISCOVERY_RESULTS_PER_KEYWORD)
    try:
        keyword_rows = search_openalex(keyword, discovery_count, None, None, "relevance")
    except OpenAlexRequestError as error:
        if error.is_timeout:
            status_area.warning(
                f"OpenAlex timed out for '{keyword}'. This does not necessarily mean no papers exist. "
                "Try narrower keywords or run one keyword at a time."
            )
            return LiteratureSearchOutcome(rows=[], had_timeout=True, all_keywords_timed_out=True)

        status_area.warning(f"OpenAlex search skipped for '{keyword}': {error}")
        return LiteratureSearchOutcome(rows=[])
    except requests.RequestException:
        status_area.warning(
            f"OpenAlex timed out for '{keyword}'. This does not necessarily mean no papers exist. "
            "Try narrower keywords or run one keyword at a time."
        )
        return LiteratureSearchOutcome(rows=[], had_timeout=True, all_keywords_timed_out=True)

    for row in keyword_rows:
        row["_research_discovery"] = True

    best_rows = keyword_rows
    for result_count in research_expansion_result_counts(max_results):
        try:
            expanded_rows = search_openalex(keyword, result_count, minimum_year, maximum_year, sort_by)
        except OpenAlexRequestError as error:
            if error.is_timeout:
                had_timeout = True
                if best_rows:
                    status_area.info(
                        f"Partial results shown for '{keyword}' because OpenAlex timed out while expanding the search."
                    )
                else:
                    status_area.warning(
                        f"OpenAlex timed out for '{keyword}'. This does not necessarily mean no papers exist. "
                        "Try narrower keywords or run one keyword at a time."
                    )
                break

            status_area.warning(f"OpenAlex search skipped for '{keyword}': {error}")
            break
        except requests.RequestException:
            had_timeout = True
            if best_rows:
                status_area.info(
                    f"Partial results shown for '{keyword}' because OpenAlex timed out while expanding the search."
                )
            else:
                status_area.warning(
                    f"OpenAlex timed out for '{keyword}'. This does not necessarily mean no papers exist. "
                    "Try narrower keywords or run one keyword at a time."
                )
            break

        best_rows = best_rows + expanded_rows

    return LiteratureSearchOutcome(
        rows=best_rows,
        had_timeout=had_timeout,
        all_keywords_timed_out=False,
    )


def search_literature_with_status(
    keywords: List[str],
    max_results: int,
    minimum_year: Optional[int],
    maximum_year: Optional[int],
    require_abstract: bool,
    sort_by: str,
    status_area: Any,
    mode: str = QUICK_SEARCH_MODE,
) -> LiteratureSearchOutcome:
    all_rows = []
    timed_out_keywords = set()
    had_timeout = False
    used_timeout_fallback = False
    for keyword in keywords:
        if mode == RESEARCH_SEARCH_MODE:
            keyword_outcome = search_research_keyword_stable_first(
                keyword,
                max_results,
                minimum_year,
                maximum_year,
                sort_by,
                status_area,
            )
            all_rows.extend(keyword_outcome.rows)
            if keyword_outcome.had_timeout:
                had_timeout = True
            if keyword_outcome.all_keywords_timed_out:
                timed_out_keywords.add(keyword)
            time.sleep(DEFAULT_PAUSE_SECONDS)
            continue

        try:
            keyword_rows = search_openalex(keyword, max_results, minimum_year, maximum_year, sort_by)
        except OpenAlexRequestError as error:
            if not error.is_timeout:
                status_area.warning(f"OpenAlex search skipped for '{keyword}': {error}")
                continue

            had_timeout = True
            try:
                keyword_rows = search_openalex(
                    keyword,
                    timeout_fallback_max_results(max_results),
                    minimum_year,
                    maximum_year,
                    sort_by,
                )
            except OpenAlexRequestError as fallback_error:
                if fallback_error.is_timeout:
                    timed_out_keywords.add(keyword)
                    status_area.warning(
                        f"OpenAlex timed out for '{keyword}'. This does not necessarily mean no papers exist. "
                        "Try fewer filters, fewer results, or a narrower phrase."
                    )
                else:
                    status_area.warning(f"OpenAlex search skipped for '{keyword}': {fallback_error}")
                continue
            except requests.RequestException:
                timed_out_keywords.add(keyword)
                status_area.warning(
                    f"OpenAlex timed out for '{keyword}'. This does not necessarily mean no papers exist. "
                    "Try fewer filters, fewer results, or a narrower phrase."
                )
                continue

            used_timeout_fallback = True
            for row in keyword_rows:
                row["_timeout_fallback"] = True
            status_area.info("OpenAlex was slow for this query, so a lighter fallback search was used.")
        except requests.RequestException as error:
            status_area.warning(f"OpenAlex search failed for '{keyword}': {error}")
            continue

        all_rows.extend(keyword_rows)
        time.sleep(DEFAULT_PAUSE_SECONDS)

    rows = deduplicate_results(all_rows)
    if require_abstract:
        regular_rows = [row for row in rows if not row.get("_timeout_fallback") and not row.get("_research_discovery")]
        fallback_rows = [row for row in rows if row.get("_timeout_fallback") or row.get("_research_discovery")]
        rows = filter_results(regular_rows, minimum_year, maximum_year, True) + filter_results(
            fallback_rows, minimum_year, maximum_year, False
        )
    else:
        rows = filter_results(rows, minimum_year, maximum_year, False)

    for index, row in enumerate(rows, start=1):
        if not row.get("doi"):
            continue
        try:
            row["unpaywall_oa_url"] = lookup_unpaywall_oa_url(row["doi"])
        except (requests.RequestException, ValueError):
            row["unpaywall_oa_url"] = ""
            logger.info("Unpaywall lookup failed for DOI %s", row["doi"], exc_info=True)
        add_access_fields(row)
        time.sleep(DEFAULT_PAUSE_SECONDS)

    rows = [add_access_fields(row) for row in rows]
    rows = sort_results(rows, sort_by)
    return LiteratureSearchOutcome(
        rows=rows,
        had_timeout=had_timeout,
        all_keywords_timed_out=bool(keywords) and len(timed_out_keywords) == len(keywords),
        used_timeout_fallback=used_timeout_fallback,
    )


def render_app() -> None:
    import streamlit as st

    st.set_page_config(page_title="Literature Finder", layout="wide")
    st.title("Literature Finder")
    st.subheader(SUBTITLE)

    st.caption(
        "Searches OpenAlex and uses Unpaywall for legal open-access links when a DOI is available. "
        "Semantic Scholar is intentionally left disabled for a future optional source."
    )
    st.caption(PUBLIC_DEMO_NOTE)
    st.markdown(RESEARCH_WORKFLOW_TIP)

    with st.expander("Example searches"):
        st.code("\n".join(EXAMPLE_SEARCHES), language=None)

    st.markdown(KEYWORD_HELPER_NOTE)
    keywords_text = st.text_area(
        "Research keywords",
        height=160,
        placeholder=(
            "perceived control AND depression AND stress\n"
            "autism disclosure employment\n"
            "autistic college students STEM"
        ),
    )

    access_code = st.sidebar.text_input("Trusted research access code", type="password")
    trusted_research_enabled = is_trusted_research_enabled(access_code)
    if trusted_research_enabled:
        st.sidebar.caption("Trusted research mode enabled.")

    selected_mode = st.sidebar.radio(
        "Search mode",
        [QUICK_SEARCH_MODE, RESEARCH_SEARCH_MODE],
        index=0,
        help=(
            "Quick search is best for testing keywords quickly. Research mode is for larger source tables "
            "when trusted research mode is enabled."
        ),
    )
    mode_config = search_mode_config(selected_mode, trusted_research_enabled)
    if selected_mode == RESEARCH_SEARCH_MODE and not trusted_research_enabled:
        st.sidebar.caption("Enter a valid access code to unlock full Research mode caps.")

    max_results = st.number_input(
        "Max results per keyword",
        min_value=1,
        max_value=mode_config.max_results_cap,
        value=mode_config.default_results,
        step=1,
        help=RESEARCH_STABILITY_HELPER_TEXT if selected_mode == RESEARCH_SEARCH_MODE else None,
    )
    if selected_mode == RESEARCH_SEARCH_MODE:
        st.caption(RESEARCH_STABILITY_HELPER_TEXT)

    st.subheader("Optional filters")
    filter_columns = st.columns(4)
    with filter_columns[0]:
        minimum_year = st.number_input(
            "Minimum year",
            min_value=1800,
            max_value=2100,
            value=None,
            step=1,
            disabled=not mode_config.allow_year_filters,
        )
    with filter_columns[1]:
        maximum_year = st.number_input(
            "Maximum year",
            min_value=1800,
            max_value=2100,
            value=None,
            step=1,
            disabled=not mode_config.allow_year_filters,
        )
    with filter_columns[2]:
        require_abstract = st.checkbox(
            "Require abstract",
            value=mode_config.default_require_abstract,
            disabled=not mode_config.allow_require_abstract,
        )
    with filter_columns[3]:
        sort_by = st.selectbox("Sort by", ["relevance", "citation count", "year"])

    status_area = st.empty()
    if "demo_search_count" not in st.session_state:
        st.session_state.demo_search_count = 0

    searches_used = int(st.session_state.demo_search_count)
    if trusted_research_enabled:
        st.caption(f"Trusted research mode allows up to {TRUSTED_MAX_KEYWORD_LINES} keyword lines.")
    else:
        searches_remaining = max(DEMO_SEARCH_LIMIT - searches_used, 0)
        st.caption(f"Demo searches remaining this session: {searches_remaining}/{DEMO_SEARCH_LIMIT}")

    if st.button("Search", type="primary"):
        keywords = parse_keyword_lines(keywords_text)
        if not keywords:
            st.warning("Enter at least one keyword, one per line.")
            return
        if not is_within_keyword_line_limit(keywords, trusted=trusted_research_enabled):
            st.warning(f"Enter no more than {keyword_line_limit(trusted_research_enabled)} keyword lines.")
            return
        if minimum_year and maximum_year and minimum_year > maximum_year:
            st.warning("Minimum year must be less than or equal to maximum year.")
            return
        if not trusted_research_enabled and not can_run_demo_search(searches_used):
            st.warning(DEMO_LIMIT_MESSAGE)
            return

        if not trusted_research_enabled:
            st.session_state.demo_search_count = searches_used + 1
        with st.spinner("Searching papers and checking legal access links..."):
            try:
                outcome = search_literature_with_status(
                    keywords=keywords,
                    max_results=int(max_results),
                    minimum_year=minimum_year,
                    maximum_year=maximum_year,
                    require_abstract=require_abstract,
                    sort_by=sort_by,
                    status_area=status_area,
                    mode=selected_mode,
                )
            except OpenAlexRequestError as error:
                st.error(str(error))
                return
            except requests.RequestException as error:
                st.error(f"OpenAlex search failed: {error}")
                return

        rows = outcome.rows
        st.caption(f"Found {len(rows)} unique papers.")
        if not rows:
            if outcome.all_keywords_timed_out:
                st.info(TIMEOUT_NO_RESULTS_GUIDANCE)
            else:
                st.info(NO_RESULTS_GUIDANCE)
        else:
            table_rows = [{column: row.get(column, "") for column in display_columns()} for row in rows]
            st.dataframe(
                table_rows,
                width="stretch",
                column_config={
                    "best_access_url": st.column_config.LinkColumn("best access URL"),
                    "landing_page_url": st.column_config.LinkColumn("landing page URL"),
                    "publisher_url": st.column_config.LinkColumn("publisher URL"),
                    "openalex_oa_url": st.column_config.LinkColumn("OpenAlex OA URL"),
                    "unpaywall_oa_url": st.column_config.LinkColumn("Unpaywall OA URL"),
                },
            )

            st.caption(BEST_ACCESS_URL_EXPLANATION)
            st.markdown(ACCESS_STATUS_EXPLANATION)

            csv_data = results_to_csv(rows)
            markdown_data = results_to_markdown(rows)
            download_columns = st.columns(2)
            with download_columns[0]:
                st.download_button(
                    "Download CSV",
                    data=csv_data,
                    file_name="literature_finder_results.csv",
                    mime="text/csv",
                )
            with download_columns[1]:
                st.download_button(
                    "Download Markdown",
                    data=markdown_data,
                    file_name="literature_finder_results.md",
                    mime="text/markdown",
                )

    st.divider()
    st.subheader("How to use the results")
    st.markdown("\n".join(f"- {item}" for item in HOW_TO_USE_RESULTS))
    st.caption(LEGAL_ETHICAL_DISCLAIMER)
    st.divider()
    st.markdown(SOFT_CTA)


if __name__ == "__main__":
    render_app()
