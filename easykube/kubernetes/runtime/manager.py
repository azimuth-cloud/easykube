import asyncio
import typing as t

from ..client import AsyncClient, LabelSelector

from .controller import Controller, ReconcileFunc
from .util import run_tasks


LabelValue = t.Union[LabelSelector, t.List[str], str]


class Manager:
    """
    Manages the execution of multiple controllers with shared resources.
    """
    def __init__(
        self,
        *, 
        namespace: t.Optional[str] = None,
        worker_count: int = 10,
        requeue_max_backoff: int = 120
    ):
        self._namespace = namespace
        self._worker_count = worker_count
        self._requeue_max_backoff = requeue_max_backoff
        self._controllers: t.List[Controller] = []

    def register_controller(self, controller: Controller) -> 'Manager':
        """
        Register the given controller with this manager.
        """
        self._controllers.append(controller)
        return self

    def create_controller(
        self,
        api_version: str,
        kind: str,
        reconcile_func: ReconcileFunc,
        *,
        labels: t.Optional[t.Dict[str, LabelValue]] = None,
        namespace: t.Optional[str] = None,
        worker_count: t.Optional[int] = None,
        requeue_max_backoff: t.Optional[int] = None
    ) -> Controller:
        """
        Creates a new controller that is registered with this manager.
        """
        controller = Controller(
            api_version,
            kind,
            reconcile_func,
            labels = labels,
            namespace = namespace or self._namespace,
            worker_count = worker_count or self._worker_count,
            requeue_max_backoff = requeue_max_backoff or self._requeue_max_backoff
        )
        self.register_controller(controller)
        return controller

    async def run(self, client: AsyncClient):
        """
        Run all the controllers registered with the manager using the given client.
        """
        assert len(self._controllers) > 0, "no controllers registered"

        # Run a task for each controller
        await run_tasks([
            asyncio.create_task(controller.run(client))
            for controller in self._controllers
        ])
