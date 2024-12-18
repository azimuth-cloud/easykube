import logging
import typing as t

from ..client import AsyncClient, LabelSelector

from .queue import Queue
from .reconcile import Request


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
        else:
            watch_kwargs["all_namespaces"] = True
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
