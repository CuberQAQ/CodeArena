"""WebSocket endpoint for live contest leaderboard updates.

Provides a single WebSocket route that pushes leaderboard updates
to connected clients every few seconds while the contest is active.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import async_session_factory
from app.core.security import decode_token
from app.models.contest_session import ContestSession
from app.models.user import User
from app.schemas.contest import LeaderboardResponse
from app.services.contest_simulation_service import ContestSimulationService

logger = logging.getLogger("code_arena.contest_ws")

router = APIRouter(tags=["Contest WebSocket"])


async def _authenticate_ws(websocket: WebSocket) -> User | None:
    """Authenticate a WebSocket connection via query param token.

    Returns the User object on success, or None on failure.
    """
    token = websocket.query_params.get("token")
    if not token:
        return None

    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None

        # Fetch user from database
        async with async_session_factory() as db:
            from sqlalchemy import select

            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is None or not user.is_active:
                return None
            return user
    except Exception:
        logger.debug("WebSocket auth failed", exc_info=True)
        return None


@router.websocket("/contest/{contest_id}/live")
async def contest_live_leaderboard(
    websocket: WebSocket,
    contest_id: uuid.UUID,
) -> None:
    """WebSocket endpoint that streams live leaderboard updates.

    Clients connect with a JWT token as a query parameter:
    ``ws://host/api/v1/contest/{contest_id}/live?token=<jwt>``

    The server sends leaderboard JSON every 5 seconds while the contest
    is active.  When the contest ends, a final leaderboard is sent and
    the connection is closed.
    """
    # Authenticate
    user = await _authenticate_ws(websocket)
    if user is None:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    # Verify contest ownership
    async with async_session_factory() as check_db:
        contest_session = await check_db.get(ContestSession, contest_id)
        if contest_session is None or str(contest_session.user_id) != str(user.id):
            await websocket.close(code=4003, reason="Contest access denied")
            return

    # Accept connection
    await websocket.accept()

    logger.info(
        "WebSocket connected: user=%s contest=%s", user.username, contest_id
    )

    try:
        while True:
            # Build leaderboard in its own session
            async with async_session_factory() as db:
                try:
                    leaderboard = await ContestSimulationService.build_leaderboard(
                        db, contest_id, user,
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.exception(
                        "Error building leaderboard for WS contest=%s", contest_id
                    )
                    leaderboard = LeaderboardResponse()

            # Send leaderboard
            await websocket.send_json(leaderboard.model_dump(mode="json"))

            # Check if contest is still active (time_elapsed >= time_total means ended)
            if leaderboard.time_total > 0 and leaderboard.time_elapsed >= leaderboard.time_total:
                # Contest has ended, send final and close
                await websocket.send_json({
                    "type": "contest_ended",
                    "leaderboard": leaderboard.model_dump(mode="json"),
                })
                break

            # Wait before next update
            await asyncio.sleep(5)

    except WebSocketDisconnect:
        logger.debug(
            "WebSocket disconnected: user=%s contest=%s", user.username, contest_id
        )
    except Exception:
        logger.exception(
            "WebSocket error: user=%s contest=%s", user.username, contest_id
        )
    finally:
        logger.info(
            "WebSocket closed: user=%s contest=%s", user.username, contest_id
        )
