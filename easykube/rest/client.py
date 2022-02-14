import logging

import httpx

from ..flow import Flowable, flow, AsyncExecutor, SyncExecutor


logger = logging.getLogger(__name__)


class BaseClient(Flowable):
    """
    Base class for sync and async REST clients.
    """
    @flow
    def send(self, request, **kwargs):
        """
        Sends the given request as part of a flow.
        """
        response = yield super().send(request, **kwargs)
        self.log_response(response)
        self.raise_for_status(response)
        return response

    def log_response(self, response):
        """
        Logs the response using standard Python logging.
        """
        logger.info(
            "API request: \"%s %s\" %s",
            response.request.method,
            response.request.url,
            response.status_code
        )

    def raise_for_status(self, response):
        """
        Raise the relevant exception for the response, if required.
        """
        response.raise_for_status()


class SyncClient(BaseClient, httpx.Client):
    """
    Class for a sync REST client.
    """
    __flow_executor__ = SyncExecutor()


class AsyncClient(BaseClient, httpx.AsyncClient):
    """
    Class for a REST client.
    """
    __flow_executor__ = AsyncExecutor()
