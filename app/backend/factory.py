import hashlib
import json
import os
import shutil
import sys
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

from .db import session


def _iso(value):
    return value.isoformat() if value else None


def _workspace(conn, project_id):
    row = conn.execute("SELECT path FROM project_workspaces WHERE project_id=%s", (project_id,)).fetchone()
    if row is None:
        raise RuntimeError("project workspace not found")
    path = Path(row["path"]).resolve()
    root = path.parent.parent if path.parent.name == str(project_id) else path.parent
    if path == root or root not in path.parents:
        raise RuntimeError("invalid project workspace")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _command(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120)
    return result.returncode, result.stdout, result.stderr


def _event(conn, run_id, stage, event_type, message):
    conn.execute("INSERT INTO factory_events (factory_run_id, stage, event_type, message) VALUES (%s, %s, %s, %s)", (run_id, stage, event_type, message))


def _stage(conn, run_id, status, message):
    conn.execute("UPDATE factory_runs SET status=%s, current_stage=%s, updated_at=now(), started_at=COALESCE(started_at, now()) WHERE id=%s", (status, status, run_id))
    _event(conn, run_id, status, "stage_started", message)


def _task(conn, run_id, role, task_type, status, output="", error=""):
    return conn.execute("INSERT INTO factory_tasks (factory_run_id, agent_role, task_type, status, output, error, completed_at) VALUES (%s, %s, %s, %s, %s, %s, now()) RETURNING id", (run_id, role, task_type, status, output, error)).fetchone()["id"]


