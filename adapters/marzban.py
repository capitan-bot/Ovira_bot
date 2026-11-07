"""Marzban-compatible panels: Marzban and Rebecca (a Marzban fork).

Auth: admin username + password -> POST /api/admin/token (OAuth2 form) -> Bearer access token.
"Inbounds" are the panel's inbound TAGS (GET /api/inbounds); a user gets proxies + inbounds per protocol.
Endpoints: POST /api/admin/token, GET /api/inbounds, POST /api/user, GET|PUT|DELETE /api/user/{username}.

Optional panel settings (PanelCredentials.extra): verify_ssl (default True), sub_base (public sub URL prefix).
Rebecca is expected to keep this API but could not be tested against a live panel (experimental).
"""
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from adapters.base import (
    ConfigFile, CreateUserRequest, InboundInfo, PanelAdapter, PanelAuthError, PanelError,
    RemoteService, UsernameTaken, register,
)

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def norm_base(url: str) -> str:
    """Accepts the dashboard address too (https://host:8000/dashboard/) and returns the bare panel address."""
    u = (url or "").strip().split("#")[0].split("?")[0].rstrip("/")
    for tail in ("/dashboard", "/api"):
        if u.lower().endswith(tail):
            u = u[: -len(tail)].rstrip("/")
    return u


