import json
import random

import httpx

from ... import rest  # noqa: TID252


class ListResponseIterator(rest.ListResponseIterator):
    """
    Iterator for list responses.
    """

    def __init__(self, client, resource, params):
        super().__init__(client, resource, params)
        self._resource_version = None

    @property
    def resource_version(self):
        """
        The last seen resource version.
        """
        return self._resource_version

    def _extract_list(self, response):
        # Store the resource version from the response as well as returning the data
        data = response.json()
        self._resource_version = data["metadata"]["resourceVersion"]
        return data["items"]


class WatchEvents(rest.TextStreamIterator):
    """
    Stream iterator that yields watch events.
    """

    def __init__(self, client, path, params, initial_resource_version):
        params = params.copy()
        params.update(
            {
                "watch": 1,
                "resourceVersion": initial_resource_version,
                "allowWatchBookmarks": "true",
            }
        )
        # Timeout is the max time between chunks of data,
        # or between bookmarks that kube sends every 60s
        timeout = httpx.Timeout(
            connect=client.timeout.connect,
            read=client.watch_inactivity_timeout,
            write=client.timeout.write,
            pool=client.timeout.pool,
        )
        super().__init__(client, "GET", path, params=params, timeout=timeout)

    def _request(self):
        # Each connect, ask for a random server side timeout to recycle the connection.
        # It's random to prevent a storm if many timeouts align at once.
        self._request_kwargs["params"]["timeoutSeconds"] = random.randint(
            *self._client.watch_timeout_seconds
        )
        return super()._request()

    def _process_chunk(self, chunk):
        event = json.loads(chunk)
        # Each event contains a resourceVersion, which we track so that we can restart
        # the watch from that version if it fails
        resource_version = event["object"]["metadata"]["resourceVersion"]
        self._request_kwargs["params"]["resourceVersion"] = resource_version
        # Bookmark events are just for us to save a resource version
        # They should not be emitted
        if event["type"] == "BOOKMARK":
            raise self.SuppressItem
        else:
            return event

    def _should_resume(self, exception):
        # In cases where, the API server is probably still healthy but the stream was
        # cut short, we can restart the watch from the last known version:
        #   * The stream ended, e.g. because timeoutSeconds elapsed
        #   * An event is not valid JSON or we get a RemoteProtocolError
        #   * No data arrived within the inactivity timeout (ReadTimeout), or the
        #     connection died mid-stream (ReadError), e.g. when TCP keepalive gives up
        #     on a half-open connection
        #
        # In all other cases, the exception should be allowed to bubble, e.g.:
        #   * The API server responds with 410 Gone, in which case the watch needs
        #     to restart from scratch
        #   * We cannot connect to the API server
        return not exception or isinstance(
            exception,
            (
                json.JSONDecodeError,
                httpx.RemoteProtocolError,
                httpx.ReadTimeout,
                httpx.ReadError,
            ),
        )
