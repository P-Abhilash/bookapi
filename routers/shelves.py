# routers/shelves.py

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase_client import supabase
from core.security import get_current_user_email
import logging
cloud_logger = logging.getLogger("bookshelf")

router = APIRouter(tags=["shelves"])
templates = Jinja2Templates(directory="templates")


@router.post("/add-to-shelf")
async def add_to_shelf(
    request: Request,
    shelf_id: int = Form(...),
    book_id: str = Form(...),
    title: str = Form(...),
    authors: str = Form(...),
    thumbnail: str = Form(...)
):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login")

    # Check if book already in shelf
    existing = supabase.table("shelf_books") \
        .select("*") \
        .eq("shelf_id", shelf_id) \
        .eq("book_id", book_id) \
        .execute()

    if not existing.data:
        supabase.table("shelf_books").insert({
            "shelf_id": shelf_id,
            "book_id": book_id,
            "title": title,
            "authors": authors,
            "thumbnail": thumbnail
        }).execute()

    return RedirectResponse(url=f"/book/{book_id}", status_code=303)


@router.post("/remove-from-shelf")
async def remove_from_shelf(request: Request, shelf_id: int = Form(...), book_id: str = Form(...)):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login")

    supabase.table("shelf_books") \
        .delete() \
        .eq("shelf_id", shelf_id) \
        .eq("book_id", book_id) \
        .execute()

    return RedirectResponse(url=f"/book/{book_id}", status_code=303)


@router.get("/shelves", response_class=HTMLResponse)
async def shelves_page(request: Request):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login", status_code=302)

    shelves = supabase.table("shelves").select("*").eq("user_email", user_email).execute()
    return templates.TemplateResponse("shelves.html", {
        "request": request,
        "user": user_email,
        "shelves": shelves.data or []
    })


@router.post("/create-shelf")
async def create_shelf(request: Request, name: str = Form(...)):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login")
    cloud_logger.info(f"🪣 {user_email} created new shelf: {name}")
    # Prevent duplicate shelf
    existing = supabase.table("shelves") \
        .select("*") \
        .eq("user_email", user_email) \
        .eq("name", name) \
        .execute()

    if not existing.data:
        supabase.table("shelves").insert({
            "user_email": user_email,
            "name": name
        }).execute()

    return RedirectResponse(url="/shelves", status_code=303)


@router.post("/delete-shelf")
async def delete_shelf(request: Request, shelf_id: int = Form(...)):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login")
    
    cloud_logger.info(f"🗑️ {user_email} deleted shelf ID: {shelf_id}")
    # Delete all shelf books first
    supabase.table("shelf_books").delete().eq("shelf_id", shelf_id).execute()
    # Delete shelf
    supabase.table("shelves").delete().eq("id", shelf_id).eq("user_email", user_email).execute()

    return RedirectResponse(url="/shelves", status_code=303)


@router.get("/shelf/{shelf_id}", response_class=HTMLResponse)
async def view_shelf(shelf_id: int, request: Request):
    user_email = get_current_user_email(request)
    if not user_email:
        return RedirectResponse(url="/login")

    shelf = supabase.table("shelves").select("*").eq("id", shelf_id).eq("user_email", user_email).execute()
    if not shelf.data:
        raise HTTPException(status_code=404, detail="Shelf not found")

    books = supabase.table("shelf_books").select("*").eq("shelf_id", shelf_id).execute()

    return templates.TemplateResponse("shelf_detail.html", {
        "request": request,
        "user": user_email,
        "shelf": shelf.data[0],
        "books": books.data or []
    })
