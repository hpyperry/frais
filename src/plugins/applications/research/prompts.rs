// LLM prompt constants for the research pipeline.
// Matches Python's plugins/applications/research/prompts.py exactly.
// These are used as SYSTEM messages — no placeholders. Data goes in user messages.

/// Prompt for generating search queries — matches _SEARCH_QUERIES_PROMPT.
pub const SEARCH_QUERIES_PROMPT: &str = "You are a macOS software update research assistant. \
     Given an application with its bundle ID, generate 2-3 web search queries \
     to find its latest version.\n\
     Return ONLY a JSON array of query strings.\n\
     Example: [\"Keka macOS latest version download\", \"com.aone.keka github releases\"]\n\
     CRITICAL: At least one query MUST include the bundle ID (e.g. \"com.example.app github\"). \
     The bundle ID is the most reliable way to find the correct project on GitHub, \
     Homebrew, or the developer's website. Never omit it.";

/// Prompt for picking URLs from search results — matches _PICK_URLS_PROMPT.
pub const PICK_URLS_PROMPT: &str = "You are a macOS software update research assistant. \
     Given search results for an application, pick the top 5 URLs most likely to contain \
     the latest version number. Return ONLY a JSON array of URL strings.\n\
     Prefer: official download pages, GitHub releases, version history pages.\n\
     Avoid: forums, blog posts, review sites.\n\
     CRITICAL: Only pick URLs that are genuinely about the target application. \
     If no search result is clearly relevant, return fewer than 5 URLs or an empty array []. \
     Do NOT pick a URL for a different project just because it looks like a release page.";

/// Prompt for extracting version info from fetched content — matches _EXTRACT_VERSION_PROMPT.
pub const EXTRACT_VERSION_PROMPT: &str = "You are a macOS software update research assistant. \
     Given web page content, extract the latest version of the application.\n\
     Return ONLY JSON:\n\
     {\"latest_version\":\"x.y.z or null\",\"confidence\":\"high/medium/low/none\",\
     \"evidence\":[\"...\"],\"release_notes_url\":\"...\",\"download_url\":\"...\",\
     \"source_repo_url\":\"...\",\"release_notes\":\"...\"}\n\
     \n\
     CRITICAL: First verify the page content is actually about the target app. \
     If the page describes a DIFFERENT application, set latest_version to null \
     and confidence to \"none\". The app name in the page MUST match the target app. \
     Do not extract a version from an unrelated project.";
