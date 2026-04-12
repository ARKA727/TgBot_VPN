# yoomoney_payment.py
import json
import logging
from typing import Any

import httpx
from yoomoney import Quickpay
from yoomoney._parsers import build_history_payload, parse_history
from yoomoney.exceptions import YooMoneyError

logger = logging.getLogger(__name__)

YOOMONEY_API_HISTORY = "https://yoomoney.ru/api/operation-history"


def _match_labeled_operation(
    operations, label: str, expected_amount: int | None
) -> dict | None:
    """Возвращает dict со статусом или None, если подходящей операции нет."""
    for operation in operations:
        op_label = (operation.label or "").strip()
        if op_label != label:
            continue
        if expected_amount is not None and operation.amount is not None:
            received = int(round(float(operation.amount)))
            if received < int(expected_amount):
                continue
        op_status = (operation.status or "").strip().lower()
        if op_status == "success":
            return {
                "success": True,
                "status": "completed",
                "amount": operation.amount,
            }
        return {
            "success": True,
            "status": "pending",
        }
    return None


class YooMoneyPayment:
    def __init__(self, token: str, wallet: str):
        self.token = token
        self.wallet = wallet

    async def _post_operation_history(self, **history_kwargs: Any):
        """
        Запрос operation-history с явным разбором JSON.
        Библиотечный AsyncTransport иногда отдаёт в parse_history не dict (например пустая строка),
        из‑за чего падает Pydantic на History.
        """
        payload = build_history_payload(**history_kwargs)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Bearer {self.token}",
        }
        timeout = httpx.Timeout(20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                YOOMONEY_API_HISTORY,
                data=payload or {},
                headers=headers,
            )
        raw = (resp.text or "").strip()
        if not raw:
            raise RuntimeError(
                f"Пустой ответ operation-history (HTTP {resp.status_code}). "
                "Проверьте токен и право operation-history."
            )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"operation-history: не JSON (HTTP {resp.status_code}): {raw[:400]!r}"
            ) from e
        if not isinstance(data, dict):
            raise RuntimeError(
                f"operation-history: ожидался JSON-объект, получено {type(data).__name__}: {data!r}"
            )
        try:
            return parse_history(data)
        except YooMoneyError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Не удалось разобрать ответ ЮMoney (HTTP {resp.status_code}): {e}"
            ) from e

    async def create_payment(self, amount: int, description: str, payment_id: str) -> dict:
        """Создает платеж через Юмани"""
        try:
            quickpay = Quickpay(
                receiver=self.wallet,
                quickpay_form="shop",
                targets=description,
                paymentType="SB",
                sum=amount,
                label=payment_id,
            )

            payment_url = quickpay.redirected_url

            return {
                "success": True,
                "payment_url": payment_url,
                "payment_id": payment_id,
            }

        except Exception as e:
            logger.error("Ошибка создания платежа Юмани: %s", e)
            return {
                "success": False,
                "error": str(e),
            }

    async def check_payment_status(
        self, payment_id: str, *, expected_amount: int | None = None
    ) -> dict:
        """Проверяет статус входящего платежа по label (Quickpay)."""
        label = (payment_id or "").strip()
        try:
            for kwargs in (
                {"label": label, "type": "deposition", "records": 50},
                {"label": label, "records": 50},
            ):
                history = await self._post_operation_history(**kwargs)
                matched = _match_labeled_operation(
                    history.operations, label, expected_amount
                )
                if matched is not None:
                    matched["payment_id"] = payment_id
                    return matched

            return {
                "success": True,
                "status": "not_found",
                "payment_id": payment_id,
            }

        except Exception as e:
            logger.error("Ошибка проверки статуса платежа: %s", e)
            return {
                "success": False,
                "error": str(e),
            }


# Глобальный экземпляр
yoomoney = None


def init_yoomoney():
    """Инициализация Юмани"""
    global yoomoney
    import config

    token = (config.YOOMONEY_TOKEN or "").strip()
    wallet = (config.YOOMONEY_WALLET or "").strip()
    if token and wallet:
        yoomoney = YooMoneyPayment(token, wallet)
        logger.info("✅ Юмани инициализирован")
        return True
    reasons = []
    if not token:
        reasons.append("YOOMONEY_TOKEN пустой")
    if not wallet:
        reasons.append("YOOMONEY_WALLET пустой")
    logger.warning("⚠️ Юмани не инициализирован: %s", "; ".join(reasons) or "неизвестно")
    return False
