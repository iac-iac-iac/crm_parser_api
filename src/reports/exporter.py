"""CSV Exporter for phone data"""
import csv
import os
from datetime import datetime
from typing import List, Dict
from src.database.manager import DatabaseManager


class CSVExporter:
    def __init__(self, db: DatabaseManager, export_dir: str = "data/exports"):
        self.db = db
        self.export_dir = export_dir
        os.makedirs(export_dir, exist_ok=True)

    def export_all_phones(self) -> str:
        """Экспорт всех уникальных телефонов"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.export_dir, f"phones_all_{timestamp}.csv")

        with self.db.get_cursor() as cursor:
            cursor.execute("""
                SELECT phone, first_seen_at, original_format, first_run_id
                FROM phones
                ORDER BY first_seen_at DESC
            """)
            rows = cursor.fetchall()

        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['phone', 'first_seen_at', 'original_format', 'first_run_id'])
            writer.writerows(rows)

        return filename

    def export_runs_summary(self) -> str:
        """Экспорт статистики по всем запускам"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.export_dir, f"runs_summary_{timestamp}.csv")

        with self.db.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    id,
                    started_at,
                    completed_at,
                    status,
                    total_phones,
                    new_phones,
                    errors_count
                FROM runs
                ORDER BY started_at DESC
            """)
            rows = cursor.fetchall()

        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                'run_id', 'started_at', 'completed_at', 'status',
                'total_phones', 'new_phones', 'errors_count'
            ])
            writer.writerows(rows)

        return filename

    def export_clients_stats(self) -> str:
        """Экспорт статистики по клиентам (топ по количеству номеров)"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.export_dir, f"clients_stats_{timestamp}.csv")

        with self.db.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    c.id,
                    c.username,
                    COUNT(DISTINCT p.id) as total_projects,
                    COUNT(DISTINCT pp.phone_id) as total_phones
                FROM clients c
                LEFT JOIN projects p ON c.id = p.client_id
                LEFT JOIN project_phones pp ON p.id = pp.project_id
                GROUP BY c.id, c.username
                HAVING total_phones > 0
                ORDER BY total_phones DESC
            """)
            rows = cursor.fetchall()

        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['client_id', 'username', 'total_projects', 'total_phones'])
            writer.writerows(rows)

        return filename

    def export_latest_run(self, run_id: int = None) -> str:
        """Экспорт телефонов конкретного запуска"""
        if run_id is None:
            with self.db.get_cursor() as cursor:
                cursor.execute("SELECT MAX(id) FROM runs")
                run_id = cursor.fetchone()[0]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.export_dir, f"phones_run_{run_id}_{timestamp}.csv")

        with self.db.get_cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT
                    p.phone,
                    p.first_seen_at,
                    pr.name as project_name,
                    c.username as client_name
                FROM phones p
                JOIN project_phones pp ON p.id = pp.phone_id
                JOIN projects pr ON pp.project_id = pr.id
                JOIN clients c ON pr.client_id = c.id
                WHERE pp.run_id = ?
                ORDER BY p.first_seen_at DESC
            """, (run_id,))
            rows = cursor.fetchall()

        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['phone', 'first_seen_at', 'project_name', 'client_name'])
            writer.writerows(rows)

        return filename

    def export_all(self) -> Dict[str, str]:
        """Экспорт всех отчётов разом"""
        return {
            'all_phones': self.export_all_phones(),
            'runs_summary': self.export_runs_summary(),
            'clients_stats': self.export_clients_stats(),
            'latest_run': self.export_latest_run(),
        }
