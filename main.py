from fastapi import FastAPI, Depends, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from models import Favorite, Shelf, ShelfBook
from typing import Optional
import json
import urllib.request
import os

from models import User, SessionLocal, Base, engine
from starlette.middleware.sessions import SessionMiddleware




app = FastAPI()
Base.metadata.create_all(bind=engine)

app.add_middleware(SessionMiddleware, secret_key="supersecret123")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if user and user.password == form_data.password:
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(key="session_user", value=user.username, max_age=86400)
        return response
    raise HTTPException(status_code=401, detail="Incorrect username or password")

@app.post("/signup")
async def signup(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        return templates.TemplateResponse("signup.html", {"request": request, "error": "Username already exists"})
    new_user = User(username=username, password=password)
    db.add(new_user)
    db.commit()
    return templates.TemplateResponse("signup.html", {"request": request, "success": "User registered successfully! You can now log in."})

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@app.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_user")
    return response

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request, db: Session = Depends(get_db)):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login")

    favorites = db.query(Favorite).filter_by(username=user).limit(5).all()
    shelves = db.query(Shelf).filter_by(username=user).all()

    search_history = request.session.get("search_history", [])
    seen = set()
    search_history = [x for x in search_history if not (x in seen or seen.add(x))][-10:][::-1]

    viewed_books = request.session.get("viewed_books", [])
    print("RENDERING DASHBOARD WITH:", [b["title"] for b in viewed_books])

    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "favorites": favorites,
        "shelves": shelves,
        "search_history": search_history,
        "viewed_books": viewed_books
    })



@app.get("/search", response_class=HTMLResponse)
async def search_books(request: Request, q: Optional[str] = None):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login")
    books = []
    search_history = request.session.get("search_history", [])
    if q and q not in search_history:
        search_history.append(q)
        if len(search_history) > 10:
            search_history = search_history[-10:] 
        request.session["search_history"] = search_history


    if q:
        try:
            url = f"https://www.googleapis.com/books/v1/volumes?q={q}"
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read())
                books = data.get("items", [])
        except Exception as e:
            print("Error fetching from Google Books API:", e)
    return templates.TemplateResponse("search.html", {"request": request, "books": books, "query": q, "user": user})

@app.get("/book/{book_id}", response_class=HTMLResponse)
async def book_detail(book_id: str, request: Request, db: Session = Depends(get_db)):
    url = f"https://www.googleapis.com/books/v1/volumes/{book_id}"
    try:
        with urllib.request.urlopen(url) as response:
            book_data = json.loads(response.read())
    except:
        raise HTTPException(status_code=404, detail="Book not found")

    user = request.cookies.get("session_user")

    # Extract info
    title = book_data["volumeInfo"].get("title")
    thumbnail = book_data["volumeInfo"].get("imageLinks", {}).get("thumbnail")
    # Inside your /book/{book_id} route
    is_favorite = db.query(Favorite).filter_by(username=user, book_id=book_id).first() is not None


    # --- HANDLE VIEWED BOOKS ---
    viewed_books = request.session.get("viewed_books", [])
    viewed_books = [b for b in viewed_books if b["id"] != book_id]

    # Add to front
    viewed_books.insert(0, {
        "id": book_id,
        "title": title,
        "thumbnail": thumbnail
    })

    # Limit to 10
    request.session["viewed_books"] = viewed_books[:10]

    print("SESSION AFTER:", [b["title"] for b in request.session["viewed_books"]])

    # Fetch shelves & shelfBooks for current user
    shelves = []
    shelf_books = []
    if user:
        shelves = db.query(Shelf).filter_by(username=user).all()
        shelf_books = db.query(ShelfBook).filter_by(book_id=book_id).all()

    return templates.TemplateResponse("book_detail.html", {
    "request": request,
    "book": book_data,
    "user": user,
    "shelves": shelves,
    "shelf_books": [sb.shelf_id for sb in shelf_books],
    "is_favorite": is_favorite
})




