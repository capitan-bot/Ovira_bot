from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog, User, Wallet


async def get_or_create_user(
    session: AsyncSession, *, telegram_id: int, first_name: str | None, last_name: str | None,
    username: str | None, referrer_telegram_id: int | None = None,
) -> tuple[User, bool]:
    """Returns (user, created). Safe against two simultaneous first messages."""
    user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
    if user:
        # keep profile fields fresh
        _old = (user.first_name, user.last_name, user.username)
        if _old != (first_name, last_name, username):
            user.profile_before = _old
            user.first_name, user.last_name, user.username = first_name, last_name, username
        return user, False

    referrer_id = None
    if referrer_telegram_id and referrer_telegram_id != telegram_id:
        referrer_id = (await session.execute(
            select(User.id).where(User.telegram_id == referrer_telegram_id)
        )).scalar_one_or_none()

    try:
        async with session.begin_nested():
            user = User(telegram_id=telegram_id, first_name=first_name, last_name=last_name,
                        username=username, referrer_id=referrer_id)
            session.add(user)
            await session.flush()
            session.add(Wallet(user_id=user.id))
            await session.flush()
        return user, True
    except IntegrityError:
        user = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()
        return user, False


async def get_wallet(session: AsyncSession, user_id: int) -> Wallet:
    return (await session.execute(select(Wallet).where(Wallet.user_id == user_id))).scalar_one()


async def audit(session: AsyncSession, actor: str, action: str, target: str | None = None,
                details: dict | None = None) -> None:
    session.add(AuditLog(actor=actor, action=action, target=target, details=details))
    await session.flush()
