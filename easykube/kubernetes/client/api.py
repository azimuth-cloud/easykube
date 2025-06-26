from ...flow import Flowable, flow  # noqa: TID252
from .resource import Resource


class Api(Flowable):
    """
    Class for a Kubernetes API.
    """

    def __init__(self, client, api_version):
        self._client = client
        self._api_version = api_version
        self._resources = None

    def get_flow_executor(self):
        """
        Returns the flow executor to use.
        """
        return self._client.get_flow_executor()

    @property
    def api_version(self):
        """
        Returns the API version for the API.
        """
        return self._api_version

    def _ensure_resources(self, refresh_cache=False):
        """
        Ensures that the resources have been loaded.
        """
        if self._resources is None or refresh_cache:
            prefix = "/apis" if "/" in self._api_version else "/api"
            response = yield self._client.get(f"{prefix}/{self._api_version}")
            self._resources = {r["name"]: r for r in response.json()["resources"]}
        return self._resources

    @flow
    def resources(self):
        """
        Returns the resources for the API.
        """
        resources = yield self._ensure_resources()
        return resources.values()

    def _resource(self, name, refresh_cache=False):
        resources = yield self._ensure_resources(refresh_cache)
        # First try a lookup by plural name
        try:
            resource = resources[name]
        except KeyError:
            # Then try a lookup by singular name or kind
            try:
                resource = next(
                    r
                    for r in resources.values()
                    if r["kind"] == name or r["singularName"] == name
                )
            except StopIteration:
                raise ValueError(f"API '{self._api_version}' has no resource '{name}'")
        return Resource(
            self._client,
            self._api_version,
            resource["name"],
            resource["kind"],
            resource["namespaced"],
        )

    @flow
    def resource(self, name):
        """
        Returns a resource for the given name.

        The given name can be either the plural name, the singular name or the kind.
        Lookups by plural name will be faster as that is the key that is indexed.
        """
        # Try once using the cached resources
        # If that fails, try again with a refreshed cache
        # If that still fails, raise
        try:
            return (yield self._resource(name))
        except ValueError:
            return (yield self._resource(name, True))
