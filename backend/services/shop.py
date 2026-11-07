"""
Shop logic: pricing, order reservation (wallet debit), completion / refund, free-test reservation,
service refresh and config-file bundles.

Money rule: the wallet is debited in its own committed transaction BEFORE the panel is called, and
refunded (REFUND row in the ledger) if the panel fails. Every ledger row has a unique idempotency key.
"""
import base64
import json
import math
import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.base import ADAPTERS, ConfigFile, PanelCredentials, RemoteService, build_adapter
from backend.services.errors import DomainError, NotFound
from backend.services.settings_service import get_settings_map
from backend.services.wallet import apply_wallet_change
from config.crypto import decrypt_bytes, decrypt_text, encrypt_bytes
from database.base import utcnow
from database.models import (
    FreeTest, Order, OrderStatus, Panel, Service, ServiceProfile, ServiceStatus, TxType,
)

GB = 1024 ** 3
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


class TestLimitReached(DomainError):
    pass


def valid_username(name: str) -> bool:
    return bool(USERNAME_RE.fullmatch(name or ""))


def calc_price(panel: Panel, gb: int, days: int) -> int:
    return gb * panel.price_per_gb + days * panel.price_per_day


def adapter_available(panel: Panel) -> bool:
    return panel.panel_type.value in ADAPTERS


def adapter_for(panel: Panel):
    creds = PanelCredentials(
        api_url=panel.api_url,
        username=decrypt_text(panel.username_enc),
        password=decrypt_text(panel.password_enc),
        token=decrypt_text(panel.token_enc),
        extra=panel.extra or {},
    )
    return build_adapter(panel.panel_type.value, creds)


def inbound_ids(profile: ServiceProfile) -> list[str]:
    return [str(i["id"]) for i in (profile.inbounds or [])]


# ---------- config files bundle (stored Fernet-encrypted in Service.config_blob_enc) ----------
def pack_files(files: list[ConfigFile]) -> bytes:
    data = [{"n": f.filename, "b": base64.b64encode(f.content).decode()} for f in files]
    return encrypt_bytes(json.dumps(data).encode())


def unpack_files(blob: bytes | None) -> list[ConfigFile]:
    if not blob:
        return []
    try:
        return [ConfigFile(x["n"], base64.b64decode(x["b"])) for x in json.loads(decrypt_bytes(blob))]
    except Exception:
        return []


def _store_bundle(svc: Service, files: list[ConfigFile]) -> None:
    if files:
        svc.config_filename = "bundle.json"
        svc.config_blob_enc = pack_files(files)


# ---------- what can be sold ----------
async def sellable_panels(session: AsyncSession) -> list[tuple[Panel, list[ServiceProfile]]]:
    panels = (await session.execute(
        select(Panel).where(Panel.is_active.is_(True), Panel.sales_enabled.is_(True))
        .order_by(Panel.sort_order, Panel.id))).scalars().all()
    profiles = (await session.execute(
        select(ServiceProfile).where(ServiceProfile.is_active.is_(True), ServiceProfile.sales_enabled.is_(True))
        .order_by(ServiceProfile.sort_order, ServiceProfile.id))).scalars().all()
    out = []
    for p in panels:
        if not adapter_available(p):
            continue
        mine = [x for x in profiles if x.panel_id == p.id and x.inbounds]
        if mine:
            out.append((p, mine))
    return out


