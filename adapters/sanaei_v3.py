"""
3x-ui v3 ("modern") API support for SanaeiAdapter.

Why this exists: 3x-ui v3 removed the legacy inbounds/addClient routes. Clients are now separate
objects created with POST /panel/api/clients/add and attached to inbounds. Connection links are
produced by the panel itself (GET /panel/api/clients/links/{email}); we never build links ourselves.

Rules enforced here:
  * a user counts as created ONLY if the panel returns it when read back;
  * links come from the panel, never from a template;
  * the subscription URL is delivered only if it answers HTTP 200 with a body;
  * if anything fails after the client was added, it is deleted again and PanelError is raised,
    so the caller can refund.
"""
import logging
import re
import secrets
import string
import uuid as uuidlib
from datetime import datetime, timezone
from urllib.parse import quote, urljoin

from adapters.base import ConfigFile, CreateUserRequest, InboundInfo, PanelError, RemoteService, UsernameTaken

log = logging.getLogger("capitan.sanaei")

_NAME_RE = re.compile(r"[A-Za-z0-9_.\-]{3,32}")
_READONLY = {"traffic", "createdAt", "updatedAt", "inboundIds"}


def _ok(j) -> bool:
    return isinstance(j, dict) and j.get("success") is True


def _msg(j) -> str:
    return str(j.get("msg"))[:200] if isinstance(j, dict) and j.get("msg") else "no message"


def _sub_id(n: int = 16) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _require_token(self) -> None:
    if not self.token:
        raise PanelError(
            "Sanaei: this 3x-ui v3 panel needs an API token for write operations "
            "(panel: Settings > Security > API Token)."
        )


async def _call(self, method: str, path: str, **kw):
    """Raw API call -> (http_status, json_or_None). Re-logs in once on 401/403."""
    if not self.logged_in:
        await self._login()
    url = urljoin(self.base, "api/" + path.lstrip("/"))
    r = await self.http.request(method, url, **kw)
    if r.status_code in (401, 403):
        self.logged_in = False
        await self._login()
        r = await self.http.request(method, url, **kw)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j


async def _inbound_map(self) -> dict:
    st, j = await _call(self, "GET", "inbounds/list")
    if st != 200 or not _ok(j):
        raise PanelError("Sanaei: cannot read inbounds (HTTP %s: %s)" % (st, _msg(j)))
    return {int(ib["id"]): ib for ib in (j.get("obj") or []) if "id" in ib}


async def _get_client(self, email: str):
    """Returns the client dict (with inboundIds) or None when the panel does not know it."""
    st, j = await _call(self, "GET", "clients/get/" + quote(email, safe=""))
    if st == 404:
        return None
    if st == 200 and _ok(j):
        obj = j.get("obj")
        if not isinstance(obj, dict) or not obj:
            return None
        c = obj.get("client") if isinstance(obj.get("client"), dict) else obj
        if not c:
            return None
        c = dict(c)
        if not c.get("inboundIds"):
            c["inboundIds"] = obj.get("inboundIds") or []
        return c
    if st == 200 and isinstance(j, dict) and j.get("success") is False:
        return None
    raise PanelError("Sanaei: unexpected answer reading client (HTTP %s: %s)" % (st, _msg(j)))


async def _links(self, email: str) -> list:
    st, j = await _call(self, "GET", "clients/links/" + quote(email, safe=""))
    if st != 200 or not _ok(j):
        return []
    obj = j.get("obj")
    if isinstance(obj, dict):
        obj = obj.get("links")
    return [str(x).strip() for x in (obj or []) if isinstance(x, str) and "://" in x]


async def _traffic(self, email: str, client: dict):
    st, j = await _call(self, "GET", "clients/traffic/" + quote(email, safe=""))
    if st == 200 and _ok(j) and isinstance(j.get("obj"), dict):
        o = j["obj"]
        return int(o.get("up") or 0) + int(o.get("down") or 0)
    t = client.get("traffic")
    if isinstance(t, dict):
        return int(t.get("up") or 0) + int(t.get("down") or 0)
    return 0


