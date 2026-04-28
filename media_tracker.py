import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import gspread
import gspread.utils
import pandas as pd
import requests
import requests.adapters
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials
from tmdbv3api import TMDb, Movie, TV, Search, Discover, Collection

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Ultimate Media Tracker", layout="wide", page_icon="🎬")

st.markdown("""
<style>
/* ═══════════════════════════════════════════
   BASE & BACKGROUND
═══════════════════════════════════════════ */
.stAppDeployButton, header, #MainMenu { display: none !important; visibility: hidden !important; }

[data-testid="stAppViewContainer"] {
    background: #0d0d14;
    color: #e8e8f0;
}
[data-testid="stSidebar"] { background: #0d0d14; }
[data-testid="block-container"] {
    padding-top: 1.5rem;
    padding-bottom: 3rem;
    max-width: 1400px;
}

/* ═══════════════════════════════════════════
   TYPOGRAPHY
═══════════════════════════════════════════ */
html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    color: #e8e8f0;
}
h1, h2, h3 { letter-spacing: -0.02em; }

/* App title */
[data-testid="stMarkdownContainer"] h1 {
    font-size: 2rem;
    font-weight: 800;
    background: linear-gradient(135deg, #e8e8f0 30%, #a78bfa 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0;
}

/* ═══════════════════════════════════════════
   NAV RADIO (tab switcher)
═══════════════════════════════════════════ */
[data-testid="stHorizontalBlock"]:has([data-testid="stRadio"]) {
    background: #16161f;
    border: 1px solid #2a2a3a;
    border-radius: 14px;
    padding: 6px;
    display: inline-flex;
    gap: 4px;
    margin-bottom: 0.5rem;
}
[data-testid="stRadio"] > div {
    display: flex;
    gap: 4px;
    flex-direction: row !important;
}
[data-testid="stRadio"] label {
    padding: 8px 22px !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    color: #888 !important;
    cursor: pointer;
    transition: all 0.2s ease;
    border: none !important;
    background: transparent !important;
}
[data-testid="stRadio"] label:has(input:checked) {
    background: linear-gradient(135deg, #7c3aed, #a78bfa) !important;
    color: #fff !important;
    box-shadow: 0 4px 15px rgba(124,58,237,0.4);
}

/* ═══════════════════════════════════════════
   INPUTS & CONTROLS
═══════════════════════════════════════════ */
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] > div > div,
[data-baseweb="select"] > div {
    background: #1a1a28 !important;
    border: 1px solid #2e2e45 !important;
    border-radius: 10px !important;
    color: #e8e8f0 !important;
    transition: border-color 0.2s;
}
[data-testid="stTextInput"] input:focus,
[data-baseweb="select"] > div:focus-within {
    border-color: #7c3aed !important;
    box-shadow: 0 0 0 3px rgba(124,58,237,0.15) !important;
}
[data-testid="stMultiSelect"] [data-baseweb="tag"] {
    background: #7c3aed !important;
    border-radius: 6px !important;
    font-size: 0.78rem !important;
}

/* ═══════════════════════════════════════════
   BUTTONS
═══════════════════════════════════════════ */
[data-testid="stButton"] > button {
    background: linear-gradient(135deg, #7c3aed, #a855f7) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    padding: 0.45rem 1.1rem !important;
    transition: all 0.2s ease !important;
    box-shadow: 0 4px 12px rgba(124,58,237,0.25) !important;
}
[data-testid="stButton"] > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 20px rgba(124,58,237,0.4) !important;
}
[data-testid="stButton"] > button:active {
    transform: translateY(0) !important;
}
/* Danger (Delete) button — second button in a 2-col layout */
[data-testid="stButton"]:last-child > button {
    background: linear-gradient(135deg, #7f1d1d, #dc2626) !important;
    box-shadow: 0 4px 12px rgba(220,38,38,0.25) !important;
}
[data-testid="stButton"]:last-child > button:hover {
    box-shadow: 0 8px 20px rgba(220,38,38,0.4) !important;
}

/* Link buttons */
[data-testid="stLinkButton"] > a {
    background: #1e1e2e !important;
    border: 1px solid #3b3b55 !important;
    border-radius: 9px !important;
    color: #a78bfa !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
}
[data-testid="stLinkButton"] > a:hover {
    background: #2a2a3f !important;
    border-color: #7c3aed !important;
    transform: translateY(-1px) !important;
}

/* Download button */
[data-testid="stDownloadButton"] > button {
    background: #1e1e2e !important;
    border: 1px solid #3b3b55 !important;
    color: #a78bfa !important;
    box-shadow: none !important;
}
[data-testid="stDownloadButton"] > button:hover {
    border-color: #7c3aed !important;
    background: #252535 !important;
}

/* ═══════════════════════════════════════════
   EXPANDERS
═══════════════════════════════════════════ */
[data-testid="stExpander"] {
    background: #13131e !important;
    border: 1px solid #22223a !important;
    border-radius: 14px !important;
    overflow: hidden;
    margin-bottom: 0.75rem;
}
[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    color: #c4c4d8 !important;
    padding: 0.75rem 1rem !important;
}
[data-testid="stExpander"] summary:hover {
    color: #e8e8f0 !important;
}
[data-testid="stExpander"] > div > div {
    padding: 0 1rem 1rem 1rem !important;
}

/* ═══════════════════════════════════════════
   GALLERY CARDS
   Wrap each image in a hover-lift card
═══════════════════════════════════════════ */
[data-testid="stImage"] {
    border-radius: 12px !important;
    overflow: hidden !important;
    transition: transform 0.25s ease, box-shadow 0.25s ease !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5) !important;
    display: block !important;
}
[data-testid="stImage"]:hover {
    transform: translateY(-4px) scale(1.02) !important;
    box-shadow: 0 12px 35px rgba(124,58,237,0.3) !important;
}
[data-testid="stImage"] img {
    border-radius: 12px !important;
    object-fit: cover !important;
}

/* ═══════════════════════════════════════════
   POPOVERS
═══════════════════════════════════════════ */
[data-testid="stPopover"] > button {
    background: #1a1a2a !important;
    border: 1px solid #2e2e45 !important;
    border-radius: 9px !important;
    color: #a78bfa !important;
    font-size: 0.82rem !important;
    padding: 0.35rem 0.8rem !important;
    font-weight: 500 !important;
    width: 100% !important;
    transition: all 0.2s !important;
}
[data-testid="stPopover"] > button:hover {
    border-color: #7c3aed !important;
    background: #22223a !important;
}
[data-testid="stPopover"] > div {
    background: #16161f !important;
    border: 1px solid #2e2e45 !important;
    border-radius: 14px !important;
    box-shadow: 0 20px 60px rgba(0,0,0,0.7) !important;
    padding: 1rem !important;
}

/* ═══════════════════════════════════════════
   ALERTS / TOASTS
═══════════════════════════════════════════ */
[data-testid="stSuccess"] {
    background: #0d2218 !important;
    border: 1px solid #166534 !important;
    border-radius: 10px !important;
    color: #4ade80 !important;
}
[data-testid="stInfo"] {
    background: #0f1a2e !important;
    border: 1px solid #1e3a5f !important;
    border-radius: 10px !important;
    color: #60a5fa !important;
}
[data-testid="stWarning"] {
    background: #1c1507 !important;
    border: 1px solid #92400e !important;
    border-radius: 10px !important;
}
[data-testid="stError"] {
    background: #1c0a0a !important;
    border: 1px solid #7f1d1d !important;
    border-radius: 10px !important;
}

/* ═══════════════════════════════════════════
   SLIDERS & NUMBER INPUTS
═══════════════════════════════════════════ */
[data-testid="stSlider"] > div > div > div {
    background: #7c3aed !important;
}
[data-testid="stNumberInput"] input {
    background: #1a1a28 !important;
    border: 1px solid #2e2e45 !important;
    border-radius: 8px !important;
    color: #e8e8f0 !important;
}

/* ═══════════════════════════════════════════
   CHECKBOX & SELECTBOX
═══════════════════════════════════════════ */
[data-testid="stCheckbox"] label {
    color: #c4c4d8 !important;
    font-size: 0.88rem !important;
}
[data-testid="stCheckbox"] input:checked + div {
    background: #7c3aed !important;
    border-color: #7c3aed !important;
}

/* ═══════════════════════════════════════════
   TEXT AREA
═══════════════════════════════════════════ */
[data-testid="stTextArea"] textarea {
    background: #1a1a28 !important;
    border: 1px solid #2e2e45 !important;
    border-radius: 10px !important;
    color: #e8e8f0 !important;
    font-size: 0.85rem !important;
}
[data-testid="stTextArea"] textarea:focus {
    border-color: #7c3aed !important;
    box-shadow: 0 0 0 3px rgba(124,58,237,0.15) !important;
}

/* ═══════════════════════════════════════════
   DIVIDERS
═══════════════════════════════════════════ */
hr {
    border: none !important;
    border-top: 1px solid #1e1e2e !important;
    margin: 1rem 0 !important;
}

/* ═══════════════════════════════════════════
   SCROLLBAR
═══════════════════════════════════════════ */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0d0d14; }
::-webkit-scrollbar-thumb { background: #2e2e45; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #7c3aed; }

/* ═══════════════════════════════════════════
   CAPTION & SMALL TEXT
═══════════════════════════════════════════ */
[data-testid="stCaptionContainer"] {
    color: #888 !important;
    font-size: 0.78rem !important;
}
small, .small { color: #888 !important; }

/* ═══════════════════════════════════════════
   SEARCH RESULT ROWS
═══════════════════════════════════════════ */
[data-testid="stHorizontalBlock"] {
    gap: 1rem;
}

/* Currently Active strip - images should be tighter */
.active-strip [data-testid="stImage"] {
    border-radius: 10px !important;
}
</style>
""", unsafe_allow_html=True)

