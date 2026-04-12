# -*- coding: utf-8 -*-

import os
import logging
from pathlib import Path
from typing import Any, Optional, TypedDict

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(_env_path)
    DOTENV_LOADED = True
except ImportError:
    DOTENV_LOADED = False

logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "F9D7AAC679CB3E599AF0B75237AD19B58C4E84A7F7FFDC5EEA0BE221356E60E7")

# Настройки базы данных
DATABASE_NAME = os.getenv("DATABASE_NAME", "vpn_bot.db")

# ID администраторов
try:
    admin_ids_str = os.getenv("ADMIN_IDS", "280478260")
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip()]
except:
    ADMIN_IDS = []

# ========== НАСТРОЙКИ ЮМАНИ ==========
YOOMONEY_TOKEN = os.getenv("YOOMONEY_TOKEN", "F9D7AAC679CB3E599AF0B75237AD19B58C4E84A7F7FFDC5EEA0BE221356E60E7")  # OAuth токен
YOOMONEY_WALLET = os.getenv("YOOMONEY_WALLET", "4100119498485026")  # Номер кошелька
YOOMONEY_REDIRECT_URL = os.getenv("YOOMONEY_REDIRECT_URL", "https://t.me/MaxkVPN_bot")  # URL для возврата
# ====================================

# --- Этап 0 (тест): одна локация = один сервер = одна панель 3x-ui ---
# Публичный хост VLESS (домен в инбаунде / сертификате) — подставьте свой.
_EE_VPN_HOST = os.getenv("EE_VPN_ENDPOINT_HOST", "replace-with-your-vless-host.example.com")
_XUI_EE_INBOUND_RAW = os.getenv("XUI_EE_INBOUND_ID", "").strip()
_XUI_EE_INBOUND_ID = int(_XUI_EE_INBOUND_RAW) if _XUI_EE_INBOUND_RAW.isdigit() else None

# Период проверки истёкших подписок в БД (секунды), фоновая задача бота
SUBSCRIPTION_EXPIRE_CHECK_SECONDS = int(os.getenv("SUBSCRIPTION_EXPIRE_CHECK_SECONDS", "3600"))

# HTTP к панели (этап 1 / дальше — API-клиент)
XUI_REQUEST_TIMEOUT = int(os.getenv("XUI_REQUEST_TIMEOUT", "30"))
# Для панели по IP с самоподписанным сертификатом: XUI_EE_VERIFY_SSL=false
_XUI_EE_VERIFY_RAW = os.getenv("XUI_EE_VERIFY_SSL", "true").strip().lower()
XUI_EE_VERIFY_SSL = _XUI_EE_VERIFY_RAW not in ("0", "false", "no", "off")
# Flow для клиента VLESS (например xtls-rprx-vision для Reality+XTLS). Пусто — по умолчанию Xray.
XUI_EE_VLESS_FLOW = os.getenv("XUI_EE_VLESS_FLOW", "").strip()
# Шаблон ссылки подписки для клиента; подставьте {sub_id} (как в URI subscription в 3x-ui).
XUI_EE_SUBSCRIPTION_URL_TEMPLATE = os.getenv("XUI_EE_SUBSCRIPTION_URL_TEMPLATE", "").strip()


class XuiPanelConfig(TypedDict):
    """Параметры для входа в API 3x-ui (не логировать password целиком)."""

    server_id: str
    panel_base_url: str
    inbound_id: int
    username: str
    password: str
    verify_ssl: bool
    request_timeout: int
    vpn_endpoint_host: str


VPN_SERVERS = [
    {
        "name": "🇪🇪 Эстония",
        "id": "ee",
        "ip": _EE_VPN_HOST,
        "location": "Tallinn",
        "flag": "🇪🇪",
        # Базовый URL веб-панели 3x-ui (https://host:port/path без финального /)
        "panel_base_url": os.getenv("XUI_EE_PANEL_BASE_URL", "").rstrip("/"),
        "inbound_id": _XUI_EE_INBOUND_ID,
    },
]


def get_server_by_id(server_id: str) -> Optional[dict[str, Any]]:
    sid = (server_id or "").strip().lower()
    for row in VPN_SERVERS:
        if row.get("id") == sid:
            return row
    return None


