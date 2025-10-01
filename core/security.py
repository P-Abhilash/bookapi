# core/security.py
from fastapi import Request
from supabase_client import supabase

def get_current_user_email(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        user = supabase.auth.get_user(token)
        return user.user.email
    except Exception:
        return None
