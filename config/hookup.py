import requests

from clients.settings import BUSINESS_TOKEN, BUSINESS_URL, PAYLOAD
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TBankAPI:

    def __init__(self):
        self.__token = BUSINESS_TOKEN
        self._headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.__token}'
        }
        self.url = BUSINESS_URL
        self._payload = PAYLOAD

    def _connect(self):
        response = requests.get(self.url, headers=self._headers, params=self._payload, verify=False)

        if response.status_code != 200:
            return []

        return response.json()['operation']

