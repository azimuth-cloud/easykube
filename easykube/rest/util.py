from yaml.representer import SafeRepresenter


class PropertyDict(dict):
    """
    Dictionary that also supports property access.
    """

    def __init__(self, *args, **kwargs):
        super().__init__({k: self._wrap(v) for k, v in dict(*args, **kwargs).items()})

    def _wrap(self, value):
        if isinstance(value, PropertyDict):
            return value
        elif isinstance(value, dict):
            return PropertyDict(value)
        else:
            return value

    def __setitem__(self, key, value):
        super().__setitem__(key, self._wrap(value))

    def setdefault(self, key, default=None):
        return super().setdefault(key, self._wrap(default))

    def update(self, *args, **kwargs):
        super().update({k: self._wrap(v) for k, v in dict(*args, **kwargs).items()})

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(
                f"'{self.__class__.__name__}' has no attribute '{name}'"
            )

    def __repr__(self):
        return f"{self.__class__.__name__}({super().__repr__()})"


# Make sure that YAML represents a PropertyDict like a regular dict
SafeRepresenter.add_representer(PropertyDict, SafeRepresenter.represent_dict)