if "search" in st.query_params:
    st.session_state.search_query_trigger = st.query_params["search"]
    st.query_params.clear()

st.markdown("# 🎬 Ultimate Media Tracker")

try:
    from streamlit_sortables import sort_items
    HAS_SORTABLES = True
except ImportError:
    HAS_SORTABLES = False

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────
try:
    TMDB_API_KEY = st.secrets["tmdb_api_key"]
except Exception:
    st.error("Secrets not found. Please set up .streamlit/secrets.toml")
    st.stop()

GOOGLE_SHEET_NAME = "My Media Tracker"
PLACEHOLDER_IMG = "https://placehold.co/300x450/1a1a2e/ffffff?text=No+Image"

tmdb = TMDb()
tmdb.api_key = TMDB_API_KEY
tmdb.language = "en"
tmdb_poster_base = "https://image.tmdb.org/t/p/w400"
tmdb_backdrop_base = "https://image.tmdb.org/t/p/w780"

TMDB_GENRE_MAP = {
    "Action": 28, "Adventure": 12, "Animation": 16, "Comedy": 35,
    "Crime": 80, "Documentary": 99, "Drama": 18, "Family": 10751,
    "Fantasy": 14, "History": 36, "Horror": 27, "Music": 10402,
    "Mystery": 9648, "Romance": 10749, "Sci-Fi": 878, "TV Movie": 10770,
    "Thriller": 53, "War": 10752, "Western": 37,
    "Action & Adventure": 10759, "Sci-Fi & Fantasy": 10765, "War & Politics": 10768,
}
ID_TO_GENRE = {v: k for k, v in TMDB_GENRE_MAP.items()}

BOOK_GENRES = [
    "Web Novel", "Fiction", "Fantasy", "Sci-Fi", "Mystery", "Thriller", "Romance",
    "History", "Biography", "Business", "Self-Help", "Psychology",
    "Philosophy", "Science", "Technology", "Manga", "Light Novel", "Computers",
    "Horror", "Poetry", "Comics", "Art", "Cooking",
]

REQUIRED_HEADERS = [
    "Title", "Type", "Country", "Status", "Genres", "Image", "Overview", "Rating", "Backdrop",
    "Current_Season", "Current_Ep", "Total_Eps", "Total_Seasons", "ID",
    "Notes", "Personal_Rating", "Date_Added", "Favorite",
]
COL = {h: i + 1 for i, h in enumerate(REQUIRED_HEADERS)}  # header -> 1-based column index

# ─────────────────────────────────────────────────────────────
# PERFORMANCE: Persistent HTTP session with connection pooling.
# Reuses TCP connections across all requests.get/post calls.
# New connections: O(1) amortized vs O(N) cold-connect per call.
# ─────────────────────────────────────────────────────────────
_http = requests.Session()
_adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=1)
_http.mount("https://", _adapter)
_http.mount("http://", _adapter)


# ─────────────────────────────────────────────────────────────
# COUNTRIES
# ─────────────────────────────────────────────────────────────
@st.cache_data
def get_tmdb_countries():
    try:
        resp = _http.get(
            f"https://api.themoviedb.org/3/configuration/countries?api_key={TMDB_API_KEY}", timeout=10
        ).json()
        return dict(sorted({c["english_name"]: c["iso_3166_1"] for c in resp}.items()))
    except Exception:
        return {"United States": "US", "India": "IN", "United Kingdom": "GB"}


tmdb_countries = get_tmdb_countries()


