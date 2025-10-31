# routers/pages.py

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from supabase_client import supabase
from core.security import get_current_user_email
import urllib.parse
import os
import httpx
import asyncio
from time import time
from datetime import datetime, timezone, timedelta

featured_cache = (
    {}
)  # { user_email: { "data": [...], "genres": [...], "timestamp": <unix_time> } }


API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")
NYT_KEY = os.getenv("NYT_BOOKS_API_KEY")
ADMIN_TOKEN = os.getenv("CAROUSEL_ADMIN_TOKEN", "secret-refresh")
CACHE_TTL_DAYS = 7  # refresh once a week

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


async def fetch_google_books(query: str, max_results=20):
    """Fetch from Google Books API."""
    async with httpx.AsyncClient() as client:
        url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(query)}&maxResults={max_results}&key={API_KEY}"
        resp = await client.get(url, timeout=10)
        return resp.json().get("items", [])


async def fetch_nytimes_books(endpoint: str):
    """Fetch current NYTimes bestseller list."""
    try:
        async with httpx.AsyncClient() as client:
            url = f"https://api.nytimes.com/svc/books/v3/{endpoint}?api-key={NYT_KEY}"
            r = await client.get(url, timeout=10)
            data = r.json()
            results = data.get("results", {}).get("books", [])
            books = []
            for b in results:
                title = b.get("title", "")
                author = b.get("author", "")
                enriched = await fetch_google_books(
                    f"intitle:{title} inauthor:{author}", 1
                )
                if enriched:
                    books.append(enriched[0])
            return books[:12]
    except Exception as e:
        print("NYTimes fetch failed:", e)
        return []


def filter_recent_books(items, min_year=2023):
    """Keep only books published in or after min_year."""
    filtered = []
    for b in items:
        info = b.get("volumeInfo", {})
        pub = info.get("publishedDate", "")
        try:
            year = int(pub.split("-")[0])
        except Exception:
            year = 0
        if year >= min_year:
            filtered.append(b)
    return filtered


async def build_month():
    """Popular this month — NYTimes bestsellers filtered to books after 2023."""
    try:
        # 1️⃣ Fetch the latest NYTimes fiction list
        nyt_books = await fetch_nytimes_books(
            "lists/current/combined-print-and-e-book-fiction.json"
        )

        # 2️⃣ Safety: if NYTimes call fails, fallback to an empty list
        if not nyt_books:
            print("⚠️ No NYTimes results, returning empty list")
            return []

        # 3️⃣ Filter by recent publication year (≥2023)
        recent_books = filter_recent_books(nyt_books, 2023)

        # 4️⃣ If filtering removed too many, fallback to original list
        if len(recent_books) < 10:
            print(
                f"⚠️ Only {len(recent_books)} recent books found, using fallback NYT list"
            )
            recent_books = nyt_books

        # 5️⃣ Limit to 12 items for carousel
        return recent_books[:12]

    except Exception as e:
        print(f"⚠️ Error in build_month(): {e}")
        return []


async def build_top():
    """Top rated this year — Google Books filtered by rating and year, with fallback."""
    genres = [
        "Fiction",
        "Romance",
        "Thriller",
        "Mystery",
        "Fantasy",
        "Nonfiction",
        "Science",
    ]
    results = []

    async with httpx.AsyncClient() as client:
        for g in genres:
            try:
                # Include both "top rated" and the year to increase relevancy
                query = f"subject:{g} (2024 OR 2025) best books OR top rated OR award winning"
                url = (
                    f"https://www.googleapis.com/books/v1/volumes?"
                    f"q={urllib.parse.quote(query)}&orderBy=relevance&maxResults=40&key={API_KEY}"
                )
                r = await client.get(url, timeout=10)
                for b in r.json().get("items", []):
                    info = b.get("volumeInfo", {})
                    pub = info.get("publishedDate", "")
                    try:
                        pub_year = int(pub.split("-")[0])
                    except:
                        pub_year = 0
                    # ✅ Allow good ratings and newer publications
                    if pub_year >= 2024:
                        results.append(b)
            except Exception as e:
                print("Error fetching top rated:", e)

    # ✅ Filter books published from 2024 onward
    results = filter_recent_books(results, 2024)

    # Sort by rating, review count, and publication date
    results = sorted(
        results,
        key=lambda b: (
            b.get("volumeInfo", {}).get("averageRating", 0),
            b.get("volumeInfo", {}).get("ratingsCount", 0),
            b.get("volumeInfo", {}).get("publishedDate", "0000"),
        ),
        reverse=True,
    )

    # ✅ If fewer than 10 results, fetch a fallback batch and merge
    if len(results) < 10:
        print(f"⚠️ Only {len(results)} top-rated books found. Fetching fallback list.")
        fallback = await fetch_google_books(f"best books 2024 OR 2025 top rated", 30)
        fallback = filter_recent_books(fallback, 2024)

        seen_titles = {b.get("volumeInfo", {}).get("title") for b in results}
        for b in fallback:
            title = b.get("volumeInfo", {}).get("title")
            if title and title not in seen_titles:
                results.append(b)
                seen_titles.add(title)
            if len(results) >= 12:
                break

    return results[:12]


