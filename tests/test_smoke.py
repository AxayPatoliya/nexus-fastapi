import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from nexus_fastapi.scaffolds import create_project

SAMPLE = Path(__file__).resolve().parent.parent / "sample_config.json"


def test_scaffold_default(tmp_path):
    root = create_project(tmp_path / "demo", project_name="demo")
    assert root == (tmp_path / "demo").resolve()
    for rel in ("apps", "core/config", "core/database", "core/security", "tests", "main.py", "run.py"):
        assert (root / rel).exists(), rel


def test_scaffold_respects_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_project(tmp_path / "elsewhere", project_name="service")
    assert not (tmp_path / "service").exists()


def test_scaffold_from_config(tmp_path):
    config = json.loads(SAMPLE.read_text())
    root = create_project(tmp_path / "cfg", project_name="cfg", config=config)
    for app in ("users", "products"):
        for f in ("models.py", "schemas.py", "crud.py", "routes.py"):
            assert (root / "apps" / app / f).exists(), (app, f)
    for py in root.rglob("*.py"):
        compile(py.read_text(), str(py), "exec")
    users_routes = (root / "apps" / "users" / "routes.py").read_text()
    assert "def read_users(" in users_routes
    assert "def read_user(" in users_routes
    assert "@router.post(" in users_routes
    assert "@router.put(" in users_routes
    assert "@router.delete(" in users_routes
    assert 'prefix="/api/users"' in (root / "main.py").read_text()


def test_scaffold_selected_routes(tmp_path):
    config = {
        "project_name": "my_app",
        "description": "My FastAPI Application",
        "version": "1.0.0",
        "apps": [
            {
                "name": "users",
                "models": [
                    {
                        "name": "User",
                        "fields": [
                            {"name": "email", "type": "string", "nullable": False},
                            {"name": "username", "type": "string", "nullable": False},
                        ],
                    }
                ],
                "routes": [
                    {"name": "get_users", "path": "/users", "method": "GET"},
                    {"name": "create_user", "path": "/users", "method": "POST"},
                    {"name": "update_user", "path": "/users/{id}", "method": "PUT"},
                    {"name": "delete_user", "path": "/users/{id}", "method": "DELETE"},
                ],
            }
        ],
    }
    root = create_project(tmp_path / "selected", project_name="selected", config=config)
    routes = (root / "apps" / "users" / "routes.py").read_text()
    service = (root / "apps" / "users" / "service.py").read_text()
    assert "def get_users(" in routes
    assert "def create_user(" in routes
    assert "def update_user(" in routes
    assert "def delete_user(" in routes
    assert '@router.get("/users"' in routes
    assert '@router.post("/users"' in routes
    assert '@router.put("/users/{id}"' in routes
    assert '@router.delete("/users/{id}"' in routes
    assert routes.count("@router.get(") == 1
    assert "@router.patch(" not in routes
    assert re.search(r"def get_user\(", service) is None
    assert "def get_users(" in service
    assert "def create_user(" in service
    assert 'prefix="/api"' in (root / "main.py").read_text()
    assert 'prefix="/api/users"' not in (root / "main.py").read_text()
    for py in root.rglob("*.py"):
        compile(py.read_text(), str(py), "exec")


def test_scaffold_patch_route(tmp_path):
    config = {
        "project_name": "my_app",
        "apps": [
            {
                "name": "users",
                "models": [
                    {"name": "User", "fields": [{"name": "email", "type": "string"}]}
                ],
                "routes": [
                    {"name": "patch_user", "path": "/users/{id}", "method": "PATCH"},
                ],
            }
        ],
    }
    root = create_project(tmp_path / "patch", project_name="patch", config=config)
    routes = (root / "apps" / "users" / "routes.py").read_text()
    assert '@router.patch("/users/{id}"' in routes
    assert "def patch_user(" in routes
    assert "@router.get(" not in routes
    compile(routes, "routes.py", "exec")


def test_scaffold_rejects_unknown_method(tmp_path):
    config = {
        "project_name": "my_app",
        "apps": [
            {
                "name": "users",
                "models": [{"name": "User", "fields": [{"name": "email", "type": "string"}]}],
                "routes": [{"name": "trace_user", "path": "/users", "method": "TRACE"}],
            }
        ],
    }
    with pytest.raises(ValueError, match="TRACE"):
        create_project(tmp_path / "bad", project_name="bad", config=config)


ALL_TYPES_CONFIG = {
    "project_name": "alltypes",
    "apps": [
        {
            "name": "things",
            "models": [
                {
                    "name": "Thing",
                    "fields": [
                        {"name": "a_string", "type": "string"},
                        {"name": "a_text", "type": "text"},
                        {"name": "an_int", "type": "integer"},
                        {"name": "a_float", "type": "float"},
                        {"name": "a_bool", "type": "boolean"},
                        {"name": "a_date", "type": "datetime"},
                        {"name": "a_json", "type": "json"},
                    ],
                }
            ],
        }
    ],
}


def test_generated_app_boots_and_serves_crud(tmp_path):
    """The generated project must import and handle a request, not just compile."""
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("httpx")
    root = create_project(tmp_path / "alltypes", project_name="alltypes", config=ALL_TYPES_CONFIG)
    script = (
        "from fastapi.testclient import TestClient\n"
        "from main import app\n"
        "c = TestClient(app)\n"
        "assert c.get('/health').status_code == 200\n"
        "r = c.post('/api/things/', json={'a_string': 'x', 'an_int': 1})\n"
        "assert r.status_code == 200, r.text\n"
        "assert c.get('/api/things/').json()[0]['a_string'] == 'x'\n"
        "id_ = r.json()['id']\n"
        "r = c.get(f'/api/things/{id_}')\n"
        "assert r.status_code == 200, r.text\n"
        "assert r.json()['a_string'] == 'x'\n"
        "r = c.put(f'/api/things/{id_}', json={'a_string': 'y'})\n"
        "assert r.status_code == 200, r.text\n"
        "r = c.get(f'/api/things/{id_}')\n"
        "assert r.status_code == 200, r.text\n"
        "assert r.json()['a_string'] == 'y'\n"
        "r = c.delete(f'/api/things/{id_}')\n"
        "assert r.status_code == 200, r.text\n"
        "assert c.get(f'/api/things/{id_}').status_code == 404\n"
    )
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", script],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