async def _fetch_sub(self, url: str) -> bool:
    import httpx  # imported lazily; separate client so the panel API token is never sent to the sub URL
    try:
        async with httpx.AsyncClient(timeout=20, verify=False, follow_redirects=True) as c:
            r = await c.get(url)
        return r.status_code == 200 and len(r.text.strip()) > 0
    except Exception as e:
        log.warning("sub url check failed: %s", type(e).__name__)
        return False


async def _sub_base(self) -> str:
    base = (self.extra or {}).get("sub_base")
    if base:
        return base.rstrip("/") + "/"
    return await self._resolve_sub_base()


async def _cleanup(self, email: str) -> None:
    try:
        await _call(self, "POST", "clients/del/" + quote(email, safe=""))
    except Exception as e:  # best effort; the original error is what matters
        log.error("cleanup of %s failed: %s", email, type(e).__name__)


def _to_ms(dt) -> int:
    if not dt:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _from_ms(ms):
    ms = int(ms or 0)
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms > 0 else None


def _scheme(links: list) -> str:
    return links[0].split("://", 1)[0].lower() if links else "vmess"


# ------------------------------------------------------------------ public adapter methods
async def list_inbounds(self):
    ibs = await _inbound_map(self)
    return [InboundInfo(id=str(i), remark=str(ib.get("remark", "")), protocol=str(ib.get("protocol", "")),
                        port=ib.get("port")) for i, ib in sorted(ibs.items())]


async def username_exists(self, username: str) -> bool:
    return (await _get_client(self, username)) is not None


def _make_create_user(allowed_ids):
    async def create_user(self, req: CreateUserRequest) -> RemoteService:
        _require_token(self)
        email = req.username
        if not _NAME_RE.fullmatch(email or ""):
            raise PanelError("Sanaei: invalid username (3-32 chars: letters, digits, _ . -)")

        inbounds = await _inbound_map(self)
        wanted = [int(x) for x in (req.inbound_ids or []) if str(x).isdigit()]
        if not wanted:
            wanted = sorted(i for i in allowed_ids if i in inbounds)
        missing = [i for i in wanted if i not in inbounds]
        if missing or not wanted:
            raise PanelError("Sanaei: inbound(s) %s not found on the panel" % (missing or "none selected"))

        if await _get_client(self, email) is not None:
            raise UsernameTaken("Sanaei: username already exists on the panel")

        client_uuid, sub_id = str(uuidlib.uuid4()), _sub_id()
        base = {"email": email, "subId": sub_id, "totalGB": int(req.total_bytes or 0),
                "expiryTime": _to_ms(req.expires_at), "enable": True, "limitIp": 0}
        attempts = [{**base, "id": client_uuid, "uuid": client_uuid}, {**base, "uuid": client_uuid},
                    {**base, "id": client_uuid}]
        last = "no attempt"
        added = False
        for c in attempts:
            st, j = await _call(self, "POST", "clients/add", json={"inboundIds": wanted, "client": c})
            if st == 200 and _ok(j):
                added = True
                break
            last = "HTTP %s: %s" % (st, _msg(j))
            if await _get_client(self, email) is not None:   # added although the answer looked odd
                added = True
                break
        if not added:
            raise PanelError("Sanaei: clients/add failed (%s)" % last)

        # --- verify: the panel must return what we created
        c = await _get_client(self, email)
        if c is None:
            raise PanelError("Sanaei: panel does not list the new client; nothing was created")
        have = {int(x) for x in (c.get("inboundIds") or [])}
        lacking = sorted(set(wanted) - have)
        if lacking:
            await _call(self, "POST", "clients/%s/attach" % quote(email, safe=""), json={"inboundIds": lacking})
            c = await _get_client(self, email) or {}
            have = {int(x) for x in (c.get("inboundIds") or [])}
            if set(wanted) - have:
                await _cleanup(self, email)
                raise PanelError("Sanaei: could not attach client to inbounds %s" % lacking)

        links = await _links(self, email)
        if not links:
            await _cleanup(self, email)
            raise PanelError("Sanaei: panel returned no connection links for the new client")

        sid = c.get("subId") or sub_id
        sub_url = (await _sub_base(self)) + sid
        if not await _fetch_sub(self, sub_url):
            log.warning("subscription URL for %s did not answer 200; delivering panel links only. "
                        "Set extra.sub_base on the panel record if the base URL is wrong.", email)
            sub_url = None

        return RemoteService(
            remote_id=str(c.get("uuid") or client_uuid), username=email, protocol=_scheme(links),
            total_bytes=int(req.total_bytes or 0), used_bytes=0, expires_at=req.expires_at, enabled=True,
            subscription_link=sub_url,
            config_files=[ConfigFile(filename=email + ".txt", content="\n".join(links).encode("utf-8"))],
        )
    return create_user


