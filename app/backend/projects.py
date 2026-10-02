import os
import re
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .db import session

router = APIRouter(prefix="/projects", tags=["projects"])
WORKSPACE_ROOT = Path(os.environ.get("FACTORY_WORKSPACE_ROOT", Path(os.getenv("TEMP", ".")) / "nairobytes-workspaces")).resolve()
MAX_ASSET_BYTES = 10 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/svg+xml",
    "image/x-icon", "application/pdf",
}


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=5000)
    project_type: str = Field(min_length=2, max_length=80)
    target_users: str = Field(default="", max_length=5000)
    business_domain: str = Field(default="", max_length=5000)
    functional_requirements: str = Field(default="", max_length=20000)
    nonfunctional_requirements: str = Field(default="", max_length=20000)
    technology_preferences: str = Field(default="", max_length=5000)
    database_requirements: str = Field(default="", max_length=5000)
    authentication_requirement: str = Field(default="No authentication", max_length=100)


class DesignUpdate(BaseModel):
    primary_color: str = Field(default="#0B5ED7", pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: str = Field(default="#DC2626", pattern=r"^#[0-9A-Fa-f]{6}$")
    background_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    text_color: str = Field(default="#111827", pattern=r"^#[0-9A-Fa-f]{6}$")
    button_color: str = Field(default="#0B5ED7", pattern=r"^#[0-9A-Fa-f]{6}$")
    warning_color: str = Field(default="#F59E0B", pattern=r"^#[0-9A-Fa-f]{6}$")
    visual_style: str = Field(default="Professional", max_length=60)
    theme: str = Field(default="Light", max_length=20)
    custom_instructions: str = Field(default="", max_length=10000)


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "project"
    return f"{base}-{uuid4().hex[:8]}"


def _iso(value):
    return value.isoformat() if value else None


def _project_out(project, design, workspace, assets):
    design_out = None
    if design:
        design_out = dict(design)
        design_out["project_id"] = str(design["project_id"])
        design_out["created_at"] = _iso(design["created_at"])
        design_out["updated_at"] = _iso(design["updated_at"])
    asset_out = []
    for asset in assets:
        item = dict(asset)
        item["id"] = str(asset["id"])
        item["project_id"] = str(asset["project_id"])
        item["created_at"] = _iso(asset["created_at"])
        item["updated_at"] = _iso(asset["updated_at"])
        asset_out.append(item)
    return {
        "id": str(project["id"]),
        "name": project["name"],
        "slug": project["slug"],
        "description": project["description"],
        "project_type": project["project_type"],
        "target_users": project["target_users"],
        "business_domain": project["business_domain"],
        "functional_requirements": project["functional_requirements"],
        "nonfunctional_requirements": project["nonfunctional_requirements"],
        "technology_preferences": project["technology_preferences"],
        "database_requirements": project["database_requirements"],
        "authentication_requirement": project["authentication_requirement"],
        "status": project["status"],
        "created_at": _iso(project["created_at"]),
        "updated_at": _iso(project["updated_at"]),
        "design": design_out,
        "workspace": {"id": str(workspace["id"]), "path": workspace["path"], "status": workspace["status"]} if workspace else None,
        "assets": asset_out,
    }


def _load_project(conn, project_id: UUID):
    project = conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    design = conn.execute("SELECT * FROM project_designs WHERE project_id = %s", (project_id,)).fetchone()
    workspace = conn.execute("SELECT * FROM project_workspaces WHERE project_id = %s", (project_id,)).fetchone()
    assets = conn.execute("SELECT * FROM project_assets WHERE project_id = %s ORDER BY sort_order, created_at", (project_id,)).fetchall()
    return _project_out(project, design, workspace, assets)


@router.post("", status_code=201)
def create_project(body: ProjectCreate):
    project_id = uuid4()
    slug = _slugify(body.name)
    workspace_path = (WORKSPACE_ROOT / str(project_id)).resolve()
    if WORKSPACE_ROOT not in workspace_path.parents:
        raise HTTPException(status_code=500, detail="invalid workspace path")
    try:
        workspace_path.mkdir(parents=True, exist_ok=False)
        with session() as conn:
            project = conn.execute(
                "INSERT INTO projects (id, name, slug, description, project_type, target_users, business_domain, functional_requirements, nonfunctional_requirements, technology_preferences, database_requirements, authentication_requirement) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (project_id, body.name.strip(), slug, body.description, body.project_type, body.target_users, body.business_domain, body.functional_requirements, body.nonfunctional_requirements, body.technology_preferences, body.database_requirements, body.authentication_requirement),
            ).fetchone()
            design = conn.execute("INSERT INTO project_designs (project_id) VALUES (%s) RETURNING *", (project_id,)).fetchone()
            workspace = conn.execute("INSERT INTO project_workspaces (project_id, path) VALUES (%s, %s) RETURNING *", (project_id, str(workspace_path))).fetchone()
            return _project_out(project, design, workspace, [])
    except Exception:
        shutil.rmtree(workspace_path, ignore_errors=True)
        raise


@router.get("")
def list_projects():
    with session() as conn:
        rows = conn.execute("SELECT id, name, slug, project_type, status, created_at, updated_at FROM projects ORDER BY created_at DESC").fetchall()
    return [{**dict(row), "id": str(row["id"]), "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])} for row in rows]


@router.get("/{project_id}")
def get_project(project_id: UUID):
    with session() as conn:
        return _load_project(conn, project_id)


@router.put("/{project_id}/design")
def update_project_design(project_id: UUID, body: DesignUpdate):
    with session() as conn:
        _load_project(conn, project_id)
        design = conn.execute(
            "UPDATE project_designs SET primary_color=%s, secondary_color=%s, accent_color=%s, background_color=%s, text_color=%s, button_color=%s, warning_color=%s, visual_style=%s, theme=%s, custom_instructions=%s, updated_at=now() WHERE project_id=%s RETURNING *",
            (*body.model_dump().values(), project_id),
        ).fetchone()
        return {**dict(design), "project_id": str(design["project_id"]), "created_at": _iso(design["created_at"]), "updated_at": _iso(design["updated_at"])}


@router.post("/{project_id}/assets", status_code=201)
def upload_project_asset(project_id: UUID, file: UploadFile = File(...), alt_text: str = Form(""), asset_type: str = Form("Other"), section: str = Form("")):
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=415, detail="unsupported asset type")
    with session() as conn:
        _load_project(conn, project_id)
        asset_id = uuid4()
        original_name = os.path.basename(file.filename or "asset")
        extension = Path(original_name).suffix.lower()
        filename = f"{asset_id}{extension}"
        project_dir = (WORKSPACE_ROOT / str(project_id) / "assets").resolve()
        if WORKSPACE_ROOT not in project_dir.parents:
            raise HTTPException(status_code=500, detail="invalid asset path")
        project_dir.mkdir(parents=True, exist_ok=True)
        storage_path = project_dir / filename
        size = 0
        with storage_path.open("wb") as destination:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ASSET_BYTES:
                    storage_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="asset exceeds 10 MB limit")
                destination.write(chunk)
        asset = conn.execute(
            "INSERT INTO project_assets (id, project_id, filename, original_filename, mime_type, size, storage_path, url, alt_text, asset_type, section) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (asset_id, project_id, filename, original_name, file.content_type, size, str(storage_path), f"/projects/{project_id}/assets/{asset_id}/file", alt_text, asset_type, section),
        ).fetchone()
    return {**dict(asset), "id": str(asset["id"]), "project_id": str(asset["project_id"]), "created_at": _iso(asset["created_at"]), "updated_at": _iso(asset["updated_at"])}


@router.get("/{project_id}/assets/{asset_id}/file")
def get_project_asset(project_id: UUID, asset_id: UUID):
    with session() as conn:
        asset = conn.execute("SELECT storage_path, mime_type, original_filename FROM project_assets WHERE id=%s AND project_id=%s", (asset_id, project_id)).fetchone()
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    path = Path(asset["storage_path"]).resolve()
    if WORKSPACE_ROOT not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(path, media_type=asset["mime_type"], filename=asset["original_filename"])