# ---------- purchase ----------
async def reserve_purchase(
    session: AsyncSession, *, user_id: int, panel_id: int, profile_id: int, username: str,
    gb: int, days: int, key: str,
) -> Order:
    """Creates the order and debits the wallet. Raises InsufficientFunds (nothing is saved then)."""
    panel = await session.get(Panel, panel_id)
    profile = await session.get(ServiceProfile, profile_id)
    ok = (panel and profile and profile.panel_id == panel.id and panel.is_active and panel.sales_enabled
          and profile.is_active and profile.sales_enabled and adapter_available(panel) and profile.inbounds)
    if not ok:
        raise NotFound("این محصول در حال حاضر قابل فروش نیست.")
    if not (panel.min_gb <= gb <= panel.max_gb and panel.min_days <= days <= panel.max_days):
        raise DomainError("حجم یا مدت خارج از محدوده مجاز است.")
    price = calc_price(panel, gb, days)
    if price <= 0:
        raise DomainError("قیمت این سرویس هنوز تنظیم نشده است.")
    order = Order(
        user_id=user_id, panel_id=panel.id, profile_id=profile.id, service_username=username,
        gb=gb, days=days, price=price, discount=0, final_price=price,
        status=OrderStatus.AWAITING_PAYMENT, idempotency_key=key,
    )
    session.add(order)
    await session.flush()
    await apply_wallet_change(
        session, user_id=user_id, delta=-price, tx_type=TxType.PURCHASE,
        idempotency_key=f"order:{order.id}:pay", ref_type="order", ref_id=order.id,
        description=f"خرید سرویس {username}",
    )
    order.status = OrderStatus.PROVISIONING
    await session.flush()
    return order


async def complete_order(session: AsyncSession, order_id: int, remote: RemoteService) -> Service:
    order = await session.get(Order, order_id)
    now = utcnow()
    svc = Service(
        user_id=order.user_id, order_id=order.id, panel_id=order.panel_id, profile_id=order.profile_id,
        username=order.service_username, remote_id=remote.remote_id, protocol=(remote.protocol or "")[:32],
        is_test=False, total_bytes=remote.total_bytes or order.gb * GB, used_bytes=remote.used_bytes or 0,
        purchased_days=order.days, started_at=now, expires_at=remote.expires_at or now + timedelta(days=order.days),
        status=ServiceStatus.ACTIVE, subscription_link=remote.subscription_link, last_synced_at=now,
    )
    _store_bundle(svc, remote.config_files)
    session.add(svc)
    order.status = OrderStatus.COMPLETED
    await session.flush()
    return svc


async def fail_order(session: AsyncSession, order_id: int, error: str) -> int:
    """Marks the order failed and refunds the wallet (once). Returns the new balance."""
    order = await session.get(Order, order_id)
    order.status = OrderStatus.FAILED
    order.error = (error or "")[:1000]
    res = await apply_wallet_change(
        session, user_id=order.user_id, delta=order.final_price, tx_type=TxType.REFUND,
        idempotency_key=f"order:{order.id}:refund", ref_type="order", ref_id=order.id,
        description=f"بازگشت وجه سفارش #{order.id}",
    )
    await session.flush()
    return res.tx.balance_after


async def username_in_use(session: AsyncSession, panel_id: int, username: str) -> bool:
    """Local check (orders in progress / existing services). The panel itself is checked by the adapter."""
    low = username.lower()
    orders = (await session.execute(
        select(func.count()).select_from(Order).where(
            Order.panel_id == panel_id, func.lower(Order.service_username) == low,
            Order.status.notin_([OrderStatus.FAILED, OrderStatus.CANCELED, OrderStatus.REFUNDED])))).scalar_one()
    services = (await session.execute(
        select(func.count()).select_from(Service).where(
            Service.panel_id == panel_id, func.lower(Service.username) == low,
            Service.status != ServiceStatus.DELETED))).scalar_one()
    return bool(orders or services)


