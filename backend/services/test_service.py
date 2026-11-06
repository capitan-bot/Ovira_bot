"""
Free test accounts for ALL panels, each with its own limits.

Per-panel options live in Panel.extra["test"] (no database migration needed):
    enabled        on/off for this panel                        (default: on)
    profile_id     profile used for the test                    (default: first active profile with inbounds)
    gb / hours     size and length of the test                  (default: the global values from settings)
    max_per_user   tests ONE user may take on THIS panel        (default: 1)
    max_total      tests this panel may give out in total       (default: 0 = no cap)

Global settings (table settings): test_enabled (master switch), test_gb, test_hours,
test_max_per_user (tests ONE user may take across ALL panels together).

Counting: per-panel numbers are counted from the services table (is_test=True) so a deleted test still
counts; the global number comes from free_tests (reserved before the panel is called).
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.errors import DomainError
from backend.services.settings_service import get_settings_map
from backend.services.shop import adapter_available, test_count
from database.models import Panel, Service, ServiceProfile

PANEL_DEFAULTS = {"enabled": True, "profile_id": None, "gb": None, "hours": None, "max_per_user": 1, "max_total": 0}


class TestNotAllowed(DomainError):
    """Customer-safe message in str(e)."""
    __test__ = False


def panel_test_cfg(panel: Panel) -> dict:
    cfg = dict(PANEL_DEFAULTS)
    cfg.update((panel.extra or {}).get("test", {}))
    return cfg


async def set_panel_test(session: AsyncSession, panel: Panel, **changes) -> None:
    extra = dict(panel.extra or {})          # new dict objects, so SQLAlchemy sees the change
    test = dict(extra.get("test", {}))
    test.update(changes)
    extra["test"] = test
    panel.extra = extra
    await session.flush()


async def global_cfg(session: AsyncSession) -> dict:
    v = await get_settings_map(session, ["test_enabled", "test_gb", "test_hours", "test_max_per_user",
                                         "test_panel_id", "test_profile_id"])
    def num(key, cast, default):
        try:
            return cast(v[key] or default)
        except (TypeError, ValueError):
            return cast(default)
    return {"enabled": v["test_enabled"] == "1", "gb": num("test_gb", float, 1), "hours": num("test_hours", int, 24),
            "max_per_user": num("test_max_per_user", int, 1),
            "legacy_panel": int(v["test_panel_id"]) if v["test_panel_id"].isdigit() else None,
            "legacy_profile": int(v["test_profile_id"]) if v["test_profile_id"].isdigit() else None}


async def usable_profiles(session: AsyncSession, panel_id: int) -> list[ServiceProfile]:
    rows = (await session.execute(
        select(ServiceProfile).where(ServiceProfile.panel_id == panel_id, ServiceProfile.is_active.is_(True))
        .order_by(ServiceProfile.sort_order, ServiceProfile.id))).scalars().all()
    return [p for p in rows if p.inbounds]


async def resolve_profile(session: AsyncSession, panel: Panel, cfg: dict, glob: dict) -> ServiceProfile | None:
    profiles = await usable_profiles(session, panel.id)
    wanted = cfg.get("profile_id")
    if wanted is None and glob["legacy_panel"] == panel.id:
        wanted = glob["legacy_profile"]                      # the single test target chosen in the older version
    if wanted is not None:
        for p in profiles:
            if p.id == wanted:
                return p
    return profiles[0] if profiles else None


async def count_user_on_panel(session: AsyncSession, user_id: int, panel_id: int) -> int:
    return int((await session.execute(select(func.count()).select_from(Service).where(
        Service.user_id == user_id, Service.panel_id == panel_id, Service.is_test.is_(True)))).scalar_one())


async def count_panel_total(session: AsyncSession, panel_id: int) -> int:
    return int((await session.execute(select(func.count()).select_from(Service).where(
        Service.panel_id == panel_id, Service.is_test.is_(True)))).scalar_one())


def effective(cfg: dict, glob: dict) -> tuple[float, int]:
    gb = float(cfg["gb"]) if cfg.get("gb") else glob["gb"]
    hours = int(cfg["hours"]) if cfg.get("hours") else glob["hours"]
    return gb, hours


async def panel_target(session: AsyncSession, panel: Panel, glob: dict | None = None) -> dict | None:
    """Everything needed to give a test on this panel, or None when the panel offers no test."""
    glob = glob or await global_cfg(session)
    cfg = panel_test_cfg(panel)
    if not (panel.is_active and cfg["enabled"] and adapter_available(panel)):
        return None
    profile = await resolve_profile(session, panel, cfg, glob)
    if profile is None:
        return None
    gb, hours = effective(cfg, glob)
    return {"panel": panel, "profile": profile, "gb": gb, "hours": hours,
            "max_per_user": max(1, int(cfg["max_per_user"] or 1)), "max_total": int(cfg["max_total"] or 0)}


async def test_options(session: AsyncSession) -> tuple[dict, list[dict]]:
    glob = await global_cfg(session)
    panels = (await session.execute(select(Panel).where(Panel.is_active.is_(True))
                                    .order_by(Panel.sort_order, Panel.id))).scalars().all()
    out = []
    for p in panels:
        t = await panel_target(session, p, glob)
        if t:
            out.append(t)
    return glob, out


async def check_allowed(session: AsyncSession, *, user_id: int, telegram_id: int, panel_id: int) -> tuple[dict, dict]:
    """Full check before a test is made. Returns (global cfg, target). Raises TestNotAllowed with a customer-safe text."""
    glob = await global_cfg(session)
    if not glob["enabled"]:
        raise TestNotAllowed("\U0001f381 تست رایگان فعلاً غیرفعال است.")
    panel = await session.get(Panel, panel_id)
    target = await panel_target(session, panel, glob) if panel else None
    if target is None:
        raise TestNotAllowed("\U0001f381 تست رایگان این پنل در حال حاضر در دسترس نیست.")
    if await test_count(session, telegram_id) >= glob["max_per_user"]:
        raise TestNotAllowed("\U0001f381 شما از سهمیه کل تست رایگان خود استفاده کرده‌اید.")
    if await count_user_on_panel(session, user_id, panel_id) >= target["max_per_user"]:
        raise TestNotAllowed("\U0001f381 شما قبلاً تست رایگان این پنل را گرفته‌اید. از پنل‌های دیگر یا خرید اشتراک استفاده کنید.")
    if target["max_total"] and await count_panel_total(session, panel_id) >= target["max_total"]:
        raise TestNotAllowed("\U0001f381 ظرفیت تست رایگان این پنل تمام شده است.")
    return glob, target
