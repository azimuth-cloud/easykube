"""Provide a fake Kubernetes API server and clients that talk to it."""

import collections
import json
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

import easykube

BASE_URL = "https://kubernetes.invalid"

Handler = Callable[[httpx.Request], httpx.Response]


def json_response(data: Any, status_code: int = 200) -> Handler:
    """Return a handler that responds with the given JSON data."""
    return lambda request: httpx.Response(status_code, json=data)


def status_response(status_code: int, message: str, reason: str = "") -> Handler:
    """Return a handler that responds with a Kubernetes Status object."""
    return json_response(
        {"kind": "Status", "message": message, "reason": reason, "code": status_code},
        status_code,
    )


def list_response(items: list[Any], resource_version: str = "1") -> Handler:
    """Return a handler that responds with a Kubernetes list."""
    return json_response(
        {"metadata": {"resourceVersion": resource_version}, "items": items}
    )


def request_json(request: httpx.Request) -> Any:
    """Return the decoded JSON body of a recorded request."""
    return json.loads(request.content)


def watch_event(event_type: str, name: str, resource_version: str) -> bytes:
    """Return a single line of a watch stream."""
    obj = {"metadata": {"name": name, "resourceVersion": resource_version}}
    return json.dumps({"type": event_type, "object": obj}).encode() + b"\n"


class RecordingStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    """
    Yield canned chunks, optionally raise afterwards, and record being closed.

    The canned chunks are a pre-written list of byte strings that the fake body hands
    back one at a time, as if they were arriving over the network.
    """

    def __init__(self, chunks: list[bytes], error: Exception | None = None) -> None:
        """Store the chunks to yield and the error to raise after them."""
        self.chunks = chunks
        self.error = error
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        """Yield the chunks synchronously."""
        yield from self.chunks
        if self.error:
            raise self.error

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Yield the chunks asynchronously."""
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error

    def close(self) -> None:
        """Record that the stream was closed."""
        self.closed = True

    async def aclose(self) -> None:
        """Record that the stream was closed."""
        self.closed = True


class FakeApiServer:
    """Record requests and answer them from routes keyed by method and path."""

    def __init__(self) -> None:
        """Serve discovery for the core and apps APIs by default."""
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], collections.deque[Handler]] = {}
        self.add(
            "GET",
            "/api/v1",
            json_response(
                {
                    "resources": [
                        {
                            "name": "pods",
                            "singularName": "pod",
                            "kind": "Pod",
                            "namespaced": True,
                        },
                        {
                            "name": "namespaces",
                            "singularName": "namespace",
                            "kind": "Namespace",
                            "namespaced": False,
                        },
                    ]
                }
            ),
        )

    def add(self, method: str, path: str, *handlers: Handler) -> None:
        """Answer requests in turn with the handlers, repeating the last one."""
        self.routes.setdefault((method, path), collections.deque()).extend(handlers)

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Record the request and return the next response for its route."""
        self.requests.append(request)
        handlers = self.routes.get((request.method, request.url.path))
        if not handlers:
            return status_response(404, "not found", "NotFound")(request)
        handler = handlers.popleft() if len(handlers) > 1 else handlers[0]
        return handler(request)

    def requests_to(self, method: str, path: str) -> list[httpx.Request]:
        """Return the recorded requests for the given method and path."""
        return [r for r in self.requests if r.method == method and r.url.path == path]


@pytest.fixture
def api_server() -> FakeApiServer:
    """Provide a fake API server with no state shared between tests."""
    return FakeApiServer()


@pytest.fixture
def client(api_server: FakeApiServer) -> Iterator[easykube.SyncClient]:
    """Provide a sync client that sends its requests to the fake API server."""
    transport = httpx.MockTransport(api_server.handle)
    with easykube.SyncClient(base_url=BASE_URL, transport=transport) as client:
        yield client


@pytest_asyncio.fixture
async def async_client(
    api_server: FakeApiServer,
) -> AsyncIterator[easykube.AsyncClient]:
    """Provide an async client that sends its requests to the fake API server."""
    transport = httpx.MockTransport(api_server.handle)
    async with easykube.AsyncClient(base_url=BASE_URL, transport=transport) as client:
        yield client


@pytest.fixture
def pods(client: easykube.SyncClient) -> Any:
    """Provide the namespaced pods resource without needing discovery."""
    return easykube.ResourceSpec("v1", "pods", "Pod", True)(client)
