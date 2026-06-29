import csv
import io
import os
import time
from typing import Any, Dict, List, Mapping, Optional

import requests


OPENALEX_URL = "https://api.openalex.org/works"
UNPAYWALL_URL_TEMPLATE = "https://api.unpaywall.org/v2/{doi}"
DEFAULT_PAUSE_SECONDS = 0.2
OPENALEX_ERROR_SNIPPET_LENGTH = 500
DEMO_SEARCH_LIMIT = 5
MAX_KEYWORD_LINES = 5
MAX_RESULTS_PER_KEYWORD = 30
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


class OpenAlexRequestError(requests.RequestException):
    def __init__(self, keyword: str, status_code: int, response_text: str):
        self.keyword = keyword
        self.status_code = status_code
        self.response_text = (response_text or "")[:OPENALEX_ERROR_SNIPPET_LENGTH]
        super().__init__(
            f"OpenAlex request failed with status {status_code} while searching "
            f"'{keyword}'. Response: {self.response_text or '[empty response]'}"
        )


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
        "title": (work.get("title") or work.get("display_name") or "").strip(),
        "authors": ", ".join(authors),
        "year": work.get("publication_year"),
        "venue": source.get("display_name") or "",
        "citation_count": int(work.get("cited_by_count") or 0),
        "abstract": inverted_index_to_text(work.get("abstract_inverted_index")),
        "doi": doi,
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
            "title,display_name,authorships,publication_year,primary_location,"
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

    response = requests.get(OPENALEX_URL, params=params, timeout=30)
    if response.status_code != 200:
        raise OpenAlexRequestError(keyword, response.status_code, response.text)
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


def is_within_keyword_line_limit(keywords: List[str]) -> bool:
    return len(keywords) <= MAX_KEYWORD_LINES


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


def results_to_csv(rows: List[Dict[str, Any]]) -> str:
    output = io.StringIO()
    columns = display_columns()
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
                f"- **Matched keyword:** {row.get('matched_keyword') or 'Not listed'}",
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
        "citation_count",
        "access_status",
        "best_access_url",
        "doi",
        "authors",
        "abstract",
        "matched_keyword",
        "publisher_url",
        "openalex_oa_url",
        "unpaywall_oa_url",
    ]


def search_literature(
    keywords: List[str],
    max_results: int,
    minimum_year: Optional[int],
    maximum_year: Optional[int],
    require_abstract: bool,
    sort_by: str,
    status_area: Any,
) -> List[Dict[str, Any]]:
    all_rows = []
    for keyword in keywords:
        try:
            keyword_rows = search_openalex(keyword, max_results, minimum_year, maximum_year, sort_by)
        except OpenAlexRequestError as error:
            status_area.error(str(error))
            raise
        except requests.RequestException as error:
            status_area.warning(f"OpenAlex search failed for '{keyword}': {error}")
            raise

        all_rows.extend(keyword_rows)
        time.sleep(DEFAULT_PAUSE_SECONDS)

    rows = deduplicate_results(all_rows)
    rows = filter_results(rows, minimum_year, maximum_year, require_abstract)

    for index, row in enumerate(rows, start=1):
        if not row.get("doi"):
            continue
        try:
            row["unpaywall_oa_url"] = lookup_unpaywall_oa_url(row["doi"])
        except requests.RequestException as error:
            row["unpaywall_oa_url"] = ""
            status_area.warning(f"Unpaywall lookup failed for DOI {row['doi']}: {error}")
        add_access_fields(row)
        time.sleep(DEFAULT_PAUSE_SECONDS)

    rows = [add_access_fields(row) for row in rows]
    return sort_results(rows, sort_by)


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

    max_results = st.number_input(
        "Max results per keyword",
        min_value=1,
        max_value=MAX_RESULTS_PER_KEYWORD,
        value=20,
        step=1,
    )

    st.subheader("Optional filters")
    filter_columns = st.columns(4)
    with filter_columns[0]:
        minimum_year = st.number_input("Minimum year", min_value=1800, max_value=2100, value=None, step=1)
    with filter_columns[1]:
        maximum_year = st.number_input("Maximum year", min_value=1800, max_value=2100, value=None, step=1)
    with filter_columns[2]:
        require_abstract = st.checkbox("Require abstract")
    with filter_columns[3]:
        sort_by = st.selectbox("Sort by", ["relevance", "citation count", "year"])

    status_area = st.empty()
    if "demo_search_count" not in st.session_state:
        st.session_state.demo_search_count = 0

    searches_used = int(st.session_state.demo_search_count)
    searches_remaining = max(DEMO_SEARCH_LIMIT - searches_used, 0)
    st.caption(f"Demo searches remaining this session: {searches_remaining}/{DEMO_SEARCH_LIMIT}")

    if st.button("Search", type="primary"):
        keywords = parse_keyword_lines(keywords_text)
        if not keywords:
            st.warning("Enter at least one keyword, one per line.")
            return
        if not is_within_keyword_line_limit(keywords):
            st.warning(f"Enter no more than {MAX_KEYWORD_LINES} keyword lines for the public demo.")
            return
        if minimum_year and maximum_year and minimum_year > maximum_year:
            st.warning("Minimum year must be less than or equal to maximum year.")
            return
        if not can_run_demo_search(searches_used):
            st.warning(DEMO_LIMIT_MESSAGE)
            return

        st.session_state.demo_search_count = searches_used + 1
        with st.spinner("Searching papers and checking legal access links..."):
            try:
                rows = search_literature(
                    keywords=keywords,
                    max_results=int(max_results),
                    minimum_year=minimum_year,
                    maximum_year=maximum_year,
                    require_abstract=require_abstract,
                    sort_by=sort_by,
                    status_area=status_area,
                )
            except OpenAlexRequestError as error:
                st.error(str(error))
                return
            except requests.RequestException as error:
                st.error(f"OpenAlex search failed: {error}")
                return

        status_area.empty()
        st.caption(f"Found {len(rows)} unique papers.")
        if not rows:
            st.info(NO_RESULTS_GUIDANCE)
        else:
            table_rows = [{column: row.get(column, "") for column in display_columns()} for row in rows]
            st.dataframe(
                table_rows,
                width="stretch",
                column_config={
                    "best_access_url": st.column_config.LinkColumn("best access URL"),
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
