"""PillTray -- FastAPI application.

Routes:
  /v1/*    Embedded OpenAI-compatible inference gateway (the product's AI
           layer -- every AI feature calls through here). Tier is selected
           by the ``model`` alias (pill-tray-frugal | pill-tray-full)
           or an ``X-Tier: frugal|full`` header.
  /api/*   Product API: regimens, tray reconciliation, synthetic demo.
  /        Static single-page demo UI.
  /healthz Health check.

Storage is in-memory in v0.1.0. Regimen labels pass the PHI redaction
gate before storage. Tray photos are health data: run the local backend
and they never leave the building (see SECURITY.md).
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import gateway, safety
from app.pilltray import detector, models, service, synth

logger = logging.getLogger("pill-tray")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

MAX_UPLOAD_BYTES = 8 * 1024 * 1024

app = FastAPI(
    title="PillTray",
    description="Open-source brown-bag medication reconciliation by "
                "set difference. One tray photo, matched only against "
                "the patient's own list, through an embedded "
                "OpenAI-compatible gateway.",
    version="0.1.0",
)

REGIMENS: dict[str, models.Regimen] = {}


def _get_regimen(regimen_id: str) -> models.Regimen:
    regimen = REGIMENS.get(regimen_id)
    if not regimen:
        raise HTTPException(status_code=404, detail="regimen not found")
    return regimen


# ---------------------------------------------------------------------------
# Gateway routes -- OpenAI-compatible shapes, served by this app
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict] = Field(default_factory=list)
    temperature: float = 0.2
    max_tokens: int = 2000
    response_format: dict | None = None


class EmbeddingsRequest(BaseModel):
    model: str | None = None
    input: str | list[str] = ""


@app.get("/v1/models")
def v1_models():
    return gateway.list_models()


@app.post("/v1/chat/completions")
def v1_chat_completions(req: ChatRequest,
                        x_tier: str | None = Header(default=None)):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    tier = gateway.resolve_tier(req.model, x_tier)
    return gateway.dispatch_chat(
        req.messages, model=req.model, temperature=req.temperature,
        max_tokens=req.max_tokens, response_format=req.response_format,
        tier=tier)


@app.post("/v1/embeddings")
def v1_embeddings(req: EmbeddingsRequest):
    return gateway.dispatch_embeddings(req.input, model=req.model)


# ---------------------------------------------------------------------------
# Product API
# ---------------------------------------------------------------------------

class MedicationIn(BaseModel):
    id: str | None = None
    name: str
    strength: str = ""
    form: str = "tablet"
    colour: str
    shape: str
    size: str = "M"
    marking_strokes: int = 2
    expected_count: int = 1


class RegimenCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    medications: list[MedicationIn]


@app.get("/healthz")
def healthz():
    return {"status": "ok", "backend": gateway.get_backend(),
            "tier_default": gateway.resolve_tier(),
            "regimens": len(REGIMENS)}


@app.post("/api/regimens")
def api_create_regimen(req: RegimenCreateRequest):
    label, _report = safety.redact_phi(req.label)
    regimen = service.build_regimen(
        label, [m.model_dump() for m in req.medications])
    REGIMENS[regimen.id] = regimen
    return regimen.to_dict()


@app.get("/api/regimens/{regimen_id}")
def api_get_regimen(regimen_id: str):
    return _get_regimen(regimen_id).to_dict()


@app.post("/api/regimens/{regimen_id}/trays")
async def api_reconcile_tray(regimen_id: str, file: UploadFile = File(...),
                             x_tier: str | None = Header(default=None)):
    regimen = _get_regimen(regimen_id)
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 8 MB)")
    tier = gateway.resolve_tier(None, x_tier)
    try:
        result = service.reconcile_photo(regimen, data, tier=tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    regimen.reports.append(result)
    logger.info("tray reconciled", extra={
        "regimen": regimen.id, "tier": tier,
        "vlm_calls": result["usage"]["vlm_calls"]})
    return result


@app.post("/api/regimens/{regimen_id}/reconcile")
def api_reconcile_descriptors(regimen_id: str, items: list[dict],
                              x_tier: str | None = Header(default=None)):
    regimen = _get_regimen(regimen_id)
    tier = gateway.resolve_tier(None, x_tier)
    result = service.reconcile_descriptors(regimen, items, tier=tier)
    regimen.reports.append(result)
    return result


@app.get("/api/regimens/{regimen_id}/tray.png", response_class=HTMLResponse)
def api_tray_note(regimen_id: str):
    _get_regimen(regimen_id)
    return ("<p>Tray photos are uploaded through the demo UI or "
            "POST /api/regimens/{id}/trays as a PNG/JPEG file.</p>")


# ---------------------------------------------------------------------------
# Synthetic demo -- the same fixtures CI measures
# ---------------------------------------------------------------------------

def _demo_regimen() -> models.Regimen:
    regimen = service.build_regimen(
        "demo regimen (synthetic medicines)",
        [dict(m) for m in synth.STANDARD_MEDICATIONS])
    return regimen


@app.get("/api/demo/regimen")
def api_demo_regimen():
    return _demo_regimen().to_dict()


@app.get("/api/demo/scenarios")
def api_demo_scenarios():
    return {"standard": [s["name"] for s in synth.SCENARIOS],
            "simple": [s["name"] for s in synth.SIMPLE_SCENARIOS]}


@app.post("/api/demo/reconcile")
def api_demo_reconcile(scenario: str,
                       x_tier: str | None = Header(default=None)):
    tier = gateway.resolve_tier(None, x_tier)
    std = {s["name"]: s for s in synth.SCENARIOS}
    simple = {s["name"]: s for s in synth.SIMPLE_SCENARIOS}
    if scenario in std:
        regimen = _demo_regimen()
        tray = synth.make_scenario(std[scenario], seed=11)
    elif scenario in simple:
        regimen = service.build_regimen(
            "demo simple regimen (synthetic medicines)",
            [dict(m) for m in synth.SIMPLE_MEDICATIONS])
        tray = synth.make_simple_scenario(simple[scenario], seed=21)
    else:
        raise HTTPException(status_code=400,
                            detail="unknown scenario; see /api/demo/scenarios")
    result = service.reconcile_photo(regimen, tray["png"], tier=tier)
    return {"scenario": scenario, "truth": tray["truth"],
            "planted_events": tray["events"], "tier": tier, **result}


# ---------------------------------------------------------------------------
# Static demo UI
# ---------------------------------------------------------------------------

_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
