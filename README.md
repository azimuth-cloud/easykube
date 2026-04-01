# easykube

A simple Python client for Kubernetes, providing both synchronous and asynchronous implementations.

## Creating a client

Clients are created using `Configuration` objects. A single `Configuration` object can produce
multiple clients, both synchronous or asynchronous.

```python
import easykube


#####
# Initialise a configuration object
#####

# From kubeconfig data as str or bytes
# Currently, only certificate authentication is supported
config = easykube.Configuration.from_kubeconfig_data(data)
# From the kubeconfig file at the given path
config = easykube.Configuration.from_kubeconfig(path)
# From a service account
config = easykube.Configuration.from_serviceaccount()
# From the environment, using the following (in order of precedence)
#   * kubeconfig file specified using KUBECONFIG environment variable if present
#   * service account if environment variables are present
#   * kubeconfig file at $HOME/.kube/config
config = easykube.Configuration.from_environment()


#####
# Create a sync or async client from the configuration
#
# Clients should be used in a context to ensure connections are properly disposed
#####

# Optionally specify a default namespace for the client
# Defaults to the namespace from the kubeconfig if present, "default" otherwise
with config.sync_client(default_namespace="default") as sync_client:
    do_something(sync_client)

async with config.async_client(default_namespace="default") as async_client:
    await do_something(async_client)
```

## Interacting with Kubernetes objects

All objects in Kubernetes are part of an API (e.g. `v1`, `networking.k8s.io/v1`) and a
resource (e.g. `pods`, `ingresses`).

The client provides methods for consuming APIs and resources and performing operations
on their objects, including subresources like pod logs, status and scale subresources.

```python
#####
# Consume a particular resource, e.g. pods, ingresses
#####
sync_pods = sync_client.api("v1").resource("pods")
async_pods = await async_client.api("v1").resource("pods")

sync_ingresses = sync_client.api("networking.k8s.io/v1").resource("ingresses")
async_ingresses = await async_client.api("networking.k8s.io/v1").resource("ingresses")

#####
# Consume a subresource
#   e.g. pod logs, status subresource
#####
sync_pod_logs = sync_client.api("v1").resource("pods/log")
async_pod_logs = await async_client.api("v1").resource("pods/log")
#   e.g. the status of a custom resource when writing controllers
sync_custom_status = sync_client.api("example.com/v1").resource("myresource/status")
async_custom_status = await async_client.api("example.com/v1").resource("myresource/status")
```

### Listing objects

```python
for obj in sync_resource.list(
    # The namespace to list resources in, defaults to the client's default namespace
    namespace="myns",
    # Whether to list resources in all namespaces (default false)
    all_namespaces=True | False,
    # Labels to match, default none
    labels={
        # Match a single value
        "label1": "value1",
        # Match one of a set of values
        "label2": ["value2", "value3", "value4"],
        # Require label to be present with any value
        "label3": easykube.PRESENT,
        # Require label to be absent
        "label4": easykube.ABSENT,
    },
    # Additional kwargs arguments are passed as URL parameters
    **kwargs
):
    do_something(obj)


# Async client produces an async iterator when listing
# Supports the same parameters as the synchronous list
async for obj in async_resource.list(...):
    await do_something(obj)
```

### Fetching individual objects

When fetching a single object by name using `fetch`, the type of the returned object is
determined using the `Content-Type` of the response. For `application/json` responses,
the object is decoded and the Python object is returned. For `text/plain` responses,
the text is returned as a `str`. For all other responses, the received bytes are returned.

```python
# Fetch the first object that matches a list query, or None if there are no matches
# Supports the same parameters as list
obj = sync_resource.first(...)
obj = await async_resource.first(...)

# Fetch a single object by name
obj = sync_resource.fetch(
    name,
    # The namespace that the object is in, defaults to the client's default namespace
    namespace="myns",
    # Additional kwargs arguments are passed as URL parameters
    **kwargs
)
obj = await async_resource.fetch(...)
```

#### Example - reading pod logs

