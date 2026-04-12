# yoomoney_payment.py
import asyncio
import json
import logging
from datetime import datetime, timedelta
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import httpx
from yoomoney import Quickpay
from yoomoney._parsers import build_history_payload, parse_history
from yoomoney.exceptions import YooMoneyError

logger = logging.getLogger(__name__)

YOOMONEY_API_BASE = "https://yoomoney.ru/api/"

# Иначе часть сетей/фильтров отдаёт нестандартное тело (в т.ч. JSON "").
_WALLET_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}


def _form_values_str(payload: dict[str, Any]) -> dict[str, str]:
    """application/x-www-form-urlencoded: только строки, bool как true/false."""
    out: dict[str, str] = {}
    for key, val in payload.items():
        if val is None:
            continue
        if val is True:
            out[str(key)] = "true"
        elif val is False:
            out[str(key)] = "false"
        else:
            out[str(key)] = str(val)
    return out


def _sync_wallet_post(method: str, token: str, payload: dict[str, Any]) -> str:
    url = YOOMONEY_API_BASE + method
    form = _form_values_str(payload)
    body = urllib.parse.urlencode(form).encode("utf-8")
    headers = {
        **_WALLET_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return (resp.read() or b"").decode("utf-8", errors="replace").strip()


def _raise_wallet_http_error(method: str, status: int, body: str) -> None:
    """Ответ Wallet API с кодом ≥400 — сразу понятная ошибка (без разбора JSON)."""
    snippet = (body or "").strip()[:400]
    if status == 401:
        raise RuntimeError(
            "HTTP 401 от ЮMoney: токен не принят (неверный, истёк или отозван) либо у приложения "
            "нет права «operation-history» (просмотр истории операций кошелька). "
            "Ссылку Quickpay можно строить без токена, а проверка оплаты ходит в API только с "
            "валидным access_token.\n\n"
            "Что сделать: https://yoomoney.ru/myservices — создать или открыть приложение, "
            "заново пройти авторизацию OAuth и при выдаче прав отметить просмотр истории операций, "
            "скопировать новый токен в переменную YOOMONEY_TOKEN в .env (одной строкой, без кавычек и пробелов по краям)."
        )
    if status == 403:
        raise RuntimeError(
            f"HTTP 403 от ЮMoney на {method}: доступ запрещён. Проверьте права приложения и токен."
        )
    raise RuntimeError(
        f"{method}: HTTP {status} от ЮMoney. Фрагмент ответа: {snippet!r}"
    )


def _loads_wallet_json(raw: str, *, method: str, http_status: int | None) -> dict[str, Any]:
    if not raw:
        raise RuntimeError(
            f"Пустой ответ {method} (HTTP {http_status}). "
            "Проверьте доступ к https://yoomoney.ru с сервера и токен."
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"{method}: ответ не JSON (HTTP {http_status}): {raw[:500]!r}"
        ) from e
    if isinstance(data, str):
        # Сервер иногда отдаёт литерал JSON "" — трактуем как сбой/блокировку API.
        logger.warning(
            "YooMoney %s: вместо объекта пришла JSON-строка %r, сырой ответ (до 800 симв.): %r",
            method,
            data,
            raw[:800],
        )
        raise RuntimeError(
            f"ЮMoney вернул некорректный ответ на {method} (JSON-строка вместо объекта). "
            "Частые причины: блокировка API с IP хостинга/VPS, антивирус/прокси, устаревший токен. "
            "Проверьте токен и право «operation-history», при необходимости запускайте бота с другой сети "
            "или используйте HTTP-уведомления ЮMoney вместо опроса истории."
        )
    if not isinstance(data, dict):
        raise RuntimeError(
            f"{method}: ожидался JSON-объект, получено {type(data).__name__}: {data!r}"
        )
    return data


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
            exp = int(expected_amount)
            # Допуск −1 ₽ из‑за округлений/комиссий отображения в истории.
            if received < exp - 1:
                continue
        op_status = (operation.status or "").strip().lower()
        if op_status == "success":
            return {
                "success": True,
                "status": "completed",
                "amount": operation.amount,
            }
        if op_status == "refused":
            continue
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
        Запрос operation-history: httpx (HTTP/1.1), при «ломаных» ответах — urllib в потоке.
        """
        payload = build_history_payload(**history_kwargs)
        # Библиотечный format_datetime без ведущих нулей — ЮMoney ожидает ISO-подобную строку.
        fd = history_kwargs.get("from_date")
        if isinstance(fd, datetime):
            payload["from"] = fd.strftime("%Y-%m-%dT%H:%M:%S")
        td = history_kwargs.get("till_date")
        if isinstance(td, datetime):
            payload["till"] = td.strftime("%Y-%m-%dT%H:%M:%S")
        form = _form_values_str(payload or {})
        headers = {
            **_WALLET_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Bearer {self.token}",
        }
        url = YOOMONEY_API_BASE + "operation-history"
        timeout = httpx.Timeout(25.0)
        raw = ""
        http_status: int | None = None
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                http2=False,
            ) as client:
                resp = await client.post(url, data=form, headers=headers)
                http_status = resp.status_code
                raw = (resp.text or "").strip()
        except httpx.HTTPError as e:
            logger.warning("httpx operation-history: %s", e)

        if http_status is not None and http_status >= 400:
            _raise_wallet_http_error("operation-history", http_status, raw)

        parsed_dict: dict[str, Any] | None = None
        if raw:
            try:
                j = json.loads(raw)
                if isinstance(j, dict):
                    parsed_dict = j
                elif isinstance(j, str):
                    logger.warning(
                        "operation-history (httpx): JSON-строка %r, пробуем urllib",
                        j,
                    )
            except json.JSONDecodeError:
                logger.warning("operation-history (httpx): не JSON, пробуем urllib")

        if parsed_dict is None:
            try:
                raw = await asyncio.to_thread(
                    _sync_wallet_post, "operation-history", self.token, payload or {}
                )
                http_status = http_status or 200
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = (e.read() or b"").decode("utf-8", errors="replace").strip()
                except Exception:
                    pass
                _raise_wallet_http_error("operation-history", int(e.code), body)
            except urllib.error.URLError as e:
                raise RuntimeError(
                    f"operation-history: сеть/SSL при обращении к ЮMoney: {e}"
                ) from e
            parsed_dict = _loads_wallet_json(
                raw, method="operation-history", http_status=http_status
            )

        try:
            return parse_history(parsed_dict)
        except YooMoneyError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Не удалось разобрать ответ operation-history (HTTP {http_status}): {e}"
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
        self,
        payment_id: str,
        *,
        expected_amount: int | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        """
        Проверяет платёж Quickpay по label.
        Сначала запрос с фильтром label (как в API); если пусто — просмотр истории
        с даты создания заказа и поиск операции с тем же label в списке (иногда
        фильтр label в operation-history не отдаёт входящие с карты).
        """
        label = (payment_id or "").strip()
        try:
            for kwargs in (
                {"label": label, "type": "deposition", "records": 100},
                {"label": label, "records": 100},
            ):
                history = await self._post_operation_history(**kwargs)
                matched = _match_labeled_operation(
                    history.operations, label, expected_amount
                )
                if matched is not None:
                    matched["payment_id"] = payment_id
                    return matched

            if created_at is not None:
                window_start = created_at - timedelta(days=1)
                start_record: str | None = None
                for _ in range(15):
                    page_kw: dict[str, Any] = {
                        "from_date": window_start,
                        "records": 100,
                    }
                    if start_record is not None:
                        page_kw["start_record"] = str(start_record)
                    history = await self._post_operation_history(**page_kw)
                    matched = _match_labeled_operation(
                        history.operations, label, expected_amount
                    )
                    if matched is not None:
                        matched["payment_id"] = payment_id
                        return matched
                    start_record = history.next_record
                    if not start_record:
                        break

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
