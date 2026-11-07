import base64
import json
import secrets
import string
import uuid
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from adapters.base import (
    ConfigFile, CreateUserRequest, InboundInfo, PanelAdapter, PanelAuthError, PanelError,
    RemoteService, UnsupportedOperation, register,
)

TIMEOUT = httpx.Timeout(25.0, connect=10.0)

# فقط اینباندهای مورد نظر شما: VIP🇩🇪 (2), USA🇺🇸 (6), TURKEY 🇹🇷 (10)
ALLOWED_INBOUND_IDS = {2, 6, 10}
SUFFIX_MAP = {2: "vip", 6: "usa", 10: "tr"}


def _gen_sub_id(length: int = 16) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _match_username(email: str, username: str) -> bool:
    if not email:
        return False
    if email == username:
        return True
    for sfx in SUFFIX_MAP.values():
        if email == f"{username}_{sfx}":
            return True
    return email.startswith(f"{username}_")


def _build_vmess_uri(host: str, port: int, client_id: str, remark: str, stream: dict) -> str:
    net = stream.get("network", "tcp")
    security = stream.get("security", "none")
    header_type = "none"
    path = ""
    sni = ""
    host_header = ""

    if net == "tcp":
        tcp_set = stream.get("tcpSettings") or {}
        header = tcp_set.get("header") or {}
        header_type = header.get("type", "none")
        req = header.get("request") or {}
        headers = req.get("headers") or {}
        if isinstance(headers.get("Host"), list) and headers["Host"]:
            host_header = headers["Host"][0]
        if isinstance(req.get("path"), list) and req["path"]:
            path = req["path"][0]
    elif net == "ws":
        ws_set = stream.get("wsSettings") or {}
        path = ws_set.get("path", "/")
        headers = ws_set.get("headers") or {}
        host_header = headers.get("Host", "")
    elif net == "grpc":
        grpc_set = stream.get("grpcSettings") or {}
        path = grpc_set.get("serviceName", "")

    if security == "tls":
        tls_set = stream.get("tlsSettings") or {}
        sni = tls_set.get("serverName", "")

    vmess_obj = {
        "v": "2",
        "ps": remark,
        "add": host,
        "port": str(port),
        "id": client_id,
        "aid": "0",
        "scy": "auto",
        "net": net,
        "type": header_type,
        "host": host_header,
        "path": path,
        "tls": "tls" if security == "tls" else "",
        "sni": sni,
        "alpn": "",
        "fp": "",
    }
    raw_json = json.dumps(vmess_obj, separators=(",", ":"), ensure_ascii=False)
    b64 = base64.b64encode(raw_json.encode("utf-8")).decode("utf-8")
    return f"vmess://{b64}"


def _build_vless_uri(host: str, port: int, client_id: str, remark: str, stream: dict) -> str:
    net = stream.get("network", "tcp")
    security = stream.get("security", "none")
    params = [f"type={net}", f"security={security}", "encryption=none"]

    if security == "reality":
        r_set = stream.get("realitySettings") or {}
        r_sub = r_set.get("settings") or {}
        pbk = r_sub.get("publicKey", "")
        fp = r_sub.get("fingerprint", "chrome")
        snames = r_set.get("serverNames") or []
        sni = snames[0] if snames else ""
        sids = r_set.get("shortIds") or []
        sid = sids[0] if sids else ""
        if pbk:
            params.append(f"pbk={pbk}")
        if fp:
            params.append(f"fp={fp}")
        if sni:
            params.append(f"sni={sni}")
        if sid:
            params.append(f"sid={sid}")

    query = "&".join(params)
    return f"vless://{client_id}@{host}:{port}?{query}#{remark}"


