"""Database Manager"""
import sqlite3
import logging
import os
from typing import Optional, Dict
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection = None

    def connect(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        
        # Оптимизация SQLite для параллельной работы
        self.connection.execute("PRAGMA journal_mode=WAL")          # Write-Ahead Logging
        self.connection.execute("PRAGMA synchronous=NORMAL")        # Баланс скорости и безопасности
        self.connection.execute("PRAGMA cache_size=-64000")         # 64MB кэш в памяти
        self.connection.execute("PRAGMA temp_store=MEMORY")         # Временные таблицы в RAM
        self.connection.execute("PRAGMA mmap_size=268435456")       # 256MB memory-mapped I/O
        
        self._create_schema()
        logger.info("Database connected with WAL mode enabled")

    def close(self):
        if self.connection:
            self.connection.close()

    @contextmanager
    def get_cursor(self):
        cursor = self.connection.cursor()
        try:
            yield cursor
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _create_schema(self):
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        with open(schema_path, 'r', encoding='utf-8') as f:
            self.connection.executescript(f.read())

    def create_run(self) -> int:
        with self.get_cursor() as cursor:
            cursor.execute("INSERT INTO runs (status) VALUES ('running')")
            return cursor.lastrowid

    def get_phone_by_number(self, phone: str) -> Optional[Dict]:
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM phones WHERE phone = ?", (phone,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def insert_phone(self, phone: str, original: str, run_id: int) -> int:
        with self.get_cursor() as cursor:
            cursor.execute(
                "INSERT INTO phones (phone, original_format, first_run_id) VALUES (?, ?, ?)",
                (phone, original, run_id)
            )
            return cursor.lastrowid

    def insert_client(self, client_id: int, username: str):
        with self.get_cursor() as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO clients (id, username) VALUES (?, ?)",
                (client_id, username)
            )

    def insert_project(self, project_id: int, name: str, client_id: int):
        with self.get_cursor() as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO projects (id, name, client_id) VALUES (?, ?, ?)",
                (project_id, name, client_id)
            )

    def insert_project_phone(self, project_id: int, phone_id: int, run_id: int, created_at: str):
        with self.get_cursor() as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO project_phones (project_id, phone_id, run_id, created_at_api) VALUES (?, ?, ?, ?)",
                (project_id, phone_id, run_id, created_at)
            )

    def update_run_stats(self, run_id: int, total_phones: int, new_phones: int, status: str = 'completed', errors_count: int = 0):
        with self.get_cursor() as cursor:
            cursor.execute(
                """UPDATE runs SET total_phones = ?, new_phones = ?, errors_count = ?,
                   status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (total_phones, new_phones, errors_count, status, run_id)
            )
    
    def get_total_stats(self) -> dict:
        """Получение общей статистики из БД."""
        if not self.connection:
            raise Exception("Database not connected. Call connect() first.")
        
        cursor = self.connection.cursor()
        
        # Общее количество записей
        total_clients = cursor.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        total_projects = cursor.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        total_phones = cursor.execute("SELECT COUNT(*) FROM phones").fetchone()[0]
        total_unique_phones = cursor.execute("SELECT COUNT(DISTINCT phone) FROM phones").fetchone()[0]
        
        # Последний запуск (ИСПРАВЛЕНЫ ИМЕНА КОЛОНОК)
        last_run = cursor.execute("""
            SELECT id, started_at, completed_at, status, total_phones, new_phones, errors_count
            FROM runs
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()
        
        return {
            'total_clients': total_clients,
            'total_projects': total_projects,
            'total_phones': total_phones,
            'total_unique_phones': total_unique_phones,
            'last_run': dict(last_run) if last_run else None
        }



    def get_runs_history(self, limit: int = 10) -> list:
        """Получение истории запусков."""
        if not self.connection:
            raise Exception("Database not connected. Call connect() first.")
        
        cursor = self.connection.cursor()
        
        rows = cursor.execute("""
            SELECT id, started_at, completed_at, status, total_phones, new_phones, errors_count
            FROM runs
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        
        return [dict(row) for row in rows]


    def get_recent_errors(self, limit: int = 10) -> list:
        """Получение последних ошибок (из логов runs с errors > 0)."""
        if not self.connection:
            raise Exception("Database not connected. Call connect() first.")
        
        cursor = self.connection.cursor()
        
        rows = cursor.execute("""
            SELECT id, started_at, status, errors_count
            FROM runs
            WHERE errors_count > 0
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        
        return [dict(row) for row in rows]


    def get_collection_speed_stats(self) -> dict:
        """Статистика скорости сбора."""
        if not self.connection:
            raise Exception("Database not connected. Call connect() first.")
        
        cursor = self.connection.cursor()
        
        # Последние 5 завершённых запусков (ИСПРАВЛЕНЫ ИМЕНА КОЛОНОК)
        rows = cursor.execute("""
            SELECT 
                id,
                started_at,
                completed_at,
                total_phones,
                new_phones,
                julianday(completed_at) - julianday(started_at) as duration_days
            FROM runs
            WHERE status = 'completed' AND completed_at IS NOT NULL
            ORDER BY id DESC
            LIMIT 5
        """).fetchall()
        
        if not rows:
            return {
                'avg_duration_minutes': 0,
                'avg_phones_per_run': 0,
                'avg_speed_phones_per_minute': 0,
                'runs_analyzed': 0
            }
        
        total_duration = sum(row['duration_days'] for row in rows)
        total_phones = sum(row['total_phones'] for row in rows)
        avg_duration_minutes = (total_duration * 24 * 60) / len(rows)
        avg_phones = total_phones / len(rows)
        avg_speed = (total_phones / (total_duration * 24 * 60)) if total_duration > 0 else 0
        
        return {
            'avg_duration_minutes': round(avg_duration_minutes, 2),
            'avg_phones_per_run': round(avg_phones),
            'avg_speed_phones_per_minute': round(avg_speed, 2),
            'runs_analyzed': len(rows)
        }
