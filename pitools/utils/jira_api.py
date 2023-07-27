import json
import logging
import os

import requests
from dotenv import load_dotenv

log = logging.getLogger("atlassian")


class AtlassianRestAPI:

    def __init__(self, url):
        self.url = url
        self.username = str()
        self.password = str()

        # get jira credential from .env
        self._get_credentials()

    def _get_credentials(self):
        load_dotenv()

        self.username = os.getenv("JIRA_USERNAME")
        self.password = os.getenv("JIRA_PASSWORD")

    def request(self, method='GET', path='/', data=None,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'}):

        return requests.request(
                method=method,
                url='{0}{1}'.format(self.url, path),
                headers=headers,
                data=json.dumps(data),
                auth=(self.username, self.password),
                timeout=60)

    def get(self, path, data=None, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}):
        return self.request('GET', path=path, data=data, headers=headers)

    def post(self, path, data=None, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}):
        try:
            return self.request('POST', path=path, data=data, headers=headers)
        except ValueError:
            log.debug('Received response with no content')
            return None

    def put(self, path, data=None, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}):
        try:
            return self.request('PUT', path=path, data=data, headers=headers)
        except ValueError:
            log.debug('Received response with no content')
            return None

    def delete(self, path, data=None, headers={'Content-Type': 'application/json', 'Accept': 'application/json'}):
        return self.request('DELETE', path=path, data=data, headers=headers)


class Jira(AtlassianRestAPI):

    def jql(self, jql, expand='None', fields='*all', maxResults=100, startAt=0):
        return self.get(
                '/rest/api/2/search?'
                + f'expand={expand}'
                + f'&fields={fields}'
                + f'&jql={jql}'
                + f'&maxResults={maxResults}'
                + f'&startAt={startAt}').json()

    def user(self, username):
        return self.get(f'/rest/api/3/user?accountId={username}')

    def myself(self):
        return self.get('/rest/api/2/myself')