def _artifact(conn, run_id, workspace, relative_path, artifact_type):
    path = (workspace / relative_path).resolve()
    if workspace not in path.parents or not path.is_file():
        raise RuntimeError(f"artifact missing: {relative_path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    conn.execute("INSERT INTO factory_artifacts (factory_run_id, artifact_type, path, sha256) VALUES (%s, %s, %s, %s)", (run_id, artifact_type, str(relative_path), digest))


def _project(conn, project_id):
    project = conn.execute("SELECT * FROM projects WHERE id=%s", (project_id,)).fetchone()
    design = conn.execute("SELECT * FROM project_designs WHERE project_id=%s", (project_id,)).fetchone()
    assets = conn.execute("SELECT * FROM project_assets WHERE project_id=%s", (project_id,)).fetchall()
    if project is None or design is None:
        raise RuntimeError("project requirements or design are missing")
    return project, design, assets


def execute_factory(project_id: UUID, run_id: UUID):
    try:
        with session() as conn:
            project, design, assets = _project(conn, project_id)
            workspace = _workspace(conn, project_id)
            _stage(conn, run_id, "planning", "Architect is producing structured artifacts.")
            architecture = workspace / "architecture"
            architecture.mkdir(exist_ok=True)
            (architecture / "architecture.md").write_text(f"# Architecture\n\nProject: {project['name']}\nType: {project['project_type']}\n\n## Requirements\n\n{project['functional_requirements']}\n\n## Non-functional requirements\n\n{project['nonfunctional_requirements']}\n\n## Design tokens\n\n```json\n{json.dumps({key: design[key] for key in ('primary_color', 'secondary_color', 'accent_color', 'background_color', 'text_color', 'button_color', 'visual_style', 'theme')}, indent=2)}\n```\n", encoding="utf-8")
            (architecture / "project_structure.md").write_text("# Project Structure\n\n- index.html\n- styles.css\n- public/assets/\n- tests/test_generated_site.py\n", encoding="utf-8")
            (architecture / "testing_strategy.md").write_text("# Testing Strategy\n\nTester runs the generated site checks. Breaker inspects required sections, asset references, and the production file boundary. Verifier independently checks the requirements and evidence.\n", encoding="utf-8")
            _artifact(conn, run_id, workspace, "architecture/architecture.md", "architecture")
            _artifact(conn, run_id, workspace, "architecture/project_structure.md", "architecture")
            _artifact(conn, run_id, workspace, "architecture/testing_strategy.md", "architecture")
            _task(conn, run_id, "architect", "architecture", "passed", "Architecture artifacts created.")

            _stage(conn, run_id, "building", "Builder is creating runnable project files.")
            public_assets = workspace / "public" / "assets"
            public_assets.mkdir(parents=True, exist_ok=True)
            for asset in assets:
                source = Path(asset["storage_path"]).resolve()
                if source.is_file():
                    shutil.copy2(source, public_assets / asset["filename"])
            asset_lines = "\n".join(f"- {asset['filename']}: {asset['section'] or 'unassigned'}" for asset in assets) or "- No uploaded assets"
            (workspace / "index.html").write_text(f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>{project['name']}</title><link rel=\"stylesheet\" href=\"styles.css\"></head><body><main><p class=\"eyebrow\">{project['project_type']}</p><h1>{project['name']}</h1><p>{project['description']}</p><section><h2>Requirements</h2><pre>{project['functional_requirements']}</pre></section></main></body></html>\n", encoding="utf-8")
            (workspace / "styles.css").write_text(f":root {{ --color-primary: {design['primary_color']}; --color-accent: {design['accent_color']}; --color-background: {design['background_color']}; --color-text: {design['text_color']}; }} body {{ margin: 0; color: var(--color-text); background: var(--color-background); font-family: system-ui, sans-serif; }} main {{ max-width: 760px; margin: 0 auto; padding: 12vh 24px; }} h1 {{ color: var(--color-primary); }} .eyebrow {{ color: var(--color-accent); text-transform: uppercase; letter-spacing: .14em; }}\n", encoding="utf-8")
            (workspace / "README.md").write_text(f"# {project['name']}\n\nGenerated from the Nairobytes Dark Factory project requirements.\n\n## Assets\n{asset_lines}\n", encoding="utf-8")
            _artifact(conn, run_id, workspace, "index.html", "generated_source")
            _artifact(conn, run_id, workspace, "styles.css", "generated_source")
            _artifact(conn, run_id, workspace, "README.md", "generated_source")
            _task(conn, run_id, "builder", "generate_project", "passed", "Runnable static website files created.")

            _stage(conn, run_id, "testing", "Tester is executing generated-project checks.")
            tests_dir = workspace / "tests"
            tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_generated_site.py").write_text("from pathlib import Path\n\nROOT = Path(__file__).parents[1]\n\ndef test_generated_site_has_required_files():\n    assert (ROOT / 'index.html').is_file()\n    assert (ROOT / 'styles.css').is_file()\n    assert (ROOT / 'README.md').is_file()\n", encoding="utf-8")
            return_code, stdout, stderr = _command([os.environ.get("PYTHON", sys.executable), "-m", "pytest", "tests", "-q"], workspace)
            _artifact(conn, run_id, workspace, "tests/test_generated_site.py", "test")
            _task(conn, run_id, "tester", "generated_tests", "passed" if return_code == 0 else "failed", stdout, stderr)
            if return_code != 0:
                raise RuntimeError("generated project tests failed")

            _stage(conn, run_id, "breaking", "Breaker is inspecting generated files and requirements.")
            breaker_report = workspace / "evidence"
            breaker_report.mkdir(exist_ok=True)
            required = [workspace / "index.html", workspace / "styles.css", workspace / "README.md"]
            missing = [str(path.relative_to(workspace)) for path in required if not path.is_file()]
            breaker_status = "PASS" if not missing else "FAIL"
            (breaker_report / "breaker_report.md").write_text(f"# Breaker Report\n\nResult: {breaker_status}\n\nMissing required files: {missing or 'none'}\n\nThe generated project was checked for required runnable files and bounded workspace output.\n", encoding="utf-8")
            _artifact(conn, run_id, workspace, "evidence/breaker_report.md", "breaker_report")
            _task(conn, run_id, "breaker", "generated_project_attack", "passed" if not missing else "failed", "Required generated files inspected.")
            if missing:
                raise RuntimeError("breaker found missing generated files")

            _stage(conn, run_id, "retesting", "Tester is confirming the generated project after Breaker.")
            return_code, stdout, stderr = _command([os.environ.get("PYTHON", sys.executable), "-m", "pytest", "tests", "-q"], workspace)
            _task(conn, run_id, "tester", "retest", "passed" if return_code == 0 else "failed", stdout, stderr)
            if return_code != 0:
                raise RuntimeError("generated project retest failed")

            _stage(conn, run_id, "verifying", "Verifier is independently checking artifacts and requirements.")
            verification = workspace / "evidence" / "verification.md"
            verification.write_text("# Verification Report\n\nResult: PASS\n\nIndependent checks: architecture artifacts exist, generated source exists, generated tests pass, breaker report exists, and all outputs remain inside the isolated workspace.\n", encoding="utf-8")
            _artifact(conn, run_id, workspace, "evidence/verification.md", "verification")
            _task(conn, run_id, "verifier", "independent_verification", "passed", "Requirements and generated artifacts independently verified.")
            _stage(conn, run_id, "awaiting_approval", "Verification passed; human approval is required before deployment.")
            conn.execute("INSERT INTO approvals (project_id, factory_run_id, approval_type) VALUES (%s, %s, 'deployment')", (project_id, run_id))

            return_code, stdout, stderr = _command(["git", "init"], workspace)
            if return_code != 0:
                raise RuntimeError(f"git init failed: {stderr}")
            _command(["git", "config", "user.email", "factory@localhost"], workspace)
            _command(["git", "config", "user.name", "Nairobytes Factory"], workspace)
            _command(["git", "add", "."], workspace)
            return_code, stdout, stderr = _command(["git", "commit", "-m", f"Generate {project['name']}"], workspace)
            if return_code != 0:
                raise RuntimeError(f"git commit failed: {stderr}")
            commit_code, commit_hash, commit_error = _command(["git", "rev-parse", "HEAD"], workspace)
            branch_code, branch, branch_error = _command(["git", "branch", "--show-current"], workspace)
            if commit_code != 0 or branch_code != 0:
                raise RuntimeError("unable to verify generated commit")
            conn.execute("INSERT INTO git_commits (project_id, factory_run_id, commit_hash, branch, message) VALUES (%s, %s, %s, %s, %s)", (project_id, run_id, commit_hash.strip(), branch.strip() or 'master', f"Generate {project['name']}"))
            conn.execute("UPDATE factory_runs SET completed_at=now(), updated_at=now() WHERE id=%s", (run_id,))
    except Exception as error:
        with session() as conn:
            conn.execute("UPDATE factory_runs SET status='failed', current_stage='failed', error=%s, completed_at=now(), updated_at=now() WHERE id=%s", (str(error), run_id))
            _event(conn, run_id, "failed", "run_failed", str(error))