@app.get("/favorites", response_class=HTMLResponse)
async def view_favorites(request: Request, db: Session = Depends(get_db)):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    favorites = db.query(Favorite).filter_by(username=user).all()

    return templates.TemplateResponse("favorites.html", {
        "request": request,
        "user": user,
        "favorites": favorites
    })


@app.post("/add-favorite")
async def add_favorite(
    request: Request,
    book_id: str = Form(...),
    title: str = Form(...),
    authors: str = Form(...),
    thumbnail: str = Form(...),
    db: Session = Depends(get_db)
):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Check if already exists
    existing = db.query(Favorite).filter_by(username=user, book_id=book_id).first()
    if not existing:
        fav = Favorite(
            username=user,
            book_id=book_id,
            title=title,
            authors=authors,
            thumbnail=thumbnail,
        )
        db.add(fav)
        db.commit()

    return RedirectResponse(url=f"/book/{book_id}", status_code=303)


@app.post("/remove-favorite")
async def remove_favorite(
    request: Request,
    book_id: str = Form(...),
    db: Session = Depends(get_db)
):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    db.query(Favorite).filter_by(username=user, book_id=book_id).delete()
    db.commit()

    return RedirectResponse(url=f"/book/{book_id}", status_code=303)


@app.post("/add-to-shelf")
async def add_to_shelf(
    request: Request,
    shelf_id: int = Form(...),
    book_id: str = Form(...),
    title: str = Form(...),
    authors: str = Form(...),
    thumbnail: str = Form(...),
    db: Session = Depends(get_db)
):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    existing = db.query(ShelfBook).filter_by(shelf_id=shelf_id, book_id=book_id).first()
    if not existing:
        entry = ShelfBook(
            shelf_id=shelf_id,
            book_id=book_id,
            title=title,
            authors=authors,
            thumbnail=thumbnail
        )
        db.add(entry)
        db.commit()

    return RedirectResponse(url=f"/book/{book_id}", status_code=303)


@app.post("/remove-from-shelf")
async def remove_from_shelf(
    request: Request,
    shelf_id: int = Form(...),
    book_id: str = Form(...),
    db: Session = Depends(get_db)
):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    db.query(ShelfBook).filter_by(shelf_id=shelf_id, book_id=book_id).delete()
    db.commit()

    return RedirectResponse(url=f"/book/{book_id}", status_code=303)

@app.get("/shelves", response_class=HTMLResponse)
async def shelves_page(request: Request, db: Session = Depends(get_db)):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    shelves = db.query(Shelf).filter_by(username=user).all()
    return templates.TemplateResponse("shelves.html", {
        "request": request,
        "user": user,
        "shelves": shelves
    })

@app.post("/create-shelf")
async def create_shelf(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    existing = db.query(Shelf).filter_by(username=user, name=name).first()
    if not existing:
        shelf = Shelf(username=user, name=name)
        db.add(shelf)
        db.commit()

    return RedirectResponse(url="/shelves", status_code=303)

@app.post("/delete-shelf")
async def delete_shelf(request: Request, shelf_id: int = Form(...), db: Session = Depends(get_db)):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    db.query(ShelfBook).filter_by(shelf_id=shelf_id).delete()
    db.query(Shelf).filter_by(id=shelf_id).delete()
    db.commit()

    return RedirectResponse(url="/shelves", status_code=303)


@app.get("/shelf/{shelf_id}", response_class=HTMLResponse)
async def view_shelf(shelf_id: int, request: Request, db: Session = Depends(get_db)):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    shelf = db.query(Shelf).filter_by(id=shelf_id, username=user).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="Shelf not found")

    books = db.query(ShelfBook).filter_by(shelf_id=shelf_id).all()

    return templates.TemplateResponse("shelf_detail.html", {
        "request": request,
        "user": user,
        "shelf": shelf,
        "books": books
    })


@app.get("/clear-recently-viewed")
async def clear_recently_viewed(request: Request):
    request.session["viewed_books"] = []
    return RedirectResponse(url="/", status_code=303)