@register("sanaei")
class SanaeiAdapter(PanelAdapter):
    _transport = None

    def __init__(self, creds):
        super().__init__(creds)
        raw_url = creds.api_url.rstrip("/")
        parsed = urlparse(raw_url)
        self.host = parsed.hostname or "localhost"
        self.scheme = parsed.scheme or "https"
        self.port = parsed.port or 4000
        base_path = parsed.path.rstrip("/")
        if base_path.endswith("/panel"):
            base_path = base_path[:-6]
        self.root_url = f"{self.scheme}://{self.host}:{self.port}{base_path}/"
        self.base = urljoin(self.root_url, "panel/")

        self.username = creds.username
        self.password = creds.password
        self.token = creds.token
        self.extra = creds.extra or {}
        verify = self.extra.get("verify_ssl", False)
        self.http = httpx.AsyncClient(timeout=TIMEOUT, verify=verify, transport=self._transport, follow_redirects=True)
        self.logged_in = False

    async def close(self):
        await self.http.aclose()

    async def _login(self):
        if self.username and self.password:
            login_url = urljoin(self.root_url, "login")
            try:
                r = await self.http.post(
                    login_url,
                    data={"username": self.username, "password": self.password},
                )
                if r.status_code == 200:
                    j = r.json()
                    if j.get("success"):
                        self.logged_in = True
                        return
            except Exception:
                pass

        if self.token:
            self.http.headers["Authorization"] = f"Bearer {self.token}"
            self.logged_in = True
            return

        raise PanelAuthError("Sanaei: login failed. Check username/password or token.")

    async def _request(self, method: str, path: str, **kw):
        if not self.logged_in:
            await self._login()

        api_path = f"api/{path.lstrip('/')}"
        url = urljoin(self.base, api_path)

        r = await self.http.request(method, url, **kw)
        if r.status_code in (401, 403):
            self.logged_in = False
            await self._login()
            r = await self.http.request(method, url, **kw)

        if r.status_code >= 400:
            raise PanelError(f"Sanaei API error HTTP {r.status_code} for {path}")
        return r

    async def _resolve_sub_base(self) -> str:
        # استفاده از ساختار صحیح ساب‌پورت پنل شما (همراه با توکن امنیتی اختصاصی)
        return "https://capi.aligater.ir:2096/xmh2jsitxe6h8o7u/"
    async def test_connection(self) -> None:
        await self._login()
        r = await self._request("GET", "inbounds/list")
        j = r.json()
        if not j.get("success", True):
            raise PanelError(f"Sanaei: failed to fetch inbounds: {j.get('msg')}")

    async def get_system_status(self) -> dict:
        try:
            r = await self._request("GET", "server/status")
            j = r.json()
            if j.get("success"):
                return j.get("obj", {})
        except Exception:
            pass
        return {}

    async def list_inbounds(self) -> list[InboundInfo]:
        r = await self._request("GET", "inbounds/list")
        items = r.json().get("obj", [])
        out = []
        for item in items:
            ib_id = int(item.get("id", 0))
            if ib_id not in ALLOWED_INBOUND_IDS:
                continue
            remark = item.get("remark", f"Inbound {ib_id}")
            protocol = item.get("protocol", "vmess")
            port = item.get("port")
            out.append(InboundInfo(id=str(ib_id), remark=remark, protocol=protocol, port=port))
        return out

    async def username_exists(self, username: str) -> bool:
        try:
            r = await self._request("GET", "inbounds/list")
            items = r.json().get("obj", [])
            for item in items:
                if int(item.get("id", 0)) not in ALLOWED_INBOUND_IDS:
                    continue
                settings_raw = item.get("settings", "{}")
                settings = json.loads(settings_raw) if isinstance(settings_raw, str) else (settings_raw or {})
                for c in settings.get("clients") or []:
                    if _match_username(c.get("email", ""), username):
                        return True
        except Exception:
            pass
        return False

    async def _save_client_on_inbound(self, obj: dict, client_dict: dict) -> None:
        inbound_id = int(obj["id"])
        single_settings_str = json.dumps({"clients": [client_dict]}, ensure_ascii=False)

        # ۱. تلاش با تمام مسیرهای استاندارد addClient در 3x-ui
        for candidate in [
            urljoin(self.base, "api/inbounds/addClient"),
            urljoin(self.base, "inbounds/addClient"),
            urljoin(self.base, "inbound/addClient"),
            urljoin(self.root_url, "panel/api/inbounds/addClient"),
            urljoin(self.root_url, "panel/inbounds/addClient"),
            urljoin(self.root_url, "panel/inbound/addClient"),
        ]:
            for send_as_json in (True, False):
                try:
                    if send_as_json:
                        r = await self.http.post(candidate, json={"id": inbound_id, "settings": single_settings_str})
                    else:
                        r = await self.http.post(candidate, data={"id": inbound_id, "settings": single_settings_str})
                    if r.status_code == 200 and r.text.strip().startswith("{"):
                        j = r.json()
                        if j.get("success"):
                            return
                except Exception:
                    pass

        # ۲. پشتیبان قطعی: آپدیت کامل اینباند
        settings_raw = obj.get("settings", "{}")
        settings = json.loads(settings_raw) if isinstance(settings_raw, str) else (settings_raw or {})
        if "clients" not in settings or not isinstance(settings["clients"], list):
            settings["clients"] = []

        settings["clients"] = [c for c in settings["clients"] if c.get("email") != client_dict["email"]]
        settings["clients"].append(client_dict)

        stream_raw = obj.get("streamSettings", "{}")
        sniff_raw = obj.get("sniffing", "{}")

        payload = {
            "up": obj.get("up", 0),
            "down": obj.get("down", 0),
            "total": obj.get("total", 0),
            "remark": obj.get("remark", ""),
            "enable": obj.get("enable", True),
            "expiryTime": obj.get("expiryTime", 0),
            "listen": obj.get("listen", ""),
            "port": obj.get("port", 0),
            "protocol": obj.get("protocol", "vmess"),
            "settings": json.dumps(settings, ensure_ascii=False),
            "streamSettings": stream_raw if isinstance(stream_raw, str) else json.dumps(stream_raw, ensure_ascii=False),
            "sniffing": sniff_raw if isinstance(sniff_raw, str) else json.dumps(sniff_raw, ensure_ascii=False),
        }
        r_up = await self._request("POST", f"inbounds/update/{inbound_id}", json=payload)
        j_up = r_up.json()
        if not j_up.get("success", True):
            raise PanelError(f"Sanaei update inbound {inbound_id} failed: {j_up.get('msg')}")

    async def create_user(self, req: CreateUserRequest) -> RemoteService:
        await self._login()

        r_list = await self._request("GET", "inbounds/list")
        all_inbounds = r_list.json().get("obj", [])

        target_inbounds = [ib for ib in all_inbounds if int(ib.get("id", 0)) in ALLOWED_INBOUND_IDS]
        if not target_inbounds:
            target_inbounds = all_inbounds[:1]
        if not target_inbounds:
            raise PanelError("Sanaei: هیچ اینباندی در پنل یافت نشد.")

        client_id = str(uuid.uuid4())
        sub_id = _gen_sub_id(16)
        expiry_ms = int(req.expires_at.timestamp() * 1000) if getattr(req, "expires_at", None) else 0
        total_bytes = int(getattr(req, "total_bytes", 0) or 0)

        config_lines = []

        for idx, ib in enumerate(target_inbounds):
            ib_id = int(ib["id"])
            remark = ib.get("remark", f"Server{ib_id}").strip()
            protocol = ib.get("protocol", "vmess").lower()
            port = int(ib.get("port", 443))

            r_get = await self._request("GET", f"inbounds/get/{ib_id}")
            obj = r_get.json().get("obj") or ib

            email = req.username if idx == 0 else f"{req.username}_{SUFFIX_MAP.get(ib_id, ib_id)}"

            new_client = {
                "id": client_id,
                "alterId": 0,
                "email": email,
                "limitIp": 0,
                "totalGB": total_bytes,
                "expiryTime": expiry_ms,
                "enable": True,
                "tgId": "",
                "subId": sub_id,
                "reset": 0,
            }
            if protocol == "vless":
                new_client["flow"] = ""

            await self._save_client_on_inbound(obj, new_client)

            stream_raw = obj.get("streamSettings", "{}")
            stream = json.loads(stream_raw) if isinstance(stream_raw, str) else (stream_raw or {})
            node_label = f"{remark} | {req.username}"

            if protocol == "vmess":
                uri = _build_vmess_uri(self.host, port, client_id, node_label, stream)
            else:
                uri = _build_vless_uri(self.host, port, client_id, node_label, stream)

            config_lines.append(uri)

        sub_base = await self._resolve_sub_base()
        sub_url = f"{sub_base}{sub_id}"

        joined_configs = "\n".join(config_lines)
        return RemoteService(
            remote_id=client_id,
            username=req.username,
            protocol="vmess",
            total_bytes=total_bytes,
            used_bytes=0,
            expires_at=getattr(req, "expires_at", None),
            enabled=True,
            config_files=[ConfigFile(filename=f"{req.username}.txt", content=joined_configs.encode("utf-8"))],
            subscription_link=sub_url,
        )

    async def get_user(self, username: str) -> RemoteService:
        """پشتیبانی کامل از دکمه دریافت کانفیگ و مشاهده وضعیت سرویس در منوی سرویس‌های من"""
        await self._login()
        r_list = await self._request("GET", "inbounds/list")
        all_inbounds = r_list.json().get("obj", [])
        target_inbounds = [ib for ib in all_inbounds if int(ib.get("id", 0)) in ALLOWED_INBOUND_IDS]
        if not target_inbounds:
            target_inbounds = all_inbounds

        config_lines = []
        client_id = None
        sub_id = None
        total_bytes = 0
        used_bytes = 0
        expiry_ms = 0
        enabled = True

        for ib in target_inbounds:
            ib_id = int(ib["id"])
            remark = ib.get("remark", f"Server{ib_id}").strip()
            protocol = ib.get("protocol", "vmess").lower()
            port = int(ib.get("port", 443))

            settings_raw = ib.get("settings", "{}")
            settings = json.loads(settings_raw) if isinstance(settings_raw, str) else (settings_raw or {})
            clients = settings.get("clients") or []

            matched_client = None
            for c in clients:
                if _match_username(c.get("email", ""), username):
                    matched_client = c
                    break

            if not matched_client:
                continue

            cid = matched_client.get("id") or str(uuid.uuid4())
            if not client_id:
                client_id = cid
            if not sub_id and matched_client.get("subId"):
                sub_id = matched_client.get("subId")

            total_bytes = max(total_bytes, int(matched_client.get("totalGB") or 0))
            expiry_ms = max(expiry_ms, int(matched_client.get("expiryTime") or 0))
            enabled = bool(matched_client.get("enable", True))

            for st in ib.get("clientStats") or []:
                if _match_username(st.get("email", ""), username):
                    used_bytes += int(st.get("up") or 0) + int(st.get("down") or 0)

            stream_raw = ib.get("streamSettings", "{}")
            stream = json.loads(stream_raw) if isinstance(stream_raw, str) else (stream_raw or {})
            node_label = f"{remark} | {username}"

            if protocol == "vmess":
                uri = _build_vmess_uri(self.host, port, cid, node_label, stream)
            else:
                uri = _build_vless_uri(self.host, port, cid, node_label, stream)
            config_lines.append(uri)

        if not config_lines:
            raise PanelError(f"کاربر {username} در پنل سنایی یافت نشد.")

        sub_base = await self._resolve_sub_base()
        sub_url = f"{sub_base}{sub_id}" if sub_id else None
        expires_at = datetime.fromtimestamp(expiry_ms / 1000.0, tz=timezone.utc) if expiry_ms > 0 else None

        joined_configs = "\n".join(config_lines)
        return RemoteService(
            remote_id=client_id or username,
            username=username,
            protocol="vmess",
            total_bytes=total_bytes,
            used_bytes=used_bytes,
            expires_at=expires_at,
            enabled=enabled,
            config_files=[ConfigFile(filename=f"{username}.txt", content=joined_configs.encode("utf-8"))],
            subscription_link=sub_url,
        )

    async def set_enabled(self, username: str, enabled: bool) -> None:
        await self._login()
        r_list = await self._request("GET", "inbounds/list")
        for ib in r_list.json().get("obj", []):
            ib_id = int(ib.get("id", 0))
            if ib_id not in ALLOWED_INBOUND_IDS:
                continue
            r_get = await self._request("GET", f"inbounds/get/{ib_id}")
            obj = r_get.json().get("obj") or ib
            settings = json.loads(obj.get("settings", "{}")) if isinstance(obj.get("settings"), str) else (obj.get("settings") or {})
            changed = False
            for c in settings.get("clients") or []:
                if _match_username(c.get("email", ""), username):
                    c["enable"] = enabled
                    changed = True
            if changed:
                payload = {
                    "up": obj.get("up", 0), "down": obj.get("down", 0), "total": obj.get("total", 0),
                    "remark": obj.get("remark", ""), "enable": obj.get("enable", True),
                    "expiryTime": obj.get("expiryTime", 0), "listen": obj.get("listen", ""),
                    "port": obj.get("port", 0), "protocol": obj.get("protocol", "vmess"),
                    "settings": json.dumps(settings, ensure_ascii=False),
                    "streamSettings": obj.get("streamSettings", "{}"),
                    "sniffing": obj.get("sniffing", "{}"),
                }
                await self._request("POST", f"inbounds/update/{ib_id}", json=payload)

    async def renew(self, username: str, add_bytes: int, new_expires_at: datetime) -> None:
        await self._login()
        expiry_ms = int(new_expires_at.timestamp() * 1000) if new_expires_at else 0
        r_list = await self._request("GET", "inbounds/list")
        for ib in r_list.json().get("obj", []):
            ib_id = int(ib.get("id", 0))
            if ib_id not in ALLOWED_INBOUND_IDS:
                continue
            r_get = await self._request("GET", f"inbounds/get/{ib_id}")
            obj = r_get.json().get("obj") or ib
            settings = json.loads(obj.get("settings", "{}")) if isinstance(obj.get("settings"), str) else (obj.get("settings") or {})
            changed = False
            for c in settings.get("clients") or []:
                if _match_username(c.get("email", ""), username):
                    c["totalGB"] = int(c.get("totalGB") or 0) + int(add_bytes or 0)
                    if expiry_ms:
                        c["expiryTime"] = expiry_ms
                    c["enable"] = True
                    changed = True
            if changed:
                payload = {
                    "up": obj.get("up", 0), "down": obj.get("down", 0), "total": obj.get("total", 0),
                    "remark": obj.get("remark", ""), "enable": obj.get("enable", True),
                    "expiryTime": obj.get("expiryTime", 0), "listen": obj.get("listen", ""),
                    "port": obj.get("port", 0), "protocol": obj.get("protocol", "vmess"),
                    "settings": json.dumps(settings, ensure_ascii=False),
                    "streamSettings": obj.get("streamSettings", "{}"),
                    "sniffing": obj.get("sniffing", "{}"),
                }
                await self._request("POST", f"inbounds/update/{ib_id}", json=payload)

    async def delete_user(self, username: str) -> None:
        await self._login()
        r_list = await self._request("GET", "inbounds/list")
        for ib in r_list.json().get("obj", []):
            ib_id = int(ib.get("id", 0))
            if ib_id not in ALLOWED_INBOUND_IDS:
                continue
            r_get = await self._request("GET", f"inbounds/get/{ib_id}")
            obj = r_get.json().get("obj") or ib
            settings = json.loads(obj.get("settings", "{}")) if isinstance(obj.get("settings"), str) else (obj.get("settings") or {})
            before = len(settings.get("clients") or [])
            settings["clients"] = [c for c in (settings.get("clients") or []) if not _match_username(c.get("email", ""), username)]
            if len(settings["clients"]) != before:
                payload = {
                    "up": obj.get("up", 0), "down": obj.get("down", 0), "total": obj.get("total", 0),
                    "remark": obj.get("remark", ""), "enable": obj.get("enable", True),
                    "expiryTime": obj.get("expiryTime", 0), "listen": obj.get("listen", ""),
                    "port": obj.get("port", 0), "protocol": obj.get("protocol", "vmess"),
                    "settings": json.dumps(settings, ensure_ascii=False),
                    "streamSettings": obj.get("streamSettings", "{}"),
                    "sniffing": obj.get("sniffing", "{}"),
                }
                await self._request("POST", f"inbounds/update/{ib_id}", json=payload)

    async def set_traffic(self, username: str, total_bytes: int) -> None:
        await self._login()
        r_list = await self._request("GET", "inbounds/list")
        for ib in r_list.json().get("obj", []):
            ib_id = int(ib.get("id", 0))
            if ib_id not in ALLOWED_INBOUND_IDS:
                continue
            r_get = await self._request("GET", f"inbounds/get/{ib_id}")
            obj = r_get.json().get("obj") or ib
            settings = json.loads(obj.get("settings", "{}")) if isinstance(obj.get("settings"), str) else (obj.get("settings") or {})
            changed = False
            for c in settings.get("clients") or []:
                if _match_username(c.get("email", ""), username):
                    c["totalGB"] = int(total_bytes)
                    changed = True
            if changed:
                payload = {
                    "up": obj.get("up", 0), "down": obj.get("down", 0), "total": obj.get("total", 0),
                    "remark": obj.get("remark", ""), "enable": obj.get("enable", True),
                    "expiryTime": obj.get("expiryTime", 0), "listen": obj.get("listen", ""),
                    "port": obj.get("port", 0), "protocol": obj.get("protocol", "vmess"),
                    "settings": json.dumps(settings, ensure_ascii=False),
                    "streamSettings": obj.get("streamSettings", "{}"),
                    "sniffing": obj.get("sniffing", "{}"),
                }
                await self._request("POST", f"inbounds/update/{ib_id}", json=payload)


# 3x-ui v3 modern API (clients/add, clients/links)
from adapters.sanaei_v3 import install as _install_v3  # noqa: E402
_install_v3(SanaeiAdapter, ALLOWED_INBOUND_IDS)
