import asyncio
import typing as t

from .util import run_tasks


class WorkerNotAvailable(RuntimeError):
    """
    Raised when a task is scheduled to a worker that already has a task.
    """


P = t.ParamSpec("P")
T = t.TypeVar("T")


Task = t.Tuple[t.Callable[P, t.Awaitable[T]], t.ParamSpecArgs, t.ParamSpecKwargs]


class Worker:
    """
    Represents a worker in a pool.
    """
    def __init__(self, pool: 'WorkerPool', id: int):
        self._pool = pool
        self._id = id
        self._available = True
        self._task: t.Optional[Task] = None

    @property
    def id(self):
        """
        The ID of the worker.
        """
        return self._id

    @property
    def available(self):
        """
        Indicates whether the worker is available.
        """
        return self._available and not self._task

    def reserve(self) -> 'Worker':
        """
        Reserve the worker by marking it as unavailable, even if no task is set yet.
        """
        self._available = False
        return self

    def set_task(
        self,
        func: t.Callable[P, t.Awaitable[T]],
        *args: P.args,
        **kwargs: P.kwargs
    ):
        """
        Run the specified function call using the worker.
        """
        if self._task:
            raise WorkerNotAvailable
        else:
            self._task = (func, args, kwargs)
            return self

    async def run(self):
        """
        Run the worker.
        """
        # We run forever, picking up and executing our task as it is set
        while True:
            if self._task:
                func, args, kwargs = self._task
                try:
                    await func(*args, **kwargs)
                finally:
                    self._available = True
                    self._task = None
            else:
                # Just relinquish control for now to allow another coroutine to run
                await asyncio.sleep(0.1)


class WorkerPool:
    """
    Represents a worker pool.
    """
    def __init__(self, worker_count):
        self._workers = [Worker(self, idx) for idx in range(worker_count)]

    async def reserve(self) -> Worker:
        """
        Returns an available worker or spins until one becomes available.
        """
        while True:
            try:
                worker = next(w for w in self._workers if w.available)
            except StopIteration:
                await asyncio.sleep(0.1)
            else:
                return worker.reserve()

    async def run(self):
        """
        Run the workers in the pool.
        """
        await run_tasks([w.run() for w in self._workers])
