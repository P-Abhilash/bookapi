# routers/books.py
from fastapi import FastAPI, Depends, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from models import Favorite, Shelf, ShelfBook
from typing import Optional
import json
import urllib.request, urllib.parse
from fastapi import FastAPI, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from supabase_client import supabase
import os
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import requests
from core.deps import get_db
from core.security import get_current_user_email
from models import Favorite

router = APIRouter(tags=["books"])
templates = Jinja2Templates(directory="templates")

GOOGLE_BOOKS_API = "https://www.googleapis.com/books/v1/volumes"

@router.get("/search", response_class=HTMLResponse)
async def search_books(request: Request,q: Optional[str] = None,filter: Optional[str] = "",db: Session = Depends(get_db)):
    user = get_current_user_email(request)
    if not user:
        return RedirectResponse(url="/login")

    books = []

    # Get or initialize session history
    search_history_raw = request.session.get(f"search_history_{user}", [])

    # Construct query
    query = f"{filter}:{q}" if filter else q

    # Add to history ONLY if query is valid and not a duplicate
    if query and query not in search_history_raw:
        search_history_raw.append(query)
        request.session[f"search_history_{user}"] = search_history_raw[-10:]  # keep last 10

    # Build display-friendly version
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

    # Combine both for display
    search_history_zipped = list(zip(search_history_raw, search_history_display))

    # Fetch books
    if query:
        try:
            url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(query)}"
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read())
                books = data.get("items", [])
        except Exception as e:
            print("Google Books API error:", e)
            url = "Failed"
    else:
        url = "None"

    return templates.TemplateResponse("search.html", {
        "request": request,
        "books": books,
        "query": q,
        "filter": filter,
        "user": user,
        "search_history_zipped": search_history_zipped,
    })



@router.get("/book/{book_id}", response_class=HTMLResponse)
async def book_detail(book_id: str, request: Request, db: Session = Depends(get_db)):
    url = f"https://www.googleapis.com/books/v1/volumes/{book_id}"
    try:
        with urllib.request.urlopen(url) as response:
            book_data = json.loads(response.read())
    except:
        raise HTTPException(status_code=404, detail="Book not found")

    user = get_current_user_email(request)
    if not user:
        return RedirectResponse(url="/login")

    # Extract info
    title = book_data["volumeInfo"].get("title")
    thumbnail = book_data["volumeInfo"].get("imageLinks", {}).get("thumbnail")
    # Inside your /book/{book_id} route
    is_favorite = (
    supabase.table("favorites")
    .select("id")
    .eq("user_email", user)
    .eq("book_id", book_id)
    .execute()
    .data
)
    is_favorite = len(is_favorite) > 0



    # --- HANDLE VIEWED BOOKS ---
    viewed_books = request.session.get(f"viewed_books_{user}", [])
    viewed_books = [b for b in viewed_books if b["id"] != book_id]

    # Add to front
    viewed_books.insert(0, {
        "id": book_id,
        "title": title,
        "thumbnail": thumbnail
    })

    # Limit to 10
    request.session[f"viewed_books_{user}"] = viewed_books[:10]

    # Fetch shelves & shelfBooks for current user
    shelves = []
    shelf_books = []
    if user:
        # Fetch shelves & shelfBooks for current user (Supabase)
        shelves = (
            supabase.table("shelves")
            .select("*")
            .eq("user_email", user)
            .execute()
            .data or []
        )

        shelf_books = (
            supabase.table("shelf_books")
            .select("shelf_id")
            .eq("book_id", book_id)
            .execute()
            .data or []
        )

    return templates.TemplateResponse("book_detail.html", {
        "request": request,
        "book": book_data,
        "user": user,
        "shelves": shelves,
        "shelf_books": [sb["shelf_id"] for sb in shelf_books],
        "is_favorite": is_favorite
    })

