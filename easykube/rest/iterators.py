import contextlib
import json
import logging

from ..flow import Flowable, flow  # noqa: TID252

logger = logging.getLogger(__name__)


class ListResponseIterator(Flowable):
    """
    Iterator for list responses.

    Can be used as either a sync or async iterator depending on the client that is
    given.
    """

    class StopIteration(Exception):  # noqa: A001,N818
        """
        Exception raised to indicate that a list response has finished iterating.
        """

    def __init__(self, client, resource, params):
        self._client = client
        self._resource = resource
        self._data = []
        self._next_index = 0
        self._next_url, self._next_params = resource._prepare_path(params=params)

    def get_flow_executor(self):
        """
        Returns the flow executor to use.
        """
        return self._client.get_flow_executor()

    def _extract_list(self, response):
        """
        Extracts a list of instances from a list response.

        By default, this is deferred to the resource method so cases where a custom
        iterator is required are rare.
        """
        return self._resource._extract_list(response)

    def _extract_next_page(self, response):
        """
        Return a (URL, params) tuple for the next page or None if there is no next page.

        By default, this is deferred to the resource method so cases where a custom
        iterator is required are rare.
        """
        return self._resource._extract_next_page(response)

    @flow
    def _next_item(self):
        """
        Flow that returns the next item in the iterator.
        """
        yield self._resource._ensure_initialised()
        # If we have run out of data, try to load some more
        if self._next_index >= len(self._data) and self._next_url:
            response = yield self._client.get(self._next_url, params=self._next_params)
            self._data = self._extract_list(response)
            self._next_index = 0
            self._next_url, self._next_params = self._extract_next_page(response) or (
                None,
                None,
            )
        # Return the item at the next index before incrementing it
        try:
            next_item = self._data[self._next_index]
        except IndexError:
            raise self.StopIteration
        else:
            self._next_index = self._next_index + 1
            return self._resource._wrap_instance(next_item)

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return self._next_item()
        except self.StopIteration:
            raise StopIteration

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self._next_item()
        except self.StopIteration:
            raise StopAsyncIteration


class StreamIterator:
    """
    Iterator over items in a stream.

    Can be used as a sync or async iterator depending on the client that is given.
    """

    class SuppressItem(Exception):  # noqa: N818
        """
        Exception that can be raised to suppress an item from being yielded.
        """

    def __init__(self, client, method, url, **kwargs):
        self._client = client
        self._method = method
        self._url = url
        # Split the given kwargs into request and send kwargs
        self._send_kwargs = {}
        if "auth" in kwargs:
            self._send_kwargs["auth"] = kwargs.pop("auth")
        if "follow_redirects" in kwargs:
            self._send_kwargs["follow_redirects"] = kwargs.pop("follow_redirects")
        self._request_kwargs = kwargs
        # Initially, there is no active response
        self._response = None

    def _request(self):
        """
        Returns the request for the iterator.
        """
        return self._client.build_request(
            self._method, self._url, **self._request_kwargs
        )

    @contextlib.contextmanager
    def _send(self):
        """
        Context manager that synchronously sends a request and yields a response,
        ensuring that the current response is updated.
        """
        self._response = self._client.send(
            self._request(), stream=True, **self._send_kwargs
        )
        try:
            yield self._response
        finally:
            self.close()

    @contextlib.asynccontextmanager
    async def _send_async(self):
        """
        Context manager that asynchronously sends a request and yields a response,
        ensuring that the current response is updated.
        """
        self._response = await self._client.send(
            self._request(), stream=True, **self._send_kwargs
        )
        try:
            yield self._response
        finally:
            await self.aclose()

    def _chunk_iterator(self, response):
        """
        Returns a synchronous chunk iterator for the response.
        """
        raise NotImplementedError

    def _async_chunk_iterator(self, response):
        """
        Returns an asynchronous chunk iterator for the response.
        """
        raise NotImplementedError

    def _process_chunk(self, chunk):
        """
        Process the given chunk of bytes and return the item to be yielded.

        To suppress the yielding of an item for a chunk, raise the special exception
        StreamIterator.SuppressItem.

        By default, chunks are processed as JSON.
        """
        return json.loads(chunk)

    def _should_resume(self, exception):
        """
        Receives the exception that caused the stream to exit, or None if the stream
        terminated without error, and returns a truthy value if the stream should be
        resumed.
        """
        # By default, this is a NOOP which causes the iterator to exit

    def __iter__(self):
        while True:
            try:
                with self._send() as response:
                    for chunk in self._chunk_iterator(response):
                        try:
                            yield self._process_chunk(chunk)
                        except self.SuppressItem:
                            continue
            except Exception as exc:
                if not self._should_resume(exc):
                    raise
            else:
                if not self._should_resume(None):
                    break

    async def __aiter__(self):
        while True:
            try:
                async with self._send_async() as response:
                    async for chunk in self._async_chunk_iterator(response):
                        try:
                            yield self._process_chunk(chunk)
                        except self.SuppressItem:
                            continue
            except Exception as exc:
                if not self._should_resume(exc):
                    raise
            else:
                if not self._should_resume(None):
                    break

    def close(self):
        if self._response:
            self._response.close()
            self._response = None

    async def aclose(self):
        if self._response:
            await self._response.aclose()
            self._response = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()


class ByteStreamIterator(StreamIterator):
    """
    Iterator for items in a byte stream.

    Chunks correspond to fixed-size chunks of a byte-stream, and are received by
    _process_chunk as bytes.
    """

    def __init__(self, client, method, url, /, chunk_size=None, **kwargs):
        super().__init__(client, method, url, **kwargs)
        self._chunk_size = chunk_size

    def _chunk_iterator(self, response):
        """
        Returns a synchronous chunk iterator for the response.
        """
        return response.iter_bytes(self._chunk_size)

    def _async_chunk_iterator(self, response):
        """
        Returns an asynchronous chunk iterator for the response.
        """
        return response.aiter_bytes(self._chunk_size)


class TextStreamIterator(StreamIterator):
    """
    Iterator for items in a text stream.

    Chunks correspond to lines of the response.
    """

    def _chunk_iterator(self, response):
        """
        Returns a synchronous chunk iterator for the response.
        """
        return response.iter_lines()

    def _async_chunk_iterator(self, response):
        """
        Returns an asynchronous chunk iterator for the response.
        """
        return response.aiter_lines()
