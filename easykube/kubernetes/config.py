import atexit
import base64
import os
import pathlib
import ssl
import tempfile

import certifi
import yaml

from .client import AsyncClient, SyncClient


class ConfigurationError(Exception):
    """
    Raised when there is an error with the configuration.
    """


def cleanup_tempfile(path):
    """
    Cleans up the specified file in a robust way.
    """
    try:
        os.remove(path)
    except OSError:
        pass


def file_or_data(obj, file_key, data_key = None):
    """
    Returns the path to a file containing the data for the specified key.
    """
    if file_key in obj:
        return obj[file_key]
    data_key = data_key or file_key + "-data"
    if data_key in obj:
        fd, path = tempfile.mkstemp()
        os.close(fd)
        # Register an exit handler to delete the file
        atexit.register(cleanup_tempfile, path)
        with open(path, 'wb') as fd:
            fd.write(base64.standard_b64decode(obj[data_key]))
        return path
    else:
        return None


class Configuration:
    """
    Configuration object that produces clients.
    """
    SA_HOST_ENV_NAME = "KUBERNETES_SERVICE_HOST"
    SA_PORT_ENV_NAME = "KUBERNETES_SERVICE_PORT"
    SA_TOKEN_FILENAME = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    SA_CERT_FILENAME = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

    def __init__(self, **kwargs):
        self._kwargs = kwargs

    def async_client(self, **kwargs):
        """
        Returns a new asynchronous client using the configuration.
        """
        merged = self._kwargs.copy()
        merged.update(kwargs)
        return AsyncClient(**merged)

    def sync_client(self, **kwargs):
        """
        Returns a new synchronous client using the configuration.
        """
        merged = self._kwargs.copy()
        merged.update(kwargs)
        return SyncClient(**merged)

    @classmethod
    def from_kubeconfig_data(cls, data, **kwargs):
        """
        Return a configuration for the given kubeconfig data, which can be bytes or str.
        """
        kubeconfig = yaml.safe_load(data)
        # Extract the cluster and user information from the current context
        context = next(
            c["context"]
            for c in kubeconfig["contexts"]
            if c["name"] == kubeconfig["current-context"]
        )
        cluster = next(
            c["cluster"]
            for c in kubeconfig["clusters"]
            if c["name"] == context["cluster"]
        )
        user = next(
            u["user"]
            for u in kubeconfig["users"]
            if u["name"] == context["user"]
        )
        # Populate the kwargs
        if "namespace" in context:
            kwargs.setdefault("default_namespace", context["namespace"])
        kwargs.setdefault("base_url", cluster["server"])
        if "proxy-url" in cluster:
            kwargs.setdefault("proxy", cluster["proxy-url"])
        # Configure the SSL context
        if "insecure-skip-tls-verify" in cluster:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        else:
            ssl_context = ssl.create_default_context()
            ca_file = file_or_data(cluster, "certificate-authority")
            if ca_file:
                ssl_context.load_verify_locations(ca_file)
            elif os.environ.get("SSL_CERT_FILE"):
                ssl_context.load_verify_locations(os.environ["SSL_CERT_FILE"])
            elif os.environ.get("SSL_CERT_DIR"):
                ssl_context.load_verify_locations(capath = os.environ["SSL_CERT_DIR"])
            else:
                ssl_context.load_verify_locations(certifi.where())
        client_cert = file_or_data(user, "client-certificate")
        if client_cert:
            ssl_context.load_cert_chain(client_cert, file_or_data(user, "client-key"))
        else:
            raise ConfigurationError("Authentication method not supported")
        kwargs["verify"] = ssl_context
        return cls(**kwargs)

    @classmethod
    def from_kubeconfig(cls, path, **kwargs):
        """
        Return a configuration for the given kubeconfig file.
        """
        with pathlib.Path(path).open() as fh:
            data = fh.read()
        return cls.from_kubeconfig_data(data, **kwargs)

    @classmethod
    def from_serviceaccount(cls, **kwargs):
        """
        Return a configuration for the configured service account.
        """
        # The server and port come from environment variables
        server_host = os.environ.get(cls.SA_HOST_ENV_NAME)
        server_port = os.environ.get(cls.SA_PORT_ENV_NAME)
        if not server_host or not server_port:
            raise ConfigurationError("Server host/port not configured")
        kwargs.setdefault("base_url", f"https://{server_host}:{server_port}")
        # Check if the certificate file exists
        if os.path.isfile(cls.SA_CERT_FILENAME):
            kwargs.setdefault("verify", ssl.create_default_context(cafile = cls.SA_CERT_FILENAME))
        else:
            raise ConfigurationError("Service account CA file not present")
        try:
            with open(cls.SA_TOKEN_FILENAME) as fd:
                token = fd.read()
        except OSError:
            raise ConfigurationError("Could not read service account token")
        else:
            kwargs.setdefault("headers", {}).setdefault("authorization", f"bearer {token}")
        return cls(**kwargs)

    @classmethod
    def from_environment(cls, **kwargs):
        """
        Return a configuration from available information in the environment.
        """
        # An explicitly-specified kubeconfig file takes precedence
        if "KUBECONFIG" in os.environ:
            return cls.from_kubeconfig(os.environ["KUBECONFIG"], **kwargs)
        # Followed by a service account if configured
        try:
            return cls.from_serviceaccount(**kwargs)
        except ConfigurationError:
            pass
        # Lastly, the default kubeconfig location
        return cls.from_kubeconfig(pathlib.Path.home() / ".kube" / "config", **kwargs)
