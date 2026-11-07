"""
Panel adapter contract. One adapter per panel type, registered in ADAPTERS.
Bot/backend code only talks to this interface, so adding a 3rd/4th panel or a new
protocol means adding one file, not touching the rest of the project.

Rule: adapters return exactly what the panel returns (links, files, bytes). Never fabricate
or rewrite subscription links / config files.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


class PanelError(Exception):
    """Any failure talking to a panel. Message must be human-readable for the admin."""


class PanelAuthError(PanelError):
    pass


class UsernameTaken(PanelError):
    pass


class UnsupportedOperation(PanelError):
    """The panel's API does not support this feature. Callers must surface this honestly."""


@dataclass
class PanelCredentials:
    api_url: str
    username: str | None = None
    password: str | None = None
    token: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class InboundInfo:
    id: str
    remark: str
    protocol: str
    port: int | None = None


@dataclass
class CreateUserRequest:
    username: str
    total_bytes: int
    expires_at: datetime
    inbound_ids: list[str]
    settings: dict = field(default_factory=dict)


@dataclass
class ConfigFile:
    filename: str      # exactly as received from the panel
    content: bytes     # exactly as received from the panel


@dataclass
class RemoteService:
    remote_id: str
    username: str
    protocol: str
    total_bytes: int
    used_bytes: int
    expires_at: datetime | None
    enabled: bool
    subscription_link: str | None = None
    config_files: list[ConfigFile] = field(default_factory=list)


class PanelAdapter(ABC):
    def __init__(self, creds: PanelCredentials):
        self.creds = creds

    @abstractmethod
    async def test_connection(self) -> None:
        """Raise PanelError / PanelAuthError on failure."""

    @abstractmethod
    async def list_inbounds(self) -> list[InboundInfo]:
        """Real inbounds from the panel, so the admin picks from a list instead of guessing ids."""

    @abstractmethod
    async def username_exists(self, username: str) -> bool: ...

    @abstractmethod
    async def create_user(self, req: CreateUserRequest) -> RemoteService: ...

    @abstractmethod
    async def get_user(self, username: str) -> RemoteService: ...

    @abstractmethod
    async def set_enabled(self, username: str, enabled: bool) -> None: ...

    @abstractmethod
    async def renew(self, username: str, add_bytes: int, new_expires_at: datetime) -> None: ...

    @abstractmethod
    async def delete_user(self, username: str) -> None: ...

    async def set_traffic(self, username: str, total_bytes: int) -> None:
        raise UnsupportedOperation("این پنل تغییر حجم را پشتیبانی نمی‌کند.")


ADAPTERS: dict[str, type[PanelAdapter]] = {}


def register(panel_type: str):
    def deco(cls: type[PanelAdapter]):
        ADAPTERS[panel_type] = cls
        return cls
    return deco


def build_adapter(panel_type: str, creds: PanelCredentials) -> PanelAdapter:
    try:
        return ADAPTERS[panel_type](creds)
    except KeyError:
        raise PanelError(f"آداپتور پنل «{panel_type}» هنوز پیاده‌سازی نشده است.")
