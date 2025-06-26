import dataclasses

from .resource import Resource


@dataclasses.dataclass
class ResourceSpec:
    """
    Specification for a Kubernetes API resource.
    """

    #: The API version, including group, of the resource
    api_version: str
    #: The name of the resource
    name: str
    #: The kind of the resource
    kind: str | None = None
    #: Whether or not the resource is namespaced
    namespaced: bool | None = None

    def __call__(self, client):
        """
        Return a resource instance for the given client.
        """
        return Resource(client, self.api_version, self.name, self.kind, self.namespaced)

    @classmethod
    def from_crd(cls, crd):
        """
        Returns a resource spec for the given CRD definition.
        """
        api_group = crd["spec"]["group"]
        preferred_version = next(
            version["name"]
            for version in crd["spec"]["versions"]
            if version.get("storage", False)
        )
        api_version = f"{api_group}/{preferred_version}"
        name = crd["spec"]["names"]["plural"]
        kind = crd["spec"]["names"]["kind"]
        namespaced = crd["spec"]["scope"] == "Namespaced"
        return cls(api_version, name, kind, namespaced)