def to_ts(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def parse_expire(value) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _detail(r: httpx.Response) -> str:
    try:
        j = r.json()
        d = j.get("detail", j) if isinstance(j, dict) else j
        return (d if isinstance(d, str) else str(d))[:300]
    except Exception:
        return (r.text or f"HTTP {r.status_code}")[:200]


def _raise_for(label: str, r: httpx.Response) -> None:
    if 300 <= r.status_code < 400:
        raise PanelError(f"{label}: پنل ریدایرکت کرد. آدرس را با http/https و پورت درست وارد کنید.")
    if r.status_code in (401, 403):
        raise PanelAuthError(f"{label}: دسترسی رد شد ({_detail(r)}). ادمین باید نقش sudo یا full_access داشته باشد.")
    if r.status_code >= 400:
        raise PanelError(f"{label}: HTTP {r.status_code}: {_detail(r)}")


def _json(label: str, r: httpx.Response):
    if not r.content:
        return {}
    try:
        return r.json()
    except Exception:
        raise PanelError(f"{label}: پاسخ پنل JSON نیست. آدرس پنل (پورت و مسیر) را بررسی کنید.")


def _flatten_inbounds(j) -> list[dict]:
    """Marzban answers {protocol: [{tag, protocol, network, tls, port}, ...]}; tolerate a plain list too."""
    out: list[dict] = []
    if isinstance(j, dict):
        if isinstance(j.get("inbounds"), list):
            return _flatten_inbounds(j["inbounds"])
        for proto, items in j.items():
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and it.get("tag"):
                        d = dict(it)
                        d.setdefault("protocol", proto)
                        out.append(d)
    elif isinstance(j, list):
        out = [dict(it) for it in j if isinstance(it, dict) and it.get("tag")]
    return out


class _Api:
    def __init__(self, creds, label, transport=None):
        self.label = label
        self.base = norm_base(creds.api_url)
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
            raise PanelError(f"{self.label}: پنل در زمان مناسب جواب نداد.")
        except httpx.HTTPError as e:
            hint = " (گواهی SSL معتبر نیست؛ extra.verify_ssl=false)" if "CERTIFICATE" in str(e).upper() else ""
            raise PanelError(f"{self.label}: اتصال به پنل ممکن نیست ({type(e).__name__}){hint}.")

    async def _login(self):
        if not (self.username and self.password):
            raise PanelAuthError(f"{self.label}: نام کاربری و رمز پنل ذخیره نشده است.")
        r = await self._raw("POST", "/api/admin/token", auth=False,
                            data={"username": self.username, "password": self.password, "grant_type": "password"})
        if 300 <= r.status_code < 400:
            raise PanelError(f"{self.label}: پنل ریدایرکت کرد. آدرس را با http/https و پورت درست وارد کنید.")
        if r.status_code == 404:
            raise PanelError(f"{self.label}: مسیر لاگین پیدا نشد. آدرس پنل اشتباه است یا API این پنل با مرزبان سازگار نیست.")
        if r.status_code in (401, 403, 422):
            raise PanelAuthError(f"{self.label}: ورود ناموفق بود ({_detail(r)}).")
        if r.status_code >= 400:
            raise PanelError(f"{self.label}: لاگین HTTP {r.status_code}: {_detail(r)}")
        try:
            j = r.json()
            self.token = j.get("access_token") or j["token"]
        except Exception:
            raise PanelAuthError(f"{self.label}: توکن برنگشت. آدرس پنل را بررسی کنید.")

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
        _raise_for(self.label, r)
        return _json(self.label, r)


@register("marzban")
class MarzbanAdapter(PanelAdapter):
    LABEL = "Marzban"
    _transport = None   # tests inject a transport here

    def _api(self) -> _Api:
        return _Api(self.creds, self.LABEL, self._transport)

    @staticmethod
    def _path(username: str) -> str:
        return f"/api/user/{quote(username, safe='')}"

    def _sub(self, url: str | None) -> str | None:
        if not url:
            return None
        if url.startswith("/"):
            base = (self.creds.extra or {}).get("sub_base")
            if base:
                return base.rstrip("/") + url
            p = urlparse(norm_base(self.creds.api_url))
            return f"{p.scheme}://{p.netloc}{url}"
        return url

    def _to_service(self, u: dict) -> RemoteService:
        links = [str(x) for x in (u.get("links") or []) if x]
        files = [ConfigFile(filename="links.txt", content="\n".join(links).encode())] if links else []
        protos = "/".join(sorted((u.get("proxies") or {}).keys())) or self.LABEL.lower()
        return RemoteService(
            remote_id=str(u["username"]), username=u["username"], protocol=protos,
            total_bytes=int(u.get("data_limit") or 0), used_bytes=int(u.get("used_traffic") or 0),
            expires_at=parse_expire(u.get("expire")), enabled=u.get("status") != "disabled",
            subscription_link=self._sub(u.get("subscription_url")), config_files=files)

    async def _fetch(self, api: _Api, username: str) -> dict | None:
        r = await api.request("GET", self._path(username))
        if r.status_code == 404:
            return None
        _raise_for(self.LABEL, r)
        return _json(self.LABEL, r)

    async def _need(self, api: _Api, username: str) -> dict:
        u = await self._fetch(api, username)
        if u is None:
            raise PanelError(f"{self.LABEL}: کاربر «{username}» روی پنل پیدا نشد.")
        return u

    # ---------- contract ----------
    async def test_connection(self) -> None:
        api = self._api()
        try:
            await api.json("GET", "/api/inbounds")      # logs in AND proves the account may read inbounds
        finally:
            await api.close()

    async def list_inbounds(self) -> list[InboundInfo]:
        api = self._api()
        try:
            items = _flatten_inbounds(await api.json("GET", "/api/inbounds"))
        finally:
            await api.close()
        out = []
        for d in items:
            try:
                port = int(d.get("port")) if d.get("port") is not None else None
            except (TypeError, ValueError):
                port = None
            out.append(InboundInfo(id=str(d["tag"]), remark=str(d["tag"]),
                                   protocol=str(d.get("protocol") or ""), port=port))
        return out

    async def username_exists(self, username: str) -> bool:
        api = self._api()
        try:
            return await self._fetch(api, username) is not None
        finally:
            await api.close()

    async def create_user(self, req: CreateUserRequest) -> RemoteService:
        api = self._api()
        try:
            known = {d["tag"]: d for d in _flatten_inbounds(await api.json("GET", "/api/inbounds"))}
            by_proto: dict[str, list[str]] = {}
            for tag in (str(i) for i in req.inbound_ids):
                d = known.get(tag)
                if d is None:
                    raise PanelError(f"{self.LABEL}: اینباند «{tag}» روی پنل پیدا نشد. پروفایل را دوباره بسازید.")
                by_proto.setdefault(str(d.get("protocol") or "").lower(), []).append(tag)
            if not by_proto:
                raise PanelError(f"{self.LABEL}: هیچ اینباندی برای این پروفایل انتخاب نشده است.")
            proxies: dict[str, dict] = {p: {} for p in by_proto}
            if "vless" in by_proto:
                flow = req.settings.get("flow")
                if flow is None:        # auto: vision flow only when every vless inbound is Reality over TCP
                    reality_tcp = all(
                        str(known[t].get("tls")).lower() == "reality"
                        and str(known[t].get("network")).lower() in ("tcp", "raw")
                        for t in by_proto["vless"])
                    flow = "xtls-rprx-vision" if reality_tcp else ""
                if flow:
                    proxies["vless"] = {"flow": str(flow)}
            body = {
                "username": req.username, "status": "active", "proxies": proxies, "inbounds": by_proto,
                "expire": to_ts(req.expires_at), "data_limit": int(req.total_bytes),
                "data_limit_reset_strategy": "no_reset",
            }
            if req.settings.get("note"):
                body["note"] = str(req.settings["note"])[:500]
            r = await api.request("POST", "/api/user", json=body)
            if r.status_code == 409 or (r.status_code in (400, 422) and re.search(
                    r"already|exist|taken|duplicate", _detail(r), re.I)):
                raise UsernameTaken(f"{self.LABEL}: user name '{req.username}' already exists.")
            _raise_for(self.LABEL, r)
            return self._to_service(_json(self.LABEL, r))
        finally:
            await api.close()

    async def get_user(self, username: str) -> RemoteService:
        api = self._api()
        try:
            return self._to_service(await self._need(api, username))
        finally:
            await api.close()

    async def _put(self, api: _Api, username: str, body: dict) -> dict:
        r = await api.request("PUT", self._path(username), json=body)
        _raise_for(self.LABEL, r)
        return _json(self.LABEL, r)

    async def set_enabled(self, username: str, enabled: bool) -> None:
        api = self._api()
        try:
            await self._need(api, username)
            await self._put(api, username, {"status": "active" if enabled else "disabled"})
        finally:
            await api.close()

    async def renew(self, username: str, add_bytes: int, new_expires_at: datetime) -> None:
        """Adds bytes to the current limit, sets the new end date and re-activates a limited/expired user."""
        api = self._api()
        try:
            u = await self._need(api, username)
            cur = int(u.get("data_limit") or 0)
            body = {"data_limit": cur + int(add_bytes) if cur > 0 else cur,
                    "expire": to_ts(new_expires_at), "status": "active"}
            after = parse_expire((await self._put(api, username, body)).get("expire"))
            if after and abs((after - new_expires_at.astimezone(timezone.utc)).total_seconds()) > 2 * 86400:
                raise PanelError(f"{self.LABEL}: تاریخ انقضای جدید درست ثبت نشد. قبل از تأیید، کاربر را روی پنل چک کنید.")
        finally:
            await api.close()

    async def delete_user(self, username: str) -> None:
        api = self._api()
        try:
            r = await api.request("DELETE", self._path(username))
            if r.status_code == 404:
                return                  # already gone
            _raise_for(self.LABEL, r)
        finally:
            await api.close()

    async def set_traffic(self, username: str, total_bytes: int) -> None:
        api = self._api()
        try:
            await self._need(api, username)
            await self._put(api, username, {"data_limit": int(total_bytes)})
        finally:
            await api.close()


@register("rebecca")
class RebeccaAdapter(MarzbanAdapter):
    """Rebecca is a Marzban fork and is expected to keep the same REST API (experimental, not tested live)."""
    LABEL = "Rebecca"
