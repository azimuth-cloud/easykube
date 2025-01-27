import asyncio
import logging
import random
import typing as t

from ..client import AsyncClient, LabelSelector

from .queue import Queue
from .reconcile import ReconcileFunc, Request, Result
from .util import run_tasks
from .watch import Watch
from .worker_pool import WorkerPool


logger = logging.getLogger(__name__)


LabelValue = t.Union[LabelSelector, t.List[str], str]


class Controller:
    """
    Class for a controller that watches a resource and its related resources and calls
    a reconciler whenever an object needs to be reconciled.
    """
    def __init__(
        self,
        api_version: str,
        kind: str,
        reconcile_func: ReconcileFunc,
        *,
        labels: t.Optional[t.Dict[str, LabelValue]] = None,
        namespace: t.Optional[str] = None,
        worker_count: int = 10,
        worker_pool: t.Optional[WorkerPool] = None,
        requeue_max_backoff: int = 120
    ):
        self._api_version = api_version
        self._kind = kind
        self._namespace = namespace
        self._worker_pool = worker_pool or WorkerPool(worker_count)
        self._requeue_max_backoff = requeue_max_backoff
        self._reconcile_func = reconcile_func
        self._watches: t.List[Watch] = [
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
            )
        ]

    def owns(
        self,
        api_version: str,
        kind: str,
        *,
        controller_only: bool = True
    ) -> 'Controller':
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
        return self
    
    def watches(
        self,
        api_version: str,
        kind: str,
        mapper: t.Callable[[t.Dict[str, t.Any]], t.Iterable[Request]],
        *,
        labels: t.Optional[t.Dict[str, LabelValue]] = None,
        namespace: t.Optional[str] = None
    ) -> 'Controller':
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
        return self

    def _request_logger(self, request: Request, worker_id: int):
        """
        Returns a logger for the given request.
        """
        return logging.LoggerAdapter(
            logger,
            {
                "api_version": self._api_version,
                "kind": self._kind,
                "instance": request.key,
                "request_id": request.id,
                "worker_id": worker_id,
            }
        )
    
    async def _handle_request(
        self,
        client: AsyncClient,
        queue: Queue,
        worker_id: int,
        request: Request,
        attempt: int
    ):
        """
        Start a worker that processes reconcile requests.
        """
        # Get a logger that populates parameters for the request
        logger = self._request_logger(request, worker_id)
        logger.info("Handling reconcile request (attempt %d)", attempt + 1)
        # Try to reconcile the request
        try:
            result = await self._reconcile_func(client, request)
        except asyncio.CancelledError:
            # Propagate cancellations with no further action
            raise
        except Exception:
            logger.exception("Error handling reconcile request")
            result = Result(True)
        else:
            # If the result is None, use the default result
            result = result or Result()
        # Work out whether we need to requeue or whether we are done
        if result.requeue:
            if result.requeue_after:
                delay = result.requeue_after
                # If a specific delay is requested, reset the attempts
                attempt = -1
            else:
                delay = min(2**attempt, self._requeue_max_backoff)
            # Add some jitter to the requeue
            delay = delay + random.uniform(0, 1)
            logger.info("Requeuing request after %.3fs", delay)
            queue.requeue(request, attempt + 1, delay)
        else:
            logger.info("Successfully handled reconcile request")
            # Mark the processing for the request as complete
            queue.processing_complete(request)

    async def _dispatch(self, client: AsyncClient, queue: Queue):
        """
        Pulls requests from the queue and dispatches them to the worker pool.
        """
        while True:
            # Spin until there is a request in the queue that is eligible to be dequeued
            while not queue.has_eligible_request():
                await asyncio.sleep(0.1)
            # Once we know there is an eligible request, wait to reserve a worker
            worker = await self._worker_pool.reserve()
            # Once we know we have a worker reserved, pull the request from the queue
            # and give the task to the worker to process asynchronously
            request, attempt = await queue.dequeue()
            worker.set_task(self._handle_request, client, queue, worker.id, request, attempt)

    async def run(self, client: AsyncClient):
        """
        Run the controller using the given client.
        """
        # The queue is used to spread work between the workers
        queue = Queue()
        # Run the tasks that make up the controller
        await run_tasks(
            [
                # Tasks to push requests onto the queue
                asyncio.create_task(watch.run(client, queue))
                for watch in self._watches
            ] + [
                # Task to dispatch requests to the worker pool
                asyncio.create_task(self._dispatch(client, queue)),
            ]
        )
