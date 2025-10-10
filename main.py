import os
from fastapi import FastAPI
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from routers import auth, books, favorites, shelves, pages
import google.cloud.logging
from google.cloud.logging.handlers import CloudLoggingHandler
import logging

# Load .env so GOOGLE_APPLICATION_CREDENTIALS is available
load_dotenv()

if "SERVICE_ACCOUNT_JSON" in os.environ:
    sa_path = "/tmp/service-account.json"
    with open(sa_path, "w") as f:
        f.write(os.environ["SERVICE_ACCOUNT_JSON"])
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = sa_path
app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "super-secret-key"),  # keep this constant!
    session_cookie="bookshelf_session",
    max_age=60 * 60 * 24 * 7,  # 7 days = persistent login
    same_site="lax",
    https_only=False  # True if using HTTPS in production
)

# Ensure the environment variable points to your key file
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

try:
    client = google.cloud.logging.Client(project="bookshelf-473905")
    handler = CloudLoggingHandler(client)

    cloud_logger = logging.getLogger("bookshelf")
    cloud_logger.setLevel(logging.INFO)
    cloud_logger.addHandler(handler)

    cloud_logger.info("✅ Cloud Logging initialized successfully using service-account.json.")
except Exception as e:
    # Fallback to local logging if Cloud Logging fails
    logging.basicConfig(level=logging.INFO)
    cloud_logger = logging.getLogger("bookshelf")
    cloud_logger.warning(f"⚠️ Could not initialize Cloud Logging: {e}")
# Mount static files (CSS, JS, images, etc.)
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Register routers
app.include_router(auth.router)
app.include_router(books.router)
app.include_router(favorites.router)
app.include_router(shelves.router)
app.include_router(pages.router)