"""Main GUI Application"""
import customtkinter as ctk
import threading
import logging
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from src.api.client import DataMasterClient
from src.database.manager import DatabaseManager
from src.collector.state_manager import StateManager
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
            try:
                self.text_widget.configure(state='normal')
                self.text_widget.insert('end', msg + '
')
                self.text_widget.see('end')
                self.text_widget.configure(state='disabled')
            except Exception:
                pass
        
        # Используем after для потокобезопасности
        try:
            self.text_widget.after(0, append)
        except Exception:
            pass

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        load_dotenv()
        
        # Конфигурация из .env
        self.api_url = os.getenv('DATAMASTER_API_URL')
        self.api_token = os.getenv('DATAMASTER_API_TOKEN')
        self.db_path = os.getenv('DATABASE_PATH', 'data/phones.db')
        self.rate_limit = float(os.getenv('RATE_LIMIT_DELAY', '0.5'))
        self.timeout = int(os.getenv('REQUESTTIMEOUT', '30'))
        self.max_retries = int(os.getenv('MAXRETRIES', '3'))

        # Состояние
        self.collection_thread = None
        self.is_collecting = False

        # Настройка окна
        self.title("DataMaster Phone Collector")
        self.geometry("950x750")

        self.setup_logging()
        self.create_widgets()

    def setup_logging(self):
        log_file = os.getenv('LOGFILE', 'logs/collector.log')
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # Основной конфиг логов
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )

    def create_widgets(self):
        # Header
        self.header = ctk.CTkLabel(
            self, text="📊 DataMaster Phone Collector", 
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.header.pack(pady=20)

        # Tabview
        self.tabview = ctk.CTkTabview(self, width=900, height=600)
        self.tabview.pack(pady=10, padx=20, fill="both", expand=True)

        self.tab_collection = self.tabview.add("Collection")
        self.tab_export = self.tabview.add("Export")
        self.tab_settings = self.tabview.add("Settings")

        self.create_collection_tab()
        self.create_export_tab()
        self.create_settings_tab()

    def create_collection_tab(self):
        # Settings Frame (Params)
        settings_frame = ctk.CTkFrame(self.tab_collection)
        settings_frame.pack(pady=10, padx=20, fill="x")

        ctk.CTkLabel(settings_frame, text="Limit Clients:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.limit_clients_var = ctk.StringVar(value="1")
        self.limit_clients_entry = ctk.CTkEntry(settings_frame, textvariable=self.limit_clients_var, width=100)
        self.limit_clients_entry.grid(row=0, column=1, padx=10, pady=5)

        ctk.CTkLabel(settings_frame, text="Limit Projects:").grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.limit_projects_var = ctk.StringVar(value="50")
        self.limit_projects_entry = ctk.CTkEntry(settings_frame, textvariable=self.limit_projects_var, width=100)
        self.limit_projects_entry.grid(row=0, column=3, padx=10, pady=5)

        ctk.CTkLabel(settings_frame, text="Max Pages:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.max_pages_var = ctk.StringVar(value="")
        self.max_pages_entry = ctk.CTkEntry(settings_frame, textvariable=self.max_pages_var, width=100)
        self.max_pages_entry.grid(row=1, column=1, padx=10, pady=5)

        # Buttons
        buttons_frame = ctk.CTkFrame(self.tab_collection)
        buttons_frame.pack(pady=10, padx=20, fill="x")

        self.btn_start = ctk.CTkButton(
            buttons_frame, text="▶ Start Collection", 
            command=self.start_collection, 
            fg_color="green", hover_color="darkgreen"
        )
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ctk.CTkButton(
            buttons_frame, text="⏹ Stop", 
            command=self.stop_collection,
            fg_color="red", hover_color="darkred",
            state="disabled"
        )
        self.btn_stop.pack(side="left", padx=5)

        self.btn_continue = ctk.CTkButton(
            buttons_frame, text="⏩ Continue", 
            command=self.continue_collection,
            fg_color="orange", hover_color="darkorange"
        )
        self.btn_continue.pack(side="left", padx=5)

        # Progress
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
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.stats_label.pack(pady=5)

        # Logs
        logs_frame = ctk.CTkFrame(self.tab_collection)
        logs_frame.pack(pady=10, padx=20, fill="both", expand=True)

        ctk.CTkLabel(logs_frame, text="Logs:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=5, pady=5)
        self.log_text = ctk.CTkTextbox(logs_frame, height=200, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Add logging handler for GUI
        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logging.getLogger().addHandler(text_handler)

    def create_export_tab(self):
        export_frame = ctk.CTkFrame(self.tab_export)
        export_frame.pack(pady=20, padx=20, fill="both", expand=True)

        ctk.CTkLabel(
            export_frame, text="Export Data to CSV", 
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=20)

        # Buttons
        ctk.CTkButton(
            export_frame, text="📂 Export All Phones", 
            command=self.export_data_phones, width=300, height=40
        ).pack(pady=10)

        self.export_status = ctk.CTkLabel(export_frame, text="", font=ctk.CTkFont(size=11))
        self.export_status.pack(pady=20)

    def create_settings_tab(self):
        settings_frame = ctk.CTkFrame(self.tab_settings)
        settings_frame.pack(pady=20, padx=20, fill="both", expand=True)

        ctk.CTkLabel(
            settings_frame, text="Settings", 
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=20)

        # Rate Limit
        rate_frame = ctk.CTkFrame(settings_frame)
        rate_frame.pack(pady=10, fill="x", padx=20)
        ctk.CTkLabel(rate_frame, text="Rate Limit Delay (seconds):").pack(side="left", padx=10)
        self.rate_limit_var = ctk.StringVar(value=str(self.rate_limit))
        ctk.CTkEntry(rate_frame, textvariable=self.rate_limit_var, width=100).pack(side="left", padx=10)

        # Paths Info
        db_frame = ctk.CTkFrame(settings_frame)
        db_frame.pack(pady=10, fill="x", padx=20)
        ctk.CTkLabel(db_frame, text=f"Database: {self.db_path}").pack(anchor="w", padx=10, pady=5)
        ctk.CTkLabel(db_frame, text=f"API URL: {self.api_url}").pack(anchor="w", padx=10, pady=5)

    def start_collection(self):
        if self.is_collecting:
            return
        
        self.is_collecting = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_continue.configure(state="disabled")
        
        # Get params
        limit_clients = self.parse_int(self.limit_clients_var.get())
        limit_projects = self.parse_int(self.limit_projects_var.get())
        max_pages = self.parse_int(self.max_pages_var.get())

        self.collection_thread = threading.Thread(
            target=self.run_collection, 
            args=(limit_clients, limit_projects, max_pages, False),
            daemon=True
        )
        self.collection_thread.start()

    def continue_collection(self):
        if self.is_collecting:
            return
            
        self.is_collecting = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_continue.configure(state="disabled")

        self.collection_thread = threading.Thread(
            target=self.run_collection, 
            args=(None, None, None, True),
            daemon=True
        )
        self.collection_thread.start()

    def stop_collection(self):
        self.is_collecting = False
        self.btn_stop.configure(state="disabled")
        self.progress_label.configure(text="Stopping... please wait")
        logging.info("STOP: User requested termination")

    def progress_callback(self, current, total, stats):
        """Callback to update UI progress"""
        def update():
            # Прогресс бар
            if total > 0:
                # Если обрабатываем только 1 клиента, прогресс бар должен быть плавным
                # Но пока сделаем просто по клиентам
                val = current / total
                self.progress_bar.set(val)
                self.progress_label.configure(text=f"Client {current} of {total}")
            
            # Статистика
            self.stats_label.configure(
                text=f"Total: {stats.get('total_phones', 0)} | New: {stats.get('new_phones', 0)} | Errors: {stats.get('errors', 0)}"
            )
        
        try:
            self.after(0, update)
        except Exception:
            pass

    def run_collection(self, limit_clients, limit_projects, max_pages, resume):
        api_client = None
        db = None
        try:
            # Init API and DB
            api_client = DataMasterClient(self.api_url, self.api_token, self.timeout, self.max_retries)
            db = DatabaseManager(self.db_path)
            db.connect()
            state_manager = StateManager()

            orchestrator = CollectionOrchestrator(
                api_client, db, self.rate_limit, state_manager
            )

            # Передаем callback для прогресса
            result = orchestrator.collect(
                limit_clients=limit_clients,
                limit_projects=limit_projects,
                max_pages=max_pages,
                resume=resume,
                progress_callback=self.progress_callback,
                stop_callback=lambda: not self.is_collecting
            )

            if result == "stopped":
                msg = "🛑 Collection stopped and progress saved"
            else:
                msg = "✅ Collection successfully completed"
            
            self.after(0, lambda: self.collection_complete(True, msg))

        except Exception as e:
            logging.error(f"FATAL: {e}")
            self.after(0, lambda: self.collection_complete(False, f"❌ Error: {e}"))
        finally:
            if api_client: api_client.close()
            if db: db.close()
            self.is_collecting = False

    def collection_complete(self, success, message):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_continue.configure(state="normal")
        self.progress_label.configure(text=message)
        if success:
            self.progress_bar.set(1.0)
        
    def export_data_phones(self):
        def do_export():
            db = None
            try:
                self.after(0, lambda: self.export_status.configure(text="Exporting..."))
                db = DatabaseManager(self.db_path)
                db.connect()
                exporter = CSVExporter(db)
                
                filepath = exporter.export_all_phones()
                msg = f"✅ Exported: {os.path.basename(filepath)}"
                
                self.after(0, lambda: self.export_status.configure(text=msg))
                logging.info(msg)
            except Exception as e:
                err_msg = f"❌ Export failed: {e}"
                self.after(0, lambda: self.export_status.configure(text=err_msg))
                logging.error(err_msg)
            finally:
                if db: db.close()

        threading.Thread(target=do_export, daemon=True).start()

    def parse_int(self, value):
        try:
            return int(value) if value and str(value).strip() else None
        except ValueError:
            return None

if __name__ == "__main__":
    app = App()
    app.mainloop()
