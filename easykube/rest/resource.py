import logging

import httpx

from ..flow import Flowable, flow  # noqa: TID252
from .iterators import ListResponseIterator
from .util import PropertyDict

logger = logging.getLogger(__name__)


class Resource(Flowable):
    """
    Class for a REST resource.
    """

    __iterator_class__ = ListResponseIterator

    def __init__(self, client, name, prefix=None):
        self._client = client
        self._name = name.strip("/")
        self._prefix = prefix or "/"
        if not self._prefix.endswith("/"):
            self._prefix = self._prefix + "/"

    def get_flow_executor(self):
        """
        Returns the flow executor to use.
        """
        return self._client.get_flow_executor()

    def _ensure_initialised(self):
        """
        Ensures that the resource is fully initialised including any HTTP operations.

        This will be called multiple times, so should become a no-op in the case where
        the resource is already initialised.
        """
        # By default, this is a noop

    def _prepare_path(self, id=None, params=None):  # noqa: A002
        """
        Prepare the path to use for the given parameters.

        Returns a (path, params) tuple where the path parameters have interpolated
        and the remaining params should be given as URL parameters.
        """
        if id:
            parts = self._name.split("/", maxsplit=1)
            parts.insert(1, id)
            return self._prefix + "/".join(parts), params
        else:
            return self._prefix + self._name, params

    def _prepare_data(self, data, id=None, params=None):  # noqa: A002
        """
        Prepare data for submitting as part of a create, replace or patch request.
        """
        return data

    def _extract_list(self, response):
        """
        Extracts a list of instances from a list response.
        """
        return response.json()

    def _extract_next_page(self, response):
        """
        Given a list response, return a (URL, params) tuple for the next page or None
        if there is no next page.
        """
        # By default, assume there is no pagination
        return None

    def _extract_one(self, response):
        """
        Extracts a single instance from a fetch, create or update response.
        """
        content_type = response.headers.get("content-type")
        if content_type == "application/json":
            return response.json()
        elif content_type == "text/plain":
            return response.text
        else:
            return response.content

    def _wrap_instance(self, instance):
        """
        Receives an instance and wraps the instance if required.
        """
        # By default, wrap the instance in a property dict
        return PropertyDict(instance) if isinstance(instance, dict) else instance

    def list(self, **params):
        """
        Returns an iterable of the resource instances that match the given parameters.
        """
        return self.__iterator_class__(self._client, self, params)

    @flow
    def first(self, **params):
        """
        Returns the first instance of a resource that matches the parameters, or None if
        one does not exist.
        """
        try:
            return (yield self.list(**params)._next_item())
        except ListResponseIterator.StopIteration:
            return None

    @flow
    def create(self, data, **params):
        """
        Creates an instance of the resource and returns it.
        """
        yield self._ensure_initialised()
        path, params = self._prepare_path(params=params)
        data = self._prepare_data(data, params=params)
        response = yield self._client.post(path, json=data, params=params)
        return self._wrap_instance(self._extract_one(response))

    @flow
    def fetch(self, id, **params):  # noqa: A002
        """
        Returns the data for the specified instance.
        """
        yield self._ensure_initialised()
        path, params = self._prepare_path(id, params)
        response = yield self._client.get(path, params=params)
        return self._wrap_instance(self._extract_one(response))

    @flow
    def replace(self, id, data, **params):  # noqa: A002
        """
        Replaces the specified instance with the given data.
        """
        yield self._ensure_initialised()
        path, params = self._prepare_path(id, params)
        data = self._prepare_data(data, id, params)
        response = yield self._client.put(path, json=data, params=params)
        return self._wrap_instance(self._extract_one(response))

    @flow
    def patch(self, id, data, **params):  # noqa: A002
        """
        Patches the specified instance with the given data.
        """
        yield self._ensure_initialised()
        path, params = self._prepare_path(id, params)
        data = self._prepare_data(data, id, params)
        response = yield self._client.patch(path, json=data, params=params)
        return self._wrap_instance(self._extract_one(response))

    def _create_or_update(self, method, id, data, params):  # noqa: A002
        """
        Flow that attempts to update an instance using the given data and method. If the
        instance does not exist, it is created with the given data.
        """
        # Always prepare the data with the id, even for a create
        data = self._prepare_data(data, id, params)
        try:
            return (yield method(id, data, **params))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return (yield self.create(data, **params))
            else:
                raise

    @flow
    def create_or_replace(self, id, data, **params):  # noqa: A002
        """
        Attempts to replace the specified instance of the resource with the given data.
        If it does not exist, a new instance is created with the given data instead.
        """
        return (yield self._create_or_update(self.replace, id, data, params))

    @flow
    def create_or_patch(self, id, data, **params):  # noqa: A002
        """
        Attempts to patch the specified instance of the resource with the given data.
        If it does not exist, a new instance is created with the given data instead.
        """
        return (yield self._create_or_update(self.patch, id, data, params))

    @flow
    def delete(self, id, data=None, **params):  # noqa: A002
        """
        Delete the specified instance.
        """
        yield self._ensure_initialised()
        path, params = self._prepare_path(id, params)
        try:
            yield self._client.delete(path, json=data, params=params)
        except httpx.HTTPStatusError as exc:
            # Suppress 404s as the desired state has been reached
            if exc.response.status_code != 404:
                raise

    @flow
    def action(self, id, action, data=None, **params):  # noqa: A002
        """
        Executes an "action" for the specified instance.

        Executing an action means making a POST request to
        `/<resourcepath>/<id>/<action>`.
        """
        yield self._ensure_initialised()
        path, params = self._prepare_path(id, params)
        # Add the action onto the path, making care to preserve any trailing slashes
        action_path = f"{path}{action}/" if path.endswith("/") else f"{path}/{action}"
        response = yield self._client.post(action_path, json=data, params=params)
        content_type = response.headers.get("content-type")
        if content_type == "application/json":
            return response.json()
        elif content_type == "text/plain":
            return response.text
        else:
            return response.content