async def get_user(self, username: str) -> RemoteService:
    c = await _get_client(self, username)
    if c is None:
        raise PanelError("Sanaei: user not found on the panel")
    links = await _links(self, username)
    used = await _traffic(self, username, c)
    sid = c.get("subId")
    return RemoteService(
        remote_id=str(c.get("uuid") or c.get("id") or username), username=username, protocol=_scheme(links),
        total_bytes=int(c.get("totalGB") or 0), used_bytes=used, expires_at=_from_ms(c.get("expiryTime")),
        enabled=bool(c.get("enable", True)),
        subscription_link=((await _sub_base(self)) + sid) if sid else None,
        config_files=[ConfigFile(filename=username + ".txt", content="\n".join(links).encode("utf-8"))] if links else [],
    )


async def _update(self, email: str, **changes) -> None:
    _require_token(self)
    c = await _get_client(self, email)
    if c is None:
        raise PanelError("Sanaei: user not found on the panel")
    body = {k: v for k, v in c.items() if k not in _READONLY}
    body.update(changes)
    path = "clients/update/" + quote(email, safe="")
    st, j = await _call(self, "POST", path, json=body)
    if not (st == 200 and _ok(j)):
        st, j = await _call(self, "POST", path, json={"client": body})
    if not (st == 200 and _ok(j)):
        raise PanelError("Sanaei: update failed (HTTP %s: %s)" % (st, _msg(j)))
    after = await _get_client(self, email) or {}
    for k, v in changes.items():
        if after.get(k) != v:
            raise PanelError("Sanaei: panel accepted the update but %s did not change" % k)


async def set_enabled(self, username: str, enabled: bool) -> None:
    await _update(self, username, enable=bool(enabled))


async def renew(self, username: str, add_bytes: int, new_expires_at) -> None:
    c = await _get_client(self, username)
    if c is None:
        raise PanelError("Sanaei: user not found on the panel")
    await _update(self, username, totalGB=int(c.get("totalGB") or 0) + int(add_bytes or 0),
                  expiryTime=_to_ms(new_expires_at))


async def set_traffic(self, username: str, total_bytes: int) -> None:
    await _update(self, username, totalGB=int(total_bytes))


async def delete_user(self, username: str) -> None:
    _require_token(self)
    st, j = await _call(self, "POST", "clients/del/" + quote(username, safe=""))
    if not (st == 200 and _ok(j)):
        raise PanelError("Sanaei: delete failed (HTTP %s: %s)" % (st, _msg(j)))
    if await _get_client(self, username) is not None:
        raise PanelError("Sanaei: panel still lists the user after delete")


def install(cls, allowed_ids=()) -> None:
    """Replace the legacy methods of SanaeiAdapter with the v3 implementations."""
    cls.list_inbounds = list_inbounds
    cls.username_exists = username_exists
    cls.create_user = _make_create_user(set(allowed_ids))
    cls.get_user = get_user
    cls.set_enabled = set_enabled
    cls.renew = renew
    cls.set_traffic = set_traffic
    cls.delete_user = delete_user
