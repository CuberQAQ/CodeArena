"""CF Handle binding and verification business logic.

Provides bind, verify, info lookup, and unbind operations.  All functions
receive an ``AsyncSession`` and are pure-logic helpers that the route layer
calls directly.

Verification codes are stored in the ``cf_verification_code`` column on the
User model so they survive server restarts and work across multiple workers.
"""

import logging
import random
import string

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.user import User
from app.services.cf_api_service import (
    CFAPIError,
    CFApiService,
    CFNetworkError,
    CFNotFoundError,
    CFRateLimitError,
)

logger = logging.getLogger("code_arena.cf_handle_service")


def _generate_verification_code(length: int = 8) -> str:
    """Generate a random alphanumeric verification code."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


async def bind_cf_handle(
    db: AsyncSession,
    user: User,
    cf_handle: str,
    cf_service: CFApiService,
) -> dict:
    """Bind a CF Handle to the current user (step 1: initiate binding).

    Validates that the handle exists on Codeforces, checks that it is not
    already bound to another user, stores a verification code in the database,
    and returns the CF user info plus the verification code.

    Raises:
        BadRequestException: If the user already has a verified CF handle.
        ConflictException: If the handle is bound to another user.
        NotFoundException: If the CF handle does not exist.
        BadRequestException: On CF API errors (network, rate limit).
    """
    # Check if user already has a verified handle
    if user.cf_handle and user.cf_handle_verified:
        raise BadRequestException(
            message="CF Handle already bound and verified",
            detail="Unbind your current handle first",
        )

    # Check if the handle is already bound to another user
    result = await db.execute(select(User).where(User.cf_handle == cf_handle))
    other_user = result.scalar_one_or_none()
    if other_user is not None and other_user.id != user.id:
        raise ConflictException(
            message="CF Handle already bound to another user",
            detail="handle",
        )

    # Validate the handle exists on Codeforces
    try:
        cf_users = await cf_service.get_user_info([cf_handle])
    except CFNotFoundError:
        raise NotFoundException(
            message="CF Handle not found on Codeforces",
            detail=cf_handle,
        )
    except (CFNetworkError, CFRateLimitError) as exc:
        raise BadRequestException(
            message=f"Failed to verify CF Handle: {exc.message}",
            detail=exc.detail,
        )
    except CFAPIError as exc:
        raise BadRequestException(
            message=f"CF API error: {exc.message}",
            detail=exc.detail,
        )

    if not cf_users:
        raise NotFoundException(
            message="CF Handle not found on Codeforces",
            detail=cf_handle,
        )

    cf_user_data = cf_users[0]

    # Generate and store verification code in the database
    verification_code = _generate_verification_code()

    # Save handle and verification code to user (unverified)
    user.cf_handle = cf_handle
    user.cf_handle_verified = False
    user.cf_verification_code = verification_code
    await db.flush()

    cf_info = _extract_cf_info(cf_user_data)

    return {
        "cf_handle": cf_handle,
        "verification_code": verification_code,
        "cf_user_info": cf_info,
        "status": "pending_verification",
    }


async def verify_cf_handle(
    db: AsyncSession,
    user: User,
    cf_handle: str,
    verification_code: str,
    cf_service: CFApiService,
) -> dict:
    """Verify a CF Handle by checking the user's CF profile for the code (step 2).

    Raises:
        BadRequestException: If the user has no pending CF handle binding, or
            the handle does not match the bound handle, or the verification
            code is incorrect.
        NotFoundException: If the CF handle cannot be found.
        BadRequestException: On CF API errors.
    """
    logger.info(
        "verify_cf_handle called: user_cf=%s, req_handle=%s, req_code=%r, db_code=%r, verified=%s",
        user.cf_handle, cf_handle, verification_code, user.cf_verification_code, user.cf_handle_verified,
    )

    # Validate that the user has a pending binding
    if not user.cf_handle:
        raise BadRequestException(
            message="No CF Handle binding pending",
            detail="Call bind first",
        )

    if user.cf_handle != cf_handle:
        raise BadRequestException(
            message="CF Handle does not match bound handle",
            detail=f"Expected {user.cf_handle}, got {cf_handle}",
        )

    if user.cf_handle_verified:
        raise BadRequestException(
            message="CF Handle already verified",
        )

    # Check verification code from database (case-insensitive)
    expected_code = user.cf_verification_code
    if expected_code is None:
        raise BadRequestException(
            message="No verification code found for this handle",
            detail="Please initiate binding again",
        )

    if verification_code.lower() != expected_code.lower():
        raise BadRequestException(
            message="Verification code does not match",
            detail="Check the code in your CF profile organization field",
        )

    # Fetch the CF user info and check profile for the verification code
    try:
        cf_users = await cf_service.get_user_info([cf_handle])
    except CFNotFoundError:
        raise NotFoundException(
            message="CF Handle not found on Codeforces",
            detail=cf_handle,
        )
    except (CFNetworkError, CFRateLimitError) as exc:
        raise BadRequestException(
            message=f"Failed to fetch CF user info: {exc.message}",
            detail=exc.detail,
        )
    except CFAPIError as exc:
        raise BadRequestException(
            message=f"CF API error: {exc.message}",
            detail=exc.detail,
        )

    if not cf_users:
        raise NotFoundException(
            message="CF Handle not found on Codeforces",
            detail=cf_handle,
        )

    cf_user_data = cf_users[0]

    # Check if the verification code is present in the user's profile fields.
    # CF API user.info returns: organization, firstName, lastName among others.
    # The user is expected to put the code in their "organization" field,
    # which is the most accessible user-editable text field returned by user.info.
    organization = cf_user_data.get("organization", "")
    first_name = cf_user_data.get("firstName", "")
    last_name = cf_user_data.get("lastName", "")

    searchable_text = f"{organization} {first_name} {last_name}".lower()
    logger.info(
        "CF verify check: handle=%s, code=%s, org=%r, fn=%r, ln=%r, searchable=%r",
        cf_handle, verification_code, organization, first_name, last_name, searchable_text,
    )
    if verification_code.lower() not in searchable_text:
        raise BadRequestException(
            message="Verification code not found in CF profile",
            detail=f"org={organization!r}, searchable={searchable_text!r}, looking_for={verification_code.lower()!r}",
        )

    # Verification successful -- clear the code and mark verified
    user.cf_handle_verified = True
    user.cf_verification_code = None
    await db.flush()

    cf_info = _extract_cf_info(cf_user_data)

    return {
        "cf_handle": cf_handle,
        "cf_user_info": cf_info,
        "verified": True,
        "status": "verified",
    }


async def get_cf_handle_info(
    cf_handle: str,
    cf_service: CFApiService,
) -> dict:
    """Look up public CF user info by handle.

    Raises:
        NotFoundException: If the handle does not exist on Codeforces.
        BadRequestException: On CF API errors.
    """
    try:
        cf_users = await cf_service.get_user_info([cf_handle])
    except CFNotFoundError:
        raise NotFoundException(
            message="CF Handle not found on Codeforces",
            detail=cf_handle,
        )
    except (CFNetworkError, CFRateLimitError) as exc:
        raise BadRequestException(
            message=f"Failed to fetch CF user info: {exc.message}",
            detail=exc.detail,
        )
    except CFAPIError as exc:
        raise BadRequestException(
            message=f"CF API error: {exc.message}",
            detail=exc.detail,
        )

    if not cf_users:
        raise NotFoundException(
            message="CF Handle not found on Codeforces",
            detail=cf_handle,
        )

    cf_info = _extract_cf_info(cf_users[0])
    return cf_info


async def unbind_cf_handle(
    db: AsyncSession,
    user: User,
) -> dict:
    """Unbind the current user's CF Handle.

    Raises:
        BadRequestException: If the user has no bound CF handle.
    """
    if not user.cf_handle:
        raise BadRequestException(
            message="No CF Handle bound to this account",
        )

    handle = user.cf_handle
    user.cf_handle = None
    user.cf_handle_verified = False
    user.cf_verification_code = None
    await db.flush()

    return {"unbound": handle}


def _extract_cf_info(cf_user_data: dict) -> dict:
    """Extract relevant CF user info from the API response."""
    return {
        "handle": cf_user_data.get("handle", ""),
        "rating": cf_user_data.get("rating"),
        "max_rating": cf_user_data.get("maxRating"),
        "avatar": cf_user_data.get("avatar"),
        "rank": cf_user_data.get("rank"),
        "max_rank": cf_user_data.get("maxRank"),
        "title_photo": cf_user_data.get("titlePhoto"),
    }
