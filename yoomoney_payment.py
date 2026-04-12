# yoomoney_payment.py
import logging
from yoomoney import AsyncClient, Quickpay

logger = logging.getLogger(__name__)


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
        self._client = AsyncClient(token)
    
    async def create_payment(self, amount: int, description: str, payment_id: str) -> dict:
        """Создает платеж через Юмани"""
        try:
            # Создаем быстрый платеж
            quickpay = Quickpay(
                receiver=self.wallet,
                quickpay_form="shop",
                targets=description,
                paymentType="SB",
                sum=amount,
                label=payment_id
            )
            
            payment_url = quickpay.redirected_url
            
            return {
                'success': True,
                'payment_url': payment_url,
                'payment_id': payment_id
            }
            
        except Exception as e:
            logger.error(f"Ошибка создания платежа Юмани: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def check_payment_status(
        self, payment_id: str, *, expected_amount: int | None = None
    ) -> dict:
        """Проверяет статус входящего платежа по label (Quickpay)."""
        label = (payment_id or "").strip()
        try:
            # Сначала только входящие; при пустом ответе — без фильтра type (разные сценарии Quickpay).
            for kwargs in (
                {"label": label, "type": "deposition", "records": 50, "details": True},
                {"label": label, "records": 50, "details": True},
            ):
                history = await self._client.operation_history(**kwargs)
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