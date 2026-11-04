"""Test that watches detect dead streams instead of waiting on them forever."""

import asyncio
import contextlib
import dataclasses
import json
import tempfile
import urllib.parse
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

import easykube
from easykube.tests.conftest import (
    FakeApiServer,
    RecordingStream,
    list_response,
    status_response,
    watch_event,
)

PODS = "/api/v1/namespaces/default/pods"
BASE_URL = "http://kubernetes.invalid"
# The API server sends a bookmark on an idle watch about once a minute
BOOKMARK_INTERVAL = 60.0
# Give up on a watch that never recovers; this is loop time, so it costs nothing
GUARD_TIMEOUT = 3600.0
# Sync clients use real socket timeouts, so their tests need short real-time values
SYNC_INACTIVITY_TIMEOUT = 0.5
SYNC_GUARD_TIMEOUT = 10.0


@dataclasses.dataclass(frozen=True)
class Pause:
    """Pause a scripted watch stream for the given number of seconds."""

    seconds: float


class Silence:
    """Hold a scripted watch stream open without sending anything, until teardown."""


SILENCE = Silence()

Step = bytes | Pause | Silence


class SocketApiServer:
    """
    Serve a minimal Kubernetes API over a Unix socket with scripted watch streams.

    A scripted watch stream is a watch stream which follows a predefined 'script',
    defined by the test. e.g. say hello, send some bytes, sleep for 10s, etc.

    It runs in the test's event loop, so looptime fast-forwards its pauses together
    with the client's timeouts. Unlike httpx.MockTransport, requests go through
    httpx's real transport, so read timeouts apply as against a real API server.
    """

    def __init__(self, watch_scripts: list[list[Step]]) -> None:
        """Serve one script per watch request; any extra watches stay silent."""
        self.watch_scripts = list(watch_scripts)
        self.watch_params: list[dict[str, str]] = []
        self.watch_times: list[float] = []
        self.stopped = asyncio.Event()
        self.handlers: set[asyncio.Task[None]] = set()

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Answer list requests with an empty list and watch requests from a script."""
        task = asyncio.current_task()
        assert task is not None
        self.handlers.add(task)
        try:
            while request_line := await reader.readline():
                while await reader.readline() not in (b"\r\n", b""):
                    pass
                url = urllib.parse.urlsplit(request_line.split()[1].decode())
                params = dict(urllib.parse.parse_qsl(url.query))
                if "watch" not in params:
                    body = json.dumps(
                        {"metadata": {"resourceVersion": "1"}, "items": []}
                    ).encode()
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
                    )
                elif not await self._stream(writer, params):
                    return
        except ConnectionError:
            pass
        finally:
            writer.close()

    async def _stream(
        self, writer: asyncio.StreamWriter, params: dict[str, str]
    ) -> bool:
        """Send a chunked watch response; return whether the connection is reusable."""
        self.watch_params.append(params)
        self.watch_times.append(asyncio.get_running_loop().time())
        script = self.watch_scripts.pop(0) if self.watch_scripts else [SILENCE]
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n"
        )
        for step in script:
            if isinstance(step, Silence):
                await self.stopped.wait()
                return False
            if isinstance(step, Pause):
                await asyncio.sleep(step.seconds)
            else:
                writer.write(b"%x\r\n%s\r\n" % (len(step), step))
            await writer.drain()
        writer.write(b"0\r\n\r\n")
        await writer.drain()
        return True


@contextlib.asynccontextmanager
async def serve(
    path: str, watch_scripts: list[list[Step]]
) -> AsyncIterator[SocketApiServer]:
    """Run a socket API server in the current event loop for the block."""
    server = SocketApiServer(watch_scripts)
    listener = await asyncio.start_unix_server(server.handle, path)
    try:
        yield server
    finally:
        server.stopped.set()
        listener.close()
        for task in server.handlers:
            task.cancel()
        await asyncio.gather(*server.handlers, return_exceptions=True)
        await listener.wait_closed()


@pytest.fixture
def socket_path() -> Iterator[str]:
    """Provide a Unix socket path short enough for AF_UNIX's length limit."""
    with tempfile.TemporaryDirectory(prefix="ek") as tmp:
        yield str(Path(tmp) / "api.sock")