# ─────────────────────────────────────────────────────────────
# GOOGLE SHEETS — worksheet object cached at process level.
# client.open().sheet1 is expensive (~500ms). With @cache_resource
# it runs once per server process and is reused for all sessions.
# ─────────────────────────────────────────────────────────────
@st.cache_resource(ttl=600)
def _get_worksheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(
                dict(st.secrets["gcp_service_account"]), scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        return client.open(GOOGLE_SHEET_NAME).sheet1
    except Exception as e:
        st.error(f"Google Sheets auth error: {e}")
        return None


def get_google_sheet():
    return _get_worksheet()


def _ensure_headers(sheet):
    """Run once per session — verifies/adds missing columns without re-reading on every call."""
    if st.session_state.get("_headers_ok"):
        return
    try:
        existing = sheet.row_values(1)
        missing = [h for h in REQUIRED_HEADERS if h not in existing]
        if not existing:
            sheet.resize(cols=len(REQUIRED_HEADERS))
            sheet.append_row(REQUIRED_HEADERS)
        elif missing:
            new_col_count = len(existing) + len(missing)
            sheet.resize(cols=new_col_count)  # expand grid BEFORE writing
            updates = []
            for h in missing:
                col_pos = len(existing) + 1
                updates.append({
                    "range": gspread.utils.rowcol_to_a1(1, col_pos),
                    "values": [[h]]
                })
                existing.append(h)
            if updates:
                sheet.batch_update(updates)
        st.session_state["_headers_ok"] = True
    except Exception as e:
        st.warning(f"Header check warning: {e}")


# ─────────────────────────────────────────────────────────────
# SINGLE DATA READ — the core performance optimization.
#
# BEFORE (3 full reads per library page load):
#   1. get_google_sheet() -> get_all_values()  [header check]  ~400ms
#   2. get_library_data() -> get_all_records()                 ~400ms
#   3. library tab        -> get_all_values()                  ~400ms
#   Total: ~1200ms of sheet I/O per page load
#
# AFTER (1 read ever, 0ms on subsequent interactions):
#   _get_sheet_data() -> session_state cache miss -> 1 read    ~400ms
#   All subsequent calls hit session_state: 0ms
#
# Also stores row_map {title.lower(): row_number} so save/delete
# skip sheet.find() (O(n) scan) and use O(1) dict lookup instead.
# ─────────────────────────────────────────────────────────────
def _get_sheet_data():
    if "sheet_cache" in st.session_state:
        return st.session_state.sheet_cache

    sheet = get_google_sheet()
    _EMPTY = {"df": pd.DataFrame(columns=REQUIRED_HEADERS), "lib_map": {}, "row_map": {}}
    if not sheet:
        st.session_state.sheet_cache = _EMPTY
        return _EMPTY

    _ensure_headers(sheet)

    try:
        raw = sheet.get_all_values()  # THE ONE AND ONLY sheet read per session
    except Exception as e:
        st.error(f"Sheet read error: {e}")
        st.session_state.sheet_cache = _EMPTY
        return _EMPTY

    if len(raw) < 2:
        st.session_state.sheet_cache = _EMPTY
        return _EMPTY

    header_row = raw[0]
    h_idx = {h: i for i, h in enumerate(header_row)}

    safe_rows, lib_map, row_map = [], {}, {}
    for sheet_row_num, row in enumerate(raw[1:], start=2):
        if not row or not row[0].strip():
            continue
        if len(row) < len(REQUIRED_HEADERS):
            row = row + [""] * (len(REQUIRED_HEADERS) - len(row))
        row = row[:len(REQUIRED_HEADERS)]
        safe_rows.append(row)

        item = {h: (row[h_idx[h]] if h in h_idx and h_idx[h] < len(row) else "") for h in REQUIRED_HEADERS}
        key = item["Title"].strip().lower()
        if key:
            lib_map[key] = item
            row_map[key] = sheet_row_num  # direct row number, no scan needed for save/delete

    df = pd.DataFrame(safe_rows, columns=REQUIRED_HEADERS) if safe_rows else pd.DataFrame(columns=REQUIRED_HEADERS)
    result = {"df": df, "lib_map": lib_map, "row_map": row_map}
    st.session_state.sheet_cache = result
    return result


def _invalidate_cache():
    st.session_state.pop("sheet_cache", None)


def get_library_data():
    return _get_sheet_data()["lib_map"]

def get_row_map():
    return _get_sheet_data()["row_map"]

def refresh_library():
    _invalidate_cache()
    _get_sheet_data()

def is_in_library(title):
    return title.strip().lower() in get_library_data()

def get_from_library(title):
    return get_library_data().get(title.strip().lower())


# ─────────────────────────────────────────────────────────────
# DATABASE ACTIONS
# ─────────────────────────────────────────────────────────────
def fetch_details_and_add(item):
    sheet = get_google_sheet()
    if not sheet:
        return False
    if is_in_library(item["Title"]):
        st.toast(f"'{item['Title']}' is already in your library!")
        return True

    total_seasons, total_eps = 1, item.get("Total_Eps", "?")
    media_id = item.get("ID")

    if item.get("Type") in ["Web Series", "K-Drama", "C-Drama", "Thai Drama", "Vertical Drama"] and media_id:
        try:
            details = TV().details(media_id)
            total_seasons = getattr(details, "number_of_seasons", 1)
            total_eps = getattr(details, "number_of_episodes", "?")
        except Exception:
            pass

    default_status = ("Plan to Read" if item.get("Type") in ["Manga","Manhwa","Manhua","Book","Novel"]
                      else "Plan to Watch")

    try:
        row_data = [
            item.get("Title",""), item.get("Type",""), item.get("Country",""),
            default_status, item.get("Genres",""), item.get("Image",""),
            item.get("Overview",""), item.get("Rating",""), item.get("Backdrop",""),
            1, 0, total_eps, total_seasons, media_id,
            "", "", date.today().isoformat(), "No",
        ]
        sheet.append_row(row_data, value_input_option="USER_ENTERED")
        st.toast(f"Added: {item.get('Title','')}")
        _invalidate_cache()
        return True
    except Exception as e:
        st.error(f"Error adding item: {e}")
        return False


def update_status_in_sheet(title, new_status, new_season, new_ep,
                           notes=None, personal_rating=None, favorite=None):
    """
    OPTIMIZED SAVE:
    Before: get_all_values (header check) + sheet.find() + 6x update_cell() = ~2500ms
    After:  row_map lookup (0ms) + 1x batch_update() = ~300ms  →  ~8x faster
    """
    sheet = get_google_sheet()
    if not sheet:
        return

    key = title.strip().lower()
    row_num = get_row_map().get(key)
    if not row_num:
        st.error(f"'{title}' not found in sheet.")
        return

    try:
        def cell(r, c):
            return gspread.utils.rowcol_to_a1(r, c)

        updates = [
            {"range": cell(row_num, COL["Status"]),         "values": [[new_status]]},
            {"range": cell(row_num, COL["Current_Season"]), "values": [[new_season]]},
            {"range": cell(row_num, COL["Current_Ep"]),     "values": [[new_ep]]},
        ]
        if notes is not None:
            updates.append({"range": cell(row_num, COL["Notes"]),           "values": [[notes]]})
        if personal_rating is not None:
            updates.append({"range": cell(row_num, COL["Personal_Rating"]), "values": [[personal_rating]]})
        if favorite is not None:
            updates.append({"range": cell(row_num, COL["Favorite"]),        "values": [[favorite]]})

        sheet.batch_update(updates)  # single API call
        st.toast(f"Saved: {title}")

        # Patch local cache without a re-read
        lib = get_library_data()
        if key in lib:
            lib[key].update({"Status": new_status, "Current_Season": new_season, "Current_Ep": new_ep})
            if notes is not None:           lib[key]["Notes"] = notes
            if personal_rating is not None: lib[key]["Personal_Rating"] = personal_rating
            if favorite is not None:        lib[key]["Favorite"] = favorite

        cache = st.session_state.get("sheet_cache", {})
        df = cache.get("df")
        if df is not None and not df.empty:
            mask = df["Title"].str.strip().str.lower() == key
            if mask.any():
                df.loc[mask, "Status"] = new_status
                df.loc[mask, "Current_Season"] = str(new_season)
                df.loc[mask, "Current_Ep"] = str(new_ep)
                if notes is not None:           df.loc[mask, "Notes"] = notes
                if personal_rating is not None: df.loc[mask, "Personal_Rating"] = str(personal_rating)
                if favorite is not None:        df.loc[mask, "Favorite"] = favorite

    except Exception as e:
        st.error(f"Save error: {e}")


def delete_from_sheet(title):
    """OPTIMIZED: O(1) row lookup via row_map, no sheet.find() scan."""
    sheet = get_google_sheet()
    if not sheet:
        return
    key = title.strip().lower()
    row_num = get_row_map().get(key)
    if not row_num:
        return
    try:
        sheet.delete_rows(row_num)
        st.toast(f"Deleted: {title}")
        _invalidate_cache()
    except Exception as e:
        st.error(f"Delete error: {e}")


def bulk_update_order(new_df):
    sheet = get_google_sheet()
    if not sheet:
        return
    try:
        sheet.update("A1", [REQUIRED_HEADERS] + new_df.astype(str).values.tolist())
        st.toast("Order Saved!")
        _invalidate_cache()
        time.sleep(0.3)
        st.rerun()
    except Exception as e:
        st.error(f"Order save error: {e}")


# ─────────────────────────────────────────────────────────────
# HELPERS — all cached, all use pooled _http session
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400)
def recover_tmdb_id(title, media_type):
    try:
        s = Search()
        results = s.movies(title) if media_type == "movie" else s.tv_shows(title)
        if results:
            return results[0].id
    except Exception:
        pass
    return None


