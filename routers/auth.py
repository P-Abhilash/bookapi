# routers/auth.py
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase_client import supabase
import os, logging
from urllib.parse import urlencode

cloud_logger = logging.getLogger("bookshelf")

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="templates")

SUPABASE_URL = os.getenv("SUPABASE_URL")
# Automatically use local or deployed redirect URL
REDIRECT_URL = os.getenv("SUPABASE_REDIRECT_URL", "http://127.0.0.1:8000/auth/callback")


# --- Login Page ---
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


# --- Email/Password Login ---
@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    try:
        session = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        if not session.user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Save user in session
        request.session["user"] = {
            "id": session.user.id,
            "email": session.user.email,
            "username": (
                session.user.user_metadata.get("username")
                if session.user.user_metadata
                else None
            ),
        }

        resp = RedirectResponse(url="/", status_code=302)
        resp.set_cookie(
            "access_token", session.session.access_token, httponly=True, max_age=86400
        )
        cloud_logger.info(f"🔍 {session.user.email} logged in (email/password)")
        return resp
    except Exception as e:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": str(e)}
        )


# --- Sign Up Page ---
@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


# --- Email/Password Sign Up ---
@router.post("/signup")
async def signup(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    try:
        # ✅ Length validation (server-side)
        if len(username) < 3 or len(username) > 20:
            return templates.TemplateResponse(
                "signup.html",
                {
                    "request": request,
                    "error": "Username must be between 3 and 20 characters.",
                },
            )

        # Create user in Supabase with metadata for username
        user = supabase.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {"data": {"username": username}},
            }
        )

        if user.user:
            cloud_logger.info(
                f"✅ {email} signed up successfully with username {username}"
            )

            request.session["user"] = {
                "id": user.user.id,
                "email": user.user.email,
                "username": username,
            }

            return templates.TemplateResponse(
                "signup.html",
                {
                    "request": request,
                    "success": "✅ Account created! Check your email to confirm your account.",
                },
            )

        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": "Failed to create user"}
        )

    except Exception as e:
        cloud_logger.error(f"Signup failed: {e}")
        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": str(e)}
        )


# --- Google Login (OAuth) ---
@router.get("/login/google")
async def google_login():
    """Start Supabase Google OAuth (PKCE flow)."""
    try:
        # Use the environment variable for redirect URL
        redirect_to = os.getenv(
            "SUPABASE_REDIRECT_URL", "http://127.0.0.1:8000/auth/callback"
        )

        cloud_logger.info(f"🔐 Starting Google OAuth with redirect: {redirect_to}")

        # Use Supabase's built-in OAuth sign-in
        response = supabase.auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {
                    "redirect_to": redirect_to,
                    "query_params": {"access_type": "offline", "prompt": "consent"},
                },
            }
        )

        if response and hasattr(response, "url"):
            cloud_logger.info(f"🔗 Redirecting to: {response.url}")
            return RedirectResponse(url=response.url)
        else:
            cloud_logger.error("No URL in OAuth response")
            raise HTTPException(status_code=500, detail="OAuth initialization failed")

    except Exception as e:
        cloud_logger.error(f"Google OAuth init failed: {e}")
        raise HTTPException(status_code=500, detail="OAuth initialization failed")


# --- OAuth Callback ---
@router.get("/auth/callback")
async def auth_callback(request: Request):
    """
    Handle Supabase redirect after Google OAuth.
    """
    try:
        # Get the URL parameters
        code = request.query_params.get("code")
        error = request.query_params.get("error")
        error_description = request.query_params.get("error_description")

        cloud_logger.info(f"Callback received - code: {bool(code)}, error: {error}")

        if error:
            cloud_logger.error(f"OAuth error: {error} - {error_description}")
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": f"Google login failed: {error_description or error}",
                },
            )

        if not code:
            cloud_logger.error("No authorization code received in callback")
            # Log all query parameters for debugging
            all_params = dict(request.query_params)
            cloud_logger.error(f"All query params: {all_params}")
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "No authorization code received. Please try again.",
                },
            )

        # Exchange the code for a session
        try:
            session = supabase.auth.exchange_code_for_session({"auth_code": code})

            if not session or not session.user:
                cloud_logger.error("Code exchange failed - no session or user")
                raise HTTPException(status_code=401, detail="Code exchange failed")

            user = session.user

            # --- Handle Google user username setup ---
            username = None

            # If metadata already has a username, use it
            if user.user_metadata and "username" in user.user_metadata:
                username = user.user_metadata["username"]
            else:
                # Otherwise create one from full_name or email prefix
                base_name = None
                if user.user_metadata and "full_name" in user.user_metadata:
                    base_name = user.user_metadata["full_name"].split(" ")[0]
                else:
                    base_name = user.email.split("@")[0]
                username = base_name

                # Save username in Supabase metadata
                try:
                    supabase.auth.update_user({"data": {"username": username}})
                    # Refresh user info so the session gets updated metadata
                    refreshed = supabase.auth.get_user(session.session.access_token)
                    if refreshed and refreshed.user:
                        user = refreshed.user
                except Exception as meta_err:
                    cloud_logger.warning(f"Could not set username metadata: {meta_err}")

            # --- Store user in session ---
            request.session["user"] = {
                "id": user.id,
                "email": user.email,
                "username": username,
                "access_token": session.session.access_token,
            }

            resp = RedirectResponse(url="/", status_code=302)
            resp.set_cookie(
                "access_token",
                session.session.access_token,
                httponly=True,
                max_age=86400,
                secure=True,  # False locally, True in production
                samesite="lax",
            )

            cloud_logger.info(
                f"🌐 Google login success: {user.email} (username: {username})"
            )
            return resp

        except Exception as exchange_error:
            cloud_logger.error(f"Code exchange error: {exchange_error}")
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "Authentication failed during code exchange.",
                },
            )

    except Exception as e:
        cloud_logger.error(f"OAuth callback failed: {str(e)}")
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Google login failed. Please try again."},
        )


# --- Logout ---
@router.get("/logout")
async def logout(request: Request):
    user = request.session.get("user")
    user_email = user["email"] if user else "Unknown"

    request.session.clear()
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")

    cloud_logger.info(f"👋 {user_email} logged out")
    return resp


# --- Forgot Password Page ---
@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request})


# --- Handle Forgot Password Submission ---
@router.post("/forgot-password")
async def forgot_password(request: Request, email: str = Form(...)):
    try:
        redirect_url = os.getenv(
            "SUPABASE_RESET_REDIRECT", "http://127.0.0.1:8000/reset-password"
        )
        supabase.auth.reset_password_for_email(email, {"redirect_to": redirect_url})
        cloud_logger.info(f"📩 Password reset email sent to {email}")
        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "success": "✅ A reset link has been sent to your email. Please check your inbox.",
            },
        )
    except Exception as e:
        cloud_logger.error(f"Password reset request failed: {e}")
        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "error": "Failed to send reset email. Try again later.",
            },
        )


# --- Reset Password Page ---
@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    return templates.TemplateResponse("reset_password.html", {"request": request})


# --- Handle Reset Password Submission ---
@router.post("/reset-password")
async def reset_password(request: Request, password: str = Form(...)):
    try:
        supabase.auth.update_user({"password": password})
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "success": "✅ Password updated successfully. You can now sign in.",
            },
        )
    except Exception as e:
        cloud_logger.error(f"Reset password failed: {e}")
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "error": "Failed to reset password. Please try again.",
            },
        )
