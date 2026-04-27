# ============================================================
# ULTIMATE MEDIA TRACKER — Fully Refactored & Google Sheets Fixed
# ============================================================

import re
import time
import threading
import urllib.parse
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from tmdbv3api import TMDb, Movie, TV, Search, Discover, Collection

try:
    from streamlit_sortables import sort_items
    HAS_SORTABLES = True
except ImportError:
    HAS_SORTABLES = False

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ============================================================
# CONSTANTS
# ============================================================
GOOGLE_SHEET_NAME = "My Media Tracker"
TMDB_POSTER_BASE  = "https://image.tmdb.org/t/p/w400"
TMDB_BACKDROP_BASE = "https://image.tmdb.org/t/p/w780"

# 1-based column indices for gspread — change here, applies everywhere
COL_TITLE          = 1
COL_TYPE           = 2
COL_COUNTRY        = 3
COL_STATUS         = 4
COL_GENRES         = 5
COL_IMAGE          = 6
COL_OVERVIEW       = 7
COL_RATING         = 8
COL_BACKDROP       = 9
COL_CURRENT_SEASON = 10
COL_CURRENT_EP     = 11
COL_TOTAL_EPS      = 12
COL_TOTAL_SEASONS  = 13
COL_ID             = 14
COL_PERSONAL_RATING = 15
COL_NOTES          = 16

REQUIRED_HEADERS = [
    "Title", "Type", "Country", "Status", "Genres", "Image",
    "Overview", "Rating", "Backdrop", "Current_Season",
    "Current_Ep", "Total_Eps", "Total_Seasons", "ID",
    "Personal_Rating", "Notes",
]

ALL_MEDIA_TYPES = [
    "Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama",
    "Anime", "Donghua", "Manga", "Manhwa", "Manhua", "Novel", "Book",
]

READ_TYPES       = {"Book", "Novel", "Manga", "Manhwa", "Manhua"}
ANILIST_TYPES    = {"Anime", "Donghua", "Manga", "Manhwa", "Manhua", "Novel"}
TMDB_LIVE_TYPES  = {"Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama"}

WATCH_STATUSES = ["Plan to Watch", "Watching", "Completed", "On Hold", "Dropped"]
READ_STATUSES  = ["Plan to Read",  "Reading",  "Completed", "On Hold", "Dropped"]

TMDB_GENRE_MAP = {
    "Action": 28, "Adventure": 12, "Animation": 16, "Comedy": 35,
    "Crime": 80, "Documentary": 99, "Drama": 18, "Family": 10751,
    "Fantasy": 14, "History": 36, "Horror": 27, "Music": 10402,
    "Mystery": 9648, "Romance": 10749, "Sci-Fi": 878, "TV Movie": 10770,
    "Thriller": 53, "War": 10752, "Western": 37,
    "Action & Adventure": 10759, "Sci-Fi & Fantasy": 10765, "War & Politics": 10768,
}
ID_TO_GENRE = {v: k for k, v in TMDB_GENRE_MAP.items()}

BOOK_GENRES = sorted([
    "Web Novel", "Fiction", "Fantasy", "Sci-Fi", "Mystery", "Thriller",
    "Romance", "History", "Biography", "Business", "Self-Help", "Psychology",
    "Philosophy", "Science", "Technology", "Light Novel", "Computers",
    "Horror", "Poetry", "Comics", "Art", "Cooking",
])

# AniList rate-limiter: max 3 concurrent calls
_anilist_sem = threading.Semaphore(3)