def get_provider_link(provider_name, title):
    q, p = urllib.parse.quote(title), provider_name.lower()
    if "netflix" in p:              return f"https://www.netflix.com/search?q={q}"
    if "amazon" in p or "prime" in p: return f"https://www.amazon.com/s?k={q}&i=instant-video"
    if "youtube" in p:              return f"https://www.youtube.com/results?search_query={q}"
    if "disney" in p:               return f"https://www.disneyplus.com/search/{q}"
    if "apple" in p:                return f"https://tv.apple.com/search?term={q}"
    if "hulu" in p:                 return f"https://www.hulu.com/search?q={q}"
    return f"https://www.google.com/search?q=watch+{q}+on+{urllib.parse.quote(provider_name)}"


@st.cache_data(ttl=3600)
def get_streaming_info(tmdb_id, media_type, country_code):
    if not tmdb_id:
        return None
    try:
        clean_id = int(float(tmdb_id))
        r = _http.get(
            f"https://api.themoviedb.org/3/{media_type}/{clean_id}/watch/providers?api_key={TMDB_API_KEY}",
            timeout=8)
        data = r.json()
        if "results" in data and country_code in data["results"]:
            return data["results"][country_code]
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600)
def get_tmdb_trailer(tmdb_id, media_type):
    if not tmdb_id:
        return None
    try:
        clean_id = int(float(tmdb_id))
        r = _http.get(
            f"https://api.themoviedb.org/3/{media_type}/{clean_id}/videos?api_key={TMDB_API_KEY}",
            timeout=8)
        data = r.json()
        if "results" in data:
            for priority in ["Trailer", "Teaser", None]:
                for vid in data["results"]:
                    if vid["site"] == "YouTube" and (priority is None or vid["type"] == priority):
                        return f"https://www.youtube.com/watch?v={vid['key']}"
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600)
def get_tmdb_relations(tmdb_id, media_type, current_title):
    if not tmdb_id:
        return []
    relations = []
    try:
        clean_id = int(float(tmdb_id))
        if media_type == "movie":
            details = Movie().details(clean_id)
            if getattr(details, "belongs_to_collection", None):
                col_data = details.belongs_to_collection
                if "id" in col_data:
                    parts = sorted(
                        getattr(Collection().details(col_data["id"]), "parts", []),
                        key=lambda x: x.get("release_date", "9999"))
                    for p in parts:
                        if p["id"] != clean_id:
                            relations.append({"title": p["title"], "type": "Movie", "relation": "Part of Series"})
        elif media_type == "tv":
            r = _http.get(
                f"https://api.themoviedb.org/3/tv/{clean_id}/recommendations?api_key={TMDB_API_KEY}&language=en-US&page=1",
                timeout=8)
            if r.status_code == 200:
                base_title = current_title.split(":")[0].split("Season")[0].strip().lower()
                for rec in r.json().get("results", [])[:6]:
                    name = rec["name"]
                    if base_title in name.lower() or "Season" in name:
                        relations.append({"title": name, "type": "TV", "relation": "Sequel/Related"})
    except Exception:
        pass
    return relations


@st.cache_data(ttl=3600)
def get_season_details(tmdb_id, season_num):
    if not tmdb_id:
        return None
    try:
        clean_id = int(float(tmdb_id))
        r = _http.get(
            f"https://api.themoviedb.org/3/tv/{clean_id}/season/{season_num}?api_key={TMDB_API_KEY}",
            timeout=8)
        if r.status_code == 200:
            data = r.json()
            return {"episode_count": len(data.get("episodes", [])), "name": data.get("name")}
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600)
def fetch_anilist_data_single(title, media_type, format_in=None, fetch_relations=False):
    relation_block = """
    relations { edges { relationType node { title { romaji english } type } } }
    """ if fetch_relations else ""

    query = f"""
    query ($s: String, $t: MediaType, $f: MediaFormat) {{
        Page(perPage: 1) {{
            media(search: $s, type: $t, format: $f) {{
                id trailer {{ id site }} externalLinks {{ site url }}
                episodes chapters volumes {relation_block}
            }}
        }}
    }}"""
    variables = {"s": title, "t": media_type}
    if format_in:
        variables["f"] = format_in
    try:
        r = _http.post("https://graphql.anilist.co",
                       json={"query": query, "variables": variables}, timeout=10)
        media = r.json()["data"]["Page"]["media"]
        if media:
            return media[0]
    except Exception:
        pass
    return {}


@st.cache_data(ttl=3600)
def fetch_anilist_list_raw(query, type_, genres, sort_opt, page, country=None, fmt=None):
    anilist_sort = ("SCORE_DESC" if sort_opt == "Top Rated"
                    else "SEARCH_MATCH" if sort_opt == "Relevance" and query
                    else "POPULARITY_DESC")
    variables = {"t": type_, "p": page, "sort": [anilist_sort]}
    q_args = ["$p: Int", "$t: MediaType", "$sort: [MediaSort]"]
    m_args = ["type: $t", "sort: $sort"]

    if query:   q_args.append("$s: String");      m_args.append("search: $s");            variables["s"] = query
    if genres:  q_args.append("$g: [String]");    m_args.append("genre_in: $g");          variables["g"] = genres
    if country: q_args.append("$c: CountryCode"); m_args.append("countryOfOrigin: $c");   variables["c"] = country
    if fmt:     q_args.append("$f: MediaFormat"); m_args.append("format: $f");            variables["f"] = fmt

    query_str = f"""query ({', '.join(q_args)}) {{
      Page(page: $p, perPage: 15) {{
        media({', '.join(m_args)}) {{
          title {{ romaji english }} coverImage {{ large }} bannerImage genres
          countryOfOrigin type format description averageScore episodes chapters volumes
          externalLinks {{ site url }}
        }}
      }}
    }}"""
    try:
        r = _http.post("https://graphql.anilist.co",
                       json={"query": query_str, "variables": variables}, timeout=10)
        if r.status_code == 200:
            return r.json()["data"]["Page"]["media"]
    except Exception:
        pass
    return []


