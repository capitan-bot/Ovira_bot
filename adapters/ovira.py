"""
Ovira panel adapter (OpenVPN / WireGuard / OpenConnect / IKEv2 / L2TP panel).

Written from the panel's own OpenAPI document (Ovira panel API 1.0.0-beta.2).

Auth:
  * API token: store it as the panel "token" (starts with ovk_). Sent as a Bearer header.
  * Otherwise username + password: signs in with the session cookie and sends X-CSRF-Token on writes.
    Accounts with 2FA need an API token instead.

api_url must be the panel origin plus its secret base path, WITHOUT /api,
e.g. https://panel.example.com:9000/abc123 .

Config files are returned exactly as the panel serves them. The file name comes from the
panel's Content-Disposition header; a name is made up only when the panel sends none.
"""
import math
import re
import time
from datetime import datetime, timezone
from urllib.parse import unquote

import httpx

from adapters.base import (
    ConfigFile, CreateUserRequest, InboundInfo, PanelAdapter, PanelAuthError, PanelError,
    RemoteService, UnsupportedOperation, UsernameTaken, register,
)

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def _ts(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _dt(ts: int | None) -> datetime | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def _filename(resp: httpx.Response, fallback: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I)
    if m:
        name = unquote(m.group(1).strip().strip('"'))
    else:
        m = re.search(r'filename="?([^";]+)"?', cd, re.I)
        name = m.group(1).strip() if m else ""
    name = name.replace("/", "_").replace("\\", "_")
    return name or fallback


class _Api:
    """Small authenticated HTTP helper (one instance per adapter call)."""

    def __init__(self, creds, transport=None):
        self.base = creds.api_url.rstrip("/")
        self.token = creds.token
        self.username = creds.username
        self.password = creds.password
        verify = (creds.extra or {}).get("verify_ssl", True)
        self.http = httpx.AsyncClient(timeout=TIMEOUT, verify=verify, transport=transport, follow_redirects=False)
        self.csrf = ""
        self.logged_in = False

    async def close(self):
        await self.http.aclose()

    async def _login(self):
        if not (self.username and self.password):
            raise PanelAuthError("Ovira: no API token and no username/password saved for this panel.")
        r = await self._raw("POST", "/api/auth/login", json={"username": self.username, "password": self.password},
                            auth=False)
        if r.status_code in (401, 403, 429):
            raise PanelAuthError(f"Ovira login failed: {self._msg(r)}")
        self._check(r)
        data = r.json()
        if data.get("mfa"):
            raise PanelAuthError("Ovira: this account has two-factor sign-in on. Create an API token "
                                 "(Settings -> API) and use it as the panel token instead.")
        self.csrf = data.get("csrf", "")
        self.logged_in = True

    async def _raw(self, method, path, auth=True, **kw):
        headers = kw.pop("headers", {})
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if auth and not self.token and method != "GET" and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        try:
            return await self.http.request(method, self.base + path, headers=headers, **kw)
        except httpx.TimeoutException:
            raise PanelError("Ovira: the panel did not answer in time.")
        except httpx.HTTPError as e:
            raise PanelError(f"Ovira: cannot reach the panel ({type(e).__name__}: {e}).")

    @staticmethod
    def _msg(r: httpx.Response) -> str:
        try:
            j = r.json()
            return str(j.get("error") or j)[:300]
        except Exception:
            return (r.text or f"HTTP {r.status_code}")[:300]

    def _check(self, r: httpx.Response):
        if r.status_code < 400:
            return
        if r.status_code == 401:
            raise PanelAuthError(f"Ovira: not authorised ({self._msg(r)}).")
        if r.status_code == 403:
            raise PanelAuthError(f"Ovira: permission denied ({self._msg(r)}).")
        raise PanelError(f"Ovira: HTTP {r.status_code}: {self._msg(r)}")

    async def request(self, method, path, **kw) -> httpx.Response:
        if not self.token and not self.logged_in:
            await self._login()
        r = await self._raw(method, path, **kw)
        if r.status_code == 401 and not self.token:      # session expired: sign in once more
            await self._login()
            r = await self._raw(method, path, **kw)
        return r

    async def json(self, method, path, **kw):
        r = await self.request(method, path, **kw)
        self._check(r)
        return r.json() if r.content else {}


@register("ovira")
class OviraAdapter(PanelAdapter):
    _transport = None   # tests inject httpx.MockTransport here

    def _api(self) -> _Api:
        return _Api(self.creds, self._transport)

    # ---------- helpers ----------
    async def _find_client(self, api: _Api, username: str) -> dict | None:
        data = await api.json("GET", "/api/clients", params={"q": username, "size": 500})
        for c in data.get("items", []):
            if c.get("name", "").lower() == username.lower():
                return c
        return None

    async def _need_client(self, api: _Api, username: str) -> dict:
        c = await self._find_client(api, username)
        if c is None:
            raise PanelError(f"Ovira: user '{username}' was not found on the panel.")
        return c

    async def _config_files(self, api: _Api, client: dict, slot: int = 1) -> list[ConfigFile]:
        files: list[ConfigFile] = []
        cid, name = client["id"], client["name"]
        detail = await api.json("GET", f"/api/clients/{cid}")
        if any(p.get("kind") == "openvpn" for p in detail.get("profiles", [])):
            r = await api.request("GET", f"/api/clients/{cid}/profile")
            if r.status_code == 200:
                files.append(ConfigFile(_filename(r, f"{name}.ovpn"), r.content))
        wg = await api.request("GET", f"/api/clients/{cid}/wireguard")
        if wg.status_code == 200:
            for srv in wg.json().get("servers", []):
                key = srv.get("key")
                if not key:
                    continue
                r = await api.request("GET", f"/api/clients/{cid}/wireguard/{slot}/{key}/config.conf")
                if r.status_code == 200:
                    files.append(ConfigFile(_filename(r, f"{name}-{key}.conf"), r.content))
        return files

    def _to_service(self, c: dict, files: list[ConfigFile]) -> RemoteService:
        return RemoteService(
            remote_id=str(c["id"]),
            username=c["name"],
            protocol="ovira",
            total_bytes=int(c.get("trafficLimit") or 0),
            used_bytes=int(c.get("usedUp") or 0) + int(c.get("usedDown") or 0),
            expires_at=_dt(c.get("expireAt")),
            enabled=bool(c.get("enabled")) and c.get("status") == "active",
            subscription_link=c.get("subUrl") or None,
            config_files=files,
        )

    # ---------- contract ----------
    async def test_connection(self) -> None:
        api = self._api()
        try:
            me = await api.json("GET", "/api/auth/me")
            perms = me.get("perms") or {}
            if perms and perms.get("clients.create", "none") == "none" and not (me.get("admin") or {}).get("role") == "owner":
                raise PanelAuthError("Ovira: this account cannot create clients (permission clients.create).")
        finally:
            await api.close()

    async def list_inbounds(self) -> list[InboundInfo]:
        api = self._api()
        try:
            rows = await api.json("GET", "/api/instances/brief")
        finally:
            await api.close()
        out = []
        for r in rows:
            if r.get("parentId"):
                continue
            node = f" @ {r['node']}" if r.get("node") else ""
            out.append(InboundInfo(id=str(r["id"]), remark=f"{r.get('name', '')}{node}",
                                   protocol=r.get("kind", "openvpn"), port=r.get("port")))
        return out

    async def username_exists(self, username: str) -> bool:
        api = self._api()
        try:
            return await self._find_client(api, username) is not None
        finally:
            await api.close()

    async def create_user(self, req: CreateUserRequest) -> RemoteService:
        body = {
            "name": req.username,
            "enabled": True,                      # the panel creates DISABLED clients unless told otherwise
            "trafficLimit": int(req.total_bytes),
            "expireAt": _ts(req.expires_at),
            "instances": [int(i) for i in req.inbound_ids],
            "maxDevices": int(req.settings.get("max_devices", 0)),
        }
        for src, dst in (("groups", "groups"), ("reset_strategy", "resetStrategy"), ("note", "note"),
                         ("contact", "contact"), ("password", "password")):
            if req.settings.get(src) not in (None, "", []):
                body[dst] = req.settings[src]
        api = self._api()
        try:
            r = await api.request("POST", "/api/clients", json=body)
            if r.status_code == 400:
                try:
                    j = r.json()
                except Exception:
                    j = {}
                if j.get("field") == "name" and re.search(r"exist|taken|used|duplicate", str(j.get("error", "")), re.I):
                    raise UsernameTaken(f"Ovira: user name '{req.username}' already exists.")
            api._check(r)
            client = r.json()
            files = await self._config_files(api, client)
            return self._to_service(client, files)
        finally:
            await api.close()

    async def get_user(self, username: str) -> RemoteService:
        api = self._api()
        try:
            c = await self._need_client(api, username)
            files = await self._config_files(api, c)
            return self._to_service(c, files)
        finally:
            await api.close()

    async def set_enabled(self, username: str, enabled: bool) -> None:
        api = self._api()
        try:
            c = await self._need_client(api, username)
            await api.json("POST", f"/api/clients/{c['id']}/{'enable' if enabled else 'disable'}")
        finally:
            await api.close()

    async def renew(self, username: str, add_bytes: int, new_expires_at: datetime) -> None:
        """Uses the panel's own 'extend' action (adds days and bytes), then verifies the new end date."""
        api = self._api()
        try:
            c = await self._need_client(api, username)
            target = _ts(new_expires_at)
            now = int(time.time())
            current = int(c.get("expireAt") or 0)
            base = max(now, current)
            days = max(0, math.ceil((target - base) / 86400))
            await api.json("POST", f"/api/clients/{c['id']}/extend", json={"days": days, "bytes": int(add_bytes)})
            after = await api.json("GET", f"/api/clients/{c['id']}")
            got = int((after.get("client") or {}).get("expireAt") or 0)
            if days and abs(got - target) > 2 * 86400:
                raise PanelError(
                    f"Ovira: extension did not land on the expected date (wanted {target}, panel has {got}). "
                    "Check the client on the panel before charging the customer.")
        finally:
            await api.close()

    async def delete_user(self, username: str) -> None:
        api = self._api()
        try:
            c = await self._find_client(api, username)
            if c is None:
                return           # already gone
            await api.json("DELETE", f"/api/clients/{c['id']}")
        finally:
            await api.close()

    async def set_traffic(self, username: str, total_bytes: int) -> None:
        raise UnsupportedOperation("Ovira: setting an absolute traffic limit is not wired up; use renew (adds bytes).")
