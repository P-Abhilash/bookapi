# routers/favorites.py
import urllib.request, json
import os

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase_client import supabase
from core.security import get_current_user_email
import logging
from fastapi import Body

cloud_logger = logging.getLogger("bookshelf")


router = APIRouter(tags=["favorites"])
templates = Jinja2Templates(directory="templates")

API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")


@router.get("/favorites", response_class=HTMLResponse)
async def view_favorites(request: Request):
    """View all favorites for the logged-in user"""
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    user_email = user["email"]
    result = (
        supabase.table("favorites").select("*").eq("user_email", user_email).execute()
    )
    favorites = result.data or []

    return templates.TemplateResponse(
        "favorites.html",
        {"request": request, "user": user, "favorites": favorites},
    )


@router.post("/remove-favorite")
async def remove_favorite(request: Request, book_id: str = Form(...)):
    """Remove a book from favorites"""
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    user_email = user["email"]
    cloud_logger.info(f"💔 {user_email} removed book {book_id} from favorites")
    supabase.table("favorites").delete().eq("user_email", user).eq(
        "book_id", book_id
    ).execute()

    return RedirectResponse(url=f"/favorites", status_code=303)


@router.post("/favorite-json")
async def toggle_favorite_json(request: Request, data: dict = Body(...)):
    user_email = get_current_user_email(request)
    if not user_email:
        return {"success": False, "message": "Unauthorized"}

    book_id = data.get("book_id")
    title = data.get("title")
    authors = data.get("authors")
    thumbnail = data.get("thumbnail")
    is_favorite = data.get("is_favorite")

    if is_favorite:
        # 💔 Remove from favorites
        supabase.table("favorites").delete().eq("user_email", user_email).eq(
            "book_id", book_id
        ).execute()
        cloud_logger.info(f"💔 {user_email} removed {book_id} from favorites")
        return {"success": True, "action": "removed"}

    else:
        # --- Try to get categories from cached book data ---
        categories = ""
        try:
            cached = (
                supabase.table("books_cache")
                .select("data")
                .eq("id", book_id)
                .execute()
                .data
            )
            if cached and "volumeInfo" in cached[0]["data"]:
                cats = cached[0]["data"]["volumeInfo"].get("categories", [])
                if cats:
                    categories = ", ".join(cats)
        except Exception as e:
            print("⚠️ Cache lookup failed:", e)

        # --- Fallback: fetch directly from Google Books if not cached ---
        if not categories:
            try:
                import urllib.request

                url = f"https://www.googleapis.com/books/v1/volumes/{book_id}?key={API_KEY}"
                with urllib.request.urlopen(url) as response:
                    data = json.loads(response.read())
                    cats = data.get("volumeInfo", {}).get("categories", [])
                    if cats:
                        categories = ", ".join(cats)
            except Exception as e:
                print("⚠️ Could not fetch categories:", e)

        # --- Save favorite with categories ---
        existing = (
            supabase.table("favorites")
            .select("*")
            .eq("user_email", user_email)
            .eq("book_id", book_id)
            .execute()
        )

        if not existing.data:
            supabase.table("favorites").insert(
                {
                    "user_email": user_email,
                    "book_id": book_id,
                    "title": title,
                    "authors": authors,
                    "thumbnail": thumbnail,
                    "categories": categories,
                }
            ).execute()

        cloud_logger.info(
            f"💖 {user_email} added '{title}' with categories: {categories}"
        )
        return {"success": True, "action": "added"}
