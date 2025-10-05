# routers/auth.py
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase_client import supabase
import logging
cloud_logger = logging.getLogger("bookshelf")

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="templates")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    try:
        session = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if not session.user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # ✅ Save both UUID + Email in session
        request.session["user"] = {
            "id": session.user.id,       # UUID
            "email": session.user.email  # For display
        }
        
        resp = RedirectResponse(url="/", status_code=302)
        resp.set_cookie("access_token", session.session.access_token, httponly=True, max_age=86400)
        cloud_logger.info(f"🔍 User {session.user.email} logged in")
        return resp
    except Exception as e:
        return templates.TemplateResponse("login.html", {"request": request, "error": str(e)})

@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@router.post("/signup")
async def signup(request: Request, email: str = Form(...), password: str = Form(...)):
    try:
        user = supabase.auth.sign_up({"email": email, "password": password})
        if user.user:
            cloud_logger.info(f"User {email} signed up")
            return templates.TemplateResponse("signup.html", {"request": request,
                                                             "success": "✅ Check your email to confirm your account."})
        return templates.TemplateResponse("signup.html", {"request": request, "error": "Failed to create user"})
    except Exception as e:
        return templates.TemplateResponse("signup.html", {"request": request, "error": str(e)})

@router.get("/logout")
async def logout(request: Request):
    user = request.session.get("user")  # ⬅️ Grab user info before clearing session
    user_email = user["email"] if user else "Unknown"

    # Clear user session and cookies
    request.session.clear()
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")

    cloud_logger.info(f"👋 User {user_email} logged out")
    return resp