# ---------- free test ----------
async def get_test_target(session: AsyncSession) -> dict:
    """Validates the free-test configuration. Raises DomainError with a customer-safe message."""
    cfg = await get_settings_map(session, [
        "test_enabled", "test_panel_id", "test_profile_id", "test_gb", "test_hours", "test_max_per_user"])
    if cfg["test_enabled"] != "1":
        raise DomainError("\U0001f381 تست رایگان فعلا\u064b غیرفعال است.")
    if not (cfg["test_panel_id"].isdigit() and cfg["test_profile_id"].isdigit()):
        raise DomainError("\U0001f381 تست رایگان هنوز تنظیم نشده است. با پشتیبانی تماس بگیرید.")
    panel = await session.get(Panel, int(cfg["test_panel_id"]))
    profile = await session.get(ServiceProfile, int(cfg["test_profile_id"]))
    if not (panel and profile and profile.panel_id == panel.id and panel.is_active and profile.is_active
            and profile.inbounds and adapter_available(panel)):
        raise DomainError("\U0001f381 تست رایگان موقتا\u064b در دسترس نیست.")
    try:
        gb = float(cfg["test_gb"] or "1")
        hours = int(cfg["test_hours"] or "24")
        max_per_user = int(cfg["test_max_per_user"] or "1")
    except ValueError:
        raise DomainError("\U0001f381 تنظیمات تست رایگان نامعتبر است.")
    return {"panel": panel, "profile": profile, "gb": gb, "hours": hours, "max_per_user": max_per_user}


async def test_count(session: AsyncSession, telegram_id: int) -> int:
    return int((await session.execute(
        select(func.count()).select_from(FreeTest).where(FreeTest.telegram_id == telegram_id))).scalar_one())


async def reserve_test(session: AsyncSession, *, user_id: int, telegram_id: int, max_per_user: int):
    n = await test_count(session, telegram_id)
    if n >= max_per_user:
        raise TestLimitReached()
    ft = FreeTest(user_id=user_id, telegram_id=telegram_id)
    session.add(ft)
    await session.flush()
    return ft, n + 1


async def complete_test(session: AsyncSession, ft_id: int, *, panel_id: int, profile_id: int, username: str,
                        total_bytes: int, hours: int, remote: RemoteService) -> Service:
    ft = await session.get(FreeTest, ft_id)
    now = utcnow()
    svc = Service(
        user_id=ft.user_id, order_id=None, panel_id=panel_id, profile_id=profile_id, username=username,
        remote_id=remote.remote_id, protocol=(remote.protocol or "")[:32], is_test=True,
        total_bytes=remote.total_bytes or total_bytes, used_bytes=remote.used_bytes or 0,
        purchased_days=max(1, math.ceil(hours / 24)), started_at=now,
        expires_at=remote.expires_at or now + timedelta(hours=hours), status=ServiceStatus.ACTIVE,
        subscription_link=remote.subscription_link, last_synced_at=now,
    )
    _store_bundle(svc, remote.config_files)
    session.add(svc)
    await session.flush()
    ft.service_id = svc.id
    await session.flush()
    return svc


async def cancel_test(session: AsyncSession, ft_id: int) -> None:
    """Failed test creation: give the attempt back to the customer."""
    ft = await session.get(FreeTest, ft_id)
    if ft is not None:
        await session.delete(ft)
        await session.flush()


# ---------- my services ----------
async def user_services(session: AsyncSession, user_id: int, limit: int = 20) -> list[Service]:
    return list((await session.execute(
        select(Service).where(Service.user_id == user_id, Service.status != ServiceStatus.DELETED)
        .order_by(Service.id.desc()).limit(limit))).scalars())


def apply_remote(svc: Service, remote: RemoteService) -> None:
    """Copies the panel's current numbers into our cache."""
    svc.used_bytes = remote.used_bytes or 0
    if remote.total_bytes:
        svc.total_bytes = remote.total_bytes
    if remote.expires_at:
        svc.expires_at = remote.expires_at
    exp = svc.expires_at if svc.expires_at.tzinfo else svc.expires_at.replace(tzinfo=utcnow().tzinfo)
    if exp < utcnow():
        svc.status = ServiceStatus.EXPIRED
    elif svc.total_bytes and svc.used_bytes >= svc.total_bytes:
        svc.status = ServiceStatus.DEPLETED
    elif not remote.enabled:
        svc.status = ServiceStatus.DISABLED
    else:
        svc.status = ServiceStatus.ACTIVE
    if remote.subscription_link:
        svc.subscription_link = remote.subscription_link
    if remote.config_files:
        _store_bundle(svc, remote.config_files)
    svc.last_synced_at = utcnow()
    svc.last_sync_error = None
