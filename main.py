from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from config import AppSettings, get_settings
from database import archive_project, create_project, get_project, init_db, list_projects


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    primary_term: str = Field(min_length=1)
    bbox: str = Field(min_length=1)
    extra_terms: list[str] = Field(default_factory=list)
    colour: str | None = None
    min_cell_degrees: float = 0.005


def create_app(settings_override: AppSettings | None = None) -> FastAPI:
    settings = settings_override or get_settings()
    app = FastAPI(title="Scraper Pro", version="0.1.0")
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.state.settings = settings

    @app.on_event("startup")
    def startup() -> None:
        init_db(settings.scraper_db_path)

    def resolve_active_project(project_id: str | None) -> dict | None:
        if project_id:
            return get_project(project_id, settings.scraper_db_path)
        projects = list_projects(settings.scraper_db_path)
        return projects[0] if projects else None

    def shell_context(request: Request, active_page: str, project_id: str | None) -> dict:
        projects = list_projects(settings.scraper_db_path)
        active_project = resolve_active_project(project_id)
        if project_id and active_project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        return {
            "request": request,
            "title": "Scraper Pro",
            "active_page": active_page,
            "projects": projects,
            "active_project": active_project,
        }

    @app.get("/", response_class=HTMLResponse)
    def root(
        request: Request,
        project_id: Annotated[str | None, Query()] = None,
    ) -> HTMLResponse:
        context = shell_context(request, "map", project_id)
        return templates.TemplateResponse("shell.html", context)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/projects")
    def api_list_projects() -> dict[str, list[dict]]:
        return {"projects": list_projects(settings.scraper_db_path)}

    @app.post("/api/projects", status_code=201)
    def api_create_project(payload: ProjectCreateRequest) -> JSONResponse:
        project = create_project(
            name=payload.name.strip(),
            primary_term=payload.primary_term.strip(),
            bbox=payload.bbox.strip(),
            extra_terms=[term.strip() for term in payload.extra_terms if term.strip()],
            colour=payload.colour,
            min_cell_degrees=payload.min_cell_degrees,
            db_path=settings.scraper_db_path,
        )
        return JSONResponse(status_code=201, content=project)

    @app.get("/api/projects/{project_id}")
    def api_get_project(project_id: str) -> dict:
        project = get_project(project_id, settings.scraper_db_path)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @app.delete("/api/projects/{project_id}", status_code=204)
    def api_delete_project(project_id: str) -> Response:
        deleted = archive_project(project_id, settings.scraper_db_path)
        if not deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        return Response(status_code=204)

    @app.get("/ui/map", response_class=HTMLResponse)
    def ui_map(
        request: Request,
        project_id: Annotated[str | None, Query()] = None,
    ) -> HTMLResponse:
        context = shell_context(request, "map", project_id)
        return templates.TemplateResponse("ui_map.html", context)

    @app.get("/ui/pipeline", response_class=HTMLResponse)
    def ui_pipeline(
        request: Request,
        project_id: Annotated[str | None, Query()] = None,
    ) -> HTMLResponse:
        context = shell_context(request, "pipeline", project_id)
        return templates.TemplateResponse("ui_pipeline.html", context)

    @app.get("/ui/leads", response_class=HTMLResponse)
    def ui_leads(
        request: Request,
        project_id: Annotated[str | None, Query()] = None,
    ) -> HTMLResponse:
        context = shell_context(request, "leads", project_id)
        return templates.TemplateResponse("ui_leads.html", context)

    @app.get("/ui/scrapes", response_class=HTMLResponse)
    def ui_scrapes(
        request: Request,
        project_id: Annotated[str | None, Query()] = None,
    ) -> HTMLResponse:
        context = shell_context(request, "scrapes", project_id)
        return templates.TemplateResponse("ui_scrapes.html", context)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("main:app", host=settings.app_host, port=settings.app_port, reload=False)