`fetch` allows additional parameters to be specified which are passed as URL parameters.
This can be useful when reading pod logs as there are
[several parameters](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.33/#read-log-pod-v1-core)
you can use to control the logs that are returned.

```python
async_pod_logs = await async_client.api("v1").resource("pods/log")

# Fetch the logs for a specific container
logs = await async_pod_logs.fetch(name, namespace="myns", container="container1")

# Fetch the logs for the last 60 seconds only
logs = await async_pod_logs.fetch(name, namespace="myns", sinceSeconds=60)

# Fetch only the last 10 lines of logs
logs = await async_pod_logs.fetch(name, namespace="myns", tailLines=10)
```

### Creating objects

```python
obj = sync_resource.create(data, namespace="myns")
obj = await async_resource.create(...)
```

### Updating objects

There are various ways to fully or partially update an object. See the
[Kubernetes docs](https://kubernetes.io/docs/reference/using-api/api-concepts/#patch-and-apply)
for more details.

```python
# Replace the whole object using a PUT request
# The metadata.resourceVersion must match the version that the server has
obj = sync_resource.replace(name, data, namespace="myns")
obj = await async_resource.replace(...)

# Update an object using a PATCH request and a JSON merge formatted patch
obj = sync_resource.patch(name, data, namespace="myns")
obj = await async_resource.patch(...)

# Update an object using a PATCH request and a JSON patch formatted patch
obj = sync_resource.json_patch(name, data, namespace="myns")
obj = await async_resource.json_patch(...)

# Update an object using server-side apply
# https://kubernetes.io/docs/reference/using-api/server-side-apply/
obj = sync_resource.server_side_apply(name, data, namespace="myns", force=True)
obj = await async_resource.server_side_apply(...)
```

### Deleting objects

Kubernetes allows for different ways of propagating deletion to dependent objects. For more
information, see the [Kubernetes docs](https://kubernetes.io/docs/tasks/administer-cluster/use-cascading-deletion/).

```python
# Delete a single object by name
obj = sync_resource.delete(
    name,
    namespace="myns",
    # The propagation policy to use
    # One of BACKGROUND, FOREGROUND or ORPHAN
    propagation_policy=easykube.DeletePropagationPolicy.BACKGROUND
)
obj = await async_resource.delete(...)

# Delete a collection of objects matching the given arguments
# Supports the same arguments as list
obj = sync_resource.delete_all(...)
obj = await async_resource.delete_all(...)
```

### Watching objects

`easykube` allows synchronous and asynchronous watching of objects.

Both `watch_list` and `watch_one` return a tuple of the initial state and an iterator of events.

For `watch_list`, the initial state is a list of objects. For `watch_one`, the initial state
is a single object or `None` if the object does not exist.

The events that are produced have the format:

```python
{
    "type": "ADDED" | "MODIFIED" | "DELETED",
    "object": {
        # ... the state of the object when the event was produced ...
    }
}
```

```python
#####
# Watch a collection of objects
#####
# Supports the same arguments as list
initial_state, sync_events = sync_resource.watch_list(...)
initial_state, async_events = await async_resource.watch_list(...)

# Process the initial state
# The initial state is always a regular list for both sync and async resources
for obj in initial_state:
    do_something(obj)

# Process events (synchronous)
for event in sync_events:
    process_event(event["type"], event["object"])

# Process events (asynchronous)
async for event in async_events:
    await process_event(event["type"], event["object"])


#####
# Watch a single object
#####
initial_state, events = sync_resource.watch_one(name, namespace="myns")
initial_state, events = await async_resource.watch_one(name, namespace="myns")
```

## Client-level methods

As well as interacting directly with individual resources, the client provides some top-level
convenience methods that operate on "fully-formed" Kubernetes objects that already include
information about their API, resource, name and namespace via the `apiVersion`, `kind`,
`metadata.name` and `metadata.namespace` fields.

The `apply_object` function is particularly useful for keeping an object consistent with
the expected representation, e.g. in a controller, using server-side apply.


```python
#####
# Create an object
#####
obj = sync_client.create_object(obj)
obj = await async_client.create_object(obj)

#####
# Replace an entire object
#####
obj = sync_client.replace_object(obj)
obj = await async_client.replace_object(obj)

#####
# Patch an object
#####
patch = {"data": {"key2": "value2-1", "key3": "value3"}}
obj = sync_client.patch_object(obj, patch)
obj = await async_client.patch_object(obj, patch)

#####
# Delete an object
#####
obj = sync_client.delete_object(obj)
obj = await async_client.delete_object(obj)

#####
# Apply an object using server-side apply
# https://kubernetes.io/docs/reference/using-api/server-side-apply/
#####
obj = sync_client.apply_object(obj, force = True)
obj = await async_client.apply_object(obj, force = True)

#####
# Apply an object from the client-side using a "create-or-update" pattern
# This is similar to what "kubectl apply" does but does not use an annotation
#####
obj = sync_client.client_side_apply_object(obj)
obj = await async_client.client_side_apply_object(obj)
```
