"""Local live-scraping API. Start with python main.py; PostgreSQL is not used."""
import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from src.scraper.live import LiveScraper, LiveScrapeError


class SearchInput(BaseModel):
    query: str = Field(min_length=3, max_length=300)


class StateInput(BaseModel):
    session_state: str | None = Field(default=None, max_length=2_000_000)


class CaptchaInput(StateInput):
    captcha: str = Field(min_length=1, max_length=20)


class ProjectInput(StateInput):
    registration_number: str = Field(min_length=1, max_length=60)


def create_app(scraper=None):
    live = scraper or LiveScraper()
    hosted = None
    if os.environ.get("VERCEL") or os.environ.get("RERA_STATELESS"):
        from src.scraper.hosted_sessions import HostedSessions
        key = os.environ.get("RERA_SESSION_KEY")
        if not key:
            raise RuntimeError("RERA_SESSION_KEY must be configured for hosted searches")
        hosted = HostedSessions(key)

    def execute(method, *args, state=None):
        if hosted:
            return hosted.execute(method, *args, session_state=state)
        return getattr(live, method)(*args)

    @asynccontextmanager
    async def lifespan(app):
        async def cleanup():
            while True:
                await asyncio.sleep(30)
                await asyncio.to_thread(live.prune)
        task = asyncio.create_task(cleanup())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        live.close()

    app = FastAPI(title="Live UP-RERA Scraper", version="2.0.0", lifespan=lifespan,
                  description="Fetch a requested project directly from RERA. No database or stored-project fallback.")
    app.state.live_scraper = live

    @app.middleware("http")
    async def no_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(LiveScrapeError)
    async def scrape_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={
            "status": "error", "code": exc.code, "message": str(exc),
        })

    @app.exception_handler(requests.RequestException)
    async def network_error(request, exc):
        return JSONResponse(status_code=502, content={
            "status": "error", "code": "source_unavailable",
            "message": "The live RERA request failed or timed out. Please try again.",
        })

    @app.get("/", response_class=HTMLResponse)
    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        return Path(__file__).with_name("live_dashboard.html").read_text(encoding="utf-8")

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "live", "database_required": False,
                "persistent_cache": False, "supported_sources": ["UP-RERA"]}

    @app.post("/api/live/search")
    def search(body: SearchInput):
        return execute('start', body.query)

    @app.post("/api/live/search/{session_id}/captcha")
    def captcha(session_id: str, body: CaptchaInput):
        return execute('submit_captcha', session_id, body.captcha, state=body.session_state)

    @app.post("/api/live/search/{session_id}/refresh-captcha")
    def refresh_captcha(session_id: str, body: StateInput):
        return execute('refresh_captcha', session_id, state=body.session_state)

    @app.post("/api/live/search/{session_id}/project")
    def select_project(session_id: str, body: ProjectInput):
        return execute('select', session_id, body.registration_number, state=body.session_state)

    @app.post("/api/live/search/{session_id}/more")
    def more_matches(session_id: str, body: StateInput):
        return execute('next_matches', session_id, state=body.session_state)

    @app.delete("/api/live/search/{session_id}")
    def cancel(session_id: str):
        if not hosted:
            live.cancel(session_id)
        return {"status": "cancelled"}

    return app


app = create_app()
