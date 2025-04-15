from fastapi import FastAPI, Depends, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Optional
import json
import urllib.request

from models import User, SessionLocal, Base, engine

app = FastAPI()
Base.metadata.create_all(bind=engine)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

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
async def homepage(request: Request):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/search", response_class=HTMLResponse)
async def search_books(request: Request, q: Optional[str] = None):
    user = request.cookies.get("session_user")
    if not user:
        return RedirectResponse(url="/login")
    books = []
    if q:
        try:
            url = f"https://www.googleapis.com/books/v1/volumes?q={q}"
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read())
                books = data.get("items", [])
        except Exception as e:
            print("Error fetching from Google Books API:", e)
    return templates.TemplateResponse("search.html", {"request": request, "books": books, "query": q, "user": user})