@st.cache_data(ttl=3600)
def fetch_open_library_raw(query, genre=None):
    params = {"limit": 15}
    if query:
        params["q"] = query + (f" subject:{genre}" if genre and genre != "Web Novel" else "")
    elif genre:
        params["subject"] = genre
    else:
        params["subject"] = "fiction"
    try:
        r = _http.get("https://openlibrary.org/search.json", params=params,
                      headers={"User-Agent": "MediaTrackerApp/1.0"}, timeout=10)
        if r.status_code == 200:
            return r.json().get("docs", [])
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────────
# RESULT PROCESSORS
# ─────────────────────────────────────────────────────────────
def process_open_library(items, detected_type):
    results = []
    for item in items:
        cover_id = item.get("cover_i")
        img_url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else PLACEHOLDER_IMG
        title = item.get("title", "Unknown")
        authors = ", ".join(item.get("author_name", [])[:2])
        if authors:
            title += f" - {authors}"
        desc = f"First published {item.get('first_publish_year', 'Unknown')}."
        if item.get("first_sentence"):
            desc = f"\"{item['first_sentence'][0]}\" — " + desc
        results.append({
            "Title": title, "Type": detected_type, "Country": "International",
            "Genres": ", ".join(item.get("subject", [])[:3]), "Image": img_url,
            "Overview": desc, "Rating": f"{round(item.get('ratings_average', 0), 1)}/5",
            "Backdrop": "", "Total_Eps": str(item.get("number_of_pages_median", "?")),
            "ID": item.get("key"), "Source": "OpenLibrary", "Links": [],
        })
    return results


def process_anilist_results(res_list, forced_type, selected_genres):
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
        clean = re.sub("<[^<]+?>", "", res.get("description", "") or "") or "No description."
        total = res.get("episodes") or res.get("chapters") or res.get("volumes") or "?"
        avg = res.get("averageScore")
        results.append({
            "Title": res["title"]["english"] or res["title"]["romaji"],
            "Type": forced_type, "Country": origin, "Genres": ", ".join(res_genres),
            "Image": res.get("coverImage", {}).get("large", ""),
            "Overview": clean, "Rating": f"{avg/10:.1f}/10" if avg else "?/10",
            "Backdrop": res.get("bannerImage", ""), "Total_Eps": total,
            "ID": None, "Links": res.get("externalLinks", []),
        })
    return results


def process_tmdb_results_batch(results, media_kind, specific_type, selected_types, selected_genres, query):
    processed = []
    for r in results:
        lang = getattr(r, "original_language", "en")
        match = True
        if not query:
            if   specific_type == "K-Drama"       and lang != "ko": match = False
            elif specific_type == "C-Drama"       and lang != "zh": match = False
            elif specific_type == "Thai Drama"    and lang != "th": match = False
            elif specific_type == "Vertical Drama" and lang != "zh": match = False
        genre_ids  = getattr(r, "genre_ids", [])
        res_genres = [ID_TO_GENRE.get(gid, "Unknown") for gid in genre_ids]
        if selected_genres and not any(g in res_genres for g in selected_genres):
            match = False
        if match:
            if   media_kind == "Movie": detected_type = "Movies"
            elif lang == "ko":          detected_type = "K-Drama"
            elif lang == "zh":          detected_type = "Vertical Drama" if specific_type == "Vertical Drama" else "C-Drama"
            elif lang == "th":          detected_type = "Thai Drama"
            elif lang == "ja":          detected_type = "Anime"
            else:                       detected_type = "Web Series"
            if detected_type not in selected_types:
                continue
            poster = getattr(r, "poster_path", None)
            processed.append({
                "Title": getattr(r, "title", getattr(r, "name", "Unknown")),
                "Type": detected_type, "Country": lang, "Genres": ", ".join(res_genres),
                "Image": f"{tmdb_poster_base}{poster}" if poster else "",
                "Overview": getattr(r, "overview", "No overview."),
                "Rating": f"{getattr(r, 'vote_average', 0)}/10",
                "Backdrop": f"{tmdb_backdrop_base}{getattr(r, 'backdrop_path', '')}",
                "Total_Eps": "?", "ID": getattr(r, "id", None),
            })
    return processed


# ─────────────────────────────────────────────────────────────
# PARALLEL SEARCH ENGINE
# ─────────────────────────────────────────────────────────────
def search_unified(query, selected_types, selected_genres, sort_option, page=1):
    results_data, futures = [], []
    live_action = ["Movies","Web Series","K-Drama","C-Drama","Thai Drama","Vertical Drama"]

    if any(t in selected_types for t in live_action):
        tmdb_genres = [g for g in selected_genres if g in TMDB_GENRE_MAP]
        g_ids = "|".join(str(TMDB_GENRE_MAP[g]) for g in tmdb_genres)
        tmdb_sort = "vote_average.desc" if sort_option == "Top Rated" else "popularity.desc"
        discover, search_api = Discover(), Search()

        def run_tmdb_job(media_kind, specific_type, lang_filter=None):
            try:
                active_q = query
                if query and specific_type == "K-Drama":   active_q = f"{query} Korean"
                elif query and specific_type == "C-Drama": active_q = f"{query} Chinese"
                if active_q:
                    raw = (search_api.movies(active_q, page=page) if media_kind == "Movie"
                           else search_api.tv_shows(active_q, page=page))
                else:
                    kwargs = {"sort_by": tmdb_sort, "page": page, "vote_count.gte": 5}
                    if g_ids:       kwargs["with_genres"] = g_ids
                    if lang_filter: kwargs["with_original_language"] = lang_filter
                    raw = (discover.discover_movies(kwargs) if media_kind == "Movie"
                           else discover.discover_tv_shows(kwargs))
                return process_tmdb_results_batch(raw, media_kind, specific_type, selected_types, selected_genres, query)
            except Exception:
                return []

    def run_anilist_job(q, t, g, s, p, c=None, f=None, forced_t="Anime"):
        return process_anilist_results(fetch_anilist_list_raw(q, t, g, s, p, c, f), forced_t, g)

    def run_openlib_job(q, g, forced_t):
        q_mod = q + " novel" if forced_t == "Novel" and q else (q or "fantasy novel")
        return process_open_library(fetch_open_library_raw(q_mod, g), forced_t)

    with ThreadPoolExecutor(max_workers=10) as executor:
        if "Movies"         in selected_types: futures.append(executor.submit(run_tmdb_job, "Movie", "Movies"))
        if "Web Series"     in selected_types: futures.append(executor.submit(run_tmdb_job, "TV", "Web Series"))
        if "K-Drama"        in selected_types: futures.append(executor.submit(run_tmdb_job, "TV", "K-Drama", "ko"))
        if "C-Drama"        in selected_types: futures.append(executor.submit(run_tmdb_job, "TV", "C-Drama", "zh"))
        if "Thai Drama"     in selected_types: futures.append(executor.submit(run_tmdb_job, "TV", "Thai Drama", "th"))
        if "Vertical Drama" in selected_types: futures.append(executor.submit(run_tmdb_job, "TV", "Vertical Drama", "zh"))
        if "Anime"          in selected_types: futures.append(executor.submit(run_anilist_job, query,"ANIME",selected_genres,sort_option,page,None,None,"Anime"))
        if "Donghua"        in selected_types: futures.append(executor.submit(run_anilist_job, query,"ANIME",selected_genres,sort_option,page,"CN",None,"Donghua"))
        if "Manga"          in selected_types: futures.append(executor.submit(run_anilist_job, query,"MANGA",selected_genres,sort_option,page,"JP",None,"Manga"))
        if "Manhwa"         in selected_types: futures.append(executor.submit(run_anilist_job, query,"MANGA",selected_genres,sort_option,page,"KR",None,"Manhwa"))
        if "Manhua"         in selected_types: futures.append(executor.submit(run_anilist_job, query,"MANGA",selected_genres,sort_option,page,"CN",None,"Manhua"))
        if "Novel"          in selected_types:
            futures.append(executor.submit(run_anilist_job, query,"MANGA",selected_genres,sort_option,page,None,"NOVEL","Novel"))
            if "Web Novel" in selected_genres:
                futures.append(executor.submit(run_anilist_job, query,"MANGA",selected_genres,sort_option,page,"KR","NOVEL","Novel"))
                futures.append(executor.submit(run_anilist_job, query,"MANGA",selected_genres,sort_option,page,"CN","NOVEL","Novel"))
            futures.append(executor.submit(run_openlib_job, query, None, "Novel"))
        if "Book"           in selected_types:
            tg = next((g for g in selected_genres if g in BOOK_GENRES), None)
            futures.append(executor.submit(run_openlib_job, query, tg, "Book"))

        for future in as_completed(futures):
            try:
                data = future.result()
                if data:
                    results_data.extend(data)
            except Exception:
                pass

    return results_data


