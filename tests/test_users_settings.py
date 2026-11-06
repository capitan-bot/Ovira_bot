from backend.services.settings_service import get_setting, set_setting
from backend.services.users import get_or_create_user, get_wallet
from bot.utils import safe_format


async def test_register_creates_wallet_once(session):
    u1, c1 = await get_or_create_user(session, telegram_id=5, first_name="a", last_name=None, username="x")
    u2, c2 = await get_or_create_user(session, telegram_id=5, first_name="b", last_name=None, username="x")
    assert c1 and not c2 and u1.id == u2.id
    assert u2.first_name == "b"
    assert (await get_wallet(session, u1.id)).balance == 0


async def test_referrer_ignored_for_self_and_unknown(session):
    a, _ = await get_or_create_user(session, telegram_id=1, first_name="a", last_name=None, username=None)
    b, _ = await get_or_create_user(session, telegram_id=2, first_name="b", last_name=None, username=None,
                                    referrer_telegram_id=1)
    c, _ = await get_or_create_user(session, telegram_id=3, first_name="c", last_name=None, username=None,
                                    referrer_telegram_id=3)
    d, _ = await get_or_create_user(session, telegram_id=4, first_name="d", last_name=None, username=None,
                                    referrer_telegram_id=999)
    assert b.referrer_id == a.id and c.referrer_id is None and d.referrer_id is None


async def test_settings_roundtrip(session):
    assert await get_setting(session, "k", "def") == "def"
    await set_setting(session, "k", "v1")
    await set_setting(session, "k", "v2")
    assert await get_setting(session, "k") == "v2"


def test_safe_format_never_crashes():
    assert safe_format("سلام {name}", name="علی") == "سلام علی"
    assert safe_format("سلام {unknown}", name="x") == "سلام {unknown}"
    assert safe_format("broken {", name="x") == "broken {"
