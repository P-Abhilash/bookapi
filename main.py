# main.py

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from routers import auth, books, favorites, shelves, pages

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "super-secret-key"),  # use a real env secret in .env
    same_site="lax",
    https_only=False  # set True in production with HTTPS
)
# Mount static files (CSS, JS, images, etc.)
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Register routers
app.include_router(auth.router)
app.include_router(books.router)
app.include_router(favorites.router)
app.include_router(shelves.router)
app.include_router(pages.router)

