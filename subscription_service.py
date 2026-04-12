# -*- coding: utf-8 -*-
"""Выдача подписки после оплаты: создание клиента в 3x-ui и текст для пользователя."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import config
from xui_client import XuiApiError, create_client_for_server

logger = logging.getLogger(__name__)


@dataclass
class ProvisionOutcome:
    """Результат выдачи подписки."""

    ok: bool
    user_message: str
    config_data: str
    xui_email: Optional[str] = None
    xui_client_uuid: Optional[str] = None
    xui_sub_id: Optional[str] = None
    xui_inbound_id: Optional[int] = None


def _subscription_link(server_id: str, sub_id: str) -> Optional[str]:
    tpl = ""
    if server_id == "ee":
        tpl = config.XUI_EE_SUBSCRIPTION_URL_TEMPLATE
    tpl = (tpl or "").strip()
    if not tpl or not sub_id:
        return None
    return tpl.replace("{sub_id}", sub_id).replace("{subId}", sub_id)


def _expiry_human(expiry_ms: int) -> str:
    try:
        dt = datetime.fromtimestamp(expiry_ms / 1000.0, tz=timezone.utc)
        return dt.astimezone().strftime("%d.%m.%Y %H:%M")
    except (OSError, ValueError, OverflowError):
        return "—"


async def provision_after_payment(
    *,
    telegram_user_id: int,
    server_id: str,
    duration_days: int,
) -> ProvisionOutcome:
    """
    Создаёт клиента в панели и формирует текст для чата и поля БД.
    При ошибке панели оплата уже может быть помечена completed — пользователю инструкция в поддержку.
    """
    sid = (server_id or "").strip().lower()
    cfg = config.get_xui_panel_config(sid)
    if not cfg:
        msg = (
            "⚠️ Оплата принята, но автоматическая выдача не настроена для этого сервера.\n"
            "Напишите в поддержку: @MXMKGN"
        )
        return ProvisionOutcome(ok=False, user_message=msg, config_data="")

    try:
        created = await create_client_for_server(sid, telegram_user_id, duration_days)
    except XuiApiError as e:
        logger.exception("3x-ui: не удалось создать клиента: %s", e)
        msg = (
            "⚠️ Оплата учтена, но панель VPN сейчас не выдала доступ автоматически.\n"
            f"Ошибка: {e}\n"
            "Напишите в поддержку @MXMKGN — подключим вручную."
        )
        return ProvisionOutcome(ok=False, user_message=msg, config_data="")

    sub_url = _subscription_link(sid, created.sub_id)
    until = _expiry_human(created.expiry_time_ms)

    lines = [
        "✅ Подписка активирована.",
        "",
        f"Локация: {sid.upper()}",
        f"Действует примерно до: {until}",
        "",
        f"Email клиента в панели: {created.email}",
        f"UUID: {created.client_uuid}",
        f"Sub ID: {created.sub_id}",
    ]
    if sub_url:
        lines += ["", "Ссылка подписки (импорт в v2rayNG / Hiddify / Streisand и т.п.):", sub_url]
    else:
        lines += [
            "",
            "Ссылку подписки можно задать в .env (`XUI_EE_SUBSCRIPTION_URL_TEMPLATE` с `{sub_id}`),",
            "если в панели включён subscription-сервер — см. настройки «Подписка» в 3x-ui.",
        ]
    lines += [
        "",
        "Клиенты с VLESS: v2rayNG, Hiddify, Nekoray и др.",
    ]

    user_message = "\n".join(lines)
    config_data = user_message

    return ProvisionOutcome(
        ok=True,
        user_message=user_message,
        config_data=config_data,
        xui_email=created.email,
        xui_client_uuid=created.client_uuid,
        xui_sub_id=created.sub_id,
        xui_inbound_id=created.inbound_id,
    )