def versions(events: list[dict[str, Any]]) -> list[str]:
    """Return the resource versions of the given watch events."""
    return [event["object"]["metadata"]["resourceVersion"] for event in events]


async def watch_pods(path: str, count: int, **settings: Any) -> list[dict[str, Any]]:
    """Watch pods over the socket until count events arrive, or fail trying."""
    received: list[dict[str, Any]] = []
    async with easykube.AsyncClient(
        base_url=BASE_URL, transport=httpx.AsyncHTTPTransport(uds=path), **settings
    ) as client:
        pods = easykube.ResourceSpec("v1", "pods", "Pod", True)(client)
        _, events = await pods.watch_list()
        stream = aiter(events)

        async def consume() -> None:
            async for event in stream:
                received.append(event)
                if len(received) == count:
                    return

        try:
            await asyncio.wait_for(consume(), GUARD_TIMEOUT)
        finally:
            await stream.aclose()
    return received


def sync_watch_pods(path: str, count: int) -> list[dict[str, Any]]:
    """Watch pods over the socket with a sync client until count events arrive."""
    received: list[dict[str, Any]] = []
    with easykube.SyncClient(
        base_url=BASE_URL,
        transport=httpx.HTTPTransport(uds=path),
        watch_inactivity_timeout=SYNC_INACTIVITY_TIMEOUT,
    ) as client:
        pods = easykube.ResourceSpec("v1", "pods", "Pod", True)(client)
        _, events = pods.watch_list()
        with events:
            for event in events:
                received.append(event)
                if len(received) == count:
                    break
    return received


@contextlib.contextmanager
def mock_pods(
    api_server: FakeApiServer, **settings: Any
) -> Iterator[easykube.Resource]:
    """Provide pods on a client with the given settings, backed by the fake server."""
    with easykube.SyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(api_server.handle), **settings
    ) as client:
        yield easykube.ResourceSpec("v1", "pods", "Pod", True)(client)


@pytest.mark.asyncio
@pytest.mark.looptime
@pytest.mark.parametrize(
    ("settings", "inactivity_timeout"),
    [({}, 70.0), ({"watch_inactivity_timeout": 30.0}, 30.0)],
    ids=["default", "configured"],
)
async def test_async_watch_resumes_after_stream_goes_silent(
    socket_path: str, settings: dict[str, Any], inactivity_timeout: float
) -> None:
    """
    Check that an async watch reconnects once its stream has been silent too long.

    A half-open connection looks exactly like this: the socket stays open but no
    data, not even bookmarks, ever arrives again.
    """
    scripts: list[list[Step]] = [
        [watch_event("ADDED", "pod1", "2"), SILENCE],
        [watch_event("MODIFIED", "pod1", "3"), SILENCE],
    ]
    async with serve(socket_path, scripts) as server:
        received = await watch_pods(socket_path, 2, **settings)
    assert versions(received) == ["2", "3"]
    assert [p["resourceVersion"] for p in server.watch_params] == ["1", "2"]
    assert server.watch_times == pytest.approx([0.0, inactivity_timeout])


@pytest.mark.asyncio
@pytest.mark.looptime
async def test_bookmarks_keep_a_quiet_watch_alive(socket_path: str) -> None:
    """
    Check that a watch receiving only bookmarks is not treated as dead.

    The inactivity timeout must measure time since the last data, not the total
    length of the watch, or every quiet watch would reconnect needlessly.
    """
    script: list[Step] = []
    for version in range(2, 12):
        script += [Pause(BOOKMARK_INTERVAL), watch_event("BOOKMARK", "", str(version))]
    script += [watch_event("ADDED", "pod1", "12"), SILENCE]
    async with serve(socket_path, [script]) as server:
        # Keep the server-side timeout out of the way, so only inactivity is tested
        received = await watch_pods(socket_path, 1, watch_timeout_seconds=(3600, 3600))
    assert versions(received) == ["12"]
    assert server.watch_times == [0.0]
    assert asyncio.get_running_loop().time() == pytest.approx(10 * BOOKMARK_INTERVAL)


