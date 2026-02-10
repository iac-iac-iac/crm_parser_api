"""Collection Orchestrator"""
import logging
import time
from src.api.client import DataMasterClient
from src.database.manager import DatabaseManager
from src.collector.state_manager import StateManager
from src.collector.normalizer import PhoneNormalizer
from datetime import datetime


logger = logging.getLogger(__name__)

class CollectionOrchestrator:
    def __init__(self, api_client, db, rate_limit: float = 0.5, state_manager: StateManager = None, notifier=None):
        self.api = api_client
        self.db = db
        self.rate_limit = rate_limit
        self.normalizer = PhoneNormalizer()
        self.state_manager = state_manager or StateManager()
        self.notifier = notifier  # Опциональный Telegram notifier

    def collect(
        self,
        limit_clients: int | None = None,
        limit_projects: int | None = None,
        max_pages: int | None = None,
        resume: bool = False,
        stop_callback=None,
        progress_callback=None,
    ):
        processed_client_ids = set()
        start_time = datetime.now()
        if resume:
            state = self.state_manager.load()
            if state:
                run_id = state['run_id']
                stats = state['stats']
                processed_client_ids = set(state.get('processed_client_ids', []))
                logger.info(f"Resuming run_id={run_id}, skipping {len(processed_client_ids)} clients")
            else:
                logger.warning("--continue specified but no state found, starting fresh")
                run_id = self.db.create_run()
                stats = {'total_phones': 0, 'new_phones': 0, 'errors': 0, 'projects_count': 0}
        else:
            run_id = self.db.create_run()
            stats = {'total_phones': 0, 'new_phones': 0, 'errors': 0, 'projects_count': 0}

        try:
            all_clients_list = self.api.get_clients()
            total_clients_original = len(all_clients_list)
            
            if limit_clients:
                all_clients_list = all_clients_list[:limit_clients]
            
            if processed_client_ids:
                all_clients_list = [c for c in all_clients_list if c.id not in processed_client_ids]

            total_clients = len(all_clients_list)
            logger.info(f"Starting collection for {total_clients} clients (run_id={run_id})")
            
            # Уведомление о старте
            if self.notifier:
                self.notifier.notify_start(run_id, total_clients)
            else:
                logger.warning("Notifier is None, Telegram notifications disabled")

            for idx, client in enumerate(all_clients_list, 1):
                if stop_callback and stop_callback():
                    logger.info(f"Collection stopped by user at client {idx}")
                    self.save_state(run_id, total_clients_original, processed_client_ids, stats)
                    return "stopped"

                try:
                    logger.info(f"Processing client {idx}/{total_clients}: {client.username}")
                    self.db.insert_client(client.id, client.username)
                    
                    projects = self.api.get_projects(client.id)
                    if limit_projects:
                        projects = projects[:limit_projects]
                    
                    for p_idx, project in enumerate(projects, 1):
                        if stop_callback and stop_callback():
                            self.save_state(run_id, total_clients_original, processed_client_ids, stats)
                            return "stopped"
                        self.db.insert_project(project.id, project.name, client.id)
                        stats['projects_count'] += 1

                        page = 1
                        while True:
                            if stop_callback and stop_callback():
                                self.save_state(run_id, total_clients_original, processed_client_ids, stats)
                                return "stopped"

                            if max_pages and page > max_pages:
                                break
                            
                            phones = self.api.get_phones(project.id, page)
                            if not phones:
                                break
                            
                            for phone_data in phones:
                                normalized, is_valid = self.normalizer.normalize(phone_data.phone)
                                if is_valid:
                                    existing = self.db.get_phone_by_number(normalized)
                                    if not existing:
                                        phone_id = self.db.insert_phone(normalized, phone_data.phone, run_id)
                                        stats['new_phones'] += 1
                                    else:
                                        phone_id = existing['id']
                                    
                                    self.db.insert_project_phone(project.id, phone_id, run_id, phone_data.created_at)
                                    stats['total_phones'] += 1
                            
                            # Update progress inside pagination loop
                            if progress_callback:
                                progress_callback(idx, total_clients, stats)
                                
                            page += 1
                            time.sleep(self.rate_limit)

                    processed_client_ids.add(client.id)
                    # Every client update state
                    self.save_state(run_id, total_clients_original, processed_client_ids, stats)
                    # Уведомление о прогрессе каждые 50 клиентов
                    if self.notifier and idx % 50 == 0:
                        logger.info(f"Sending progress notification at client {idx}/{total_clients}")
                        self.notifier.notify_progress(
                            run_id, idx, total_clients,
                            stats.get('projects_count', 0),
                            stats['total_phones']
                        )

                except Exception as e:
                    logger.error(f"Error client {client.id}: {e}")
                    stats['errors'] += 1
                    # Уведомление об ошибке
                    if self.notifier:
                        self.notifier.notify_error(run_id, str(e), client.id)
            # Подсчёт дополнительных статистик для финального уведомления
            duration = (datetime.now() - start_time).total_seconds()

            self.db.update_run_stats(run_id, stats['total_phones'], stats['new_phones'], 'completed', stats['errors'])

            # Финальное уведомление
            if self.notifier:
                final_stats = {
                    'clients_processed': len(processed_client_ids),
                    'projects_found': stats.get('projects_count', 0),  # ← Используем счётчик
                    'numbers_found': stats['total_phones'],
                    'duration_seconds': duration,
                    'errors_count': stats['errors']
                }
                self.notifier.notify_finish(run_id, final_stats)
            self.state_manager.clear()
            return "completed"

        except Exception as e:
            logger.error(f"Orchestrator failed: {e}")
            self.db.update_run_stats(run_id, stats['total_phones'], stats['new_phones'], 'failed', stats['errors'])
            raise

    def save_state(self, run_id, total_clients, processed_client_ids, stats):
        self.state_manager.save(
            run_id=run_id,
            total_clients=total_clients,
            processed_clients=len(processed_client_ids),
            processed_client_ids=list(processed_client_ids),
            stats=stats
        )
        self.db.update_run_stats(run_id, stats['total_phones'], stats['new_phones'], 'stopped', stats['errors'])
