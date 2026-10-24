"""API end to end: regimen creation, tray upload, demo, UI."""

from app.pilltray import synth


def _make_regimen(client):
    resp = client.post("/api/regimens", json={
        "label": "demo",
        "medications": [dict(m) for m in synth.SIMPLE_MEDICATIONS]})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_healthz_and_models(client):
    assert client.get("/healthz").json()["status"] == "ok"
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert "pill-tray-frugal" in ids and "pill-tray-full" in ids


def test_create_regimen_and_reconcile_tray_upload(client):
    regimen_id = _make_regimen(client)
    tray = synth.make_simple_scenario(synth.SIMPLE_SCENARIOS[0], seed=21)
    resp = client.post(f"/api/regimens/{regimen_id}/trays",
                       files={"file": ("tray.png", tray["png"], "image/png")})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["diff"]["diff_found"] is False
    assert data["usage"]["vlm_calls"] == 0


def test_tray_upload_rejects_unreadable_image(client):
    regimen_id = _make_regimen(client)
    resp = client.post(f"/api/regimens/{regimen_id}/trays",
                       files={"file": ("tray.png", b"not an image",
                                       "image/png")})
    assert resp.status_code == 400


def test_demo_reconcile_and_ui(client):
    resp = client.post("/api/demo/reconcile?scenario=simple-missing-vitd",
                       headers={"X-Tier": "frugal"})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["diff"]["missing"]) == 1
    ui = client.get("/")
    assert ui.status_code == 200
    assert "NOT CLINICALLY TESTED" in ui.text
    assert "dial 911" in ui.text