STATUS_EMOJI = {
    "Plan to Watch": "🔖", "Plan to Read": "🔖",
    "Watching": "▶️",      "Reading":  "📖",
    "Completed": "✅",      "Dropped":  "❌",
    "On Hold": "⏸️",
}

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Ultimate Media Tracker",
    layout="wide",
    page_icon="📚",
)
st.markdown(
    """
    <style>
        .stAppDeployButton {display:none;}
        header          {visibility:hidden;}
        #MainMenu        {visibility:hidden;}
        .progress-wrap  {background:#2d2d2d;border-radius:4px;height:6px;width:100%;margin-top:4px;}
        .progress-fill  {background:#ff4b4b;height:6px;border-radius:4px;}
        .badge          {display:inline-block;padding:2px 8px;border-radius:10px;
                         font-size:11px;font-weight:600;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# QUERY-PARAM NAVIGATION (sequel link clicks)
# ============================================================
if "search" in st.query_params:
    st.session_state.search_query_trigger = st.query_params["search"]
    st.query_params.clear()

st.title("🎬 Ultimate Media Tracker")

# ============================================================
# SECRETS & TMDB
# ============================================================
try:
    TMDB_API_KEY = st.secrets["tmdb_api_key"]
except Exception:
    st.error("❌ Secrets missing. Add `tmdb_api_key` to .streamlit/secrets.toml")
    st.stop()

tmdb = TMDb()
tmdb.api_key  = TMDB_API_KEY
tmdb.language = "en"

# ============================================================
# CACHED COUNTRY LIST
# ============================================================
@st.cache_data(ttl=86400)
def get_tmdb_countries() -> dict:
    try:
        url  = f"https://api.themoviedb.org/3/configuration/countries?api_key={TMDB_API_KEY}"
        resp = requests.get(url, timeout=5).json()
        return dict(sorted({c["english_name"]: c["iso_3166_1"] for c in resp}.items()))
    except Exception as exc:
        logger.warning("Country fetch failed: %s", exc)
        return {"India": "IN", "United States": "US", "United Kingdom": "GB"}

tmdb_countries = get_tmdb_countries()

# ============================================================
# GOOGLE SHEETS (FIXED VERSION)
# ============================================================
def get_google_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        if "gcp_service_account" in st.secrets:
            # Safely cast Streamlit secrets to a standard Python dictionary
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
            
        client = gspread.authorize(creds)
        sheet  = client.open(GOOGLE_SHEET_NAME).sheet1

        vals = sheet.get_all_values()
        
        # If the sheet is completely empty
        if not vals:
            sheet.resize(cols=len(REQUIRED_HEADERS))
            sheet.append_row(REQUIRED_HEADERS)
        else:
            existing = vals[0]
            # FIX: Force Google Sheets to expand the grid if it doesn't have enough columns
            if len(existing) < len(REQUIRED_HEADERS):
                sheet.resize(cols=len(REQUIRED_HEADERS))
                
            for i, header in enumerate(REQUIRED_HEADERS):
                col_pos = i + 1
                if i >= len(existing):
                    sheet.update_cell(1, col_pos, header)
                elif existing[i] != header and header not in existing:
                    sheet.update_cell(1, col_pos, header)
        return sheet
    except Exception as exc:
        logger.error("Sheet connection failed: %s", exc)
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_sheet_records() -> dict:
    sheet = get_google_sheet()
    if not sheet:
        return {}
    try:
        data = sheet.get_all_records()
        return {
            item.get("Title", "").strip(): item
            for item in data
            if item.get("Title", "").strip()
        }
    except Exception as exc:
        logger.error("Sheet records fetch failed: %s", exc)
        return {}


def get_library_data() -> dict:
    if "lib_data" not in st.session_state:
        st.session_state.lib_data = _fetch_sheet_records()
    return st.session_state.lib_data


def refresh_library():
    st.session_state.pop("lib_data", None)
    _fetch_sheet_records.clear()
    get_library_data()

# ============================================================
# DATABASE ACTIONS
# ============================================================
def fetch_details_and_add(item: dict) -> bool:
    sheet = get_google_sheet()
    if not sheet:
        return False

    title_clean = item["Title"].strip()
    if title_clean in get_library_data():
        st.toast(f"⚠️ '{title_clean}' is already in your library!")
        return True

    total_seasons = 1
    total_eps     = item.get("Total_Eps", "?")
    media_id      = item.get("ID")

    if item["Type"] in {"Web Series", "K-Drama", "C-Drama", "Thai Drama"} and media_id:
        try:
            details      = TV().details(media_id)
            total_seasons = getattr(details, "number_of_seasons", 1)
            total_eps    = getattr(details, "number_of_episodes", "?")
        except Exception as exc:
            logger.warning("TV details fetch failed: %s", exc)

    default_status = "Plan to Read" if item["Type"] in READ_TYPES else "Plan to Watch"

    try:
        row = [
            title_clean, item["Type"], item["Country"],
            default_status, item["Genres"], item["Image"],
            item["Overview"], item["Rating"], item.get("Backdrop", ""),
            1, 0, total_eps, total_seasons, media_id, "", "",
        ]
        sheet.append_row(row)
        st.toast(f"✅ Added: {title_clean}")

        st.session_state.lib_data[title_clean] = {
            "Title": title_clean,         "Type": item["Type"],
            "Country": item["Country"],   "Status": default_status,
            "Genres": item["Genres"],     "Image": item["Image"],
            "Overview": item["Overview"], "Rating": item["Rating"],
            "Backdrop": item.get("Backdrop", ""),
            "Current_Season": 1,          "Current_Ep": 0,
            "Total_Eps": total_eps,       "Total_Seasons": total_seasons,
            "ID": media_id,               "Personal_Rating": "",
            "Notes": "",
        }
        return True
    except Exception as exc:
        st.error(f"Failed to add item: {exc}")
        return False


def update_status_in_sheet(
    title: str,
    new_status: str,
    new_season: int,
    new_ep: int,
    personal_rating: str | None = None,
    notes: str | None = None,
):
    sheet = get_google_sheet()
    if not sheet:
        return
    try:
        # findall + in_column for exact-column safety (fixes wrong-row bug)
        cells = sheet.findall(title, in_column=COL_TITLE)
        if not cells:
            st.warning(f"Could not find '{title}' in sheet.")
            return
        row = cells[0].row
        updates = {
            COL_STATUS:         new_status,
            COL_CURRENT_SEASON: new_season,
            COL_CURRENT_EP:     new_ep,
        }
        if personal_rating is not None:
            updates[COL_PERSONAL_RATING] = personal_rating
        if notes is not None:
            updates[COL_NOTES] = notes

        for col, val in updates.items():
            sheet.update_cell(row, col, val)

        st.toast(f"✅ Saved: {title}")

        # Mirror into local cache
        if "lib_data" in st.session_state and title in st.session_state.lib_data:
            entry = st.session_state.lib_data[title]
            entry["Status"]         = new_status
            entry["Current_Season"] = new_season
            entry["Current_Ep"]     = new_ep
            if personal_rating is not None:
                entry["Personal_Rating"] = personal_rating
            if notes is not None:
                entry["Notes"] = notes
    except Exception as exc:
        logger.error("Update failed for %s: %s", title, exc)
        st.error(f"Update failed: {exc}")


def delete_from_sheet(title: str):
    sheet = get_google_sheet()
    if not sheet:
        return
    try:
        cells = sheet.findall(title, in_column=COL_TITLE)
        if cells:
            sheet.delete_rows(cells[0].row)
            st.toast(f"🗑️ Deleted: {title}")
            st.session_state.lib_data.pop(title, None)
    except Exception as exc:
        logger.error("Delete failed for %s: %s", title, exc)
        st.error(f"Delete failed: {exc}")


def bulk_update_order(new_df: pd.DataFrame):
    sheet = get_google_sheet()
    if not sheet:
        return
    try:
        backup = sheet.get_all_values()
        header = backup[0] if backup else REQUIRED_HEADERS
        rows   = new_df.astype(str).values.tolist()
        sheet.clear()
        sheet.append_row(header)
        if rows:
            sheet.append_rows(rows)
        st.toast("✅ Order saved!")
        refresh_library()
        time.sleep(0.4)
        st.rerun()
    except Exception as exc:
        logger.error("Bulk reorder failed: %s", exc)
        st.error(f"Reorder failed (data is safe): {exc}")

# ============================================================
# HELPERS
# ============================================================
def recover_tmdb_id(title: str, media_type: str):
    try:
        s = Search()
        results = s.movies(title) if media_type == "movie" else s.tv_shows(title)
        if results:
            return results[0].id
    except Exception as exc:
        logger.warning("TMDB ID recovery failed for %s: %s", title, exc)
    return None


def get_streaming_info(tmdb_id, media_type: str, country_code: str):
    if not tmdb_id:
        return None
    try:
        clean = int(float(tmdb_id))
        url   = (f"https://api.themoviedb.org/3/{media_type}/{clean}"
                 f"/watch/providers?api_key={TMDB_API_KEY}")
        data  = requests.get(url, timeout=5).json()
        return data.get("results", {}).get(country_code)
    except Exception as exc:
        logger.warning("Streaming info failed: %s", exc)
    return None


def get_provider_link(provider_name: str, title: str) -> str:
    q = urllib.parse.quote(title)
    p = provider_name.lower()
    if "netflix"            in p: return f"https://www.netflix.com/search?q={q}"
    if "amazon" in p or "prime" in p: return f"https://www.amazon.com/s?k={q}&i=instant-video"
    if "youtube"            in p: return f"https://www.youtube.com/results?search_query={q}"
    return f"https://www.google.com/search?q=watch+{q}+on+{urllib.parse.quote(provider_name)}"


def calc_progress(current_ep, total_eps) -> float:
    """Returns 0.0–1.0, or -1 if unknown."""
    try:
        return min(int(current_ep) / int(total_eps), 1.0)
    except (ValueError, TypeError, ZeroDivisionError):
        return -1.0


def render_progress_bar(progress: float):
    if progress < 0:
        return
    pct = int(progress * 100)
    st.markdown(
        f'<div class="progress-wrap">'
        f'<div class="progress-fill" style="width:{pct}%"></div>'
        f'</div><small style="color:#888">{pct}% complete</small>',
        unsafe_allow_html=True,
    )

# ============================================================
# TMDB API CALLS
# ============================================================
@st.cache_data(ttl=3600)
def get_tmdb_relations(tmdb_id, media_type: str, current_title: str) -> list:
    if not tmdb_id:
        return []
    relations = []
    try:
        clean = int(float(tmdb_id))
        if media_type == "movie":
            details = Movie().details(clean)
            col = getattr(details, "belongs_to_collection", None)
            if col and isinstance(col, dict) and "id" in col:
                parts = sorted(
                    getattr(Collection().details(col["id"]), "parts", []),
                    key=lambda x: x.get("release_date", "9999"),
                )
                for p in parts:
                    if p["id"] != clean:
                        relations.append({
                            "title": p["title"],
                            "type": "Movie",
                            "relation": "Part of Series",
                        })
        else:
            url = (f"https://api.themoviedb.org/3/tv/{clean}/recommendations"
                   f"?api_key={TMDB_API_KEY}&language=en-US&page=1")
            recs = requests.get(url, timeout=5).json().get("results", [])[:6]
            base = current_title.split(":")[0].split("Season")[0].strip().lower()
            for rec in recs:
                name = rec["name"]
                if base in name.lower() or "Season" in name:
                    relations.append({
                        "title": name, "type": "TV", "relation": "Sequel/Related"
                    })
    except Exception as exc:
        logger.warning("TMDB relations failed: %s", exc)
    return relations


@st.cache_data(ttl=3600)
def get_season_details(tmdb_id, season_num: int):
    if not tmdb_id:
        return None
    try:
        clean = int(float(tmdb_id))
        url   = (f"https://api.themoviedb.org/3/tv/{clean}/season/{season_num}"
                 f"?api_key={TMDB_API_KEY}")
        data  = requests.get(url, timeout=5).json()
        return {
            "episode_count": len(data.get("episodes", [])),
            "name": data.get("name"),
        }
    except Exception as exc:
        logger.warning("Season details failed: %s", exc)
    return None


@st.cache_data(ttl=3600)
def get_tmdb_trailer(tmdb_id, media_type: str) -> str | None:
    if not tmdb_id:
        return None
    try:
        clean  = int(float(tmdb_id))
        url    = (f"https://api.themoviedb.org/3/{media_type}/{clean}/videos"
                  f"?api_key={TMDB_API_KEY}")
        videos = requests.get(url, timeout=5).json().get("results", [])
        for v_type in ("Trailer", "Teaser", None):
            for vid in videos:
                if vid["site"] == "YouTube" and (v_type is None or vid["type"] == v_type):
                    return f"https://www.youtube.com/watch?v={vid['key']}"
    except Exception as exc:
        logger.warning("Trailer fetch failed: %s", exc)
    return None

# ============================================================
# ANILIST API CALLS (rate-limited)
# ============================================================
@st.cache_data(ttl=3600)
def fetch_anilist_data_single(
    title: str,
    media_type: str,
    format_in=None,
    fetch_relations: bool = False,
) -> dict:
    """
    Single-item AniList fetch.
    fetch_relations=True adds the relations block so we never call twice.
    """
    rel_block = ""
    if fetch_relations:
        rel_block = """
        relations {
            edges {
                relationType
                node { title { romaji english } type }
            }
        }"""

    gql = f"""
    query ($s: String, $t: MediaType, $f: MediaFormat) {{
        Page(perPage: 1) {{
            media(search: $s, type: $t, format: $f) {{
                id
                trailer {{ id site }}
                externalLinks {{ site url }}
                episodes chapters volumes
                {rel_block}
            }}
        }}
    }}"""
    variables: dict = {"s": title, "t": media_type}
    if format_in:
        variables["f"] = format_in

    with _anilist_sem:
        try:
            r    = requests.post(
                "https://graphql.anilist.co",
                json={"query": gql, "variables": variables},
                timeout=8,
            )
            data = r.json()
            media = data["data"]["Page"]["media"]
            if media:
                return media[0]
        except Exception as exc:
            logger.warning("AniList single fetch failed for %s: %s", title, exc)
    return {}


@st.cache_data(ttl=3600)
def fetch_anilist_list_raw(
    query: str,
    type_: str,
    genres: list,
    sort_opt: str,
    page: int,
    country=None,
    format_=None,
) -> list:
    sort_map   = {"Top Rated": "SCORE_DESC", "Relevance": "SEARCH_MATCH"}
    al_sort    = sort_map.get(sort_opt, "POPULARITY_DESC")
    if sort_opt == "Relevance" and not query:
        al_sort = "POPULARITY_DESC"

    variables  = {"t": type_, "p": page, "sort": [al_sort]}
    q_args     = ["$p: Int", "$t: MediaType", "$sort: [MediaSort]"]
    m_args     = ["type: $t", "sort: $sort", "isAdult: false"]

    if query:
        q_args.append("$s: String"); m_args.append("search: $s"); variables["s"] = query
    if genres:
        q_args.append("$g: [String]"); m_args.append("genre_in: $g"); variables["g"] = genres
    if country:
        q_args.append("$c: CountryCode"); m_args.append("countryOfOrigin: $c"); variables["c"] = country
    if format_:
        q_args.append("$f: MediaFormat"); m_args.append("format: $f"); variables["f"] = format_

    gql = f"""
    query ({', '.join(q_args)}) {{
        Page(page: $p, perPage: 15) {{
            media({', '.join(m_args)}) {{
                title {{ romaji english }}
                coverImage {{ large }} bannerImage genres countryOfOrigin
                type format description averageScore episodes chapters volumes
                externalLinks {{ site url }}
            }}
        }}
    }}"""

    with _anilist_sem:
        try:
            r = requests.post(
                "https://graphql.anilist.co",
                json={"query": gql, "variables": variables},
                timeout=10,
            )
            if r.status_code == 200:
                return r.json()["data"]["Page"]["media"]
        except Exception as exc:
            logger.warning("AniList list fetch failed: %s", exc)
    return []

# ============================================================
# OPEN LIBRARY
# ============================================================
@st.cache_data(ttl=3600)
def fetch_open_library_raw(query: str, genre=None) -> list:
    params: dict = {"limit": 15}
    if query:
        params["q"] = query + (f" subject:{genre}" if genre and genre != "Web Novel" else "")
    elif genre:
        params["subject"] = genre
    else:
        params["subject"] = "fiction"
    try:
        r = requests.get(
            "https://openlibrary.org/search.json",
            params=params,
            headers={"User-Agent": "MediaTrackerApp/1.0"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("docs", [])
    except Exception as exc:
        logger.warning("OpenLibrary fetch failed: %s", exc)
    return []

# ============================================================
# PROCESSORS
# ============================================================
def process_open_library(items: list, detected_type: str) -> list:
    results = []
    for item in items:
        cid   = item.get("cover_i")
        img   = (f"https://covers.openlibrary.org/b/id/{cid}-L.jpg"
                 if cid else "https://via.placeholder.com/300x450?text=No+Cover")
        title = item.get("title", "Unknown")
        auth  = ", ".join(item.get("author_name", [])[:2])
        if auth:
            title += f" — {auth}"
        desc = f"First published in {item.get('first_publish_year', 'Unknown')}."
        if item.get("first_sentence"):
            desc = f'"{item["first_sentence"][0]}" — ' + desc
        avg = item.get("ratings_average", 0) or 0
        results.append({
            "Title": title,          "Type": detected_type,
            "Country": "International",
            "Genres": ", ".join(item.get("subject", [])[:3]),
            "Image": img,            "Overview": desc,
            "Rating": f"{round(avg, 1)}/5",
            "Backdrop": "",          "Total_Eps": str(item.get("number_of_pages_median", "?")),
            "ID": item.get("key"),   "Links": [],
        })
    return results


def process_anilist_results(res_list: list, forced_type: str, selected_genres: list) -> list:
    results = []
    for res in res_list:
        origin = res.get("countryOfOrigin", "JP")
        if forced_type == "Donghua" and origin != "CN": continue
        if forced_type == "Manhwa"  and origin != "KR": continue
        if forced_type == "Manhua"  and origin != "CN": continue

        res_genres = res.get("genres", [])
        if selected_genres:
            filtered = [g for g in selected_genres if g != "Web Novel"]
            if filtered and not any(g in res_genres for g in filtered):
                continue

        raw   = res.get("description", "") or ""
        clean = re.sub(r"<[^<]+?>", "", raw) or "No description."
        total = res.get("episodes") or res.get("chapters") or res.get("volumes") or "?"
        avg   = res.get("averageScore")

        results.append({
            "Title":   res["title"]["english"] or res["title"]["romaji"],
            "Type":    forced_type,
            "Country": origin,
            "Genres":  ", ".join(res_genres),
            "Image":   res.get("coverImage", {}).get("large", ""),
            "Overview": clean,
            "Rating":  f"{avg / 10:.1f}/10" if avg else "?/10",
            "Backdrop": res.get("bannerImage", ""),
            "Total_Eps": total,
            "ID": None,
            "Links": res.get("externalLinks", []),
        })
    return results


def process_tmdb_results_batch(
    results,
    media_kind: str,
    specific_type: str,
    selected_types: list,
    selected_genres: list,
    query: str,
) -> list:
    lang_to_type = {
        "ko": "K-Drama", "zh": "C-Drama", "th": "Thai Drama",
        "ja": "Anime",   "en": "Web Series",
    }
    processed = []
    for r in results:
        lang = getattr(r, "original_language", "en")

        # Language filter in discovery mode
        if not query:
            expected = {
                "K-Drama": "ko", "C-Drama": "zh", "Thai Drama": "th"
            }.get(specific_type)
            if expected and lang != expected:
                continue

        genre_ids  = getattr(r, "genre_ids", [])
        res_genres = [ID_TO_GENRE.get(g, "Unknown") for g in genre_ids]
        if selected_genres and not any(g in res_genres for g in selected_genres):
            continue

        detected = "Movies" if media_kind == "Movie" else lang_to_type.get(lang, "Web Series")
        if detected not in selected_types:
            continue

        poster = getattr(r, "poster_path", None)
        processed.append({
            "Title":   getattr(r, "title", getattr(r, "name", "Unknown")),
            "Type":    detected,
            "Country": lang,
            "Genres":  ", ".join(res_genres),
            "Image":   f"{TMDB_POSTER_BASE}{poster}" if poster else "",
            "Overview": getattr(r, "overview", "No overview."),
            "Rating":  f"{getattr(r, 'vote_average', 0):.1f}/10",
            "Backdrop": f"{TMDB_BACKDROP_BASE}{getattr(r, 'backdrop_path', '')}",
            "Total_Eps": "?",
            "ID": getattr(r, "id", None),
        })
    return processed

# ============================================================
# PARALLEL SEARCH ENGINE
# ============================================================
def search_unified(
    query: str,
    selected_types: list,
    selected_genres: list,
    sort_option: str,
    page: int = 1,
) -> list:
    all_results: list = []
    futures      = []
    tmdb_sort    = "vote_average.desc" if sort_option == "Top Rated" else "popularity.desc"
    g_ids        = "|".join(str(TMDB_GENRE_MAP[g]) for g in selected_genres if g in TMDB_GENRE_MAP)

    discover  = Discover()
    search_api = Search()

    def tmdb_job(media_kind: str, specific_type: str, lang_filter=None) -> list:
        try:
            if query:
                raw = (search_api.movies(query, page=page)
                       if media_kind == "Movie"
                       else search_api.tv_shows(query, page=page))
            else:
                kwargs: dict = {"sort_by": tmdb_sort, "page": page, "vote_count.gte": 10}
                if g_ids:        kwargs["with_genres"]            = g_ids
                if lang_filter:  kwargs["with_original_language"] = lang_filter
                raw = (discover.discover_movies(kwargs)
                       if media_kind == "Movie"
                       else discover.discover_tv_shows(kwargs))
            return process_tmdb_results_batch(
                raw, media_kind, specific_type, selected_types, selected_genres, query
            )
        except Exception as exc:
            logger.warning("TMDB job failed (%s): %s", specific_type, exc)
            return []

    def anilist_job(q, t, g, s, p, c=None, f=None, forced_t="Anime") -> list:
        raw = fetch_anilist_list_raw(q, t, g, s, p, c, f)
        return process_anilist_results(raw, forced_t, g)

    def openlib_job(q: str, g, forced_t: str) -> list:
        suffix = " novel" if forced_t == "Novel" and q else ""
        q_mod  = (q + suffix) if q else ("fantasy novel" if forced_t == "Novel" else "fiction")
        return process_open_library(fetch_open_library_raw(q_mod, g), forced_t)

    with ThreadPoolExecutor(max_workers=8) as executor:
        if "Movies"     in selected_types: futures.append(executor.submit(tmdb_job, "Movie", "Movies"))
        if "Web Series" in selected_types: futures.append(executor.submit(tmdb_job, "TV", "Web Series"))
        if "K-Drama"    in selected_types: futures.append(executor.submit(tmdb_job, "TV", "K-Drama",   "ko"))
        if "C-Drama"    in selected_types: futures.append(executor.submit(tmdb_job, "TV", "C-Drama",   "zh"))
        if "Thai Drama" in selected_types: futures.append(executor.submit(tmdb_job, "TV", "Thai Drama","th"))
        if "Anime"      in selected_types: futures.append(executor.submit(anilist_job, query, "ANIME", selected_genres, sort_option, page, None, None, "Anime"))
        if "Donghua"    in selected_types: futures.append(executor.submit(anilist_job, query, "ANIME", selected_genres, sort_option, page, "CN",   None, "Donghua"))
        if "Manga"      in selected_types: futures.append(executor.submit(anilist_job, query, "MANGA", selected_genres, sort_option, page, "JP",   None, "Manga"))
        if "Manhwa"     in selected_types: futures.append(executor.submit(anilist_job, query, "MANGA", selected_genres, sort_option, page, "KR",   None, "Manhwa"))
        if "Manhua"     in selected_types: futures.append(executor.submit(anilist_job, query, "MANGA", selected_genres, sort_option, page, "CN",   None, "Manhua"))
        if "Novel"      in selected_types:
            futures.append(executor.submit(anilist_job, query, "MANGA", selected_genres, sort_option, page, None, "NOVEL", "Novel"))
            futures.append(executor.submit(openlib_job, query, None, "Novel"))
        if "Book" in selected_types:
            bg = next((g for g in selected_genres if g in BOOK_GENRES), None)
            futures.append(executor.submit(openlib_job, query, bg, "Book"))

        for future in as_completed(futures):
            try:
                data = future.result()
                if data:
                    all_results.extend(data)
            except Exception as exc:
                logger.warning("Search future failed: %s", exc)

    return all_results

# ============================================================
# SHARED MANAGE WIDGET
# ============================================================
def render_manage_widget(
    item: dict,
    unique_key: str,
    is_read: bool,
    tmdb_id=None,
    show_season_ep: bool = True,
):
    opts    = READ_STATUSES if is_read else WATCH_STATUSES
    curr_st = item.get("Status", opts[0])
    if curr_st not in opts:
        curr_st = opts[0]

    new_status = st.selectbox("Status", opts, index=opts.index(curr_st), key=f"st_{unique_key}")

    new_season, new_ep = 1, 0
    if show_season_ep and item.get("Type") != "Movies":
        try: c_sea = int(item.get("Current_Season", 1))
        except: c_sea = 1
        try: c_ep  = int(item.get("Current_Ep", 0))
        except: c_ep = 0

        sea_lbl = "Vol."   if is_read else "Season"
        ep_lbl  = "Ch."    if is_read else "Episode"
        total   = item.get("Total_Eps", "?")

        if not is_read and tmdb_id:
            si = get_season_details(tmdb_id, c_sea)
            if si:
                total = si["episode_count"]

        c1, c2 = st.columns(2)
        with c1: new_season = st.number_input(sea_lbl, min_value=1, value=c_sea, key=f"s_{unique_key}")
        with c2:
            lbl    = f"{ep_lbl} (/{total})" if str(total) != "?" else ep_lbl
            new_ep = st.number_input(lbl, min_value=0, value=c_ep, key=f"e_{unique_key}")

    # Personal rating
    try:   curr_pr = float(item.get("Personal_Rating") or 0)
    except: curr_pr = 0.0
    personal_rating = st.slider("⭐ My Rating", 0.0, 10.0, curr_pr, 0.5, key=f"pr_{unique_key}")

    # Notes
    notes = st.text_area(
        "📝 Notes / Review",
        value=item.get("Notes", "") or "",
        height=80,
        key=f"notes_{unique_key}",
    )

    c_sv, c_dl = st.columns(2)
    with c_sv:
        if st.button("💾 Save", key=f"sv_{unique_key}"):
            update_status_in_sheet(
                item["Title"], new_status, new_season, new_ep,
                str(personal_rating) if personal_rating else "",
                notes,
            )
            st.rerun()
    with c_dl:
        if st.button("🗑️ Delete", key=f"dl_{unique_key}"):
            delete_from_sheet(item["Title"])
            st.rerun()

# ============================================================
# STATS TAB RENDERER
# ============================================================
def render_stats(df: pd.DataFrame):
    st.subheader("📊 Library Statistics")
    if df.empty:
        st.info("Add some media to see stats!")
        return

    total     = len(df)
    completed = len(df[df["Status"] == "Completed"])
    ongoing   = len(df[df["Status"].isin(["Watching", "Reading"])])
    planned   = len(df[df["Status"].isin(["Plan to Watch", "Plan to Read"])])
    on_hold   = len(df[df["Status"] == "On Hold"])
    dropped   = len(df[df["Status"] == "Dropped"])

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("📚 Total",      total)
    c2.metric("✅ Completed",  completed)
    c3.metric("▶️ Ongoing",    ongoing)
    c4.metric("🔖 Planned",    planned)
    c5.metric("⏸️ On Hold",   on_hold)
    c6.metric("❌ Dropped",    dropped)

    if total:
        st.progress(completed / total, text=f"Completion rate: {completed/total*100:.1f}%")

    st.divider()

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Items by Type**")
        st.bar_chart(df["Type"].value_counts())
    with col_r:
        st.markdown("**Items by Status**")
        st.bar_chart(df["Status"].value_counts())

    st.divider()
    st.markdown("**Top Genres across Library**")
    genre_flat = []
    for g_str in df["Genres"].dropna():
        genre_flat.extend(g.strip() for g in g_str.split(",") if g.strip())
    if genre_flat:
        top15 = pd.Series(dict(Counter(genre_flat).most_common(15)))
        st.bar_chart(top15)

    # Personal ratings distribution
    rated = df[df["Personal_Rating"].astype(str).str.strip().ne("")]
    if not rated.empty:
        st.divider()
        st.markdown("**My Ratings Distribution**")
        try:
            vals = pd.to_numeric(rated["Personal_Rating"], errors="coerce").dropna()
            st.bar_chart(vals.value_counts().sort_index())
        except Exception:
            pass

    st.divider()
    st.markdown("**📤 Export Library**")
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Download CSV",
        data=csv,
        file_name="media_library.csv",
        mime="text/csv",
    )

# ============================================================
# SESSION STATE DEFAULTS
# ============================================================
_DEFAULTS = {
    "search_results":       [],
    "search_page":          1,
    "search_query_trigger": "",
}
for k, v in _DEFAULTS.items():
    st.session_state.setdefault(k, v)

# ============================================================
# NAVIGATION
# ============================================================
tab = st.sidebar.radio(
    "Menu",
    ["🏠 My Gallery", "🔍 Search & Add", "📊 Stats"],
    key="main_nav",
)

# ════════════════════════════════════════════════════════════
# TAB: SEARCH & ADD
# ════════════════════════════════════════════════════════════
if tab == "🔍 Search & Add":
    st.subheader("Global Database Search")

    # Pop trigger (from sequel link or back-nav)
    default_q = ""
    if st.session_state.search_query_trigger:
        default_q = st.session_state.search_query_trigger
        st.session_state.search_query_trigger = ""

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        search_query = st.text_input("Title (Optional)", value=default_q, key="search_box")
    with c2:
        selected_types = st.multiselect("Type", ALL_MEDIA_TYPES, default=["Movies"])
    with c3:
        genres_pool = list(TMDB_GENRE_MAP.keys())
        if any(t in selected_types for t in ("Book", "Novel")):
            genres_pool = sorted(set(genres_pool + BOOK_GENRES))
        selected_genres = st.multiselect("Genre", genres_pool)
    with c4:
        sort_option = st.selectbox("Sort By", ["Popularity", "Relevance", "Top Rated"])

    # FIX: Only trigger on button or sequel link — NOT on every keystroke
    do_search = st.button("🚀 Search / Discover") or bool(default_q)

    if do_search and (search_query or selected_types):
        st.session_state.search_page    = 1
        st.session_state.search_results = []
        with st.spinner("Searching databases in parallel…"):
            st.session_state.search_results = search_unified(
                search_query, selected_types or ["Movies"],
                selected_genres, sort_option, page=1,
            )
        if not st.session_state.search_results:
            st.warning("No results. Try broader filters.")

    if st.session_state.search_results:
        lib_map = get_library_data()
        st.caption(f"Found **{len(st.session_state.search_results)}** results")

        for idx, item in enumerate(st.session_state.search_results):
            with st.container():
                ci, ct = st.columns([1, 6])
                with ci:
                    if item.get("Image"):
                        st.image(item["Image"], use_container_width=True)
                with ct:
                    st.subheader(item["Title"])
                    st.caption(
                        f"**{item['Type']}** | ⭐ {item['Rating']} | 🌍 {item['Country']}"
                    )
                    st.caption(f"🏷️ {item['Genres']}")

                    with st.popover("📜 Overview & Relations"):
                        st.write(item["Overview"])
                        st.divider()

                        # Single AniList call covers both relations & links
                        found_rels = []
                        if item["Type"] in ANILIST_TYPES:
                            a_t = "ANIME" if item["Type"] in {"Anime", "Donghua"} else "MANGA"
                            ad  = fetch_anilist_data_single(item["Title"], a_t, fetch_relations=True)
                            if ad and "relations" in ad:
                                for edge in ad["relations"]["edges"]:
                                    rt = edge["relationType"]
                                    if rt not in {"SEQUEL","PREQUEL","PARENT","SIDE_STORY","ALTERNATIVE"}:
                                        continue
                                    rtitle = (edge["node"]["title"]["english"]
                                              or edge["node"]["title"]["romaji"])
                                    if rtitle:
                                        found_rels.append({
                                            "type": rt.replace("_"," ").title(),
                                            "title": rtitle,
                                        })
                        elif item.get("ID"):
                            m_t = "movie" if item["Type"] == "Movies" else "tv"
                            found_rels = get_tmdb_relations(item["ID"], m_t, item["Title"])

                        if found_rels:
                            st.caption("🔗 **Watch / Read Order:**")
                            for rel in found_rels:
                                lbl  = rel.get("relation", rel.get("type", ""))
                                url  = f"/?search={urllib.parse.quote(rel['title'])}"
                                st.markdown(f"• [{lbl}: {rel['title']}]({url})")

                        if item["Type"] in {"Manga","Manhwa","Manhua","Novel"} and item.get("Links"):
                            st.write("**Official Sources:**")
                            for lnk in item["Links"]:
                                st.link_button(f"🔗 {lnk['site']}", lnk["url"])

                    is_added = item["Title"].strip() in lib_map
                    if is_added:
                        existing = lib_map[item["Title"].strip()]
                        emoji    = STATUS_EMOJI.get(existing.get("Status",""), "")
                        st.success(f"{emoji} In Library — {existing.get('Status','')}")
                        with st.expander("✏️ Update", expanded=False):
                            is_read = item["Type"] in READ_TYPES
                            render_manage_widget(
                                existing, f"sr_{idx}", is_read,
                                show_season_ep=(item["Type"] != "Movies"),
                            )
                    else:
                        if st.button("➕ Add to Library", key=f"add_{idx}"):
                            with st.spinner("Adding…"):
                                if fetch_details_and_add(item):
                                    st.rerun()
            st.divider()

        if st.button("⬇️ Load More Results"):
            st.session_state.search_page += 1
            with st.spinner(f"Loading page {st.session_state.search_page}…"):
                more = search_unified(
                    search_query, selected_types or ["Movies"],
                    selected_genres, sort_option,
                    page=st.session_state.search_page,
                )
                st.session_state.search_results.extend(more)
                st.rerun()

# ════════════════════════════════════════════════════════════
# TAB: MY GALLERY
# ════════════════════════════════════════════════════════════
elif tab == "🏠 My Gallery":
    col_h, col_c = st.columns([3, 1])
    with col_h:
        st.subheader("My Library")
    with col_c:
        try:   def_ix = list(tmdb_countries.keys()).index("India")
        except: def_ix = 0
        stream_country = st.selectbox(
            "Streaming Country", list(tmdb_countries.keys()), index=def_ix
        )
        country_code = tmdb_countries[stream_country]

    sheet = get_google_sheet()
    if not sheet:
        st.error("❌ Google Sheets connection failed. Check credentials.")
        st.stop()

    get_library_data()          # warm session cache
    raw_data = sheet.get_all_values()

    if len(raw_data) <= 1:
        st.info("Library is empty — head to **Search & Add** to get started!")
        st.stop()

    safe_rows = []
    for row in raw_data[1:]:
        if not row or not row[0].strip():
            continue
        if len(row) < len(REQUIRED_HEADERS):
            row += [""] * (len(REQUIRED_HEADERS) - len(row))
        safe_rows.append(row[: len(REQUIRED_HEADERS)])

    df = pd.DataFrame(safe_rows, columns=REQUIRED_HEADERS)

    # ── Recently Added ──────────────────────────────────────
    with st.expander("🆕 Recently Added (last 5)", expanded=False):
        recent = df.tail(5).iloc[::-1]
        r_cols = st.columns(min(len(recent), 5))
        for col, (_, it) in zip(r_cols, recent.iterrows()):
            with col:
                img = it.get("Image", "")
                if img.startswith("http"):
                    st.image(img, use_container_width=True)
                st.caption(f"**{str(it['Title'])[:20]}**")

    # ── Filters ─────────────────────────────────────────────
    with st.expander("🔎 Filter Collection", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        with fc1: filter_text   = st.text_input("Search Title")
        with fc2: filter_type   = st.multiselect("Type",   sorted(df["Type"].unique()))
        with fc3: filter_status = st.multiselect("Status", WATCH_STATUSES + READ_STATUSES)

    if filter_text:   df = df[df["Title"].str.contains(filter_text,  case=False, na=False)]
    if filter_type:   df = df[df["Type"].isin(filter_type)]
    if filter_status: df = df[df["Status"].isin(filter_status)]

    st.caption(f"Showing **{len(df)}** items")
    st.divider()

    # ── Reorder ─────────────────────────────────────────────
    if HAS_SORTABLES and not df.empty:
        with st.expander("🔄 Reorder List", expanded=False):
            st.caption("Drag to reorder, then click Save.")
            titles_orig   = df["Title"].tolist()
            titles_sorted = sort_items(titles_orig, key="sort_all")
            if titles_sorted != titles_orig and st.button("💾 Save Order"):
                tmap = {}
                for i in df.index:
                    tmap.setdefault(df.loc[i, "Title"], []).append(i)
                new_idx = [tmap[t].pop(0) for t in titles_sorted if tmap.get(t)]
                bulk_update_order(df.iloc[new_idx].reset_index(drop=True))

    if df.empty:
        st.info("No items match your filters.")
        st.stop()

    # ── Grid ────────────────────────────────────────────────
    CPR = 5   # cards per row
    for chunk in [df.iloc[i: i + CPR] for i in range(0, len(df), CPR)]:
        cols = st.columns(CPR)
        for col, (index, item) in zip(cols, chunk.iterrows()):
            with col:
                img = item.get("Image", "")
                if not str(img).startswith("http"):
                    img = "https://via.placeholder.com/300x450?text=No+Image"
                st.image(img, use_container_width=True)

                title_short = str(item["Title"])[:22]
                st.markdown(f"**{title_short}**")

                status_e = STATUS_EMOJI.get(item.get("Status", ""), "")
                st.caption(f"{status_e} {item.get('Status', '')}")

                pr = str(item.get("Personal_Rating", "")).strip()
                if pr and pr not in ("0", "0.0", ""):
                    st.caption(f"⭐ My: {pr}/10")

                prog = calc_progress(item.get("Current_Ep", 0), item.get("Total_Eps", "?"))
                render_progress_bar(prog)

                u_key = f"gal_{index}"

                # ── Overview popover ─────────────────────────
                with st.popover("📜"):
                    tmdb_id = item.get("ID") or None
                    m_type  = "movie" if item["Type"] == "Movies" else "tv"

                    if not tmdb_id and item["Type"] in TMDB_LIVE_TYPES:
                        tmdb_id = recover_tmdb_id(item["Title"], m_type)

                    found_rels  = []
                    trailer_url = None

                    if item["Type"] in ANILIST_TYPES:
                        a_type = "ANIME" if item["Type"] in {"Anime", "Donghua"} else "MANGA"
                        # ONE call — covers both relations and trailer (was 2 calls before)
                        ad = fetch_anilist_data_single(item["Title"], a_type, fetch_relations=True)
                        if ad:
                            if "relations" in ad:
                                for edge in ad["relations"]["edges"]:
                                    rt = edge["relationType"]
                                    if rt not in {"SEQUEL","PREQUEL","PARENT","SIDE_STORY","ALTERNATIVE"}:
                                        continue
                                    rtitle = (edge["node"]["title"]["english"]
                                              or edge["node"]["title"]["romaji"])
                                    if rtitle:
                                        found_rels.append({
                                            "type": rt.replace("_"," ").title(),
                                            "title": rtitle,
                                        })
                            t_data = ad.get("trailer")
                            if t_data and t_data.get("site") == "youtube":
                                trailer_url = f"https://www.youtube.com/watch?v={t_data['id']}"
                    elif tmdb_id:
                        found_rels  = get_tmdb_relations(tmdb_id, m_type, item["Title"])
                        trailer_url = get_tmdb_trailer(tmdb_id, m_type)

                    st.markdown(f"**{item['Title']}**")
                    st.caption(f"{item['Type']} | ⭐ TMDB: {item['Rating']}")
                    if pr and pr not in ("0","0.0",""):
                        st.caption(f"My Rating: ⭐ {pr}/10")
                    notes_val = str(item.get("Notes","") or "").strip()
                    if notes_val:
                        st.info(f"📝 {notes_val}")
                    st.caption(item.get("Overview",""))

                    if found_rels:
                        st.divider()
                        st.caption("🔗 **Watch / Read Order:**")
                        for rel in found_rels:
                            lbl = rel.get("relation", rel.get("type",""))
                            url = f"/?search={urllib.parse.quote(rel['title'])}"
                            st.markdown(f"• [{lbl}: {rel['title']}]({url})")

                    if trailer_url:
                        st.divider()
                        st.caption("🎬 Trailer")
                        st.video(trailer_url)

                    st.divider()
                    is_book  = item["Type"] in {"Book", "Novel"}
                    is_comic = item["Type"] in {"Manga", "Manhwa", "Manhua"}

                    if is_book:
                        st.link_button(
                            "📘 Google Books",
                            f"https://www.google.com/search?tbm=bks&q={item['Title']}",
                        )
                    elif is_comic:
                        st.link_button(
                            "📖 Read Online",
                            f"https://www.google.com/search?q=read+{urllib.parse.quote(item['Title'])}+online",
                        )
                        live = fetch_anilist_data_single(item["Title"], "MANGA")
                        if live and live.get("externalLinks"):
                            for lnk in live["externalLinks"]:
                                st.link_button(f"🔗 {lnk['site']}", lnk["url"])
                    else:
                        if item["Type"] == "Anime":
                            st.link_button(
                                "🟠 Crunchyroll",
                                f"https://www.crunchyroll.com/search?q={item['Title']}",
                            )
                        elif item["Type"] in {"K-Drama","C-Drama","Thai Drama"}:
                            st.link_button(
                                "💙 Viki",
                                f"https://www.viki.com/search?q={urllib.parse.quote(item['Title'])}",
                            )
                        provs = get_streaming_info(tmdb_id, m_type, country_code)
                        if provs:
                            for cat, label in [("flatrate","Streaming"),("rent","Rent"),("buy","Buy")]:
                                if cat in provs:
                                    st.caption(f"**{label}:**")
                                    for p in provs[cat]:
                                        lnk = get_provider_link(p["provider_name"], item["Title"])
                                        st.markdown(f"- [{p['provider_name']}]({lnk})")
                        else:
                            st.caption("No official streams found for this country.")

                # ── Manage expander ──────────────────────────
                with st.expander("⚙️ Manage"):
                    is_read = item["Type"] in READ_TYPES
                    render_manage_widget(
                        item.to_dict(), u_key, is_read,
                        tmdb_id=tmdb_id if item["Type"] in TMDB_LIVE_TYPES else None,
                        show_season_ep=(item["Type"] != "Movies"),
                    )

# ════════════════════════════════════════════════════════════
# TAB: STATS
# ════════════════════════════════════════════════════════════
elif tab == "📊 Stats":
    sheet = get_google_sheet()
    if not sheet:
        st.error("❌ Connection failed.")
        st.stop()

    raw = sheet.get_all_values()
    if len(raw) <= 1:
        st.info("Library is empty — nothing to analyse yet.")
        st.stop()

    safe = []
    for row in raw[1:]:
        if not row or not row[0].strip(): continue
        if len(row) < len(REQUIRED_HEADERS):
            row += [""] * (len(REQUIRED_HEADERS) - len(row))
        safe.append(row[: len(REQUIRED_HEADERS)])

    render_stats(pd.DataFrame(safe, columns=REQUIRED_HEADERS))
