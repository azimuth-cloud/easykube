import dataclasses
import typing
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
    namespace: typing.Optional[str] = None
    #: The ID of the request
    id: str = dataclasses.field(default_factory = lambda: str(uuid.uuid4()))

    @property
    def key(self):
        """
        The key for the request.
        """
        return f"{self.namespace}/{self.name}"


@dataclasses.dataclass(frozen = True)
class Result:
    """
    Represents the result of a reconciliation.
    """
    #: Indicates whether the request should be requeued
    requeue: bool = False
    #: Indicates the time in seconds after which the request should be requeued
    #: If not given, a clamped exponential backoff is used
    requeue_after: typing.Optional[int] = None


class Reconciler:
    """
    Base class for a reconciler.
    """
    def reconcile(self, client: AsyncClient, request: Request) -> Result:
        """
        Reconcile the given request.
        """
        raise NotImplementedError

    def handle_exception(self, client: AsyncClient, request: Request, exc: Exception) -> Result:
        """
        Handle an exception that occured while processing a request.
        """
        raise NotImplementedError
