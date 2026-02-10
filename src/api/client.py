"""DataMaster API Client"""
import requests
import logging
from typing import List, Dict
from dataclasses import dataclass
from src.utils.retry import retry

logger = logging.getLogger(__name__)


@dataclass
class Client:
    id: int
    username: str


@dataclass
class Project:
    id: int
    name: str
    client_id: int


@dataclass
class PhoneRecord:
    phone: str
    created_at: str


class DataMasterAPIError(Exception):
    pass


class DataMasterClient:
    def __init__(self, api_url: str, token: str, timeout: int = 30, max_retries: int = 3):
        self.api_url = api_url
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        
        # Настройка session с connection pooling и retry
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        
        # HTTPAdapter с connection pool и retry стратегией
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,  # 1, 2, 4 секунды между попытками
            status_forcelist=[429, 500, 502, 503, 504],  # Повторять при этих статусах
            allowed_methods=["POST", "GET"]  # Для каких методов
        )
        
        adapter = HTTPAdapter(
            pool_connections=10,    # Количество connection pools
            pool_maxsize=20,        # Максимальный размер каждого pool
            max_retries=retry_strategy
        )
        
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)


    @retry(max_attempts=3, delay=2.0, backoff=2.0, exceptions=(requests.exceptions.RequestException,))
    def _make_request(self, command: str, **params) -> Dict:
        """
        Выполнить API-запрос с автоматическими повторами при сбоях.
        
        Args:
            command: Команда API (clients, gck_projects, gck_phones)
            **params: Дополнительные параметры запроса
            
        Returns:
            Dict с результатом API
            
        Raises:
            DataMasterAPIError: При ошибке API или превышении лимита попыток
        """
        payload = {'token': self.token, 'command': command, **params}
        
        try:
            response = self.session.post(self.api_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            
            if result.get('status') != 'success':
                raise DataMasterAPIError(f"API error: {result.get('error', 'Unknown')}")
            
            return result
            
        except requests.exceptions.Timeout as e:
            logger.error(f"Request timeout after {self.timeout}s: {e}")
            raise
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {e}")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code}: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise

    def get_clients(self) -> List[Client]:
        result = self._make_request('clients')
        clients = [Client(id=c['id'], username=c['username']) for c in result.get('result', [])]
        logger.info(f"Retrieved {len(clients)} clients")
        return clients

    def get_projects(self, user_id: int) -> List[Project]:
        result = self._make_request('gck_projects', user_id=user_id)
        projects = [
            Project(id=int(p['id']), name=p['name'], client_id=user_id)
            for p in result.get('result', [])
        ]
        return projects

    def get_phones(self, project_id: int, page: int = 1) -> List[PhoneRecord]:
        result = self._make_request('gck_phones', id=project_id, page=page)
        return [PhoneRecord(phone=p['phone'], created_at=p['created_at']) 
                for p in result.get('result', [])]

    def close(self):
        self.session.close()