async def build_featured():
    """Editor's Picks — curated genre mix with fallback and year filter."""
    curated = ["Romance", "Science Fiction", "Mystery"]
    picks = []

    try:
        # Fetch 3–4 books from each curated genre
        for g in curated:
            items = await fetch_google_books(f"subject:{g} 2024 OR 2025", 8)
            picks.extend(items[:4])

        # ✅ Filter by publication year ≥ 2023
        picks = filter_recent_books(picks, 2023)

        # --- Fallback if too few books found ---
        if len(picks) < 10:
            print(f"⚠️ Only {len(picks)} featured books found, using cached fallback.")

            # try to fetch cached data (old Supabase results)
            old_cache = get_cache("featured")
            old_books = old_cache["data"] if old_cache else []

            # combine old books with new, avoid duplicates
            seen_titles = {b.get("volumeInfo", {}).get("title") for b in picks}
            for b in old_books:
                title = b.get("volumeInfo", {}).get("title")
                if title and title not in seen_titles:
                    picks.append(b)
                    seen_titles.add(title)
                if len(picks) >= 12:
                    break

        return picks[:12]

    except Exception as e:
        print(f"⚠️ Error in build_featured(): {e}")
        return []


# --------------------------
# Supabase cache helpers
# --------------------------


def get_cache(filter_id: str):
    res = (
        supabase.table("carousel_cache").select("*").eq("id", filter_id).execute().data
    )
    return res[0] if res else None


