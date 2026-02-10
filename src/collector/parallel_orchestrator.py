"""Parallel Collection Orchestrator with ThreadPoolExecutor"""
import logging
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from typing import Optional, Callable

from src.collector.normalizer import PhoneNormalizer
from src.collector.state_manager import StateManager


logger = logging.getLogger(__name__)


class RateLimiter:
    """Централизованный rate limiter для всех потоков."""
    
    def __init__(self, delay: float):
        self.delay = delay
        self.lock = threading.Lock()
        self.last_request_time = 0
    
    def wait(self):
        """Ждёт необходимое время перед следующим запросом."""
        with self.lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            
            if time_since_last < self.delay:
                sleep_time = self.delay - time_since_last
                time.sleep(sleep_time)
            
            self.last_request_time = time.time()


class ParallelOrchestrator:
    """Параллельный оркестратор сбора с ThreadPoolExecutor."""
    
    def __init__(
        self, 
        api_client, 
        db, 
        rate_limit: float = 0.5, 
        state_manager: StateManager = None,
        notifier=None,
        workers: int = 5
    ):
        self.api = api_client
        self.db = db
        self.db_path = db.db_path
        self.rate_limit = rate_limit
        self.normalizer = PhoneNormalizer()
        self.state_manager = state_manager or StateManager()
        self.notifier = notifier
        self.workers = workers
        self.rate_limiter = RateLimiter(rate_limit)
        
        # Thread-safe счётчики
        self.stats_lock = threading.Lock()
        self.processed_lock = threading.Lock()
        self.active_workers = 0
        self.active_workers_lock = threading.Lock()
        
        logger.info(f"ParallelOrchestrator initialized with {workers} workers")
    
    def collect(
        self,
        limit_clients: Optional[int] = None,
        limit_projects: Optional[int] = None,
        max_pages: Optional[int] = None,
        resume: bool = False,
        stop_callback: Optional[Callable] = None,
        progress_callback: Optional[Callable] = None,
    ):
        """Главный метод сбора с параллелизацией."""
        processed_client_ids = set()
        start_time = datetime.now()
        
        # Resume logic
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
            # Получаем список клиентов
            all_clients_list = self.api.get_clients()
            total_clients_original = len(all_clients_list)
            
            if limit_clients:
                all_clients_list = all_clients_list[:limit_clients]
            
            if processed_client_ids:
                all_clients_list = [c for c in all_clients_list if c.id not in processed_client_ids]
            
            total_clients = len(all_clients_list)
            logger.info(f"Starting PARALLEL collection for {total_clients} clients with {self.workers} workers (run_id={run_id})")
            
            # Уведомление о старте
            if self.notifier:
                logger.info(f"Sending Telegram start notification for run_id={run_id}")
                result = self.notifier.notify_start(run_id, total_clients)
                logger.info(f"Telegram start notification result: {result}")
            
            # Параллельная обработка
            completed_count = 0
            
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                # Создаём задачи для каждого клиента
                future_to_client = {
                    executor.submit(
                        self._process_client,
                        client,
                        run_id,
                        limit_projects,
                        max_pages,
                        stop_callback
                    ): (client, idx)
                    for idx, client in enumerate(all_clients_list, 1)
                }
                
                # Обрабатываем результаты по мере завершения
                for future in as_completed(future_to_client):
                    if stop_callback and stop_callback():
                        logger.info("Stop requested, cancelling remaining tasks")
                        executor.shutdown(wait=False, cancel_futures=True)
                        self.save_state(run_id, total_clients_original, processed_client_ids, stats)
                        return "stopped"
                    
                    client, idx = future_to_client[future]
                    
                    try:
                        client_stats = future.result()
                        
                        # Thread-safe обновление статистики
                        with self.stats_lock:
                            stats['total_phones'] += client_stats['phones']
                            stats['new_phones'] += client_stats['new_phones']
                            stats['projects_count'] += client_stats['projects']
                        
                        with self.processed_lock:
                            processed_client_ids.add(client.id)
                            completed_count = len(processed_client_ids)
                        
                        # Сохранение состояния каждые 10 клиентов
                        if completed_count % 10 == 0:
                            self.save_state(run_id, total_clients_original, processed_client_ids, stats)
                        
                        # Уведомление о прогрессе каждые 50 клиентов
                        if self.notifier and completed_count % 50 == 0:
                            logger.info(f"Sending progress notification at client {completed_count}/{total_clients}")
                            self.notifier.notify_progress(
                                run_id, completed_count, total_clients,
                                stats['projects_count'],
                                stats['total_phones']
                            )
                        
                        # Callback для GUI
                        if progress_callback:
                            # Добавляем информацию об активных воркерах в stats
                            with self.active_workers_lock:
                                stats['active_workers'] = self.active_workers
                            
                            progress_callback(completed_count, total_clients, stats)

                    except Exception as e:
                        logger.error(f"Error processing client {client.id}: {e}")
                        with self.stats_lock:
                            stats['errors'] += 1
                        
                        if self.notifier:
                            self.notifier.notify_error(run_id, str(e), client.id)
            
            # Финальное сохранение
            duration = (datetime.now() - start_time).total_seconds()
            self.db.update_run_stats(run_id, stats['total_phones'], stats['new_phones'], 'completed', stats['errors'])
            
            # Финальное уведомление
            if self.notifier:
                final_stats = {
                    'clients_processed': len(processed_client_ids),
                    'projects_found': stats['projects_count'],
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
    
    def _process_client(
        self, 
        client, 
        run_id: int,
        limit_projects: Optional[int],
        max_pages: Optional[int],
        stop_callback: Optional[Callable]
    ) -> dict:
        """Обработка одного клиента (выполняется в отдельном потоке)."""
        from src.database.manager import DatabaseManager
        
        client_stats = {'phones': 0, 'new_phones': 0, 'projects': 0}
        
        # Увеличиваем счётчик активных воркеров
        with self.active_workers_lock:
            self.active_workers += 1
            current_active = self.active_workers
        
        logger.info(f"[Worker-{threading.current_thread().name}] Starting client: {client.username} (Active workers: {current_active})")
        
        # Создаём отдельное подключение к БД для этого потока
        thread_db = DatabaseManager(self.db_path)
        thread_db.connect()
        
        # Создаём отдельное подключение к БД для этого потока
        thread_db = DatabaseManager(self.db.db_path)
        thread_db.connect()
        
        try:
            logger.info(f"[Worker-{threading.current_thread().name}] Processing client: {client.username}")
            
            # Вставка клиента
            self.rate_limiter.wait()
            thread_db.insert_client(client.id, client.username)
            
            # Получение проектов
            self.rate_limiter.wait()
            projects = self.api.get_projects(client.id)
            
            if limit_projects:
                projects = projects[:limit_projects]
            
            # Обработка проектов
            for project in projects:
                if stop_callback and stop_callback():
                    break
                
                self.rate_limiter.wait()
                thread_db.insert_project(project.id, project.name, client.id)
                client_stats['projects'] += 1
                
                # Пагинация номеров
                page = 1
                while True:
                    if stop_callback and stop_callback():
                        break
                    
                    if max_pages and page > max_pages:
                        break
                    
                    self.rate_limiter.wait()
                    phones = self.api.get_phones(project.id, page)
                    
                    if not phones:
                        break
                    
                    # Обработка номеров
                    for phone_data in phones:
                        normalized, is_valid = self.normalizer.normalize(phone_data.phone)
                        
                        if is_valid:
                            existing = thread_db.get_phone_by_number(normalized)
                            
                            if not existing:
                                phone_id = thread_db.insert_phone(normalized, phone_data.phone, run_id)
                                client_stats['new_phones'] += 1
                            else:
                                phone_id = existing['id']
                            
                            thread_db.insert_project_phone(project.id, phone_id, run_id, phone_data.created_at)
                            client_stats['phones'] += 1
                    
                    page += 1
            
            return client_stats
            
        except Exception as e:
            logger.error(f"Error in client {client.id}: {e}")
            raise
        finally:
            # Закрываем соединение после обработки клиента
            thread_db.close()
            # Уменьшаем счётчик активных воркеров
            with self.active_workers_lock:
                self.active_workers -= 1
                logger.info(f"[Worker-{threading.current_thread().name}] Finished. Active workers: {self.active_workers}")

    
    def save_state(self, run_id: int, total_clients: int, processed_client_ids: set, stats: dict):
        """Thread-safe сохранение состояния."""
        with self.processed_lock:
            self.state_manager.save(
                run_id=run_id,
                total_clients=total_clients,
                processed_clients=len(processed_client_ids),
                processed_client_ids=list(processed_client_ids),
                stats=stats
            )
            self.db.update_run_stats(run_id, stats['total_phones'], stats['new_phones'], 'stopped', stats['errors'])
