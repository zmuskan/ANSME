"""Supabase access-token verification for protected API routes."""

from __future__ import annotations

import os
from uuid import UUID

import httpx
from fastapi import Header, HTTPException, status


def get_current_user_id(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> UUID:
    """Verify a Supabase access token and return its authenticated user UUID."""
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, separator, access_token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not access_token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    supabase_url = (
        os.getenv("SUPABASE_URL", "").strip()
        or os.getenv("VITE_SUPABASE_URL", "").strip()
    ).rstrip("/")
    anon_key = (
        os.getenv("SUPABASE_ANON_KEY", "").strip()
        or os.getenv("VITE_SUPABASE_ANON_KEY", "").strip()
    )
    if not supabase_url or not anon_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Supabase token verification is not configured on the backend. "
                "Set SUPABASE_URL and SUPABASE_ANON_KEY, or the matching "
                "VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY values, for the "
                "same Supabase project used by the frontend."
            ),
        )

    try:
        response = httpx.get(
            f"{supabase_url}/auth/v1/user",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {access_token.strip()}",
            },
            timeout=5.0,
        )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable",
        ) from error

    if response.status_code in (400, 401, 403):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not response.is_success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable",
        )

    try:
        user_id = UUID(response.json()["id"])
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    return user_id
