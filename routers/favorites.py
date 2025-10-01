# routers/favorites.py
import urllib.request, json

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase_client import supabase
from core.security import get_current_user_email

router = APIRouter(tags=["favorites"])
templates = Jinja2Templates(directory="templates")


@router.get("/favorites", response_class=HTMLResponse)
async def view_favorites(request: Request):
    """View all favorites for the logged-in user"""
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login", status_code=302)

    result = supabase.table("favorites").select("*").eq("user_email", user_email).execute()
    favorites = result.data or []

    return templates.TemplateResponse("favorites.html", {
        "request": request,
        "user": user_email,
        "favorites": favorites
    })


@router.post("/add-favorite")
async def add_favorite(
    request: Request,
    book_id: str = Form(...),
    title: str = Form(...),
    authors: str = Form(...),
    thumbnail: str = Form(...)
):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login", status_code=302)

    # --- Fetch categories once from Google Books ---
    categories = ""
    try:
        url = f"https://www.googleapis.com/books/v1/volumes/{book_id}"
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read())
            volume_info = data.get("volumeInfo", {})
            cats = volume_info.get("categories", [])
            if cats:
                categories = ", ".join(cats)
    except Exception as e:
        print("⚠️ Could not fetch categories:", e)

    # --- Prevent duplicates ---
    existing = supabase.table("favorites") \
        .select("*") \
        .eq("user_email", user_email) \
        .eq("book_id", book_id) \
        .execute()

    if not existing.data:
        supabase.table("favorites").insert({
            "user_email": user_email,
            "book_id": book_id,
            "title": title,
            "authors": authors,
            "thumbnail": thumbnail,
            "categories": categories
        }).execute()

    return RedirectResponse(url=f"/book/{book_id}", status_code=303)

@router.post("/remove-favorite")
async def remove_favorite(request: Request, book_id: str = Form(...)):
    """Remove a book from favorites"""
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login", status_code=302)

    supabase.table("favorites") \
        .delete() \
        .eq("user_email", user_email) \
        .eq("book_id", book_id) \
        .execute()

    return RedirectResponse(url=f"/book/{book_id}", status_code=303)
