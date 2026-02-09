"""State Manager for resumable collection"""
import json
import os
import logging
from typing import Optional, Dict, Set
from datetime import datetime

logger = logging.getLogger(__name__)


class StateManager:
    def __init__(self, state_file: str = "data/state.json"):
        self.state_file = state_file
        self.state: Optional[Dict] = None

    def load(self) -> Optional[Dict]:
        """Загрузить состояние из файла"""
        if not os.path.exists(self.state_file):
            logger.info("No state file found, starting fresh")
            return None

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                self.state = json.load(f)
            logger.info(f"Loaded state: run_id={self.state['run_id']}, "
                       f"processed={self.state['processed_clients']}/{self.state['total_clients']}")
            return self.state
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return None

    def save(self, run_id: int, total_clients: int, processed_clients: int,
             processed_client_ids: Set[int], stats: Dict):
        """Сохранить текущее состояние"""
        self.state = {
            'run_id': run_id,
            'started_at': datetime.now().isoformat(),
            'total_clients': total_clients,
            'processed_clients': processed_clients,
            'processed_client_ids': list(processed_client_ids),
            'stats': stats,
        }

        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2)
            logger.debug(f"State saved: {processed_clients}/{total_clients} clients")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def clear(self):
        """Удалить файл состояния после успешного завершения"""
        if os.path.exists(self.state_file):
            try:
                os.remove(self.state_file)
                logger.info("State cleared")
            except Exception as e:
                logger.error(f"Failed to clear state: {e}")

    def get_processed_client_ids(self) -> Set[int]:
        """Получить множество уже обработанных client_id"""
        if self.state:
            return set(self.state.get('processed_client_ids', []))
        return set()

    def get_run_id(self) -> Optional[int]:
        """Получить run_id из сохранённого состояния"""
        return self.state.get('run_id') if self.state else None

    def get_stats(self) -> Dict:
        """Получить статистику из сохранённого состояния"""
        return self.state.get('stats', {'total_phones': 0, 'new_phones': 0, 'errors': 0}) if self.state else {
            'total_phones': 0, 'new_phones': 0, 'errors': 0
        }
