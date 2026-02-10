import os
import sys

# Добавляем корневую директорию проекта в путь поиска
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
from src.notifications.telegram_bot import TelegramNotifier

# Загрузка переменных из корня проекта
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def test_connection():
    """Тест базовой отправки сообщения."""
    notifier = TelegramNotifier(TOKEN, CHAT_ID)
    
    print("Отправка тестового сообщения...")
    result = notifier.send_message("🧪 <b>Тест подключения</b>\n\nБот работает!")
    
    if result:
        print("✅ Сообщение отправлено успешно!")
    else:
        print("❌ Ошибка отправки")
    
    return result


def test_notifications():
    """Тест всех типов уведомлений."""
    notifier = TelegramNotifier(TOKEN, CHAT_ID)
    
    print("\n1. Тест уведомления о старте...")
    notifier.notify_start(run_id=999, clients_count=50)
    
    print("2. Тест уведомления о прогрессе...")
    notifier.notify_progress(run_id=999, processed=25, total=50, 
                            projects=100, numbers=250)
    
    print("3. Тест уведомления об ошибке...")
    notifier.notify_error(run_id=999, error_msg="Test error message", client_id=123)
    
    print("4. Тест уведомления о завершении...")
    stats = {
        'clients_processed': 50,
        'projects_found': 200,
        'numbers_found': 500,
        'duration_seconds': 300,
        'errors_count': 2
    }
    notifier.notify_finish(run_id=999, stats=stats)
    
    print("\n✅ Все тесты завершены! Проверь Telegram.")


if __name__ == "__main__":
    if not TOKEN or not CHAT_ID:
        print("❌ Ошибка: Установи TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env")
        print(f"Файл .env должен быть в: {project_root}")
    else:
        print(f"📁 Проект: {project_root}")
        print(f"🔑 Токен: {TOKEN[:10]}...")
        print(f"💬 Chat ID: {CHAT_ID}\n")
        
        test_connection()
        
        if input("\nПродолжить тестирование всех типов уведомлений? (y/n): ").lower() == 'y':
            test_notifications()
