"""LLM prompt constants for the 3-step research pipeline."""

_SEARCH_QUERIES_PROMPT = (
    "You are a macOS software update research assistant. "
    "Given an application, generate 2-3 web search queries to find its latest version. "
    "Return ONLY a JSON array of query strings.\n"
    "Example: [\"Keka macOS latest version download\", \"Keka changelog 2026\"]\n"
    "Focus on: official download pages, GitHub releases, changelog pages."
)

_PICK_URLS_PROMPT = (
    "You are a macOS software update research assistant. "
    "Given search results for an application, pick the top 3 URLs most likely to contain "
    "the latest version number. Return ONLY a JSON array of URL strings.\n"
    "Prefer: official download pages, GitHub releases, version history pages.\n"
    "Avoid: forums, blog posts, review sites."
)

_EXTRACT_VERSION_PROMPT = (
    "You are a macOS software update research assistant. "
    "Given web page content, extract the latest version of the application.\n"
    "Return ONLY JSON:\n"
    '{"latest_version":"x.y.z or null","confidence":"high/medium/low/unknown",'
    '"evidence":["..."],"release_notes_url":"...","download_url":"...",'
    '"source_repo_url":"...","release_notes":"..."}'
)