# ─────────────────────────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────────────────────────
for k, v in [("search_results", []), ("search_page", 1),
              ("search_query_trigger", ""), ("last_search_query", "")]:
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────────────────────
# NAVIGATION
# ─────────────────────────────────────────────────────────────
default_tab = 1 if st.session_state.search_query_trigger else 0
tab = st.radio("Navigation", ["🏠 My Library", "🔍 Search & Add"],
               horizontal=True, label_visibility="collapsed", index=default_tab)
st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# SEARCH TAB
# ─────────────────────────────────────────────────────────────
if tab == "🔍 Search & Add":
    st.markdown("""
    <div style='margin-bottom:1.25rem'>
        <h2 style='font-size:1.4rem;font-weight:700;color:#e8e8f0;margin:0'>
            🔍 Global Database Search
        </h2>
        <p style='color:#666;font-size:0.85rem;margin:0.25rem 0 0'>
            Movies · Series · Anime · Manga · Books — all in one place
        </p>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])

    default_q = ""
    if st.session_state.search_query_trigger:
        default_q = st.session_state.search_query_trigger
        st.session_state.search_query_trigger = ""

    with c1: search_query = st.text_input("Title (Optional)", value=default_q, key="search_box_input")
    with c2:
        all_types = ["Movies","Web Series","K-Drama","C-Drama","Vertical Drama",
                     "Thai Drama","Anime","Donghua","Manga","Manhwa","Manhua","Novel","Book"]
        selected_types = st.multiselect("Type", all_types, default=[], help="Leave empty to search ALL types")
    current_genres = list(TMDB_GENRE_MAP.keys())
    if "Book" in selected_types or "Novel" in selected_types:
        current_genres = sorted(set(current_genres + BOOK_GENRES))
    with c3: selected_genres = st.multiselect("Genre", current_genres)
    with c4: sort_option = st.selectbox("Sort By", ["Popularity", "Relevance", "Top Rated"])

    do_search = st.button("🚀 Search / Discover")
    if default_q and not st.session_state.search_results:
        do_search = True

    if do_search:
        st.session_state.search_page = 1
        st.session_state.search_results = []
        st.session_state.last_search_query = search_query
        with st.spinner("Fetching from global databases..."):
            active_types = selected_types or all_types
            st.session_state.search_results = search_unified(search_query, active_types, selected_genres, sort_option)
        if not st.session_state.search_results:
            st.warning("No results found.")

    if st.session_state.search_results:
        for idx, item in enumerate(st.session_state.search_results):
            with st.container():
                col_img, col_txt = st.columns([1, 6])
                with col_img:
                    st.image(item.get("Image") or PLACEHOLDER_IMG, use_container_width=True)
                with col_txt:
                    st.subheader(item.get("Title", "Unknown"))
                    st.caption(f"**{item.get('Type','')}** | ⭐ {item.get('Rating','')} | {item.get('Country','')}")
                    st.caption(f"🏷️ {item.get('Genres','')}")

                    with st.popover("📜 Overview"):
                        tmdb_id = item.get("ID")
                        m_type  = "movie" if item.get("Type") == "Movies" else "tv"
                        st.write(item.get("Overview",""))

                        found_relations = []
                        if item.get("Type") in ["Anime","Donghua","Manga","Manhwa","Manhua","Novel"]:
                            ad = fetch_anilist_data_single(
                                item.get("Title",""),
                                "ANIME" if item.get("Type") in ["Anime","Donghua"] else "MANGA",
                                fetch_relations=True)
                            if ad and "relations" in ad:
                                for edge in ad["relations"]["edges"]:
                                    rt = edge["relationType"]
                                    if rt not in ["SEQUEL","PREQUEL","PARENT","SIDE_STORY","ALTERNATIVE","SOURCE"]: continue
                                    rtitle = edge["node"]["title"]["english"] or edge["node"]["title"]["romaji"]
                                    if rtitle: found_relations.append({"type": rt.replace("_"," ").title(), "title": rtitle})
                        elif tmdb_id:
                            found_relations.extend(get_tmdb_relations(tmdb_id, m_type, item.get("Title","")))

                        if found_relations:
                            st.write("---")
                            st.markdown("**Watch Order:** " + " | ".join(
                                f"[{r['type']}: {r['title']}](/?search={urllib.parse.quote(r['title'])})"
                                for r in found_relations))
                            st.write("---")

                        trailer_url = None
                        try:
                            if item.get("Type") in ["Anime","Donghua"]:
                                ad = fetch_anilist_data_single(item.get("Title",""), "ANIME")
                                if ad and ad.get("trailer") and ad["trailer"].get("site") == "youtube":
                                    trailer_url = f"https://www.youtube.com/watch?v={ad['trailer']['id']}"
                            elif item.get("Type") in ["Movies","Web Series","K-Drama","C-Drama","Thai Drama","Vertical Drama"] and tmdb_id:
                                trailer_url = get_tmdb_trailer(tmdb_id, m_type)
                        except Exception:
                            pass
                        if trailer_url:
                            st.caption("🎬 Trailer"); st.video(trailer_url)

                        if item.get("Type") in ["Manga","Manhwa","Manhua","Novel"] and item.get("Links"):
                            st.write("**Official Sources:**")
                            for link in item["Links"]:
                                st.link_button(f"🔗 {link['site']}", link["url"])

                    is_added = is_in_library(item.get("Title",""))
                    if is_added:
                        existing = get_from_library(item.get("Title",""))
                        st.success("✅ In Collection")
                        with st.expander("Update Status", expanded=False):
                            is_read = item.get("Type") in ["Book","Novel","Manga","Manhwa","Manhua"]
                            opts = (["Plan to Read","Reading","Completed","Dropped"] if is_read
                                    else ["Plan to Watch","Watching","Completed","Dropped"])
                            curr_status = existing.get("Status", opts[0])
                            if curr_status not in opts: curr_status = opts[0]
                            try: curr_sea = int(existing.get("Current_Season",1))
                            except: curr_sea = 1
                            try: curr_ep = int(existing.get("Current_Ep",0))
                            except: curr_ep = 0
                            new_s = st.selectbox("Status", opts, index=opts.index(curr_status), key=f"s_s_{idx}")
                            if item.get("Type") != "Movies":
                                cs, ce = st.columns(2)
                                ns = cs.number_input("Vol." if is_read else "S", value=curr_sea, min_value=1, key=f"ns_s_{idx}")
                                ne = ce.number_input("Ch." if is_read else "E", value=curr_ep, min_value=0, key=f"ne_s_{idx}")
                            else:
                                ns, ne = 1, 0
                            b1, b2 = st.columns(2)
                            with b1:
                                if st.button("Save", key=f"save_s_{idx}"):
                                    update_status_in_sheet(item.get("Title",""), new_s, ns, ne)
                                    st.rerun()
                            with b2:
                                if st.button("Delete", key=f"del_s_{idx}"):
                                    delete_from_sheet(item.get("Title",""))
                                    st.rerun()
                    else:
                        if st.button("➕ Add to Library", key=f"add_{idx}"):
                            with st.spinner("Adding..."):
                                if fetch_details_and_add(item):
                                    st.rerun()
            st.divider()

        if st.button("⬇️ Load More Results"):
            st.session_state.search_page += 1
            with st.spinner(f"Loading page {st.session_state.search_page}..."):
                active_types = selected_types or all_types
                new_results = search_unified(
                    st.session_state.last_search_query, active_types,
                    selected_genres, sort_option, page=st.session_state.search_page)
                st.session_state.search_results.extend(new_results)
                st.rerun()


# ─────────────────────────────────────────────────────────────
# LIBRARY TAB — zero extra sheet reads; uses single cached read
# ─────────────────────────────────────────────────────────────
elif tab == "🏠 My Library":
    col_h, col_c = st.columns([3, 1])
    with col_h:
        st.markdown("""
        <h2 style='font-size:1.4rem;font-weight:700;color:#e8e8f0;margin:0 0 0.5rem'>
            🏠 My Library
        </h2>""", unsafe_allow_html=True)
    with col_c:
        try: def_ix = list(tmdb_countries.keys()).index("India")
        except ValueError: def_ix = 0
        stream_country = st.selectbox("Streaming Country", list(tmdb_countries.keys()), index=def_ix)
        country_code = tmdb_countries[stream_country]

    if not get_google_sheet():
        st.error("Google Sheets connection failed. Check your secrets configuration.")
        st.stop()

    # Zero extra API calls — df already built from the one cached read
    df = _get_sheet_data()["df"].copy()

    if df.empty:
        st.info("Your library is empty. Go to **Search & Add** to find something!")
        st.stop()

    # ── STATS PANEL ──
    with st.expander("📊 Library Statistics", expanded=False):
        total = len(df)
        st.markdown(f"**Total items: {total}**")
        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown("**By Status:**")
            for s, c in df["Status"].value_counts().items():
                emoji = {"Completed":"✅","Watching":"▶️","Reading":"📖",
                         "Plan to Watch":"🕒","Plan to Read":"📌","Dropped":"❌"}.get(s,"•")
                st.markdown(f"{emoji} **{s}:** {c} ({int(c/total*100)}%)")
        with sc2:
            st.markdown("**By Type:**")
            for t, c in df["Type"].value_counts().items():
                st.markdown(f"• **{t}:** {c}")

    # ── CURRENTLY ACTIVE STRIP ──
    active_df = df[df["Status"].isin(["Watching","Reading"])]
    if not active_df.empty:
        with st.expander(f"🔥 Currently Active ({len(active_df)})", expanded=True):
            act_cols = st.columns(min(len(active_df), 6))
            for col, (_, item) in zip(act_cols, active_df.iterrows()):
                with col:
                    img = item.get("Image") or PLACEHOLDER_IMG
                    if not str(img).startswith("http"): img = PLACEHOLDER_IMG
                    st.image(img, use_container_width=True)
                    t = item["Title"]
                    st.caption(f"**{t[:18]+'…' if len(t)>18 else t}**")
                    if item.get("Type") in ["Manga","Manhwa","Manhua"]:
                        st.caption(f"Vol.{item.get('Current_Season',1)} Ch.{item.get('Current_Ep',0)}")
                    elif item.get("Type") in ["Book","Novel"]:
                        st.caption(f"Pg.{item.get('Current_Season',0)}")
                    else:
                        st.caption(f"S{item.get('Current_Season',1)} E{item.get('Current_Ep',0)}")

    st.divider()

    # ── FILTERS ──
    with st.expander("🔽 Filter Collection", expanded=False):
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1: filter_text   = st.text_input("Search Title")
        with fc2: filter_type   = st.multiselect("Filter Type", sorted(df["Type"].unique()))
        with fc3: filter_status = st.multiselect("Status", ["Plan to Watch","Plan to Read","Watching","Reading","Completed","Dropped"])
        with fc4: filter_fav    = st.checkbox("❤️ Favorites Only")

    if filter_text:   df = df[df["Title"].astype(str).str.contains(filter_text, case=False, na=False)]
    if filter_type:   df = df[df["Type"].isin(filter_type)]
    if filter_status: df = df[df["Status"].isin(filter_status)]
    if filter_fav:    df = df[df.get("Favorite", pd.Series("No", index=df.index)) == "Yes"]

    # ── EXPORT ──
    _, exp_col = st.columns([6, 1])
    with exp_col:
        st.download_button("📥 Export CSV", data=df.to_csv(index=False).encode("utf-8"),
                           file_name="my_media_library.csv", mime="text/csv", use_container_width=True)

    # ── REORDER ──
    if HAS_SORTABLES and not df.empty:
        with st.expander("🔄 Reorder List", expanded=False):
            st.caption("Drag items to reorder, then click Save.")
            titles = df["Title"].tolist()
            sorted_titles = sort_items(titles, key="sort_all")
            if sorted_titles != titles and st.button("💾 Save Order"):
                title_map = {}
                for idx in df.index.tolist():
                    title_map.setdefault(df.loc[idx, "Title"], []).append(idx)
                new_order = [title_map[t].pop(0) for t in sorted_titles if t in title_map and title_map[t]]
                bulk_update_order(df.iloc[new_order].reset_index(drop=True))

    # ── GALLERY GRID ──
    if not df.empty:
        for row_chunk in [df.iloc[i:i+5] for i in range(0, len(df), 5)]:
            cols = st.columns(5)
            for col, (index, item) in zip(cols, row_chunk.iterrows()):
                with col:
                    img = item.get("Image") or PLACEHOLDER_IMG
                    if not str(img).startswith("http"): img = PLACEHOLDER_IMG
                    st.image(img, use_container_width=True)

                    fav_badge = "❤️ " if item.get("Favorite") == "Yes" else ""
                    status = item.get("Status", "")
                    status_colors = {
                        "Watching":      ("#7c3aed", "#e9d5ff"),
                        "Reading":       ("#7c3aed", "#e9d5ff"),
                        "Completed":     ("#065f46", "#6ee7b7"),
                        "Dropped":       ("#7f1d1d", "#fca5a5"),
                        "Plan to Watch": ("#1e3a5f", "#93c5fd"),
                        "Plan to Read":  ("#1e3a5f", "#93c5fd"),
                    }
                    bg, fg = status_colors.get(status, ("#222", "#aaa"))
                    title_text = item.get('Title', '')
                    short_title = (title_text[:22] + "…") if len(title_text) > 22 else title_text
                    st.markdown(f"""
                    <div style='margin:6px 0 2px'>
                        <div style='font-size:0.82rem;font-weight:700;color:#e8e8f0;
                                    line-height:1.3;margin-bottom:4px' title='{title_text}'>
                            {fav_badge}{short_title}
                        </div>
                        <span style='background:{bg};color:{fg};font-size:0.68rem;
                                     font-weight:600;padding:2px 7px;border-radius:20px;
                                     letter-spacing:0.02em;white-space:nowrap'>
                            {status}
                        </span>
                    </div>
                    """, unsafe_allow_html=True)
                    uk = f"gal_{index}"

                    # Must be defined BEFORE any popover/expander that uses them
                    is_book  = item.get("Type") in ["Book","Novel"]
                    is_comic = item.get("Type") in ["Manga","Manhwa","Manhua"]
                    is_read  = is_book or is_comic

                    with st.popover("📜 Overview"):
                        tmdb_id = item.get("ID")
                        m_type  = "movie" if item.get("Type") == "Movies" else "tv"
                        if not tmdb_id and item.get("Type") in ["Movies","Web Series","K-Drama","C-Drama","Thai Drama","Vertical Drama"]:
                            tmdb_id = recover_tmdb_id(item.get("Title",""), m_type)

                        st.write(item.get("Overview",""))

                        found_relations = []
                        if item.get("Type") in ["Anime","Donghua","Manga","Manhwa","Manhua","Novel"]:
                            ad = fetch_anilist_data_single(
                                item.get("Title",""),
                                "ANIME" if item.get("Type") in ["Anime","Donghua"] else "MANGA",
                                fetch_relations=True)
                            if ad and "relations" in ad:
                                for edge in ad["relations"]["edges"]:
                                    rt = edge["relationType"]
                                    if rt not in ["SEQUEL","PREQUEL","PARENT","SIDE_STORY","ALTERNATIVE","SOURCE"]: continue
                                    rtitle = edge["node"]["title"]["english"] or edge["node"]["title"]["romaji"]
                                    if rtitle: found_relations.append({"type": rt.replace("_"," ").title(), "title": rtitle})
                        elif tmdb_id:
                            found_relations.extend(get_tmdb_relations(tmdb_id, m_type, item.get("Title","")))

                        if found_relations:
                            st.write("---")
                            st.markdown("**Watch Order:** " + " | ".join(
                                f"[{r['type']}: {r['title']}](/?search={urllib.parse.quote(r['title'])})"
                                for r in found_relations))
                            st.write("---")

                        trailer_url = None
                        try:
                            if item.get("Type") in ["Anime","Donghua"]:
                                ad = fetch_anilist_data_single(item.get("Title",""), "ANIME")
                                if ad and ad.get("trailer") and ad["trailer"].get("site") == "youtube":
                                    trailer_url = f"https://www.youtube.com/watch?v={ad['trailer']['id']}"
                            elif item.get("Type") in ["Movies","Web Series","K-Drama","C-Drama","Thai Drama","Vertical Drama"] and tmdb_id:
                                trailer_url = get_tmdb_trailer(tmdb_id, m_type)
                        except Exception:
                            pass
                        if trailer_url:
                            st.caption("🎬 Trailer"); st.video(trailer_url)

                        st.write(f"**Status:** {item.get('Status','')} | **Rating:** {item.get('Rating','')}")
                        if item.get("Personal_Rating"):
                            pr = str(item["Personal_Rating"])
                            stars = "⭐" * int(pr) if pr.isdigit() else ""
                            st.write(f"**Your Rating:** {stars} {pr}/5")
                        if item.get("Notes"):
                            st.write(f"**Notes:** {item['Notes']}")
                        if item.get("Date_Added"):
                            st.caption(f"Added: {item['Date_Added']}")
                        st.divider()

                        if is_book:
                            st.link_button("📘 Google Books", f"https://www.google.com/search?tbm=bks&q={item.get('Title','')}")
                        elif is_comic:
                            st.link_button("📖 Comix.to", f"https://www.google.com/search?q=site:comix.to+{item.get('Title','')}")
                            live_data = fetch_anilist_data_single(item.get("Title",""), "MANGA")
                            if live_data and live_data.get("externalLinks"):
                                for lnk in live_data["externalLinks"]:
                                    st.link_button(f"🔗 {lnk['site']}", lnk["url"])
                        else:
                            st.caption(f"📺 Watch in {stream_country}")
                            if item.get("Type") == "Anime":
                                st.link_button("🟠 Crunchyroll", f"https://www.crunchyroll.com/search?q={item.get('Title','')}")
                            elif item.get("Type") in ["K-Drama","C-Drama","Thai Drama","Vertical Drama"]:
                                st.link_button("💙 Viki", f"https://www.viki.com/search?q={urllib.parse.quote(item.get('Title',''))}")
                            provs = get_streaming_info(tmdb_id, m_type, country_code)
                            has_streams = False
                            if provs:
                                for label, key in [("Streaming","flatrate"),("Rent","rent"),("Buy","buy")]:
                                    if key in provs:
                                        st.write(f"**{label}:**")
                                        for p in provs[key]:
                                            st.markdown(f"- [{p['provider_name']}]({get_provider_link(p['provider_name'], item.get('Title',''))})")
                                        has_streams = True
                            if not has_streams:
                                st.caption("No official streams found.")

                    with st.expander("⚙️ Manage"):
                        opts = (["Plan to Read","Reading","Completed","Dropped"] if is_read
                                else ["Plan to Watch","Watching","Completed","Dropped"])
                        curr = item.get("Status", opts[0])
                        if curr not in opts: curr = opts[0]
                        new_s = st.selectbox("Status", opts, key=f"st_{uk}", index=opts.index(curr))

                        if is_book:
                            try: c_pg = int(item.get("Current_Season",0))
                            except: c_pg = 0
                            new_sea = st.number_input("Pages/Chapters", value=c_pg, key=f"s_{uk}")
                            new_ep  = 0
                            st.caption(f"Total: {item.get('Total_Eps','?')}")
                        elif item.get("Type") != "Movies":
                            try: c_sea = int(item.get("Current_Season",1))
                            except: c_sea = 1
                            try: c_ep  = int(item.get("Current_Ep",0))
                            except: c_ep  = 0
                            sea_lbl, ep_lbl = ("Vol.","Ch.") if is_comic else ("S","E")
                            total_str = item.get("Total_Eps","?")
                            if not is_comic and tmdb_id:
                                si = get_season_details(tmdb_id, c_sea)
                                if si: total_str = si["episode_count"]
                            cs, ce = st.columns(2)
                            with cs: new_sea = st.number_input(sea_lbl, min_value=1, value=c_sea, key=f"s_{uk}")
                            with ce: new_ep  = st.number_input(
                                f"{ep_lbl} (/{total_str})" if total_str != "?" else ep_lbl,
                                min_value=0, value=c_ep, key=f"e_{uk}")
                        else:
                            new_sea, new_ep = 1, 0

                        try: curr_pr = int(item.get("Personal_Rating",0))
                        except: curr_pr = 0
                        new_pr    = st.slider("⭐ Your Rating (0–5)", 0, 5, curr_pr, key=f"pr_{uk}")
                        new_notes = st.text_area("📝 Notes", value=str(item.get("Notes","")), key=f"nt_{uk}", height=70)
                        new_fav   = st.checkbox("❤️ Favorite", value=item.get("Favorite","No")=="Yes", key=f"fv_{uk}")

                        sv_col, dl_col = st.columns(2)
                        with sv_col:
                            if st.button("💾 Save", key=f"sv_{uk}"):
                                update_status_in_sheet(item.get("Title",""), new_s, new_sea, new_ep,
                                    notes=new_notes, personal_rating=str(new_pr),
                                    favorite="Yes" if new_fav else "No")
                                st.rerun()
                        with dl_col:
                            if st.button("🗑️ Delete", key=f"dl_{uk}"):
                                delete_from_sheet(item.get("Title",""))
                                st.rerun()
    else:
        st.info("No items found matching your filters.")