@pytest.mark.asyncio
@pytest.mark.looptime(False)
async def test_sync_watch_resumes_after_stream_goes_silent(socket_path: str) -> None:
    """
    Check that a sync watch reconnects once its stream has been silent too long.

    Sync clients use real socket timeouts, which looptime cannot fast-forward, so
    this test runs in real time with a short timeout.
    """
    scripts: list[list[Step]] = [
        [watch_event("ADDED", "pod1", "2"), SILENCE],
        [watch_event("MODIFIED", "pod1", "3"), SILENCE],
    ]
    async with serve(socket_path, scripts) as server:
        worker = asyncio.create_task(asyncio.to_thread(sync_watch_pods, socket_path, 2))
        done, _ = await asyncio.wait({worker}, timeout=SYNC_GUARD_TIMEOUT)
    # A thread cannot be cancelled, but closing the server unblocks a stuck client,
    # so wait for it to finish and release its socket before reporting the failure
    await asyncio.wait({worker}, timeout=SYNC_GUARD_TIMEOUT)
    outcome = worker.exception() if worker.done() else "still running"
    assert done, f"watch blocked on a silent stream; afterwards: {outcome!r}"
    received = worker.result()
    assert versions(received) == ["2", "3"]
    assert [p["resourceVersion"] for p in server.watch_params] == ["1", "2"]


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("timed out"),
        httpx.ReadError("[Errno 110] Connection timed out"),
    ],
    ids=["read-timeout", "read-error"],
)
def test_watch_resumes_after_read_failure(
    api_server: FakeApiServer, error: httpx.TransportError
) -> None:
    """
    Check that a watch resumes from the last version after a failed read.

    This is how a dead connection surfaces: as a read timeout, or as a read error
    once TCP keepalive gives up on the peer. Each abandoned response must be closed,
    or every resume would leak a pooled connection.
    """
    failed = RecordingStream([watch_event("ADDED", "pod1", "2")], error)
    ended = RecordingStream([watch_event("MODIFIED", "pod1", "3")])
    api_server.add(
        "GET",
        PODS,
        list_response([], resource_version="1"),
        lambda request: httpx.Response(200, stream=failed),
        lambda request: httpx.Response(200, stream=ended),
        status_response(410, "too old", "Expired"),
    )
    received = []
    with mock_pods(api_server) as pods:
        _, events = pods.watch_list()
        with pytest.raises(easykube.ApiError):
            for event in events:
                received.append(event)
    assert versions(received) == ["2", "3"]
    assert failed.closed and ended.closed
    watches = api_server.requests_to("GET", PODS)[1:]
    assert [r.url.params["resourceVersion"] for r in watches] == ["1", "2", "3"]


@pytest.mark.parametrize(
    ("settings", "bounds"),
    [
        ({}, (300, 600)),
        ({"watch_timeout_seconds": (30, 30)}, (30, 30)),
        ({"watch_timeout_seconds": (45, 90)}, (45, 90)),
    ],
    ids=["default", "configured-fixed", "configured-range"],
)
def test_watch_asks_the_server_to_end_the_stream(
    api_server: FakeApiServer, settings: dict[str, Any], bounds: tuple[int, int]
) -> None:
    """
    Check that watches send a server-side timeoutSeconds within the client's bounds.

    The server then ends every watch regularly, so connections get recycled even if
    a dead stream is never noticed on the client side.
    """
    api_server.add(
        "GET",
        PODS,
        list_response([], resource_version="1"),
        lambda request: httpx.Response(
            200, stream=RecordingStream([watch_event("ADDED", "pod1", "2")])
        ),
    )
    with mock_pods(api_server, **settings) as pods:
        _, events = pods.watch_list()
        next(iter(events))
    watch = api_server.requests_to("GET", PODS)[1]
    assert bounds[0] <= int(watch.url.params["timeoutSeconds"]) <= bounds[1]
