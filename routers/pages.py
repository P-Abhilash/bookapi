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

        # --- Personalized Featured Books (category search, parallel async fetch, cached per session) ---
        featured_books = []
        try:
            if request.session.get("featured_books"):
                # ✅ Use cached featured list for this login/session
                featured_books = request.session["featured_books"]
                print("✅ Using cached featured books for this session.")
            else:
                # Reuse already calculated top genres
                top_genres = [g["name"] for g in genres[:3] if g["name"]]

                # Fallback if user has no favorites at all
                if not top_genres:
                    top_genres = ["Fiction", "Romance", "Mystery"]

                async def fetch_books_for_genre(client, genre):
                    """Fetch books for a specific genre via category search."""
                    try:
                        feature_query = f"subject:{genre}"
                        url_feat = (
                            f"https://www.googleapis.com/books/v1/volumes?"
                            f"q={urllib.parse.quote(feature_query)}&maxResults=4&orderBy=relevance&key={API_KEY}"
                        )
                        print(f"📚 Fetching featured for genre: {genre}")
                        resp = await client.get(url_feat, timeout=10.0)
                        if resp.status_code == 200:
                            return resp.json().get("items", [])
                    except Exception as e:
                        print(f"❌ Error fetching {genre}: {e}")
                    return []

                async with httpx.AsyncClient() as client:
                    # Run all genre requests in parallel
                    tasks = [fetch_books_for_genre(client, g) for g in top_genres]
                    results = await asyncio.gather(*tasks)

                # Combine results from all genres
                for r in results:
                    if r:
                        featured_books.extend(r)

                # ✅ Cache in session for this login
                request.session["featured_books"] = featured_books
                print(
                    f"🧠 Cached featured books ({len(featured_books)} total) for this session."
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
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login")
    supabase.table("recently_viewed").delete().eq("user_email", user_email).execute()
    return RedirectResponse(url="/", status_code=303)


# --- Clear Search History ---
@router.get("/clear-search-history")
async def clear_search_history(request: Request):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login")
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
