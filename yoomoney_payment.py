# yoomoney_payment.py
import logging
import asyncio
from yoomoney import Client, Quickpay

logger = logging.getLogger(__name__)

class YooMoneyPayment:
    def __init__(self, token: str, wallet: str):
        self.token = token
        self.wallet = wallet
        self.client = Client(token)
    
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
    
    async def check_payment_status(self, payment_id: str) -> dict:
        """Проверяет статус платежа"""
        try:
            # Получаем историю операций
            history = self.client.operation_history(label=payment_id)
            
            for operation in history.operations:
                if operation.label == payment_id:
                    if operation.status == 'success':
                        return {
                            'success': True,
                            'status': 'completed',
                            'amount': operation.amount,
                            'payment_id': payment_id
                        }
                    else:
                        return {
                            'success': True,
                            'status': 'pending',
                            'payment_id': payment_id
                        }
            
            return {
                'success': True,
                'status': 'not_found',
                'payment_id': payment_id
            }
            
        except Exception as e:
            logger.error(f"Ошибка проверки статуса платежа: {e}")
            return {
                'success': False,
                'error': str(e)
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