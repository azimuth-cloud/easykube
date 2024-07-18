import asyncio
import logging
import random
import typing as t

from ..client import AsyncClient, LabelSelector

from .queue import Queue
from .reconciler import Request, Result, Reconciler


logger = logging.getLogger(__name__)


LabelValue = t.Union[LabelSelector, t.List[str], str]


class Watch:
    """
    Watches a Kubernetes resource and produces reconcile requests.
    """
    def __init__(
        self,
        api_version: str,
        kind: str,
        mapper: t.Callable[[t.Dict[str, t.Any]], t.Iterable[Request]],
        *,
        labels: t.Optional[t.Dict[str, LabelValue]] = None,
        namespace: t.Optional[str] = None
    ):
        self._api_version = api_version
        self._kind = kind
        self._mapper = mapper
        self._labels = labels
        self._namespace = namespace

    async def run(self, client: AsyncClient, queue: Queue):
        """
        Run the watch, pushing requests onto the specified queue.
        """
        resource = await client.api(self._api_version).resource(self._kind)
        watch_kwargs = {}
        if self._labels:
            watch_kwargs["labels"] = self._labels
        if self._namespace:
            watch_kwargs["namespace"] = self._namespace
        logger.info(
            "Starting watch",
            extra = {
                "api_version": self._api_version,
                "kind": self._kind,
            }
        )
        initial, events = await resource.watch_list(**watch_kwargs)
        for obj in initial:
            for request in self._mapper(obj):
                queue.enqueue(request)
        async for event in events:
            for request in self._mapper(event["object"]):
                queue.enqueue(request)


class Controller:
    """
    Class for a controller that watches a resource and its related resources and calls
    a reconciler whenever an object needs to be reconciled.
    """
    def __init__(
        self,
        api_version: str,
        kind: str,
        *,
        labels: t.Optional[t.Dict[str, LabelValue]] = None,
        namespace: t.Optional[str] = None,
        worker_count: int = 10,
        requeue_max_backoff: int = 120,
    ):
        self._api_version = api_version
        self._kind = kind
        self._namespace = namespace
        self._worker_count = worker_count
        self._requeue_max_backoff = requeue_max_backoff
        self._watches: t.List[Watch] = [
            # Start with a watch for the controller resource that produces reconciliation
            # requests using the name and namespace from the metadata
            Watch(
                api_version,
                kind,
                lambda obj: [
                    Request(
                        obj["metadata"]["name"],
                        obj["metadata"].get("namespace")
                    ),
                ],
                labels = labels,
                namespace = namespace
            ),
        ]

    def owns(
        self,
        api_version: str,
        kind: str,
        *,
        controller_only: bool = True
    ):
        """
        Specifies child objects that the controller objects owns and that should trigger
        reconciliation of the parent object.
        """
        self._watches.append(
            Watch(
                api_version,
                kind,
                lambda obj: [
                    Request(ref["name"], obj["metadata"].get("namespace"))
                    for ref in obj["metadata"].get("ownerReferences", [])
                    if (
                        ref["apiVersion"] == self._api_version and
                        ref["kind"] == self._kind and
                        (not controller_only or ref.get("controller", False))
                    )
                ],
                namespace = self._namespace
            )
        )
    
    def watches(
        self,
        api_version: str,
        kind: str,
        mapper: t.Callable[[t.Dict[str, t.Any]], t.Iterable[Request]],
        *,
        labels: t.Optional[t.Dict[str, LabelValue]] = None,
        namespace: t.Optional[str] = None
    ):
        """
        Watches the specified resource and uses the given mapper function to produce
        reconciliation requests for the controller resource.
        """
        self._watches.append(
            Watch(
                api_version,
                kind,
                mapper,
                labels = labels,
                namespace = namespace or self._namespace
            )
        )

    def _request_logger(self, request: Request, worker_idx: int):
        """
        Returns a logger for the given request.
        """
        return logging.LoggerAdapter(
            self._logger,
            {
                "api_version": self._api_version,
                "kind": self._kind,
                "instance": request.key,
                "request_id": request.id,
                "worker_idx": worker_idx,
            }
        )
    
    async def _worker(
        self,
        client: AsyncClient,
        reconciler: Reconciler,
        queue: Queue,
        worker_idx: int
    ):
        """
        Start a worker that processes reconcile requests using the given reconciler.
        """
        while True:
            request, attempt = await queue.dequeue()
            # Get a logger that populates parameters for the request
            logger = self._request_logger(request)
            logger.info("Handling reconcile request (attempt %d)", attempt + 1)
            # Try to reconcile the request
            try:
                result = reconciler.reconcile(client, request)
            except asyncio.CancelledError:
                # Propagate cancellations with no further action
                raise
            except Exception as exc:
                # Log the exception before doing anything
                logger.exception("Error handling reconcile request")
                # Allow the reconciler to handle the exception
                # By returning a result, the reconciler can choose not to requeue the request or
                # opt for a fixed delay rather than the exponential backoff
                # If it raises an exception, the request is requeued with an exponential backoff
                try:
                    result = reconciler.handle_exception(client, request, exc)
                except NotImplementedError:
                    # If the method is not implemented, we just want to requeue with a backoff
                    result = Result(True)
                except Exception:
                    # If a different exception is raised, log that as well before requeuing
                    logger.exception("Error handling reconcile exception")
                    result = Result(True)
            # Work out whether we need to requeue or whether we are done
            if result.requeue:
                if result.requeue_after:
                    delay = result.requeue_after
                    # If a specific delay is requested, reset the attempts
                    attempt = -1
                else:
                    delay = min(2**attempt + random.uniform(0, 1), self._requeue_max_backoff)
                logger.info("Requeuing request after %ds", delay)
                queue.requeue(request, attempt + 1, delay)
            else:
                logger.info("Successfully handled reconcile request")
                # Mark the processing for the request as complete
                queue.processing_complete(request)

    async def _task_cancel_and_wait(self, task: asyncio.Task):
        """
        Cancels a task and waits for it to be done.
        """
        # We cannot wait on the task directly as we want this function to be cancellable
        # e.g. the task might be shielded from cancellation
        # Instead, we make a future that completes when the task completes and wait on that
        future = asyncio.get_running_loop().create_future()
        def callback(task: asyncio.Task):
            if not future.done():
                try:
                    # Try to resolve the future with the result of the task
                    future.set_result(task.result())
                except BaseException as exc:
                    # If the task raises an exception, resolve with that
                    future.set_exception(exc)
        task.add_done_callback(callback)
        # Cancel the task, but wait on our proxy future
        try:
            task.cancel()
            await future
        finally:
            task.remove_done_callback(callback)

    async def run(self, client: AsyncClient, reconciler: Reconciler):
        """
        Run the controller with reconciliation using the given reconciler.
        """
        # The queue is used to spread work between the workers
        queue = Queue()
        # Create the tasks that we will coordinate
        tasks = [
            # Tasks to push requests onto the queue
            asyncio.create_task(watch.run(client, queue))
            for watch in self._watches
        ] + [
            # Worker tasks to process requests
            asyncio.create_task(self._worker(client, reconciler, queue, idx))
            for idx in range(self._worker_count)
        ]
        # All of the tasks should run forever, so we exit when the first one completes
        done, not_done = await asyncio.wait(tasks, return_when = asyncio.FIRST_COMPLETED)
        for task in not_done:
            await self._task_cancel_and_wait(task)
        for task in done:
            task.result()
