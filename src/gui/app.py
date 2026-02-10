"""Main GUI Application"""
import customtkinter as ctk
import threading
import logging
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from src.api.client import DataMasterClient
from src.reports.exporter import CSVExporter
from src.database.manager import DatabaseManager
from src.collector.state_manager import StateManager
from src.notifications.telegram_bot import TelegramNotifier
from src.collector.orchestrator import CollectionOrchestrator
from src.collector.parallel_orchestrator import ParallelOrchestrator  

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
                
                # Принудительно добавляем перенос строки
                if not msg.endswith('\n'):
                    full_msg = msg + '\n'
                else:
                    full_msg = msg
                
                # Вставляем текст
                self.text_widget.insert('end', full_msg)
                
                # Автопрокрутка вниз
                self.text_widget.see('end')
                
                # Блокируем редактирование
                self.text_widget.configure(state='disabled')
            except Exception as e:
                # Игнорируем ошибки (например, если виджет уже уничтожен)
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
        
        # Telegram настройки
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.telegram_enabled = os.getenv('TELEGRAM_ENABLED', 'false').lower() == 'true'
        
        # Параллелизация
        self.parallel_enabled = os.getenv('PARALLEL_ENABLED', 'true').lower() == 'true'
        self.workers_count = int(os.getenv('WORKERS_COUNT', '5'))

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

        self.tab_dashboard = self.tabview.add("Dashboard")
        self.tab_collection = self.tabview.add("Collection")
        self.tab_export = self.tabview.add("Export")
        self.tab_settings = self.tabview.add("Settings")

        self.create_dashboard_tab()
        self.create_collection_tab()
        self.create_export_tab()
        self.create_settings_tab()
    
    def create_dashboard_tab(self):
        """Создание вкладки Dashboard."""
        # Main container
        dashboard_frame = ctk.CTkScrollableFrame(self.tab_dashboard, width=850, height=550)
        dashboard_frame.pack(pady=10, padx=10, fill="both", expand=True)
        
        # Header
        header = ctk.CTkLabel(
            dashboard_frame,
            text="📊 Collection Dashboard",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        header.pack(pady=10)
        
        # === ОБЩАЯ СТАТИСТИКА ===
        stats_section = ctk.CTkFrame(dashboard_frame)
        stats_section.pack(pady=10, padx=10, fill="x")
        
        ctk.CTkLabel(
            stats_section,
            text="Overall Statistics",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=5)
        
        # Контейнер для метрик (4 колонки)
        metrics_frame = ctk.CTkFrame(stats_section)
        metrics_frame.pack(pady=10, padx=10, fill="x")
        
        # Метрики
        self.metric_clients = self._create_metric_card(metrics_frame, "👥 Clients", "0", 0)
        self.metric_projects = self._create_metric_card(metrics_frame, "📁 Projects", "0", 1)
        self.metric_phones = self._create_metric_card(metrics_frame, "📞 Total Phones", "0", 2)
        self.metric_unique = self._create_metric_card(metrics_frame, "✨ Unique", "0", 3)
        
        # === ПОСЛЕДНИЙ ЗАПУСК ===
        last_run_section = ctk.CTkFrame(dashboard_frame)
        last_run_section.pack(pady=10, padx=10, fill="x")
        
        ctk.CTkLabel(
            last_run_section,
            text="Last Run",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=5)
        
        self.last_run_info = ctk.CTkLabel(
            last_run_section,
            text="No runs yet",
            font=ctk.CTkFont(size=12),
            justify="left"
        )
        self.last_run_info.pack(pady=10, padx=20, anchor="w")
        
        # === ПРОИЗВОДИТЕЛЬНОСТЬ ===
        performance_section = ctk.CTkFrame(dashboard_frame)
        performance_section.pack(pady=10, padx=10, fill="x")
        
        ctk.CTkLabel(
            performance_section,
            text="Performance Stats (Last 5 Runs)",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=5)
        
        self.performance_info = ctk.CTkLabel(
            performance_section,
            text="No completed runs yet",
            font=ctk.CTkFont(size=12),
            justify="left"
        )
        self.performance_info.pack(pady=10, padx=20, anchor="w")

        # === ГРАФИК ДИНАМИКИ ===
        graph_section = ctk.CTkFrame(dashboard_frame)
        graph_section.pack(pady=10, padx=10, fill="x")

        ctk.CTkLabel(
            graph_section,
            text="Collection Trend (Last 10 Runs)",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=5)

        # Canvas для графика
        self.graph_canvas = ctk.CTkCanvas(
            graph_section,
            width=800,
            height=200,
            bg="#2b2b2b",
            highlightthickness=0
        )
        self.graph_canvas.pack(pady=10, padx=10)

        # === ИСТОРИЯ ЗАПУСКОВ (оставь как было) ===
        history_section = ctk.CTkFrame(dashboard_frame)
                
        # === ИСТОРИЯ ЗАПУСКОВ ===
        history_section = ctk.CTkFrame(dashboard_frame)
        history_section.pack(pady=10, padx=10, fill="both", expand=True)
        
        ctk.CTkLabel(
            history_section,
            text="Recent Runs History",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=5)
        
        # Таблица истории
        self.history_text = ctk.CTkTextbox(history_section, height=150, state="disabled")
        self.history_text.pack(pady=10, padx=10, fill="both", expand=True)
        
        # Кнопка обновления
        refresh_btn = ctk.CTkButton(
            dashboard_frame,
            text="🔄 Refresh Dashboard",
            command=self.refresh_dashboard,
            fg_color="blue",
            hover_color="darkblue",
            width=200
        )
        refresh_btn.pack(pady=20)
        
        # Автозагрузка при открытии
        self.refresh_dashboard()
    
    def _create_metric_card(self, parent, label: str, value: str, column: int):
        """Создание карточки метрики."""
        card = ctk.CTkFrame(parent, width=180, height=80)
        card.grid(row=0, column=column, padx=10, pady=10)
        
        ctk.CTkLabel(
            card,
            text=label,
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(pady=(10, 0))
        
        value_label = ctk.CTkLabel(
            card,
            text=value,
            font=ctk.CTkFont(size=24, weight="bold")
        )
        value_label.pack(pady=(0, 10))
        
        return value_label

    def refresh_dashboard(self):
        """Обновление данных Dashboard."""
        def do_refresh():
            db = None
            try:
                logging.info("Starting dashboard refresh...")
                db = DatabaseManager(self.db_path)
                logging.info(f"DatabaseManager created, db_path={self.db_path}")

                db.connect()
                logging.info("Database connected successfully")
                
                # Общая статистика
                logging.info("Fetching total stats...")
                stats = db.get_total_stats()
                logging.info(f"Total stats: {stats}")
                
                self.after(0, lambda: self.metric_clients.configure(text=f"{stats['total_clients']:,}"))
                self.after(0, lambda: self.metric_projects.configure(text=f"{stats['total_projects']:,}"))
                self.after(0, lambda: self.metric_phones.configure(text=f"{stats['total_phones']:,}"))
                self.after(0, lambda: self.metric_unique.configure(text=f"{stats['total_unique_phones']:,}"))
                
                # Последний запуск
                if stats['last_run']:
                    lr = stats['last_run']
                    duration = "N/A"
                    if lr.get('completed_at'):  # ← Используй .get() для безопасности
                        from datetime import datetime
                        try:
                            start = datetime.fromisoformat(lr['started_at'])
                            end = datetime.fromisoformat(lr['completed_at'])
                            duration = f"{(end - start).total_seconds() / 60:.1f} min"
                        except Exception as e:
                            logging.error(f"Error calculating duration: {e}")
                            duration = "N/A"
                    
                    last_run_text = (
                        f"Run #{lr['id']} | Status: {lr['status']}\n"
                        f"Start: {lr['started_at']}\n"
                        f"Duration: {duration}\n"
                        f"Phones: {lr['total_phones']} (New: {lr['new_phones']}) | Errors: {lr.get('errors_count', 0)}"
                    )
                else:
                    last_run_text = "No runs yet"

                self.after(0, lambda: self.last_run_info.configure(text=last_run_text))
                
                # Производительность
                perf = db.get_collection_speed_stats()
                if perf['runs_analyzed'] > 0:
                    perf_text = (
                        f"Avg Duration: {perf['avg_duration_minutes']:.1f} min\n"
                        f"Avg Phones/Run: {perf['avg_phones_per_run']:,}\n"
                        f"Speed: {perf['avg_speed_phones_per_minute']:.2f} phones/min\n"
                        f"(Based on {perf['runs_analyzed']} completed runs)"
                    )
                else:
                    perf_text = "No completed runs yet"
                
                self.after(0, lambda: self.performance_info.configure(text=perf_text))
                
                # История запусков
                history = db.get_runs_history(10)
                if history:
                    self.after(0, lambda: self.draw_collection_graph(history))
                history_lines = ["ID | Start Time              | Status      | Phones | New | Errors\n"]
                history_lines.append("-" * 70 + "\n")
                
                for run in history:
                    line = (
                        f"{run['id']:2} | {run['started_at'][:19]} | "
                        f"{run['status']:11} | {run['total_phones']:6} | {run['new_phones']:3} | {run['errors_count']:2}\n"
                    )
                    history_lines.append(line)
                
                history_text = "".join(history_lines) if history else "No runs yet\n"
                
                def update_history():
                    self.history_text.configure(state="normal")
                    self.history_text.delete("1.0", "end")
                    self.history_text.insert("1.0", history_text)
                    self.history_text.configure(state="disabled")
                
                self.after(0, update_history)
                
                logging.info("Dashboard refreshed")
                
            except Exception as e:
                logging.error(f"Failed to refresh dashboard: {e}")
            finally:
                if db:
                    db.close()
        
        # Запускаем в отдельном потоке
        import threading
        threading.Thread(target=do_refresh, daemon=True).start()
    
    def draw_collection_graph(self, runs_data: list):
        """Отрисовка графика динамики сбора."""
        if not runs_data or len(runs_data) < 2:
            return
        
        canvas = self.graph_canvas
        canvas.delete("all")
        
        width = 800
        height = 200
        padding = 40
        
        # Получаем данные
        phones_data = [run['total_phones'] for run in reversed(runs_data)]  # От старых к новым
        max_phones = max(phones_data) if phones_data else 1
        
        # Масштабирование
        x_step = (width - 2 * padding) / (len(phones_data) - 1) if len(phones_data) > 1 else 0
        y_scale = (height - 2 * padding) / max_phones if max_phones > 0 else 1
        
        # Оси
        canvas.create_line(padding, height - padding, width - padding, height - padding, fill="gray", width=2)  # X
        canvas.create_line(padding, padding, padding, height - padding, fill="gray", width=2)  # Y
        
        # Линия графика
        points = []
        for i, phones in enumerate(phones_data):
            x = padding + i * x_step
            y = height - padding - (phones * y_scale)
            points.extend([x, y])
            
            # Точки
            canvas.create_oval(x-4, y-4, x+4, y+4, fill="#1f6aa5", outline="white", width=2)
        
        # Соединяющая линия
        if len(points) >= 4:
            canvas.create_line(points, fill="#1f6aa5", width=3, smooth=True)
        
        # Подписи осей
        canvas.create_text(width // 2, height - 10, text="Runs", fill="white", font=("Arial", 10))
        canvas.create_text(15, height // 2, text="Phones", fill="white", font=("Arial", 10), angle=90)
        
        # Значения на оси Y
        for i in range(5):
            y_val = (max_phones / 4) * i
            y_pos = height - padding - (y_val * y_scale)
            canvas.create_text(padding - 20, y_pos, text=f"{int(y_val)}", fill="gray", font=("Arial", 8))

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
        
        # Parallel mode
        ctk.CTkLabel(settings_frame, text="Parallel Mode:").grid(row=1, column=2, padx=10, pady=5, sticky="w")
        self.parallel_mode_var = ctk.StringVar(value="yes" if self.parallel_enabled else "no")
        self.parallel_mode_switch = ctk.CTkSwitch(
            settings_frame,
            text="",
            variable=self.parallel_mode_var,
            onvalue="yes",
            offvalue="no"
        )
        self.parallel_mode_switch.grid(row=1, column=3, padx=10, pady=5)
        if self.parallel_enabled:
            self.parallel_mode_switch.select()

        # Workers count
        ctk.CTkLabel(settings_frame, text="Workers:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.workers_var = ctk.StringVar(value=str(self.workers_count))
        self.workers_entry = ctk.CTkEntry(settings_frame, textvariable=self.workers_var, width=100)
        self.workers_entry.grid(row=2, column=1, padx=10, pady=5)

        # Info label
        self.parallel_info_label = ctk.CTkLabel(
            settings_frame,
            text="ℹ️ Parallel mode uses multiple threads to speed up collection",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        self.parallel_info_label.grid(row=2, column=2, columnspan=2, padx=10, pady=5, sticky="w")

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
        self.log_text = ctk.CTkTextbox(
            logs_frame, 
            height=200, 
            state="disabled",
            wrap="none",  # ← ВАЖНО: "none" для горизонтального скролла
            font=("Courier New", 15)  # Моноширинный шрифт
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Настройка тега для моноширинного шрифта (опционально)
        # self.log_text.tag_config("monospace", font=("Courier New", 10))


        # Add logging handler for GUI
        text_handler = TextHandler(self.log_text)

        # Более читаемый формат с переносом
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'  # Только время (без даты)
        )
        text_handler.setFormatter(formatter)

        # Добавляем handler только если его ещё нет
        logger = logging.getLogger()
        if not any(isinstance(h, TextHandler) for h in logger.handlers):
            logger.addHandler(text_handler)


    def create_export_tab(self):
        export_frame = ctk.CTkFrame(self.tab_export)
        export_frame.pack(pady=20, padx=20, fill="both", expand=True)
        
        ctk.CTkLabel(
            export_frame, text="Export Data", 
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=20)
        
        # CSV Export Section
        csv_section = ctk.CTkFrame(export_frame)
        csv_section.pack(pady=10, padx=20, fill="x")
        
        ctk.CTkLabel(
            csv_section, 
            text="📄 CSV Export",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(pady=10)
        
        ctk.CTkButton(
            csv_section, 
            text="📂 Export All Phones (CSV)", 
            command=self.export_data_phones, 
            width=300, 
            height=40
        ).pack(pady=5)
        
        # Database Export Section
        db_section = ctk.CTkFrame(export_frame)
        db_section.pack(pady=10, padx=20, fill="x")
        
        ctk.CTkLabel(
            db_section, 
            text="💾 Database Export",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(pady=10)
        
        ctk.CTkButton(
            db_section, 
            text="📊 Export Phone Base (SQLite)", 
            command=self.export_phone_base,
            width=300, 
            height=40,
            fg_color="blue",
            hover_color="darkblue"
        ).pack(pady=5)
        
        ctk.CTkLabel(
            db_section,
            text="ℹ️ Creates a new .db file with only unique phone numbers",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(pady=5)
        
        # Status label
        self.export_status = ctk.CTkLabel(
            export_frame, 
            text="", 
            font=ctk.CTkFont(size=11)
        )
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
        
        # Telegram Settings
        telegram_label = ctk.CTkLabel(
            settings_frame, 
            text="Telegram Notifications", 
            font=ctk.CTkFont(size=16, weight="bold")
        )
        telegram_label.pack(pady=(20, 10))

        # Telegram Enabled
        telegram_enabled_frame = ctk.CTkFrame(settings_frame)
        telegram_enabled_frame.pack(pady=5, fill="x", padx=20)
        ctk.CTkLabel(telegram_enabled_frame, text="Enable Telegram:").pack(side="left", padx=10)
        self.telegram_enabled_var = ctk.StringVar(value="yes" if self.telegram_enabled else "no")
        self.telegram_enabled_switch = ctk.CTkSwitch(
            telegram_enabled_frame,
            text="",
            variable=self.telegram_enabled_var,
            onvalue="yes",
            offvalue="no"
        )
        self.telegram_enabled_switch.pack(side="left", padx=10)
        if self.telegram_enabled:
            self.telegram_enabled_switch.select()

        # Telegram Chat ID
        telegram_chat_frame = ctk.CTkFrame(settings_frame)
        telegram_chat_frame.pack(pady=5, fill="x", padx=20)
        ctk.CTkLabel(telegram_chat_frame, text="Telegram Chat ID:").pack(side="left", padx=10)
        self.telegram_chat_id_var = ctk.StringVar(value=self.telegram_chat_id or "")
        self.telegram_chat_entry = ctk.CTkEntry(
            telegram_chat_frame, 
            textvariable=self.telegram_chat_id_var, 
            width=200
        )
        self.telegram_chat_entry.pack(side="left", padx=10)

        # Telegram Token (read-only display)
        telegram_token_frame = ctk.CTkFrame(settings_frame)
        telegram_token_frame.pack(pady=5, fill="x", padx=20)
        ctk.CTkLabel(telegram_token_frame, text="Bot Token:").pack(side="left", padx=10)
        token_display = "***" + (self.telegram_token[-10:] if self.telegram_token and len(self.telegram_token) > 10 else "NOT SET")
        ctk.CTkLabel(
            telegram_token_frame, 
            text=token_display,
            text_color="gray"
        ).pack(side="left", padx=10)

        # Save Button
        save_btn = ctk.CTkButton(
            settings_frame, 
            text="💾 Save Settings",
            command=self.save_settings,
            fg_color="green",
            hover_color="darkgreen",
            width=200
        )
        save_btn.pack(pady=20)
        
        # Parallel Settings
        parallel_label = ctk.CTkLabel(
            settings_frame, 
            text="Parallel Processing", 
            font=ctk.CTkFont(size=16, weight="bold")
        )
        parallel_label.pack(pady=(20, 10))

        # Parallel Enabled
        parallel_enabled_frame = ctk.CTkFrame(settings_frame)
        parallel_enabled_frame.pack(pady=5, fill="x", padx=20)
        ctk.CTkLabel(parallel_enabled_frame, text="Enable Parallel Mode:").pack(side="left", padx=10)
        self.parallel_enabled_var = ctk.StringVar(value="yes" if self.parallel_enabled else "no")
        self.parallel_enabled_switch = ctk.CTkSwitch(
            parallel_enabled_frame,
            text="",
            variable=self.parallel_enabled_var,
            onvalue="yes",
            offvalue="no"
        )
        self.parallel_enabled_switch.pack(side="left", padx=10)
        if self.parallel_enabled:
            self.parallel_enabled_switch.select()

        # Workers count
        workers_frame = ctk.CTkFrame(settings_frame)
        workers_frame.pack(pady=5, fill="x", padx=20)
        ctk.CTkLabel(workers_frame, text="Workers Count (1-10):").pack(side="left", padx=10)
        self.workers_count_var = ctk.StringVar(value=str(self.workers_count))
        self.workers_count_entry = ctk.CTkEntry(
            workers_frame, 
            textvariable=self.workers_count_var, 
            width=100
        )
        self.workers_count_entry.pack(side="left", padx=10)

        # Info
        parallel_info = ctk.CTkLabel(
            settings_frame,
            text="ℹ️ More workers = faster collection, but higher API load",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=400
        )
        parallel_info.pack(pady=5)

        # Save Button for Parallel Settings
        save_parallel_btn = ctk.CTkButton(
            settings_frame, 
            text="💾 Save Parallel Settings",
            command=self.save_parallel_settings,
            fg_color="blue",
            hover_color="darkblue",
            width=200
        )
        save_parallel_btn.pack(pady=10)

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
                val = current / total
                self.progress_bar.set(val)
                self.progress_label.configure(text=f"Client {current} of {total}")
            
            # Статистика с активными воркерами
            active_workers = stats.get('active_workers', 0)
            worker_info = f" | 🔄 Active: {active_workers}" if active_workers > 0 else ""
            
            self.stats_label.configure(
                text=f"Total: {stats.get('total_phones', 0)} | New: {stats.get('new_phones', 0)} | Errors: {stats.get('errors_count', 0)}{worker_info}"
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
            
            # Инициализация Telegram notifier
            notifier = None
            
            # Берём актуальный Chat ID из GUI (если изменён)
            current_chat_id = self.telegram_chat_id_var.get().strip() if hasattr(self, 'telegram_chat_id_var') else self.telegram_chat_id
            current_enabled = (self.telegram_enabled_var.get() == "yes") if hasattr(self, 'telegram_enabled_var') else self.telegram_enabled

            # logging.info(f"Telegram settings: enabled={self.telegram_enabled}, token={bool(self.telegram_token)}, chat_id={bool(self.telegram_chat_id)}") #Логи по телеграмм уведомлениям

            if current_enabled and self.telegram_token and current_chat_id:
                notifier = TelegramNotifier(
                    self.telegram_token,
                    current_chat_id,
                    enabled=True
                )
                logging.info(f"Telegram notifications enabled. Notifier created: {notifier}")
            else:
                logging.warning(f"Telegram notifications NOT enabled. Check: enabled={self.telegram_enabled}, token={'***' if self.telegram_token else 'MISSING'}, chat_id={self.telegram_chat_id}")

            # Выбор режима работы (параллельный или обычный)
            parallel_mode = (self.parallel_mode_var.get() == "yes") if hasattr(self, 'parallel_mode_var') else self.parallel_enabled
            workers = self.parse_int(self.workers_var.get()) if hasattr(self, 'workers_var') else self.workers_count

            if parallel_mode:
                # Используем параллельный orchestrator
                orchestrator = ParallelOrchestrator(
                    api_client, db, self.rate_limit, state_manager, notifier,
                    workers=workers or 5
                )
                # logging.info(f"ParallelOrchestrator created with {workers} workers, notifier: {orchestrator.notifier}") # Логи уведомления Telegram (выключены)
            else:
                # Используем обычный orchestrator
                orchestrator = CollectionOrchestrator(
                    api_client, db, self.rate_limit, state_manager, notifier
                )
                # logging.info(f"CollectionOrchestrator created with notifier: {orchestrator.notifier}") # Логи уведомления Telegram (выключены)

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
        
        if hasattr(self, 'refresh_dashboard'):
            self.refresh_dashboard()
            
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

    def export_phone_base(self):
        """Экспорт SQL базы только с уникальными номерами."""
        def do_export():
            db = None
            try:
                self.after(0, lambda: self.export_status.configure(text="Exporting phone base..."))
                
                db = DatabaseManager(self.db_path)
                db.connect()
                
                # Генерируем имя файла с датой
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                export_filename = f"phones_base_{timestamp}.db"
                export_path = os.path.join("data", "exports", export_filename)
                
                # Экспортируем
                result = db.export_phone_base(export_path)
                
                if result['success']:
                    msg = f"✅ Phone base exported: {export_filename}\n📊 Total phones: {result['phones_count']:,}"
                    logging.info(f"Phone base exported to {export_path}")
                else:
                    msg = f"❌ Export failed: {result['error']}"
                    logging.error(msg)
                
                self.after(0, lambda: self.export_status.configure(text=msg))
                
            except Exception as e:
                err_msg = f"❌ Export failed: {e}"
                self.after(0, lambda: self.export_status.configure(text=err_msg))
                logging.error(err_msg)
            finally:
                if db:
                    db.close()
        
        threading.Thread(target=do_export, daemon=True).start()

    def save_settings(self):
        """Сохранение настроек из GUI."""
        try:
            # Обновляем настройки из полей
            new_chat_id = self.telegram_chat_id_var.get().strip()
            new_enabled = self.telegram_enabled_var.get() == "yes"
            
            # Валидация Chat ID
            if new_enabled and not new_chat_id:
                logging.error("Chat ID cannot be empty when Telegram is enabled")
                self.show_message("Error", "Please enter Telegram Chat ID", "error")
                return
            
            # Обновляем переменные экземпляра
            self.telegram_chat_id = new_chat_id
            self.telegram_enabled = new_enabled
            
            # Сохраняем в .env файл
            self.update_env_file()
            
            logging.info(f"Settings saved: Telegram enabled={new_enabled}, Chat ID={new_chat_id}")
            self.show_message("Success", "Settings saved successfully!", "success")
            
        except Exception as e:
            logging.error(f"Failed to save settings: {e}")
            self.show_message("Error", f"Failed to save: {e}", "error")
    
    def save_parallel_settings(self):
        """Сохранение настроек параллелизации."""
        try:
            # Обновляем настройки из полей
            new_parallel_enabled = self.parallel_enabled_var.get() == "yes"
            new_workers = self.parse_int(self.workers_count_var.get())
            
            # Валидация workers
            if new_workers and (new_workers < 1 or new_workers > 10):
                logging.error("Workers count must be between 1 and 10")
                self.show_message("Error", "Workers count must be between 1 and 10", "error")
                return
            
            # Обновляем переменные экземпляра
            self.parallel_enabled = new_parallel_enabled
            self.workers_count = new_workers or 5
            
            # Сохраняем в .env файл
            self.update_parallel_env()
            
            logging.info(f"Parallel settings saved: enabled={new_parallel_enabled}, workers={self.workers_count}")
            self.show_message("Success", "Parallel settings saved successfully!", "success")
            
        except Exception as e:
            logging.error(f"Failed to save parallel settings: {e}")
            self.show_message("Error", f"Failed to save: {e}", "error")

    def update_parallel_env(self):
        """Обновление .env файла с настройками параллелизации."""
        from pathlib import Path
        
        env_path = Path(".env")
        
        # Читаем существующий .env
        lines = []
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        
        # Обновляем нужные строки
        updated_parallel = False
        updated_workers = False
        
        for i, line in enumerate(lines):
            if line.startswith('PARALLEL_ENABLED='):
                lines[i] = f'PARALLEL_ENABLED={"true" if self.parallel_enabled else "false"}\n'
                updated_parallel = True
            elif line.startswith('WORKERS_COUNT='):
                lines[i] = f'WORKERS_COUNT={self.workers_count}\n'
                updated_workers = True
        
        # Добавляем, если не было
        if not updated_parallel:
            lines.append(f'PARALLEL_ENABLED={"true" if self.parallel_enabled else "false"}\n')
        if not updated_workers:
            lines.append(f'WORKERS_COUNT={self.workers_count}\n')
        
        # Записываем обратно
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    def update_env_file(self):
        """Обновление .env файла с новыми настройками."""
        import os
        from pathlib import Path
        
        env_path = Path(".env")
        
        # Читаем существующий .env
        lines = []
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        
        # Обновляем нужные строки
        updated_chat_id = False
        updated_enabled = False
        
        for i, line in enumerate(lines):
            if line.startswith('TELEGRAM_CHAT_ID='):
                lines[i] = f'TELEGRAM_CHAT_ID={self.telegram_chat_id}\n'
                updated_chat_id = True
            elif line.startswith('TELEGRAM_ENABLED='):
                lines[i] = f'TELEGRAM_ENABLED={"true" if self.telegram_enabled else "false"}\n'
                updated_enabled = True
        
        # Добавляем, если не было
        if not updated_chat_id:
            lines.append(f'TELEGRAM_CHAT_ID={self.telegram_chat_id}\n')
        if not updated_enabled:
            lines.append(f'TELEGRAM_ENABLED={"true" if self.telegram_enabled else "false"}\n')
        
        # Записываем обратно
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    def show_message(self, title: str, message: str, msg_type: str = "info"):
        """Показ всплывающего сообщения."""
        import tkinter.messagebox as messagebox
        
        if msg_type == "success":
            messagebox.showinfo(title, message)
        elif msg_type == "error":
            messagebox.showerror(title, message)
        else:
            messagebox.showinfo(title, message)

    def parse_int(self, value):
        try:
            return int(value) if value and str(value).strip() else None
        except ValueError:
            return None

if __name__ == "__main__":
    app = App()
    app.mainloop()