def get_xui_panel_config(server_id: str) -> Optional[XuiPanelConfig]:
    """
    Полная привязка бота к панели 3x-ui для локации.
    Возвращает None, если не хватает URL, inbound, логина или пароля.
    Учётные данные только из .env (не кладём пароль в VPN_SERVERS).
    """
    row = get_server_by_id(server_id)
    if not row:
        return None

    sid = str(row["id"])
    base = (row.get("panel_base_url") or "").strip().rstrip("/")
    inbound = row.get("inbound_id")
    if not base or not isinstance(inbound, int):
        return None

    if sid == "ee":
        username = os.getenv("XUI_EE_USERNAME", "").strip()
        password = os.getenv("XUI_EE_PASSWORD", "")
    else:
        username = ""
        password = ""

    if not username or not password:
        return None

    verify = XUI_EE_VERIFY_SSL if sid == "ee" else True

    return XuiPanelConfig(
        server_id=sid,
        panel_base_url=base,
        inbound_id=inbound,
        username=username,
        password=password,
        verify_ssl=verify,
        request_timeout=XUI_REQUEST_TIMEOUT,
        vpn_endpoint_host=str(row.get("ip") or "").strip(),
    )


def xui_config_status(server_id: str) -> dict[str, Any]:
    """Диагностика без секретов (для логов / админки)."""
    row = get_server_by_id(server_id)
    if not row:
        return {"ok": False, "reason": "unknown_server_id"}
    base = (row.get("panel_base_url") or "").strip()
    inbound = row.get("inbound_id")
    if not base:
        return {"ok": False, "reason": "panel_base_url_empty"}
    if not isinstance(inbound, int):
        return {"ok": False, "reason": "inbound_id_missing_or_invalid"}
    cfg = get_xui_panel_config(server_id)
    if not cfg:
        return {"ok": False, "reason": "credentials_missing"}
    return {
        "ok": True,
        "server_id": cfg["server_id"],
        "panel_base_url": cfg["panel_base_url"],
        "inbound_id": cfg["inbound_id"],
        "verify_ssl": cfg["verify_ssl"],
        "request_timeout": cfg["request_timeout"],
        "vpn_endpoint_host": cfg["vpn_endpoint_host"],
    }


# Тарифные планы
VPN_PLANS = [
    {
        'name': '1 месяц',
        'duration': 30,
        'price_stars': 100,
        'price_rub': 299,  # Цена в рублях для Юмани
        'price_usd': 2.99,
        'popular': False
    },
    {
        'name': '3 месяца',
        'duration': 90,
        'price_stars': 250,
        'price_rub': 699,  # Цена в рублях для Юмани
        'price_usd': 7.99,
        'popular': True,
        'discount': '20%'
    },
    {
        'name': '6 месяцев',
        'duration': 180,
        'price_stars': 450,
        'price_rub': 1199,  # Цена в рублях для Юмани
        'price_usd': 14.99,
        'popular': False,
        'discount': '25%'
    },
    {
        'name': '12 месяцев',
        'duration': 365,
        'price_stars': 800,
        'price_rub': 1999,  # Цена в рублях для Юмани
        'price_usd': 24.99,
        'popular': False,
        'discount': '30%'
    },
]

def check_config():
    """Проверка конфигурации"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
        return False
    
    logger.info(f"✅ Конфигурация проверена успешно")
    logger.info(f"🤖 Бот токен: {BOT_TOKEN[:10]}...")
    
    # Проверка Юмани
    if YOOMONEY_TOKEN:
        logger.info("✅ Юмани токен установлен")
    else:
        logger.warning("⚠️ Юмани токен не установлен - оплата через Юмани недоступна")

    for s in VPN_SERVERS:
        sid = s.get("id", "")
        st = xui_config_status(str(sid))
        if st.get("ok"):
            logger.info(
                "✅ 3x-ui (%s): панель %s, inbound=%s, SSL verify=%s",
                sid,
                st["panel_base_url"],
                st["inbound_id"],
                st["verify_ssl"],
            )
        else:
            logger.warning(
                "⚠️ 3x-ui (%s): не готово к API — %s",
                sid,
                st.get("reason", "unknown"),
            )
    
    return True