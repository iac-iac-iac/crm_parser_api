"""Collection Orchestrator"""
import logging
import time
from src.api.client import DataMasterClient
from src.database.manager import DatabaseManager
from src.collector.state_manager import StateManager
from src.collector.normalizer import PhoneNormalizer

logger = logging.getLogger(__name__)


class CollectionOrchestrator:
    def __init__(self, api_client, db, rate_limit: float = 0.5, state_manager: StateManager = None):
        self.api = api_client
        self.db = db
        self.rate_limit = rate_limit
        self.normalizer = PhoneNormalizer()
        self.state_manager = state_manager or StateManager()

    def collect(
        self,
        limit_clients: int | None = None,
        limit_projects: int | None = None,
        max_pages: int | None = None,
        resume: bool = False,
        stop_callback=None,  # ← НОВОЕ
        progress_callback=None,  # ← НОВОЕ
    ):
        # Если resume, пытаемся загрузить состояние
        processed_client_ids = set()
        if resume:
            state = self.state_manager.load()
            if state:
                run_id = state['run_id']
                stats = state['stats']
                processed_client_ids = self.state_manager.get_processed_client_ids()
                logger.info(f"Resuming run_id={run_id}, skipping {len(processed_client_ids)} clients")
            else:
                logger.warning("--continue specified but no state found, starting fresh")
                run_id = self.db.create_run()
                stats = {'total_phones': 0, 'new_phones': 0, 'errors': 0}
        else:
            # Новый запуск
            run_id = self.db.create_run()
            stats = {'total_phones': 0, 'new_phones': 0, 'errors': 0}

        try:
            # Загружаем клиентов ОДИН РАЗ
            all_clients_list = self.api.get_clients()
            total_clients_original = len(all_clients_list)
            
            if limit_clients:
                all_clients_list = all_clients_list[:limit_clients]

            # Фильтруем уже обработанных клиентов
            if processed_client_ids:
                all_clients_list = [c for c in all_clients_list if c.id not in processed_client_ids]
                logger.info(f"Skipped {len(processed_client_ids)} already processed clients")

            total_clients = len(all_clients_list)
            logger.info(
                f"Starting collection for {total_clients} clients "
                f"(run_id={run_id}, limit_projects={limit_projects}, max_pages={max_pages})"
            )

            for idx, client in enumerate(all_clients_list, 1):
                # ← НОВОЕ: Проверка на остановку
                if stop_callback and stop_callback():
                    logger.info("Collection stopped by user (via callback)")
                    self.state_manager.save(
                        run_id=run_id,
                        total_clients=total_clients_original,
                        processed_clients=len(processed_client_ids),
                        processed_client_ids=processed_client_ids,
                        stats=stats
                    )
                    self.db.update_run_stats(run_id, stats['total_phones'], stats['new_phones'], 'stopped', stats['errors'])
                    return  # ← Прерываем цикл

                try:
                    logger.info(f"[{idx}/{total_clients}] Processing client {client.username} (id={client.id})")
                    self.db.insert_client(client.id, client.username)

                    # ← НОВОЕ: Обновление прогресса
                    if progress_callback:
                        progress_callback(idx, total_clients, stats)

                    projects = self.api.get_projects(client.id)
                    if limit_projects:
                        projects = projects[:limit_projects]

                    logger.info(f"  Client {client.username}: {len(projects)} projects to process")
                    time.sleep(self.rate_limit)

                    for p_idx, project in enumerate(projects, 1):
                        # Сохраняем проект
                        self.db.insert_project(project.id, project.name, client.id)

                        logger.info(
                            f"  Project {p_idx}/{len(projects)} id={project.id} name={project.name!r}"
                        )
                        page = 1
                        while True:
                            # ← НОВОЕ: Проверка на остановку внутри пагинации
                            if stop_callback and stop_callback():
                                logger.info("Collection stopped during pagination")
                                raise KeyboardInterrupt  # Выходим через exception

                            if max_pages and page > max_pages:
                                logger.info(
                                    f"    Reached max_pages={max_pages} for project_id={project.id}"
                                )
                                break

                            logger.info(
                                f"    Fetching phones: project_id={project.id}, page={page}"
                            )
                            phones = self.api.get_phones(project.id, page)
                            if not phones:
                                logger.info(
                                    f"    No more phones for project_id={project.id}, stop pagination"
                                )
                                break

                            for phone_data in phones:
                                normalized, is_valid = self.normalizer.normalize(phone_data.phone)
                                if not is_valid:
                                    continue

                                existing = self.db.get_phone_by_number(normalized)
                                if not existing:
                                    phone_id = self.db.insert_phone(normalized, phone_data.phone, run_id)
                                    stats['new_phones'] += 1
                                else:
                                    phone_id = existing['id']

                                self.db.insert_project_phone(project.id, phone_id, run_id, phone_data.created_at)
                                stats['total_phones'] += 1

                            page += 1
                            time.sleep(self.rate_limit)

                    # Клиент обработан
                    processed_client_ids.add(client.id)

                    # Сохраняем state каждые 5 клиентов
                    if idx % 5 == 0:
                        self.state_manager.save(
                            run_id=run_id,
                            total_clients=total_clients_original,
                            processed_clients=len(processed_client_ids),
                            processed_client_ids=processed_client_ids,
                            stats=stats
                        )

                except Exception as e:
                    logger.error(f"Error processing client {client.id}: {e}")
                    stats['errors'] += 1

            # Успешное завершение
            self.db.update_run_stats(run_id, stats['total_phones'], stats['new_phones'], 'completed', stats['errors'])
            logger.info(f"Collection completed: {stats}")

            # Очищаем state после успешного завершения
            self.state_manager.clear()

        except KeyboardInterrupt:
            logger.warning("Collection interrupted by user")
            # Сохраняем state перед выходом
            self.state_manager.save(
                run_id=run_id,
                total_clients=total_clients_original,
                processed_clients=len(processed_client_ids),
                processed_client_ids=processed_client_ids,
                stats=stats
            )
            self.db.update_run_stats(run_id, stats['total_phones'], stats['new_phones'], 'stopped', stats['errors'])
            raise
        except Exception as e:
            logger.error(f"Collection failed: {e}")
            self.db.update_run_stats(run_id, stats['total_phones'], stats['new_phones'], 'failed', stats['errors'])
            raise
