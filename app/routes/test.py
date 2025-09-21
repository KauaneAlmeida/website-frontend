from fastapi import APIRouter
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/test/simple")
async def test_simple():
    return {"status": "ok", "message": "Simple test works"}

@router.get("/test/orchestrator")
async def test_orchestrator():
    try:
        from app.services.orchestration_service import intelligent_orchestrator
        return {"status": "ok", "orchestrator": "imported successfully"}
    except Exception as e:
        return {"status": "error", "error": str(e)}