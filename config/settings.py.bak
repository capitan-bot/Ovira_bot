from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str = ""
    admin_ids_raw: str = Field("", validation_alias="ADMIN_TELEGRAM_IDS")
    database_url: str
    encryption_key: str
    jwt_secret: str = ""
    storage_dir: str = "storage"
    log_group_id: int = 0

    seed_shop_name: str = "CAPITAN VPN"
    seed_card_number: str = ""
    seed_card_holder: str = ""
    seed_support_id: str = ""

    @property
    def admin_telegram_ids(self) -> list[int]:
        return [int(x) for x in self.admin_ids_raw.replace(" ", "").split(",") if x]


@lru_cache
def get_settings() -> Settings:
    return Settings()
