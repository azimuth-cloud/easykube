import dataclasses
import typing as t
import uuid

from ..client import AsyncClient


@dataclasses.dataclass(frozen = True)
class Request:
    """
    Represents a request to reconcile an object.
    """
    #: The name of the object to reconcile
    name: str
    #: The namespace of the object to reconcile, or none for cluster-scoped objects
    namespace: t.Optional[str] = None
    #: The ID of the request
    id: str = dataclasses.field(default_factory = lambda: str(uuid.uuid4()))

    @property
    def key(self):
        """
        The key for the request.
        """
        return f"{self.namespace}/{self.name}" if self.namespace else self.name


@dataclasses.dataclass(frozen = True)
class Result:
    """
    Represents the result of a reconciliation.
    """
    #: Indicates whether the request should be requeued
    requeue: bool = False
    #: Indicates the time in seconds after which the request should be requeued
    #: If not given, a clamped exponential backoff is used
    requeue_after: t.Optional[int] = None


#: Type for a reconciliation function
ReconcileFunc = t.Callable[[AsyncClient, Request], t.Awaitable[t.Optional[Result]]]
