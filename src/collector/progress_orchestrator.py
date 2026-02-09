"""Collection Orchestrator with Progress Callbacks"""
from src.collector.orchestrator import CollectionOrchestrator


class ProgressOrchestrator(CollectionOrchestrator):
    def __init__(self, api_client, db, rate_limit, state_manager, progress_callback=None):
        super().__init__(api_client, db, rate_limit, state_manager)
        self.progress_callback = progress_callback

    def collect(self, limit_clients=None, limit_projects=None, max_pages=None, resume=False):
        # Wrapper для вызова callback
        original_method = super().collect
        
        # Здесь можно добавить логику вызова progress_callback
        # при обработке каждого клиента
        
        return original_method(limit_clients, limit_projects, max_pages, resume)
