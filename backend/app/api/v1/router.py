from fastapi import APIRouter

api_router = APIRouter()


@api_router.get("/status")
async def get_status() -> dict[str, str]:
    return {"status": "running", "version": "v1"}
