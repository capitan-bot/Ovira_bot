"""
PasarGuard panel adapter.

Auth: admin username + password -> POST /api/admin/token (OAuth2 form) -> Bearer access token.
      (An existing access token saved as the panel "token" is used as is.)
api_url = the panel address, e.g. https://panel.example.com:8000  (no /dashboard, no trailing slash).

"Inbounds" of this panel are its GROUPS (a group decides which hosts/inbounds a user may use), so the
profile's selected inbounds become the user's group_ids.
The customer receives the panel's own subscription link (UserResponse.subscription_url, untouched;
only a relative path is completed with the panel address).

Endpoints used (from the PasarGuard panel source / SDKs): POST /api/admin/token, GET /api/groups,
POST /api/user, GET|PUT|DELETE /api/user/{username} (with /api/user/by-username/{username} and
/api/user/by-id/{id} as fallbacks, because the vendor is moving lookups to the numeric id).
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from adapters.base import (
    CreateUserRequest, InboundInfo, PanelAdapter, PanelAuthError, PanelError, RemoteService,
    UnsupportedOperation, UsernameTaken, register,
)

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_expire(value) -> datetime | None:
    """The panel returns an ISO date-time, a unix timestamp, or null/0 for 'never'."""
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def full_sub_url(url: str | None, api_url: str) -> str | None:
    if not url:
        return None
    if url.startswith("/"):
        p = urlparse(api_url)
        return f"{p.scheme}://{p.netloc}{url}"
    return url


def _detail(r: httpx.Response) -> str:
    try:
        j = r.json()
        d = j.get("detail", j) if isinstance(j, dict) else j
        return (d if isinstance(d, str) else str(d))[:300]
    except Exception:
        return (r.text or f"HTTP {r.status_code}")[:300]


class _Api:
    def __init__(self, creds, transport=None):
        self.base = creds.api_url.rstrip("/")
        self.token = creds.token
        self.username = creds.username
        self.password = creds.password
        verify = (creds.extra or {}).get("verify_ssl", True)
        self.http = httpx.AsyncClient(timeout=TIMEOUT, verify=verify, transport=transport, follow_redirects=False)

    async def close(self):
        await self.http.aclose()

    async def _raw(self, method, path, auth=True, **kw):
        headers = kw.pop("headers", {})
        headers.setdefault("Accept", "application/json")
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            return await self.http.request(method, self.base + path, headers=headers, **kw)
        except httpx.TimeoutException:
            raise PanelError("PasarGuard: the panel did not answer in time.")
        except httpx.HTTPError as e:
            raise PanelError(f"PasarGuard: cannot reach the panel ({type(e).__name__}: {e}).")

    async def _login(self):
        if not (self.username and self.password):
            raise PanelAuthError("PasarGuard: no username/password saved for this panel.")
        r = await self._raw("POST", "/api/admin/token", auth=False,
                            data={"username": self.username, "password": self.password, "grant_type": "password"})
        if r.status_code in (401, 403, 422):
            raise PanelAuthError(f"PasarGuard login failed: {_detail(r)}")
        if r.status_code >= 400:
            raise PanelError(f"PasarGuard: login answered HTTP {r.status_code}: {_detail(r)}")
        try:
            self.token = r.json()["access_token"]
        except Exception:
            raise PanelAuthError("PasarGuard: login did not return an access token (check the panel address).")

    async def request(self, method, path, **kw) -> httpx.Response:
        if not self.token:
            await self._login()
        r = await self._raw(method, path, **kw)
        if r.status_code == 401 and self.username and self.password:      # token expired: sign in once more
            await self._login()
            r = await self._raw(method, path, **kw)
        return r

    async def json(self, method, path, **kw):
        r = await self.request(method, path, **kw)
        if r.status_code in (401, 403):
            raise PanelAuthError(f"PasarGuard: not authorised ({_detail(r)}).")
        if r.status_code >= 400:
            raise PanelError(f"PasarGuard: HTTP {r.status_code}: {_detail(r)}")
        return r.json() if r.content else {}


@register("pasargad")
@register("pasarguard")
class PasarGuardAdapter(PanelAdapter):
    _transport = None   # tests inject a transport here

    def _api(self) -> _Api:
        return _Api(self.creds, self._transport)

    # ---------- helpers ----------
    async def _fetch(self, api: _Api, username: str) -> dict | None:
        for path in (f"/api/user/{username}", f"/api/user/by-username/{username}"):
            r = await api.request("GET", path)
            if r.status_code in (401, 403):
                raise PanelAuthError(f"PasarGuard: not authorised ({_detail(r)}).")
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (404, 405):
                raise PanelError(f"PasarGuard: HTTP {r.status_code}: {_detail(r)}")
        return None

    async def _need(self, api: _Api, username: str) -> dict:
        u = await self._fetch(api, username)
        if u is None:
            raise PanelError(f"PasarGuard: user '{username}' was not found on the panel.")
        return u

    async def _send(self, api: _Api, method: str, user: dict, body: dict | None = None) -> httpx.Response:
        """PUT / DELETE on a user: numeric id first (vendor's new way), then the username routes."""
        paths = []
        if user.get("id") is not None:
            paths.append(f"/api/user/by-id/{user['id']}")
        paths += [f"/api/user/{user['username']}", f"/api/user/by-username/{user['username']}"]
        last = None
        for p in paths:
            r = await api.request(method, p, **({"json": body} if body is not None else {}))
            if r.status_code in (401, 403):
                raise PanelAuthError(f"PasarGuard: not authorised ({_detail(r)}).")
            if r.status_code not in (404, 405):
                return r
            last = r
        raise PanelError(f"PasarGuard: no {method} route worked for user '{user['username']}' "
                         f"(HTTP {last.status_code if last else '?'}).")

    def _to_service(self, u: dict) -> RemoteService:
        return RemoteService(
            remote_id=str(u.get("id") if u.get("id") is not None else u["username"]),
            username=u["username"], protocol="pasargad",
            total_bytes=int(u.get("data_limit") or 0), used_bytes=int(u.get("used_traffic") or 0),
            expires_at=parse_expire(u.get("expire")), enabled=u.get("status") != "disabled",
            subscription_link=full_sub_url(u.get("subscription_url"), self.creds.api_url), config_files=[])

    # ---------- contract ----------
    async def _groups(self, api: _Api) -> list[dict]:
        r = await api.request("GET", "/api/groups", params={"offset": 0, "limit": 500})
        if r.status_code == 422:                               # this version has no paging parameters
            r = await api.request("GET", "/api/groups")
        if r.status_code in (401, 403):
            raise PanelAuthError(f"PasarGuard: not authorised ({_detail(r)}).")
        if r.status_code >= 400:
            raise PanelError(f"PasarGuard: HTTP {r.status_code}: {_detail(r)}")
        j = r.json()
        return j.get("groups", []) if isinstance(j, dict) else (j or [])

    async def test_connection(self) -> None:
        api = self._api()
        try:
            await self._groups(api)         # logs in AND proves the account may read groups
        finally:
            await api.close()

    async def list_inbounds(self) -> list[InboundInfo]:
        api = self._api()
        try:
            groups = await self._groups(api)
        finally:
            await api.close()
        out = []
        for g in groups:
            if g.get("is_disabled"):
                continue
            tags = g.get("inbound_tags") or []
            out.append(InboundInfo(id=str(g["id"]), remark=g.get("name") or f"group {g['id']}",
                                   protocol="group" + (f" ({len(tags)} inbounds)" if tags else ""), port=None))
        return out

    async def username_exists(self, username: str) -> bool:
        api = self._api()
        try:
            return await self._fetch(api, username) is not None
        finally:
            await api.close()

    async def create_user(self, req: CreateUserRequest) -> RemoteService:
        body = {
            "username": req.username, "status": "active", "data_limit": int(req.total_bytes),
            "expire": iso_utc(req.expires_at),
            "group_ids": [int(i) for i in req.inbound_ids],
        }
        if req.settings.get("note"):
            body["note"] = str(req.settings["note"])[:500]
        api = self._api()
        try:
            r = await api.request("POST", "/api/user", json=body)
            if r.status_code == 409 or (r.status_code in (400, 422) and re.search(
                    r"already|exist|taken|duplicate", _detail(r), re.I)):
                raise UsernameTaken(f"PasarGuard: user name '{req.username}' already exists.")
            if r.status_code in (401, 403):
                raise PanelAuthError(f"PasarGuard: not authorised ({_detail(r)}).")
            if r.status_code >= 400:
                raise PanelError(f"PasarGuard: HTTP {r.status_code}: {_detail(r)}")
            return self._to_service(r.json())
        finally:
            await api.close()

    async def get_user(self, username: str) -> RemoteService:
        api = self._api()
        try:
            return self._to_service(await self._need(api, username))
        finally:
            await api.close()

    async def set_enabled(self, username: str, enabled: bool) -> None:
        api = self._api()
        try:
            u = await self._need(api, username)
            r = await self._send(api, "PUT", u, {"status": "active" if enabled else "disabled"})
            if r.status_code >= 400:
                raise PanelError(f"PasarGuard: HTTP {r.status_code}: {_detail(r)}")
        finally:
            await api.close()

    async def renew(self, username: str, add_bytes: int, new_expires_at: datetime) -> None:
        """Adds bytes to the current limit, sets the new end date and re-activates a limited/expired user."""
        api = self._api()
        try:
            u = await self._need(api, username)
            cur = int(u.get("data_limit") or 0)
            body = {"data_limit": cur + int(add_bytes) if cur > 0 else cur,
                    "expire": iso_utc(new_expires_at), "status": "active"}
            r = await self._send(api, "PUT", u, body)
            if r.status_code >= 400:
                raise PanelError(f"PasarGuard: HTTP {r.status_code}: {_detail(r)}")
            after = parse_expire(r.json().get("expire")) if r.content else None
            if after and abs((after - new_expires_at.astimezone(timezone.utc)).total_seconds()) > 2 * 86400:
                raise PanelError("PasarGuard: the new end date did not land as expected. "
                                 "Check the user on the panel before charging the customer.")
        finally:
            await api.close()

    async def delete_user(self, username: str) -> None:
        api = self._api()
        try:
            u = await self._fetch(api, username)
            if u is None:
                return                  # already gone
            r = await self._send(api, "DELETE", u)
            if r.status_code >= 400 and r.status_code != 404:
                raise PanelError(f"PasarGuard: HTTP {r.status_code}: {_detail(r)}")
        finally:
            await api.close()

    async def set_traffic(self, username: str, total_bytes: int) -> None:
        raise UnsupportedOperation("PasarGuard: setting an absolute limit is not wired up; use renew (adds bytes).")
