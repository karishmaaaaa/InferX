import hashlib
import logging
import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import APIKey, User
from app.db.session import get_db_session

logger = logging.getLogger(__name__)
_AUTH_CACHE: dict[str, tuple[float, "AuthenticatedAccount"]] = {}


class AuthenticatedAccount(BaseModel):
    user_id: str
    api_key_id: str
    tier: str
    key_prefix: str


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def api_key_prefix(api_key: str) -> str:
    return api_key[:8]


async def authenticate_api_key(
    api_key: str,
    session: AsyncSession,
    cache_ttl_seconds: float = 60.0,
) -> AuthenticatedAccount:
    key_hash = hash_api_key(api_key)
    cached = _AUTH_CACHE.get(key_hash)
    now = time.monotonic()
    if cached is not None:
        expires_at, account = cached
        if expires_at >= now:
            return account
        _AUTH_CACHE.pop(key_hash, None)

    result = await session.execute(
        select(APIKey, User)
        .join(User, APIKey.user_id == User.id)
        .where(APIKey.key_hash == key_hash, APIKey.is_active.is_(True))
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    key, user = row
    account = AuthenticatedAccount(
        user_id=user.id,
        api_key_id=key.id,
        tier=user.tier,
        key_prefix=key.prefix,
    )
    if cache_ttl_seconds > 0:
        _AUTH_CACHE[key_hash] = (now + cache_ttl_seconds, account)
    return account


async def require_api_key(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> AuthenticatedAccount:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )
    settings = get_settings()
    return await authenticate_api_key(
        api_key,
        session,
        cache_ttl_seconds=settings.api_key_cache_ttl_seconds,
    )


async def bootstrap_local_dev_accounts(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not settings.bootstrap_dev_data:
        return

    keys = [
        ("local-free", "free", settings.local_free_api_key),
        ("local-premium", "premium", settings.local_premium_api_key),
    ]
    configured_keys = [(name, tier, key) for name, tier, key in keys if key]
    if not configured_keys:
        logger.warning("bootstrap_dev_data enabled but no local API keys were provided")
        return

    async with session_factory() as session:
        for name, tier, plain_key in configured_keys:
            email = f"{tier}-{settings.local_dev_user_email}"
            user = await _get_or_create_user(session, email=email, tier=tier)
            await _get_or_create_api_key(session, user=user, name=name, plain_key=plain_key)
        await session.commit()


async def _get_or_create_user(session: AsyncSession, email: str, tier: str) -> User:
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        existing.tier = tier
        return existing

    user = User(email=email, tier=tier)
    session.add(user)
    await session.flush()
    return user


async def _get_or_create_api_key(
    session: AsyncSession,
    user: User,
    name: str,
    plain_key: str,
) -> APIKey:
    key_hash = hash_api_key(plain_key)
    existing = await session.scalar(select(APIKey).where(APIKey.key_hash == key_hash))
    if existing is not None:
        existing.user_id = user.id
        existing.name = name
        existing.is_active = True
        return existing

    api_key = APIKey(
        user_id=user.id,
        key_hash=key_hash,
        prefix=api_key_prefix(plain_key),
        name=name,
        is_active=True,
    )
    session.add(api_key)
    await session.flush()
    return api_key
