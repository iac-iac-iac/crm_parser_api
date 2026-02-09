"""DataMaster API Client"""
import requests
import logging
from typing import List, Dict
from dataclasses import dataclass

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
    def __init__(self, api_url: str, token: str, timeout: int = 30):
        self.api_url = api_url
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

    def _make_request(self, command: str, **params) -> Dict:
        payload = {'token': self.token, 'command': command, **params}
        try:
            response = self.session.post(self.api_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            
            if result.get('status') != 'success':
                raise DataMasterAPIError(f"API error: {result.get('error', 'Unknown')}")
            
            return result
        except requests.exceptions.RequestException as e:
            raise DataMasterAPIError(f"Request failed: {e}")

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
