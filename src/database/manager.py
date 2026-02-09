"""Database Manager"""
import sqlite3
import os
from typing import Optional, Dict
from contextlib import contextmanager


class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection = None

    def connect(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

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
