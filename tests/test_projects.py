from pathlib import Path


def project_payload(**overrides):
    payload = {
        "name": "Nairobytes Demo Website",
        "description": "A professional technology company website.",
        "project_type": "Website",
        "target_users": "Technology company customers",
        "business_domain": "Software engineering",
        "functional_requirements": "Home\nAbout\nServices\nProjects\nContact",
        "nonfunctional_requirements": "Responsive, accessible, SEO-ready",
        "technology_preferences": "React, Vite, Tailwind CSS",
        "database_requirements": "No database required",
        "authentication_requirement": "No authentication",
    }
    payload.update(overrides)
    return payload


def test_create_project_creates_design_and_isolated_workspace(client):
    response = client.post("/projects", json=project_payload())
    assert response.status_code == 201, response.text
    data = response.json()

    assert data["name"] == "Nairobytes Demo Website"
    assert data["status"] == "draft"
    assert data["design"]["primary_color"] == "#0B5ED7"
    assert data["workspace"]["status"] == "ready"
    assert Path(data["workspace"]["path"]).name == data["id"]
    assert data["assets"] == []

    fetched = client.get(f"/projects/{data['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["slug"].startswith("nairobytes-demo-website-")


def test_design_update_requires_hex_tokens(client):
    project = client.post("/projects", json=project_payload()).json()
    response = client.put(
        f"/projects/{project['id']}/design",
        json={
            "primary_color": "#123456",
            "secondary_color": "#FFFFFF",
            "accent_color": "#DC2626",
            "background_color": "#F8FAFC",
            "text_color": "#111827",
            "button_color": "#123456",
            "warning_color": "#F59E0B",
            "visual_style": "Modern",
            "theme": "Light",
            "custom_instructions": "Spacious and premium.",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["primary_color"] == "#123456"


def test_asset_upload_stores_metadata_and_serves_only_project_asset(client):
    project = client.post("/projects", json=project_payload()).json()
    response = client.post(
        f"/projects/{project['id']}/assets",
        files={"file": ("logo.svg", b"<svg></svg>", "image/svg+xml")},
        data={"alt_text": "Nairobytes logo", "asset_type": "Logo", "section": "Header"},
    )
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["original_filename"] == "logo.svg"
    assert asset["asset_type"] == "Logo"
    assert asset["section"] == "Header"
    assert asset["size"] == len(b"<svg></svg>")
    assert project["id"] in asset["url"]

    fetched = client.get(asset["url"])
    assert fetched.status_code == 200
    assert fetched.content == b"<svg></svg>"


def test_asset_upload_rejects_unsupported_type(client):
    project = client.post("/projects", json=project_payload()).json()
    response = client.post(
        f"/projects/{project['id']}/assets",
        files={"file": ("script.exe", b"not executable", "application/octet-stream")},
    )
    assert response.status_code == 415