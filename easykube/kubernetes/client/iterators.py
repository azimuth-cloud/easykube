import json

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
        super().__init__(client, "GET", path, params=params, timeout=None)

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
        # In the case where an event is not valid JSON or we get a RemoteProtocolError,
        # it is likely that the API server is still healthy but the read has just timed
        # out
        #
        # In this case, we should be able to restart the watch from the last known
        # version
        #
        # In all other cases, the exception should be allowed to bubble, e.g.:
        #   * The API server responds with 410 Gone, in which case the watch needs
        #     to restart from scratch
        #   * We cannot connect to the API server
        return (
            not exception
            or isinstance(exception, json.JSONDecodeError)
            or isinstance(exception, httpx.RemoteProtocolError)
        )
