import asyncio
import collections
import typing as t

from .reconcile import Request


class Queue:
    """
    Queue of (request, attempt) tuples representing requests to reconcile objects.

    The queue is "smart" in a few ways:

      1. It has explicit operations for enqueuing a new request and requeuing a request that
         has previously been attempted.

      2. Requeuing of a request that has been previously attempted only happens after a delay.
         This happens asynchronously so that it does not block the worker from moving on to the
         next request.

      3. At most one request per object can be in the queue at any given time.

      4. Only one request per object is allowed to be "active" at any given time.
         The queue records when a request leaves the queue and does not allow any more requests
         for the same object to leave the queue until it has been notified that the
         previous request has been completed (either explicitly or by requeuing).

    Note that this means that requests for objects that are changing often will be pushed to
    the back of the queue.
    """
    def __init__(self):
        # The main queue of (request, attempt) tuples
        self._queue: t.List[t.Tuple[Request, int]] = []
        # A queue of futures
        # Each waiting "dequeuer" adds a future to the queue and waits on it
        # When a request becomes available, the first future in the queue is resolved, which
        # "wakes up" the corresponding dequeuer to read the request from the queue
        self._futures: t.Deque[asyncio.Future] = collections.deque()
        # A map of request key to request ID for active requests
        self._active: t.Dict[str, str] = {}
        # A map of request key to handles for requeue callbacks
        self._handles: t.Dict[str, asyncio.TimerHandle] = {}

    def _eligible_idx(self):
        """
        Returns the index of the first request in the queue that is eligible to be dequeued.
        """
        return next(
            (
                i
                for i, (req, _) in enumerate(self._queue)
                if req.key not in self._active
            ),
            -1
        )

    def has_eligible_request(self):
        """
        Indicates if the queue has a request that is eligible to be dequeued.
        """
        return self._eligible_idx() >= 0

    def _wakeup_next_dequeue(self):
        """
        Wake up the next eligible dequeuer by resolving the first future in the queue.
        """
        while self._futures:
            future = self._futures.popleft()
            if not future.done():
                future.set_result(None)
                break

    async def dequeue(self) -> t.Tuple[Request, int]:
        """
        Remove and return a request from the queue.

        If there are no requests that are eligible to leave the queue, wait until there is one.
        """
        while True:
            # Find the index of the first request in the queue for which there is no active task
            idx = self._eligible_idx()
            # If there is such a request, extract it from the queue and return it
            if idx >= 0:
                request, attempt = self._queue.pop(idx)
                # Register the request as having an active processing task
                self._active[request.key] = request.id
                return (request, attempt)
            # If there is no such request, wait to be woken up when the situation changes
            future = asyncio.get_running_loop().create_future()
            self._futures.append(future)
            await future

    def _do_enqueue(self, request: Request, attempt: int = 0):
        # Cancel any pending requeues for the same request
        self._cancel_requeue(request)
        # Append the request to the queue
        self._queue.append((request, attempt))
        # Wake up the next waiting dequeuer
        self._wakeup_next_dequeue()

    def enqueue(self, request: Request):
        """
        Add a new request to the queue.
        """
        # If a request with the same key is in the queue, discard it
        idx = next(
            (
                i
                for i, (req, _) in enumerate(self._queue)
                if req.key == request.key
            ),
            -1
        )
        if idx >= 0:
            self._queue.pop(idx)
        # Add the new request to the end of the queue
        self._do_enqueue(request)

    def _do_requeue(self, request: Request, attempt: int):
        # If a request with the same key is already in the queue, discard this one
        # If not, enqueue it
        if not any(req.key == request.key for req, _ in self._queue):
            self._do_enqueue(request, attempt)
        else:
            self._cancel_requeue(request)

    def _cancel_requeue(self, request: Request):
        # Cancel and discard any requeue handle for the request
        handle = self._handles.pop(request.key, None)
        if handle:
            handle.cancel()

    def requeue(self, request: Request, attempt: int, delay: int):
        """
        Requeue a request after the specified delay.

        If a request with the same key is already in the queue when the delay has elapsed,
        the request is discarded.
        """
        # If there is already an existing requeue handle, cancel it
        self._cancel_requeue(request)
        # If there is already a request with the same key on the queue, there is nothing to do
        # If not, schedule a requeue after a delay
        #
        # NOTE(mkjpryor)
        # We use a callback rather than a task to schedule the requeue
        # This is because it allows us to cancel the requeue cleanly without trapping
        # CancelledError, allowing the controller as a whole to be cancelled reliably
        if not any(req.key == request.key for req, _ in self._queue):
            # Schedule the requeue for the future and stash the handle
            self._handles[request.key] = asyncio.get_running_loop().call_later(
                delay,
                self._do_requeue,
                request,
                attempt
            )
        # If a request is being requeued, assume the processing is complete
        self.processing_complete(request)

    def processing_complete(self, request: Request):
        """
        Indicates to the queue that processing for the given request is complete.
        """
        # Only clear the active record if the request ID matches
        if request.key in self._active and self._active[request.key] == request.id:
            self._active.pop(request.key)
            # Clearing the key may make another request eligible for processing
            self._wakeup_next_dequeue()
