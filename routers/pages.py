# routers/pages.py

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase_client import supabase
from core.security import get_current_user_email
import urllib.parse
import os
import httpx
import asyncio
from time import time
from datetime import datetime, timezone

featured_cache = (
    {}
)  # { user_email: { "data": [...], "genres": [...], "timestamp": <unix_time> } }


API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")
router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


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
    filter_option = filter_option or "new"
    selected_query = search_terms.get(filter_option, "new book releases")

    carousel_books, featured_books = [], []
    async with httpx.AsyncClient() as client:
        try:
            url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(selected_query)}&maxResults=10&key={API_KEY}"
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                carousel_books = data.get("items", [])
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
    """
    Returns JSON data for carousel and featured books based on selected filter.
    Used by frontend AJAX (no full page reload).
    """
    search_terms = {
        "week": "trending books this week",
        "month": "bestsellers this month",
        "top": "top rated books",
        "new": "new book releases",
    }

    # ✅ Default to "new arrivals" if no filter specified
    filter_option = filter or "new"
    selected_query = search_terms.get(filter_option, "new book releases")

    carousel_books = []
    async with httpx.AsyncClient() as client:
        try:
            url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(selected_query)}&maxResults=10&key={API_KEY}"
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                carousel_books = response.json().get("items", [])
        except Exception as e:
            print("❌ Error fetching carousel books:", e)
    return {"carousel_books": carousel_books}
