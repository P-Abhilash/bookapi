# routers/auth.py
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase_client import supabase

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
        resp = RedirectResponse(url="/", status_code=302)
        resp.set_cookie("access_token", session.session.access_token, httponly=True, max_age=86400)
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
            return templates.TemplateResponse("signup.html", {"request": request,
                                                             "success": "✅ Check your email to confirm your account."})
        return templates.TemplateResponse("signup.html", {"request": request, "error": "Failed to create user"})
    except Exception as e:
        return templates.TemplateResponse("signup.html", {"request": request, "error": str(e)})

@router.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp
