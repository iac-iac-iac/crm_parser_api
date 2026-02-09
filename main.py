"""DataMaster Phone Collector - Entry Point"""
import os
import sys
import logging
import argparse
from dotenv import load_dotenv
from src.api.client import DataMasterClient
from src.reports.exporter import CSVExporter
from src.database.manager import DatabaseManager
from src.collector.state_manager import StateManager
from src.collector.orchestrator import CollectionOrchestrator


def setup_logging(log_file: str, log_level: str):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )


def parse_args():
    parser = argparse.ArgumentParser(description="DataMaster Phone Collector")
    parser.add_argument("--limit-clients", type=int, default=None,
                        help="Максимум клиентов для обработки")
    parser.add_argument("--limit-projects", type=int, default=None,
                        help="Максимум проектов на клиента")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Максимум страниц телефонов на проект")
    parser.add_argument("--export", type=str, choices=['all', 'phones', 'runs', 'clients', 'latest'],
                        help="Экспорт данных в CSV (all/phones/runs/clients/latest)")
    parser.add_argument("--continue", dest='resume', action='store_true',
                        help="Продолжить прерванный сбор")
    
    return parser.parse_args()


def main():
    load_dotenv()
    args = parse_args()

    # Конфигурация
    api_url = os.getenv('DATAMASTER_API_URL')
    api_token = os.getenv('DATAMASTER_API_TOKEN')
    db_path = os.getenv('DATABASE_PATH', 'data/phones.db')
    rate_limit = float(os.getenv('RATE_LIMIT_DELAY', '0.5'))
    timeout = int(os.getenv('REQUEST_TIMEOUT', '30'))
    max_retries = int(os.getenv('MAX_RETRIES', '3'))  # ← Новое
    log_file = os.getenv('LOG_FILE', 'logs/collector.log')
    log_level = os.getenv('LOG_LEVEL', 'INFO')

    setup_logging(log_file, log_level)
    logger = logging.getLogger(__name__)

    # Инициализация БД
    db = DatabaseManager(db_path)
    db.connect()

    # Если запрошен экспорт
    if args.export:
        exporter = CSVExporter(db)
        logger.info(f"Starting export: {args.export}")
        
        try:
            if args.export == 'all':
                files = exporter.export_all()
                logger.info(f"✅ Exported all reports:")
                for report_type, filepath in files.items():
                    logger.info(f"  - {report_type}: {filepath}")
            elif args.export == 'phones':
                filepath = exporter.export_all_phones()
                logger.info(f"✅ Exported all phones: {filepath}")
            elif args.export == 'runs':
                filepath = exporter.export_runs_summary()
                logger.info(f"✅ Exported runs summary: {filepath}")
            elif args.export == 'clients':
                filepath = exporter.export_clients_stats()
                logger.info(f"✅ Exported clients stats: {filepath}")
            elif args.export == 'latest':
                filepath = exporter.export_latest_run()
                logger.info(f"✅ Exported latest run: {filepath}")
        except Exception as e:
            logger.error(f"❌ Export failed: {e}")
        finally:
            db.close()
        
        return

    # Обычный сбор данных
    api_client = DataMasterClient(api_url, api_token, timeout, max_retries)  # ← Передаём max_retries
    state_manager = StateManager()
    orchestrator = CollectionOrchestrator(api_client, db, rate_limit, state_manager)

    logger.info(
        f"Starting collection (resume={args.resume}, limit_clients={args.limit_clients}, "
        f"limit_projects={args.limit_projects}, max_pages={args.max_pages})"
    )

    try:
        orchestrator.collect(
            limit_clients=args.limit_clients,
            limit_projects=args.limit_projects,
            max_pages=args.max_pages,
            resume=args.resume,
        )
        logger.info("✅ Collection completed successfully")
    except KeyboardInterrupt:
        logger.warning("Collection stopped by user")
    except Exception as e:
        logger.error(f"❌ Collection failed: {e}")
    finally:
        api_client.close()
        db.close()


if __name__ == '__main__':
    main()
