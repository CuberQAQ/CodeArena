from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.cf_handle import router as cf_handle_router
from app.api.v1.challenge import router as challenge_router
from app.api.v1.contest import router as contest_router
from app.api.v1.contest_ws import router as contest_ws_router
from app.api.v1.economy import router as economy_router
from app.api.v1.hints import router as hints_router
from app.api.v1.pve_challenge import router as pve_challenge_router
from app.api.v1.training import router as training_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(cf_handle_router)
api_router.include_router(challenge_router)
api_router.include_router(pve_challenge_router)
api_router.include_router(training_router)
api_router.include_router(contest_router)
api_router.include_router(economy_router)
api_router.include_router(hints_router)
api_router.include_router(admin_router)
api_router.include_router(contest_ws_router)


@api_router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for monitoring and load balancers."""
    return {"status": "ok", "version": "v1"}


@api_router.get("/status")
async def get_status() -> dict[str, str]:
    """API status endpoint."""
    return {"status": "running", "version": "v1"}