def save_cache(filter_id: str, data):
    supabase.table("carousel_cache").upsert(
        {
            "id": filter_id,
            "data": data,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()


async def ensure_cached(filter_id: str, force_refresh: bool = False):
    now = datetime.now(timezone.utc)
    row = get_cache(filter_id)
    old_data = row["data"] if row else []
    last_updated = None

    if row and not force_refresh:
        try:
            ts = row["updated_at"]
            if isinstance(ts, str):
                ts = ts.replace("Z", "+00:00") if "Z" in ts else ts
            last_updated = datetime.fromisoformat(ts)
        except Exception:
            last_updated = now - timedelta(days=999)

        if (now - last_updated) < timedelta(days=CACHE_TTL_DAYS):
            return old_data

    # --- Rebuild fresh data ---
    if filter_id == "month":
        new_data = await build_month()
    elif filter_id == "top":
        new_data = await build_top()
    elif filter_id == "featured":
        new_data = await build_featured()
    else:
        new_data = []

    # --- Combine if too few results ---
    if len(new_data) < 10 and old_data:
        print(
            f"⚠️ {filter_id} fetched only {len(new_data)} new books, reusing cached ones."
        )
        needed = 12 - len(new_data)
        # append old cached books that are not duplicates
        seen_titles = {b.get("volumeInfo", {}).get("title") for b in new_data}
        for b in old_data:
            title = b.get("volumeInfo", {}).get("title")
            if title and title not in seen_titles:
                new_data.append(b)
                seen_titles.add(title)
            if len(new_data) >= 12:
                break

    # --- Save merged result ---
    save_cache(filter_id, new_data)
    return new_data


# --------------------------
# Main page route
# --------------------------


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    user_email = user["email"]
    filter_option = request.query_params.get("filter", "")

    all_favorites = (
        supabase.table("favorites")
        .select("*")
        .eq("user_email", user_email)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    favorites = all_favorites[:5]
    shelves = (
        supabase.table("shelves")
        .select("*")
        .eq("user_email", user_email)
        .limit(5)
        .execute()
        .data
        or []
    )

    history_res = (
        supabase.table("search_history")
        .select("query")
        .eq("user_email", user_email)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    search_history_raw = (
        [h["query"] for h in history_res.data] if history_res.data else []
    )

    search_history_display = []
    for item in search_history_raw:
        if item.startswith("inauthor:"):
            label = "Author: " + item.replace("inauthor:", "")
        elif item.startswith("intitle:"):
            label = "Title: " + item.replace("intitle:", "")
        elif item.startswith("subject:"):
            label = "Category: " + item.replace("subject:", "")
        else:
            label = item
        search_history_display.append(label)
    search_history_zipped = list(zip(search_history_raw, search_history_display))

    viewed_books = (
        supabase.table("recently_viewed")
        .select("book_id, title, thumbnail")
        .eq("user_email", user_email)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
        .data
        or []
    )

    seen_ids = set()
    # Normalize keys so the template expects "id" instead of "book_id"
    filtered_books = []
    for book in viewed_books:
        if book["book_id"] not in seen_ids:
            seen_ids.add(book["book_id"])
            filtered_books.append(
                {
                    "id": book["book_id"],
                    "title": book["title"],
                    "thumbnail": book.get("thumbnail", ""),
                }
            )

    # --- Build base genres ---
    default_genres = [
        {"name": "Romance", "link": "Romance", "count": 0},
        {"name": "Mystery", "link": "Mystery", "count": 0},
        {"name": "Fantasy", "link": "Fantasy", "count": 0},
        {"name": "Action", "link": "Action", "count": 0},
        {"name": "Science Fiction", "link": "Science Fiction", "count": 0},
        {"name": "Horror", "link": "Horror", "count": 0},
        {"name": "Adventure", "link": "Adventure", "count": 0},
        {"name": "Western", "link": "Western", "count": 0},
    ]

    # start fresh, don't reuse default references
    genres = []
    genre_map = {}

    # add defaults first
    for g in default_genres:
        genres.append(g)
        genre_map[g["name"].lower()] = g

    # --- Add user genres dynamically ---
    for fav in all_favorites:
        if fav.get("categories"):
            for raw_cat in fav["categories"].split(","):
                c = raw_cat.strip()
                if "/" in c:
                    c = c.split("/", 1)[0].strip()
                else:
                    c = c.strip()

                # skip empty or too short
                if len(c) < 4:
                    continue

                # normalize capitalization
                c = c.title()

                key = c.lower()
                if key in genre_map:
                    genre_map[key]["count"] += 1
                else:
                    genres.append({"name": c, "link": c, "count": 1})
                    genre_map[key] = genres[-1]

    # --- Sort user-added genres above defaults ---
    genres = sorted(
        genres,
        key=lambda x: (
            x["count"],
            x["name"] not in [d["name"] for d in default_genres],
        ),
        reverse=True,
    )
    genres = genres[:15]

    #  carousel_books
    search_terms = {
        "week": "trending books this week",
        "month": "bestsellers this month",
        "top": "top rated books in 2025",
        "new": "new book releases",
    }

    # ✅ Default to "new arrivals" if no filter specified
    filter_option = filter_option or "month"

    selected_query = search_terms.get(filter_option, "new book releases")

    carousel_books, featured_books = [], []
    async with httpx.AsyncClient() as client:
        try:
            carousel_books = await ensure_cached(filter_option)
        except Exception as e:
            print("Error fetching carousel books:", e)

        # --- Personalized Featured Books (Supabase + memory cache) ---
        featured_books = []
        try:
            top_genres = [g["name"] for g in genres[:3] if g["name"]] or [
                "Fiction",
                "Romance",
                "Mystery",
            ]
            user_email = user["email"]

            cache_entry = featured_cache.get(user_email)
            cache_valid = (
                cache_entry
                and cache_entry["genres"] == top_genres
                and time() - cache_entry["timestamp"] < 6 * 60 * 60  # 6 hours
            )

            if cache_valid:
                featured_books = cache_entry["data"]
                print(f"✅ Using in-memory featured cache for {user_email}.")
            else:
                # 🔍 Check Supabase persistent cache
                db_cache = (
                    supabase.table("featured_cache")
                    .select("*")
                    .eq("user_email", user_email)
                    .execute()
                    .data
                )

                db_valid = False
                if db_cache:
                    db_entry = db_cache[0]
                    # Check if genres match and data is recent (6 hrs)

                    updated_at = datetime.fromisoformat(
                        db_entry["updated_at"].replace("Z", "+00:00")
                    )
                    age_seconds = (
                        datetime.now(timezone.utc) - updated_at
                    ).total_seconds()
                    if db_entry["genres"] == top_genres and age_seconds < 6 * 60 * 60:
                        featured_books = db_entry["data"]
                        db_valid = True
                        print(f"✅ Using Supabase cached featured for {user_email}.")

                if not db_valid:
                    print(
                        f"📚 Rebuilding featured for {user_email} (new genres: {top_genres})"
                    )

                    async def fetch_books_for_genre(client, genre):
                        try:
                            feature_query = f"subject:{genre}"
                            url_feat = (
                                f"https://www.googleapis.com/books/v1/volumes?"
                                f"q={urllib.parse.quote(feature_query)}&maxResults=4&orderBy=relevance&key={API_KEY}"
                            )
                            resp = await client.get(url_feat, timeout=10.0)
                            if resp.status_code == 200:
                                return resp.json().get("items", [])
                        except Exception as e:
                            print(f"❌ Error fetching {genre}: {e}")
                        return []

                    async with httpx.AsyncClient() as client:
                        tasks = [fetch_books_for_genre(client, g) for g in top_genres]
                        results = await asyncio.gather(*tasks)
                    featured_books = [b for r in results for b in r if r]

                    # ✅ Save both in memory and Supabase
                    featured_cache[user_email] = {
                        "data": featured_books,
                        "genres": top_genres,
                        "timestamp": time(),
                    }

                    # Upsert (insert or update)
                    supabase.table("featured_cache").upsert(
                        {
                            "user_email": user_email,
                            "genres": top_genres,
                            "data": featured_books,
                            "updated_at": datetime.utcnow().isoformat() + "Z",
                        }
                    ).execute()

                    print(
                        f"🧠 Cached featured books ({len(featured_books)}) for {user_email} in Supabase."
                    )
        except Exception as e:
            print("❌ Error fetching personalized featured books:", e)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "favorites": favorites,
            "shelves": shelves,
            "search_history_zipped": search_history_zipped,
            "viewed_books": filtered_books,
            "genres": genres,
            "carousel_books": carousel_books,
            "featured_books": featured_books,
            "filter": filter_option,
        },
    )


# --- Clear Recently Viewed ---
@router.get("/clear-recently-viewed")
async def clear_recently_viewed(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    user_email = user["email"]
    supabase.table("recently_viewed").delete().eq("user_email", user_email).execute()
    return RedirectResponse(url="/", status_code=303)


# --- Clear Search History ---
@router.get("/clear-search-history")
async def clear_search_history(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    user_email = user["email"]
    supabase.table("search_history").delete().eq("user_email", user_email).execute()
    return RedirectResponse(url="/", status_code=303)


# --- API endpoint for AJAX updates (no full reload) ---
@router.get("/api/books")
async def api_books(filter: str = ""):
    data = await ensure_cached(filter or "month")
    return {"carousel_books": data}


# --------------------------
# Admin refresh endpoint
# --------------------------
@router.get("/admin/refresh-carousel")
async def refresh_cache(token: str):
    if token != ADMIN_TOKEN:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    month = await ensure_cached("month", force_refresh=True)
    top = await ensure_cached("top", force_refresh=True)
    featured = await ensure_cached("featured", force_refresh=True)
    return {
        "status": "refreshed",
        "counts": {
            "month": len(month or []),
            "top": len(top or []),
            "featured": len(featured or []),
        },
    }
