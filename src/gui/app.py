"""Main GUI Application"""
import customtkinter as ctk
import threading
import logging
import os
from datetime import datetime
from dotenv import load_dotenv
from src.api.client import DataMasterClient
from src.database.manager import DatabaseManager
from src.collector.state_manager import StateManager  # ← ИСПРАВЛЕНО: state_manager
from src.collector.orchestrator import CollectionOrchestrator
from src.reports.exporter import CSVExporter


# Настройка темы
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class TextHandler(logging.Handler):
    """Handler для вывода логов в текстовый виджет"""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state='normal')
            self.text_widget.insert('end', msg + '\n')
            self.text_widget.see('end')
            self.text_widget.configure(state='disabled')
        
        self.text_widget.after(0, append)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Загрузка конфигурации
        load_dotenv()
        self.api_url = os.getenv('DATAMASTER_API_URL')
        self.api_token = os.getenv('DATAMASTER_API_TOKEN')
        self.db_path = os.getenv('DATABASE_PATH', 'data/phones.db')
        self.rate_limit = float(os.getenv('RATE_LIMIT_DELAY', '0.5'))
        self.timeout = int(os.getenv('REQUEST_TIMEOUT', '30'))
        self.max_retries = int(os.getenv('MAX_RETRIES', '3'))

        # Состояние
        self.collection_thread = None
        self.is_collecting = False

        # Настройка окна
        self.title("DataMaster Phone Collector")
        self.geometry("900x700")
        
        # Настройка логирования
        self.setup_logging()

        # Создание UI
        self.create_widgets()

    def setup_logging(self):
        """Настройка логирования"""
        log_file = os.getenv('LOG_FILE', 'logs/collector.log')
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8')
            ]
        )

    def create_widgets(self):
        """Создание виджетов интерфейса"""
        # Заголовок
        self.header = ctk.CTkLabel(
            self, 
            text="📱 DataMaster Phone Collector",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.header.pack(pady=20)

        # Табы
        self.tabview = ctk.CTkTabview(self, width=850, height=550)
        self.tabview.pack(pady=10, padx=20)

        # Создаём вкладки
        self.tab_collection = self.tabview.add("Collection")
        self.tab_export = self.tabview.add("Export")
        self.tab_settings = self.tabview.add("Settings")

        # Заполнение вкладок
        self.create_collection_tab()
        self.create_export_tab()
        self.create_settings_tab()

    def create_collection_tab(self):
        """Вкладка сбора данных"""
        # Фрейм настроек
        settings_frame = ctk.CTkFrame(self.tab_collection)
        settings_frame.pack(pady=10, padx=20, fill="x")

        # Лимиты
        ctk.CTkLabel(settings_frame, text="Limit Clients:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.limit_clients_var = ctk.StringVar(value="")
        self.limit_clients_entry = ctk.CTkEntry(settings_frame, textvariable=self.limit_clients_var, width=100)
        self.limit_clients_entry.grid(row=0, column=1, padx=10, pady=5)

        ctk.CTkLabel(settings_frame, text="Limit Projects:").grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.limit_projects_var = ctk.StringVar(value="")
        self.limit_projects_entry = ctk.CTkEntry(settings_frame, textvariable=self.limit_projects_var, width=100)
        self.limit_projects_entry.grid(row=0, column=3, padx=10, pady=5)

        ctk.CTkLabel(settings_frame, text="Max Pages:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.max_pages_var = ctk.StringVar(value="")
        self.max_pages_entry = ctk.CTkEntry(settings_frame, textvariable=self.max_pages_var, width=100)
        self.max_pages_entry.grid(row=1, column=1, padx=10, pady=5)

        # Кнопки управления
        buttons_frame = ctk.CTkFrame(self.tab_collection)
        buttons_frame.pack(pady=10, padx=20, fill="x")

        self.btn_start = ctk.CTkButton(
            buttons_frame, 
            text="▶ Start Collection",
            command=self.start_collection,
            fg_color="green",
            hover_color="darkgreen"
        )
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ctk.CTkButton(
            buttons_frame,
            text="⏹ Stop",
            command=self.stop_collection,
            fg_color="red",
            hover_color="darkred",
            state="disabled"
        )
        self.btn_stop.pack(side="left", padx=5)

        self.btn_continue = ctk.CTkButton(
            buttons_frame,
            text="▶▶ Continue",
            command=self.continue_collection,
            fg_color="orange",
            hover_color="darkorange"
        )
        self.btn_continue.pack(side="left", padx=5)

        # Прогресс
        progress_frame = ctk.CTkFrame(self.tab_collection)
        progress_frame.pack(pady=10, padx=20, fill="x")

        self.progress_label = ctk.CTkLabel(progress_frame, text="Ready to start", font=ctk.CTkFont(size=12))
        self.progress_label.pack(pady=5)

        self.progress_bar = ctk.CTkProgressBar(progress_frame, width=800)
        self.progress_bar.pack(pady=5)
        self.progress_bar.set(0)

        self.stats_label = ctk.CTkLabel(
            progress_frame, 
            text="Total: 0 | New: 0 | Errors: 0",
            font=ctk.CTkFont(size=11)
        )
        self.stats_label.pack(pady=5)

        # Логи
        logs_frame = ctk.CTkFrame(self.tab_collection)
        logs_frame.pack(pady=10, padx=20, fill="both", expand=True)

        ctk.CTkLabel(logs_frame, text="Logs:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=5, pady=5)

        self.log_text = ctk.CTkTextbox(logs_frame, height=200, state='disabled')
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Добавляем handler для логов
        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(text_handler)

    def create_export_tab(self):
        """Вкладка экспорта"""
        export_frame = ctk.CTkFrame(self.tab_export)
        export_frame.pack(pady=20, padx=20, fill="both", expand=True)

        ctk.CTkLabel(
            export_frame, 
            text="Export Data to CSV",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=20)

        # Кнопки экспорта
        ctk.CTkButton(
            export_frame,
            text="📊 Export All Reports",
            command=lambda: self.export_data('all'),
            width=300,
            height=40
        ).pack(pady=10)

        ctk.CTkButton(
            export_frame,
            text="📱 Export All Phones",
            command=lambda: self.export_data('phones'),
            width=300,
            height=40
        ).pack(pady=10)

        ctk.CTkButton(
            export_frame,
            text="📈 Export Runs Summary",
            command=lambda: self.export_data('runs'),
            width=300,
            height=40
        ).pack(pady=10)

        ctk.CTkButton(
            export_frame,
            text="👥 Export Clients Stats",
            command=lambda: self.export_data('clients'),
            width=300,
            height=40
        ).pack(pady=10)

        ctk.CTkButton(
            export_frame,
            text="🕒 Export Latest Run",
            command=lambda: self.export_data('latest'),
            width=300,
            height=40
        ).pack(pady=10)

        self.export_status = ctk.CTkLabel(export_frame, text="", font=ctk.CTkFont(size=11))
        self.export_status.pack(pady=20)

    def create_settings_tab(self):
        """Вкладка настроек"""
        settings_frame = ctk.CTkFrame(self.tab_settings)
        settings_frame.pack(pady=20, padx=20, fill="both", expand=True)

        ctk.CTkLabel(
            settings_frame,
            text="Settings",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=20)

        # Rate Limit
        rate_frame = ctk.CTkFrame(settings_frame)
        rate_frame.pack(pady=10, fill="x", padx=20)

        ctk.CTkLabel(rate_frame, text="Rate Limit Delay (seconds):").pack(side="left", padx=10)
        self.rate_limit_var = ctk.StringVar(value=str(self.rate_limit))
        ctk.CTkEntry(rate_frame, textvariable=self.rate_limit_var, width=100).pack(side="left", padx=10)

        # Database info
        db_frame = ctk.CTkFrame(settings_frame)
        db_frame.pack(pady=10, fill="x", padx=20)

        ctk.CTkLabel(db_frame, text=f"Database: {self.db_path}").pack(anchor="w", padx=10, pady=5)
        ctk.CTkLabel(db_frame, text=f"API URL: {self.api_url}").pack(anchor="w", padx=10, pady=5)

    def start_collection(self):
        """Запуск сбора данных"""
        if self.is_collecting:
            return

        self.is_collecting = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_continue.configure(state="disabled")
        self.progress_label.configure(text="Collection in progress...")
        
        # Получение параметров
        limit_clients = self._parse_int(self.limit_clients_var.get())
        limit_projects = self._parse_int(self.limit_projects_var.get())
        max_pages = self._parse_int(self.max_pages_var.get())

        # Запуск в отдельном потоке
        self.collection_thread = threading.Thread(
            target=self._run_collection,
            args=(limit_clients, limit_projects, max_pages, False),
            daemon=True
        )
        self.collection_thread.start()

    def continue_collection(self):
        """Продолжение прерванного сбора"""
        if self.is_collecting:
            return

        self.is_collecting = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_continue.configure(state="disabled")
        self.progress_label.configure(text="Resuming collection...")

        # Запуск в отдельном потоке
        self.collection_thread = threading.Thread(
            target=self._run_collection,
            args=(None, None, None, True),
            daemon=True
        )
        self.collection_thread.start()

    def stop_collection(self):
        """Остановка сбора"""
        self.is_collecting = False  # ← Этот флаг будет проверяться в orchestrator
        self.btn_stop.configure(state="disabled")
        self.progress_label.configure(text="Stopping...")
        logging.info("Stop requested by user")

    def _should_stop(self):
        """Callback для проверки остановки"""
        return not self.is_collecting

    def _update_progress(self, current, total, stats):
        """Callback для обновления прогресса"""
        def update_ui():
            # Обновление прогресс-бара
            progress = current / total if total > 0 else 0
            self.progress_bar.set(progress)
            
            # Обновление статистики
            self.stats_label.configure(
                text=f"Total: {stats['total_phones']} | New: {stats['new_phones']} | Errors: {stats['errors']}"
            )
            
            # Обновление текста прогресса
            self.progress_label.configure(
                text=f"Processing client {current}/{total}..."
            )
        
        self.after(0, update_ui)

    def _run_collection(self, limit_clients, limit_projects, max_pages, resume):
        """Выполнение сбора в фоновом потоке"""
        try:
            # Инициализация
            api_client = DataMasterClient(self.api_url, self.api_token, self.timeout, self.max_retries)
            db = DatabaseManager(self.db_path)
            db.connect()
            state_manager = StateManager()
            
            # Создание orchestrator
            orchestrator = CollectionOrchestrator(api_client, db, self.rate_limit, state_manager)

            # Запуск сбора с callback'ами
            orchestrator.collect(
                limit_clients=limit_clients,
                limit_projects=limit_projects,
                max_pages=max_pages,
                resume=resume,
                stop_callback=self._should_stop,  # ← НОВОЕ
                progress_callback=self._update_progress  # ← НОВОЕ
            )

            # Завершение
            self._collection_complete(success=True)

        except KeyboardInterrupt:
            logging.warning("Collection stopped by user")
            self._collection_complete(success=False, message="Stopped by user")
        except Exception as e:
            logging.error(f"Collection failed: {e}")
            self._collection_complete(success=False, message=f"Error: {e}")
        finally:
            api_client.close()
            db.close()
            self.is_collecting = False

    def _run_collection(self, limit_clients, limit_projects, max_pages, resume):
        """Выполнение сбора в фоновом потоке"""
        try:
            # Инициализация
            api_client = DataMasterClient(self.api_url, self.api_token, self.timeout, self.max_retries)
            db = DatabaseManager(self.db_path)
            db.connect()
            state_manager = StateManager()
            
            # Создание orchestrator
            orchestrator = CollectionOrchestrator(api_client, db, self.rate_limit, state_manager)

            # Запуск сбора
            orchestrator.collect(
                limit_clients=limit_clients,
                limit_projects=limit_projects,
                max_pages=max_pages,
                resume=resume
            )

            # Завершение
            self._collection_complete(success=True)

        except KeyboardInterrupt:
            logging.warning("Collection stopped by user")
            self._collection_complete(success=False, message="Stopped by user")
        except Exception as e:
            logging.error(f"Collection failed: {e}")
            self._collection_complete(success=False, message=f"Error: {e}")
        finally:
            api_client.close()
            db.close()
            self.is_collecting = False

    def _collection_complete(self, success, message="Collection completed"):
        """Вызывается после завершения сбора"""
        def update_ui():
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.btn_continue.configure(state="normal")
            
            if success:
                self.progress_label.configure(text="✅ " + message)
                self.progress_bar.set(1.0)
            else:
                self.progress_label.configure(text="❌ " + message)
        
        self.after(0, update_ui)

    def export_data(self, export_type):
        """Экспорт данных в CSV"""
        def do_export():
            try:
                self.export_status.configure(text="Exporting...")
                
                db = DatabaseManager(self.db_path)
                db.connect()
                exporter = CSVExporter(db)

                if export_type == 'all':
                    files = exporter.export_all()
                    message = f"✅ Exported {len(files)} reports to data/exports/"
                elif export_type == 'phones':
                    filepath = exporter.export_all_phones()
                    message = f"✅ Exported: {os.path.basename(filepath)}"
                elif export_type == 'runs':
                    filepath = exporter.export_runs_summary()
                    message = f"✅ Exported: {os.path.basename(filepath)}"
                elif export_type == 'clients':
                    filepath = exporter.export_clients_stats()
                    message = f"✅ Exported: {os.path.basename(filepath)}"
                elif export_type == 'latest':
                    filepath = exporter.export_latest_run()
                    message = f"✅ Exported: {os.path.basename(filepath)}"
                
                db.close()
                
                def update_status():
                    self.export_status.configure(text=message)
                    logging.info(message)
                
                self.after(0, update_status)

            except Exception as e:
                error_msg = f"❌ Export failed: {e}"
                logging.error(error_msg)
                
                def update_status():
                    self.export_status.configure(text=error_msg)
                
                self.after(0, update_status)

        # Запуск в отдельном потоке
        threading.Thread(target=do_export, daemon=True).start()

    def _parse_int(self, value):
        """Парсинг целого числа из строки"""
        try:
            return int(value) if value.strip() else None
        except ValueError:
            return None


def run_gui():
    """Запуск GUI приложения"""
    app = App()
    app.mainloop()


if __name__ == '__main__':
    run_gui()