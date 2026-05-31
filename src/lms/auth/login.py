"""Login and logout routes + session-aware auth dependency.

This module ships the production-side of LMS authentication: a Pico-styled
``/login`` form, a ``/logout`` route, and a dependency
(:func:`require_authenticated_user`) that the deployed instance uses in place
of the local-dev shortcut.

Design notes:

- Sessions are server-signed cookies handled by Starlette's
  :class:`SessionMiddleware`, which uses ``itsdangerous`` internally. We only
  store the user's stable id (``user_id``) in the session payload — never the
  username, display name, or any other PII. That keeps the cookie small and
  means a stolen session can't be re-decoded into account metadata; the
  attacker would still need to query the DB.
- The login form POSTs to ``/login``; the same handler serves the GET render.
  On success the user is redirected back to the ``next`` query parameter
  (validated to be a same-origin path) or to ``/app/learner``.
- ``/logout`` is a POST (per OWASP CSRF guidance, logout should never be
  triggered by a cross-site GET). The form on the navbar submits to it.
- The ``require_authenticated_user`` dependency raises ``HTTPException(401)``
  for API requests and redirects for HTML requests. We disambiguate via the
  ``Accept`` header, which is the simplest reliable signal available before
  routing happens.
"""

from __future__ import annotations

from typing import Annotated, NoReturn
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.auth.repository import (
    LOCAL_DEV_USERNAME,
    authenticate,
    get_or_create_local_dev_user,
    get_user,
)
from lms.db.session import get_session
from lms.settings import Settings, get_settings
from lms.ui.shell import render_page

router = APIRouter(tags=["auth"])
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

SESSION_USER_ID_KEY = "user_id"
DEFAULT_POST_LOGIN_PATH = "/app/learner"


def _safe_next_path(candidate: str | None) -> str:
    """Return a same-origin path safe to redirect to after login.

    Rejects anything that isn't a plain path starting with ``/`` and not with
    ``//`` (which browsers interpret as a protocol-relative URL). This blocks
    the open-redirect class of bugs without requiring a full URL parser.
    """
    if not candidate:
        return DEFAULT_POST_LOGIN_PATH
    if not candidate.startswith("/"):
        return DEFAULT_POST_LOGIN_PATH
    if candidate.startswith("//"):
        return DEFAULT_POST_LOGIN_PATH
    return candidate


def _render_login_page(*, next_path: str, error: str | None = None) -> str:
    """Render the Pico-styled login form."""
    from html import escape

    error_block = (
        f'<p role="alert" class="login-error" style="color:var(--pico-color-red-500);">'
        f"{escape(error)}</p>"
        if error
        else ""
    )
    body = f"""
    <main class="surface app-surface login-surface">
      <header>
        <p class="eyebrow">Sign in</p>
        <h1>Learning Management System</h1>
      </header>
      <article style="max-width:32rem;">
        {error_block}
        <form method="post" action="/login">
          <input type="hidden" name="next" value="{escape(next_path)}">
          <label for="username">Username
            <input type="text" id="username" name="username"
                   required autocomplete="username" autofocus>
          </label>
          <label for="password">Password
            <input type="password" id="password" name="password"
                   required autocomplete="current-password">
          </label>
          <button type="submit">Sign in</button>
        </form>
      </article>
    </main>
    """
    return render_page("Sign in", body)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str | None = None) -> HTMLResponse:
    """Render the login form.

    If the caller already has a valid session, send them to the post-login
    destination instead of re-prompting.
    """
    next_path = _safe_next_path(next)
    if SESSION_USER_ID_KEY in request.session:
        return HTMLResponse(  # 303 isn't appropriate for a GET-only response,
            status_code=status.HTTP_200_OK,  # so render a tiny redirect page.
            content=("<!doctype html><meta http-equiv='refresh' " f"content='0; url={next_path}'>"),
            headers={"Location": next_path},
        )
    return HTMLResponse(content=_render_login_page(next_path=next_path))


@router.post("/login")
def login_submit(
    request: Request,
    session: SessionDep,
    username: Annotated[str, Form(...)],
    password: Annotated[str, Form(...)],
    next: Annotated[str | None, Form()] = None,
) -> Response:
    """Validate credentials and start a session.

    On success: writes ``user_id`` into the signed session cookie and 303s
    to the validated ``next`` path. On failure: re-renders the form with a
    generic error message (we deliberately don't say whether the username or
    the password was wrong, to avoid username enumeration).
    """
    next_path = _safe_next_path(next)
    user = authenticate(session, username=username, password=password)
    if user is None:
        return HTMLResponse(
            content=_render_login_page(
                next_path=next_path,
                error="Invalid username or password.",
            ),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    session.commit()
    request.session[SESSION_USER_ID_KEY] = user.id
    return RedirectResponse(url=next_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    """Clear the session and redirect to the login page."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


def _wants_html(request: Request) -> bool:
    """Return True when the caller looks like a browser navigation.

    We treat any request whose ``Accept`` header advertises ``text/html`` as
    a browser. Pure-API callers (the JSON endpoints under ``/api/*``) tend to
    send ``Accept: application/json`` or no Accept at all and should receive
    401 instead of an HTML redirect.
    """
    accept = request.headers.get("accept", "")
    return "text/html" in accept.lower()


def require_authenticated_user(
    request: Request, session: SessionDep, settings: SettingsDep
) -> User:
    """Return the authenticated user or refuse the request.

    Behavior depends on ``Settings.auth_required``:

    - **auth_required=False** (local dev, tests): returns the local-dev
      shortcut user, preserving the pre-auth behavior so the existing test
      suite and dev workflow keep working.
    - **auth_required=True** (deployed): looks up the user id from the signed
      session cookie. If no session exists, raises 401 (JSON callers) or
      302-redirects to /login with a ``next`` param (HTML callers).

    Settings is injected via Depends rather than read from ``get_settings()``
    directly so tests can flip ``auth_required`` via ``dependency_overrides``
    without subverting the ``@lru_cache`` on the production accessor.
    """
    if not settings.auth_required:
        return get_or_create_local_dev_user(session)

    user_id = request.session.get(SESSION_USER_ID_KEY)
    if not user_id:
        _raise_unauthenticated(request)
    user = get_user(session, user_id)
    if user is None:
        # Stale session pointing at a deleted user.
        request.session.clear()
        _raise_unauthenticated(request)
    return user


def _raise_unauthenticated(request: Request) -> NoReturn:
    """Raise the right kind of failure for the caller (HTML redirect vs 401)."""
    if _wants_html(request):
        # Preserve the originally requested path so the user lands back there
        # after a successful login.
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"
        next_param = urlencode({"next": target}, quote_via=quote)
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": f"/login?{next_param}"},
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


# Re-export the canonical username for tests / scripts that need it.
__all__ = [
    "DEFAULT_POST_LOGIN_PATH",
    "LOCAL_DEV_USERNAME",
    "SESSION_USER_ID_KEY",
    "require_authenticated_user",
    "router",
]
