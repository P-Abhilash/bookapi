# routers/books.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
from typing import Optional
import os
import urllib.parse
from supabase_client import supabase
from core.security import get_current_user_email
import httpx
import logging

cloud_logger = logging.getLogger("bookshelf")

CACHE_EXPIRY_HOURS = 72  # adjust to taste (3 days)

router = APIRouter(tags=["books"])
templates = Jinja2Templates(directory="templates")

GOOGLE_BOOKS_API = "https://www.googleapis.com/books/v1/volumes"
API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")


@router.get("/search", response_class=HTMLResponse)
async def search_books(
    request: Request, q: Optional[str] = None, filter: Optional[str] = ""
):
    user = get_current_user_email(request)
    if not user:
        return RedirectResponse(url="/login")

    books = []
    query = f"{filter}:{q}" if filter else q

    # --- Save query to Supabase search history (prevent duplicates) ---

    if query:
        existing = (
            supabase.table("search_history")
            .select("id")
            .eq("user_email", user)
            .eq("query", query)
            .execute()
            .data
        )

        if existing:
            # ✅ Update timestamp instead of adding duplicate
            supabase.table("search_history").update(
                {"created_at": datetime.utcnow().isoformat()}
            ).eq("id", existing[0]["id"]).execute()
        else:
            # ✅ Insert new if not found
            supabase.table("search_history").insert(
                {"user_email": user, "query": query}
            ).execute()

    # --- Fetch last 10 searches for display ---
    history_res = (
        supabase.table("search_history")
        .select("query")
        .eq("user_email", user)
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

    # --- Fetch books from Google Books API ---
    if query:
        async with httpx.AsyncClient() as client:
            try:
                cloud_logger.info(f"🔍 User {user} searched for: {query}")
                url = f"{GOOGLE_BOOKS_API}?q={urllib.parse.quote(query)}&key={API_KEY}"
                response = await client.get(url, timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    books = data.get("items", [])
            except Exception as e:
                print("Google Books API error:", e)

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "books": books,
            "query": q,
            "filter": filter,
            "user": user,
            "search_history_zipped": search_history_zipped,
        },
    )


@router.get("/book/{book_id}", response_class=HTMLResponse)
async def book_detail(book_id: str, request: Request):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login")

    # --- Check cache ---
    cache_result = (
        supabase.table("books_cache")
        .select("data, created_at")
        .eq("id", book_id)
        .execute()
        .data
    )

    book_data = None
    if cache_result:
        cached = cache_result[0]
        created_at = datetime.fromisoformat(cached["created_at"].ljust(26, "0"))
        if datetime.utcnow() - created_at < timedelta(hours=CACHE_EXPIRY_HOURS):
            book_data = cached["data"]

    # --- Fetch from Google Books if not cached ---
    if not book_data:
        async with httpx.AsyncClient() as client:
            # Try volumeId first
            try:
                url = f"{GOOGLE_BOOKS_API}/{book_id}?key={API_KEY}"
                response = await client.get(url, timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("volumeInfo"):
                        book_data = data
            except Exception as e:
                print("Volume ID fetch error:", e)

            # If not found, try ISBN fallback (still inside same client)
            if not book_data:
                try:
                    url = f"{GOOGLE_BOOKS_API}?q=isbn:{book_id}&key={API_KEY}"
                    response = await client.get(url, timeout=10.0)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("totalItems", 0) > 0:
                            book_data = data["items"][0]
                except Exception as e:
                    print("ISBN fetch error:", e)

        # Cache the result
        if book_data:
            try:
                title = book_data["volumeInfo"].get("title")
                authors = book_data["volumeInfo"].get("authors", [])
                thumbnail = (
                    book_data["volumeInfo"].get("imageLinks", {}).get("thumbnail")
                )
                supabase.table("books_cache").upsert(
                    {
                        "id": book_id,
                        "title": title,
                        "authors": authors,
                        "thumbnail": thumbnail,
                        "data": book_data,
                        "created_at": datetime.utcnow().isoformat(),
                    }
                ).execute()
            except Exception as e:
                print("Cache insert error:", e)

    # --- Not found handler ---
    if not book_data:
        return templates.TemplateResponse(
            "book_not_found.html",
            {"request": request, "user": user_email, "book_id": book_id},
            status_code=404,
        )

    # --- Log user viewing the book (safe handling) ---
    volume_info = (book_data or {}).get("volumeInfo", {})
    title = volume_info.get("title", "Unknown Title")

    if book_data:
        cloud_logger.info(f"👁️ {user_email} opened book: '{title}' (ID: {book_id})")
    else:
        cloud_logger.warning(
            f"⚠️ {user_email} tried to open a non-existent or invalid book (ID: {book_id})"
        )

    # --- Favorites ---
    fav_check = (
        supabase.table("favorites")
        .select("id")
        .eq("user_email", user_email)
        .eq("book_id", book_id)
        .execute()
        .data
    )
    is_favorite = bool(fav_check)

    # --- Shelves ---
    shelves_res = (
        supabase.table("shelves").select("*").eq("user_email", user_email).execute()
    )
    shelves = shelves_res.data or []

    shelf_books_res = (
        supabase.table("shelf_books")
        .select("shelf_id, book_id")
        .eq("book_id", book_id)
        .execute()
    )
    shelf_books = (
        [s["shelf_id"] for s in shelf_books_res.data] if shelf_books_res.data else []
    )

    # --- Save recently viewed book in Supabase ---
    if book_data:
        title = book_data["volumeInfo"].get("title", "Untitled")
        thumbnail = book_data["volumeInfo"].get("imageLinks", {}).get("thumbnail", "")

        # Remove duplicates
        supabase.table("recently_viewed").delete().eq("user_email", user_email).eq(
            "book_id", book_id
        ).execute()

        # Insert latest viewed book
        supabase.table("recently_viewed").insert(
            {
                "user_email": user_email,
                "book_id": book_id,
                "title": title,
                "thumbnail": thumbnail,
            }
        ).execute()

    # --- Render ---
    return templates.TemplateResponse(
        "book_detail.html",
        {
            "request": request,
            "book": book_data,
            "user": user_email,
            "is_favorite": is_favorite,
            "shelves": shelves,
            "shelf_books": shelf_books,
        },
    )
