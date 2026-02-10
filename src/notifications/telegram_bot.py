import logging
from typing import Optional
from datetime import datetime
import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Упрощённый Telegram-уведомитель через requests (без async)."""
    
    def __init__(self, token: str, chat_id: str, enabled: bool = True):
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.last_error_time = 0  # ← Добавь
        self.error_cooldown = 10  # ← Минимум 10 сек между ошибками
        
        if not self.enabled:
            logger.info("Telegram notifications disabled")
    
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Отправка текстового сообщения."""
        if not self.enabled:
            return False
        
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.debug(f"Telegram message sent: {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def notify_start(self, run_id: int, clients_count: int) -> bool:
        """Уведомление о старте сбора."""
        text = (
            f"🚀 <b>Запуск #{run_id}</b>\n\n"
            f"📊 Клиентов: {clients_count}\n"
            f"🕐 Старт: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send_message(text)
    
    def notify_progress(self, run_id: int, processed: int, total: int, 
                       projects: int, numbers: int) -> bool:
        """Уведомление о прогрессе."""
        percent = (processed / total * 100) if total > 0 else 0
        text = (
            f"📈 <b>Прогресс #{run_id}</b>\n\n"
            f"✅ Обработано: {processed}/{total} ({percent:.1f}%)\n"
            f"📁 Проектов собрано: {projects}\n"
            f"📞 Номеров найдено: {numbers}"
        )
        return self.send_message(text)
    
    def notify_error(self, run_id: int, error_msg: str, client_id: Optional[int] = None) -> bool:
        """Уведомление об ошибке с защитой от спама."""
        import time
        
        # Проверка cooldown
        current_time = time.time()
        if current_time - self.last_error_time < self.error_cooldown:
            logger.debug("Skipping error notification due to cooldown")
            return False
        
        self.last_error_time = current_time
        
        client_info = f" (Клиент #{client_id})" if client_id else ""
        text = (
            f"❌ <b>Ошибка #{run_id}</b>{client_info}\n\n"
            f"de>{error_msg[:300]}</code>"
        )
        return self.send_message(text)
    
    def notify_finish(self, run_id: int, stats: dict) -> bool:
        """Уведомление о завершении."""
        duration_min = stats.get('duration_seconds', 0) / 60
        text = (
            f"✅ <b>Завершено #{run_id}</b>\n\n"
            f"📊 Клиентов обработано: {stats.get('clients_processed', 0)}\n"
            f"📁 Проектов найдено: {stats.get('projects_found', 0)}\n"
            f"📞 Номеров собрано: {stats.get('numbers_found', 0)}\n"
            f"⏱ Время выполнения: {duration_min:.1f} мин\n"
            f"❌ Ошибок: {stats.get('errors_count', 0)}"
        )
        return self.send_message(text)
