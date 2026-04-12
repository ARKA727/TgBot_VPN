# -*- coding: utf-8 -*-
"""
Клиент HTTP API панели 3x-ui (MHSanaei/3x-ui): логин по cookie-сессии и addClient.

В панели должно быть:
  - VLESS inbound с id, совпадающим с XUI_*_INBOUND_ID;
  - логин/пароль без опечаток; если включена 2FA — в .env нужен код невозможен,
    отключите 2FA для сервисной учётки или добавьте поддержку twoFactorCode позже;
  - уведомления о входе в Telegram с панели могут срабатывать при каждом логине бота.

URL: panel_base_url без завершающего «/», далее /login и /panel/api/...
"""

from __future__ import annotations

import json
import logging
import secrets
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp

import config
from config import XuiPanelConfig, get_xui_panel_config

logger = logging.getLogger(__name__)


class XuiApiError(Exception):
    """Ошибка ответа API или сети."""

    def __init__(self, message: str, *, status: Optional[int] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class CreatedInboundClient:
    """Данные клиента после успешного addClient."""

    email: str
    client_uuid: str
    sub_id: str
    expiry_time_ms: int
    inbound_id: int


def _url(base: str, *parts: str) -> str:
    root = base.rstrip("/")
    return root + "".join("/" + p.strip("/") for p in parts)


def _ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def _read_json(resp: aiohttp.ClientResponse) -> Any:
    text = await resp.text()
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        raise XuiApiError(
            "Некорректный JSON от панели",
            status=resp.status,
            body=text[:500],
        ) from None


class XuiApiClient:
    """Одна сессия: логин → вызовы API → закрытие."""

    def __init__(self, cfg: XuiPanelConfig):
        self._cfg = cfg
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "XuiApiClient":
        timeout = aiohttp.ClientTimeout(total=self._cfg["request_timeout"])
        connector = aiohttp.TCPConnector(ssl=_ssl_context(self._cfg["verify_ssl"]))
        jar = aiohttp.CookieJar(unsafe=True)
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            cookie_jar=jar,
            headers={"User-Agent": "MI_BotTGv1-xui-client/1.0"},
        )
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    @property
    def _s(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise XuiApiError("Сессия не открыта, используйте async with XuiApiClient(cfg)")
        return self._session

    async def login(self, two_factor_code: str = "") -> None:
        url = _url(self._cfg["panel_base_url"], "login")
        payload = {
            "username": self._cfg["username"],
            "password": self._cfg["password"],
            "twoFactorCode": two_factor_code or "",
        }
        async with self._s.post(url, json=payload) as resp:
            data = await _read_json(resp)
        if resp.status != 200:
            raise XuiApiError(
                f"Логин: HTTP {resp.status}",
                status=resp.status,
                body=str(data)[:500],
            )
        if not isinstance(data, dict) or not data.get("success"):
            msg = (data or {}).get("msg") if isinstance(data, dict) else str(data)
            raise XuiApiError(f"Логин отклонён: {msg or 'unknown'}")

    async def get_inbound(self, inbound_id: Optional[int] = None) -> dict[str, Any]:
        """GET /panel/api/inbounds/get/:id — проверка сессии и просмотр инбаунда."""
        iid = inbound_id if inbound_id is not None else self._cfg["inbound_id"]
        url = _url(self._cfg["panel_base_url"], "panel", "api", "inbounds", "get", str(iid))
        async with self._s.get(url) as resp:
            data = await _read_json(resp)
        if resp.status == 404:
            raise XuiApiError(
                "API вернул 404 (часто: не залогинились или неверный путь к панели). "
                "Проверьте XUI_*_PANEL_BASE_URL и что инбаунд существует.",
                status=404,
            )
        if resp.status != 200:
            raise XuiApiError(f"getInbound: HTTP {resp.status}", status=resp.status, body=str(data)[:500])
        if not isinstance(data, dict) or not data.get("success"):
            msg = (data or {}).get("msg") if isinstance(data, dict) else str(data)
            raise XuiApiError(f"getInbound: {msg or 'unknown'}")
        obj = data.get("obj")
        if not isinstance(obj, dict):
            raise XuiApiError("getInbound: пустой obj")
        return obj

    async def add_inbound_client(
        self,
        *,
        telegram_user_id: int,
        duration_days: int,
        email: Optional[str] = None,
        limit_ip: int = 0,
        total_gb: int = 0,
    ) -> CreatedInboundClient:
        """
        POST /panel/api/inbounds/addClient
        Добавляет одного клиента в существующий inbound (как в веб-панели).
        """
        inbound_id = self._cfg["inbound_id"]
        client_uuid = str(uuid.uuid4())
        sub_id = secrets.token_hex(8)
        if not email:
            email = f"tg{telegram_user_id}_{self._cfg['server_id']}_{sub_id[:10]}"

        expiry_ms = int(
            (datetime.now(timezone.utc) + timedelta(days=max(1, int(duration_days)))).timestamp() * 1000
        )

        flow = ""
        if self._cfg["server_id"] == "ee":
            flow = config.XUI_EE_VLESS_FLOW

        client_obj: dict[str, Any] = {
            "id": client_uuid,
            "email": email,
            "security": "",
            "password": "",
            "flow": flow,
            "limitIp": limit_ip,
            "totalGB": total_gb,
            "expiryTime": expiry_ms,
            "enable": True,
            "tgId": int(telegram_user_id),
            "subId": sub_id,
            "comment": "",
            "reset": 0,
        }
        settings_str = json.dumps({"clients": [client_obj]}, separators=(",", ":"))

        url = _url(self._cfg["panel_base_url"], "panel", "api", "inbounds", "addClient")
        payload = {"id": inbound_id, "settings": settings_str}

        async with self._s.post(url, json=payload) as resp:
            data = await _read_json(resp)

        if resp.status == 404:
            raise XuiApiError(
                "addClient: 404 — сессия не действует или неверный URL панели.",
                status=404,
            )
        if resp.status != 200:
            raise XuiApiError(f"addClient: HTTP {resp.status}", status=resp.status, body=str(data)[:500])
        if not isinstance(data, dict) or not data.get("success"):
            msg = (data or {}).get("msg") if isinstance(data, dict) else str(data)
            raise XuiApiError(f"addClient: {msg or 'unknown'}")

        return CreatedInboundClient(
            email=email,
            client_uuid=client_uuid,
            sub_id=sub_id,
            expiry_time_ms=expiry_ms,
            inbound_id=inbound_id,
        )

    async def extend_inbound_client(
        self,
        *,
        client_uuid: str,
        duration_days: int,
    ) -> CreatedInboundClient:
        """
        POST /panel/api/inbounds/updateClient/{clientUuid}
        Продлевает срок: max(сейчас, текущий expiry) + duration (как типичное продление).
        """
        inbound_id = self._cfg["inbound_id"]
        inbound = await self.get_inbound(inbound_id)
        settings_raw = inbound.get("settings")
        if not settings_raw or not isinstance(settings_raw, str):
            raise XuiApiError("Инбаунд без settings")
        try:
            root = json.loads(settings_raw)
        except json.JSONDecodeError as e:
            raise XuiApiError(f"Не удалось разобрать settings инбаунда: {e}") from e

        clients = root.get("clients")
        if not isinstance(clients, list):
            raise XuiApiError("В settings нет clients")

        found: Optional[dict[str, Any]] = None
        for c in clients:
            if not isinstance(c, dict):
                continue
            if str(c.get("id", "")) == str(client_uuid):
                found = dict(c)
                break

        if not found:
            raise XuiApiError(f"Клиент с UUID {client_uuid!r} не найден в инбаунде")

        email = str(found.get("email") or "")
        sub_id = str(found.get("subId") or found.get("sub_id") or "")

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        raw_exp = found.get("expiryTime")
        try:
            old_ms = int(raw_exp) if raw_exp is not None else 0
        except (TypeError, ValueError):
            old_ms = 0
        if old_ms <= 0:
            base_ms = now_ms
        else:
            base_ms = max(now_ms, old_ms)
        new_expiry_ms = base_ms + int(max(1, int(duration_days))) * 86400 * 1000

        flow = found.get("flow", "")
        if self._cfg["server_id"] == "ee" and not (flow or "").strip():
            flow = config.XUI_EE_VLESS_FLOW

        updated: dict[str, Any] = {
            **found,
            "id": str(found.get("id", client_uuid)),
            "email": email,
            "expiryTime": new_expiry_ms,
            "enable": True,
            "flow": flow or "",
        }

        settings_str = json.dumps({"clients": [updated]}, separators=(",", ":"))
        url = _url(
            self._cfg["panel_base_url"],
            "panel",
            "api",
            "inbounds",
            "updateClient",
            str(client_uuid),
        )
        payload = {"id": inbound_id, "settings": settings_str}

        async with self._s.post(url, json=payload) as resp:
            data = await _read_json(resp)

        if resp.status == 404:
            raise XuiApiError("updateClient: 404 — нет сессии, клиента или неверный URL.", status=404)
        if resp.status != 200:
            raise XuiApiError(
                f"updateClient: HTTP {resp.status}",
                status=resp.status,
                body=str(data)[:500],
            )
        if not isinstance(data, dict) or not data.get("success"):
            msg = (data or {}).get("msg") if isinstance(data, dict) else str(data)
            raise XuiApiError(f"updateClient: {msg or 'unknown'}")

        return CreatedInboundClient(
            email=email,
            client_uuid=str(client_uuid),
            sub_id=sub_id,
            expiry_time_ms=new_expiry_ms,
            inbound_id=inbound_id,
        )


async def create_client_for_server(
    server_id: str,
    telegram_user_id: int,
    duration_days: int,
    *,
    email: Optional[str] = None,
) -> CreatedInboundClient:
    """
    Удобная обёртка: загрузить конфиг по server_id, залогиниться, создать клиента.
    """
    cfg = get_xui_panel_config(server_id)
    if not cfg:
        raise XuiApiError(
            f"Нет конфигурации 3x-ui для server_id={server_id!r} "
            "(URL, inbound id, логин/пароль в .env).",
        )
    async with XuiApiClient(cfg) as api:
        return await api.add_inbound_client(
            telegram_user_id=telegram_user_id,
            duration_days=duration_days,
            email=email,
        )


async def extend_client_for_server(
    server_id: str,
    client_uuid: str,
    duration_days: int,
) -> CreatedInboundClient:
    """Продлить существующего клиента по UUID (как в панели updateClient)."""
    cfg = get_xui_panel_config(server_id)
    if not cfg:
        raise XuiApiError(
            f"Нет конфигурации 3x-ui для server_id={server_id!r} "
            "(URL, inbound id, логин/пароль в .env).",
        )
    async with XuiApiClient(cfg) as api:
        return await api.extend_inbound_client(
            client_uuid=client_uuid,
            duration_days=duration_days,
        )


async def ping_panel(server_id: str) -> dict[str, Any]:
    """Логин + getInbound — для проверки из скрипта или админки."""
    cfg = get_xui_panel_config(server_id)
    if not cfg:
        raise XuiApiError("Конфиг панели не задан")
    async with XuiApiClient(cfg) as api:
        return await api.get_inbound()


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)

    async def _main() -> None:
        config.check_config()
        sid = config.VPN_SERVERS[0]["id"]
        info = await ping_panel(str(sid))
        logger.info("Панель отвечает, inbound protocol=%s port=%s", info.get("protocol"), info.get("port"))

    asyncio.run(_main())
