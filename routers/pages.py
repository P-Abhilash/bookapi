# routers/pages.py

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase_client import supabase
from core.security import get_current_user_email
import urllib.request, urllib.parse, json

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login", status_code=302)

    filter_option = request.query_params.get("filter", "week")

    # === Favorites (limit 5) ===
    favorites = (
        supabase.table("favorites")
        .select("*")
        .eq("user_email", user_email)
        .limit(5)
        .execute()
        .data or []
    )

    # === Shelves (limit 5) ===
    shelves = (
        supabase.table("shelves")
        .select("*")
        .eq("user_email", user_email)
        .limit(5)
        .execute()
        .data or []
    )

    # === Search History ===
    search_history_raw = list(reversed(request.session.get(f"search_history_{user_email}", [])))
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

    # === Recently Viewed ===
    viewed_books = request.session.get(f"viewed_books_{user_email}", [])
    seen_ids = set()
    filtered_books = []
    for book in viewed_books:
        if book["id"] not in seen_ids:
            seen_ids.add(book["id"])
            filtered_books.append(book)
    filtered_books = filtered_books[:5]

    # === Genres ===
    genres = [
        {"name": "Romance", "link": "Romance", "count": 0},
        {"name": "Mystery", "link": "Mystery", "count": 0},
        {"name": "Fantasy", "link": "Fantasy", "count": 0},
        {"name": "Action", "link": "Action", "count": 0},
        {"name": "Science Fiction", "link": "Science Fiction", "count": 0},
        {"name": "Horror", "link": "Horror", "count": 0},
        {"name": "Adventure", "link": "Adventure", "count": 0},
        {"name": "Western", "link": "Western", "count": 0},
    ]

    # Count categories from favorites (Supabase column)
    genre_map = {g["name"]: g for g in genres}  # quick lookup
    for fav in favorites:
        if fav.get("categories"):
            for c in fav["categories"].split(","):
                c = c.strip()
                if c in genre_map:
                    genre_map[c]["count"] += 1
                else:
                    genres.append({"name": c, "link": c, "count": 1})
                    genre_map[c] = genres[-1]

    # Sort by count, top 20
    genres = sorted(genres, key=lambda x: x["count"], reverse=True)[:20]

    # === Featured Books ===
    search_terms = {
        "week": "trending books this week",
        "month": "bestsellers this month",
        "top": "top rated books",
        "new": "new book releases",
    }
    selected_query = search_terms.get(filter_option, "trending books")

    carousel_books, featured_books = [], []
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(selected_query)}&maxResults=10"
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read())
            carousel_books = data.get("items", [])
    except Exception as e:
        print("Error fetching featured books:", e)

    try:
        feature_query = "best books of 2024"
        url_feat = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(feature_query)}&maxResults=10"
        with urllib.request.urlopen(url_feat) as response:
            data_feat = json.loads(response.read())
            featured_books = data_feat.get("items", [])
    except Exception as e:
        print("❌ Error fetching featured books:", e)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user_email,
        "favorites": favorites,
        "shelves": shelves,
        "search_history_zipped": search_history_zipped,
        "viewed_books": filtered_books,
        "genres": genres,
        "carousel_books": carousel_books,
        "featured_books": featured_books,
        "filter": filter_option,
    })


# --- Clear Recently Viewed ---
@router.get("/clear-recently-viewed")
async def clear_recently_viewed(request: Request):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login")
    request.session[f"viewed_books_{user_email}"] = []
    return RedirectResponse(url="/", status_code=303)


# --- Clear Search History ---
@router.get("/clear-search-history")
async def clear_search_history(request: Request):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login")
    request.session[f"search_history_{user_email}"] = []
    return RedirectResponse(url="/", status_code=303)
