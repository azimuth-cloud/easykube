import httpx

from ... import rest  # noqa: TID252
from ...flow import flow  # noqa: TID252
from .api import Api
from .errors import ApiError


class BaseClient:
    """
    Base class for sync and async clients.
    """

    def __init__(
        self,
        /,
        # This is the name of the field manager for server-side apply
        default_field_manager="easykube",
        default_namespace="default",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.default_field_manager = default_field_manager
        self.default_namespace = default_namespace
        # Cache of API version -> API objects
        self.apis = {}
        # Cache of API group -> API version using preferred version
        self.preferred_versions = {}

    @flow
    def raise_for_status(self, response):
        # Convert response errors into ApiErrors for better messages
        try:
            yield super().raise_for_status(response)
        except httpx.HTTPStatusError as source:
            raise ApiError(source)

    def build_request(self, method, url, **kwargs):
        # For patch requests, set the content-type as merge-patch unless otherwise
        # specified
        if method.lower() == "patch":
            headers = kwargs.get("headers") or {}
            headers.setdefault("Content-Type", "application/merge-patch+json")
            kwargs["headers"] = headers
        return super().build_request(method, url, **kwargs)

    def api(self, api_version):
        """
        Returns an API object for the specified API version.
        """
        if api_version not in self.apis:
            self.apis[api_version] = Api(self, api_version)
        return self.apis[api_version]

    @flow
    def api_preferred_version(self, group):
        """
        Returns an API object for the given group at the preferred version.
        """
        if group not in self.preferred_versions:
            response = yield self.get(f"/apis/{group}")
            api_version = response.json()["preferredVersion"]["groupVersion"]
            self.preferred_versions[group] = api_version
        return self.api(self.preferred_versions[group])

    def _resource_for_object(self, object):  # noqa: A002
        """
        Returns a resource for the given object.
        """
        # Get the resource using the api version and kind from the object
        api_version = object["apiVersion"]
        kind = object["kind"]
        return (yield self.api(api_version).resource(kind))

    @flow
    def create_object(self, object):  # noqa: A002
        """
        Create the given object.
        """
        resource = yield self._resource_for_object(object)
        namespace = object["metadata"].get("namespace")
        return (yield resource.create(object, namespace=namespace))

    @flow
    def replace_object(self, object):  # noqa: A002
        """
        Replace the given object with the specified state.
        """
        resource = yield self._resource_for_object(object)
        name = object["metadata"]["name"]
        namespace = object["metadata"].get("namespace")
        return (yield resource.replace(name, object, namespace=namespace))

    @flow
    def patch_object(self, object, patch):  # noqa: A002
        """
        Apply the given patch to the specified object.
        """
        resource = yield self._resource_for_object(object)
        name = object["metadata"]["name"]
        namespace = object["metadata"].get("namespace")
        return (yield resource.patch(name, patch, namespace=namespace))

    @flow
    def delete_object(self, object):  # noqa: A002
        """
        Delete the specified object.
        """
        resource = yield self._resource_for_object(object)
        name = object["metadata"]["name"]
        namespace = object["metadata"].get("namespace")
        return (yield resource.delete(name, namespace=namespace))

    @flow
    def apply_object(self, object, /, field_manager=None, force=False):  # noqa: A002
        """
        Applies the given object using server-side apply.

        See https://kubernetes.io/docs/reference/using-api/server-side-apply/.
        """
        resource = yield self._resource_for_object(object)
        name = object["metadata"]["name"]
        namespace = object["metadata"].get("namespace")
        return (
            yield resource.server_side_apply(
                name,
                object,
                field_manager=field_manager,
                namespace=namespace,
                force=force,
            )
        )

    @flow
    def client_side_apply_object(self, object):  # noqa: A002
        """
        Create or update the given object, equivalent to "kubectl apply".
        """
        resource = yield self._resource_for_object(object)
        name = object["metadata"]["name"]
        namespace = object["metadata"].get("namespace")
        return (yield resource.create_or_replace(name, object, namespace=namespace))


class SyncClient(BaseClient, rest.SyncClient):
    """
    Sync client for Kubernetes.
    """


class AsyncClient(BaseClient, rest.AsyncClient):
    """
    Async client for Kubernetes.
    """
