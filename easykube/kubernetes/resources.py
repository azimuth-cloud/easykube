from .client import ResourceSpec

Binding = ResourceSpec("v1", "bindings", "Binding", True)
ComponentStatus = ResourceSpec("v1", "componentstatuses", "ComponentStatus", False)
ConfigMap = ResourceSpec("v1", "configmaps", "ConfigMap", True)
Endpoints = ResourceSpec("v1", "endpoints", "Endpoints", True)
Event = ResourceSpec("v1", "events", "Event", True)
LimitRange = ResourceSpec("v1", "limitranges", "LimitRange", True)
Namespace = ResourceSpec("v1", "namespaces", "Namespace", False)
Node = ResourceSpec("v1", "nodes", "Node", False)
PersistentVolumeClaim = ResourceSpec(
    "v1", "persistentvolumeclaims", "PersistentVolumeClaim", True
)
PersistentVolume = ResourceSpec("v1", "persistentvolumes", "PersistentVolume", False)
Pod = ResourceSpec("v1", "pods", "Pod", True)
PodTemplate = ResourceSpec("v1", "podtemplates", "PodTemplate", True)
ReplicationController = ResourceSpec(
    "v1", "replicationcontrollers", "ReplicationController", True
)
ResourceQuota = ResourceSpec("v1", "resourcequotas", "ResourceQuota", True)
Secret = ResourceSpec("v1", "secrets", "Secret", True)
ServiceAccount = ResourceSpec("v1", "serviceaccounts", "ServiceAccount", True)
Service = ResourceSpec("v1", "services", "Service", True)

MutatingWebhookConfiguration = ResourceSpec(
    "admissionregistration.k8s.io/v1",
    "mutatingwebhookconfigurations",
    "MutatingWebhookConfiguration",
    False,
)
ValidatingWebhookConfiguration = ResourceSpec(
    "admissionregistration.k8s.io/v1",
    "validatingwebhookconfigurations",
    "ValidatingWebhookConfiguration",
    False,
)

CustomResourceDefinition = ResourceSpec(
    "apiextensions.k8s.io/v1",
    "customresourcedefinitions",
    "CustomResourceDefinition",
    False,
)

APIService = ResourceSpec(
    "apiregistration.k8s.io/v1", "apiservices", "APIService", False
)

ControllerRevision = ResourceSpec(
    "apps/v1", "controllerrevisions", "ControllerRevision", True
)
DaemonSet = ResourceSpec("apps/v1", "daemonsets", "DaemonSet", True)
Deployment = ResourceSpec("apps/v1", "deployments", "Deployment", True)
ReplicaSet = ResourceSpec("apps/v1", "replicasets", "ReplicaSet", True)
StatefulSet = ResourceSpec("apps/v1", "statefulsets", "StatefulSet", True)

TokenReview = ResourceSpec(
    "authentication.k8s.io/v1", "tokenreviews", "TokenReview", False
)

LocalSubjectAccessReview = ResourceSpec(
    "authorization.k8s.io/v1",
    "localsubjectaccessreviews",
    "LocalSubjectAccessReview",
    True,
)
SelfSubjectAccessReview = ResourceSpec(
    "authorization.k8s.io/v1",
    "selfsubjectaccessreviews",
    "SelfSubjectAccessReview",
    False,
)
SelfSubjectRulesReview = ResourceSpec(
    "authorization.k8s.io/v1",
    "selfsubjectrulesreviews",
    "SelfSubjectRulesReview",
    False,
)
SubjectAccessReview = ResourceSpec(
    "authorization.k8s.io/v1", "subjectaccessreviews", "SubjectAccessReview", False
)

HorizontalPodAutoscaler = ResourceSpec(
    "autoscaling/v1", "horizontalpodautoscalers", "HorizontalPodAutoscaler", True
)

CronJob = ResourceSpec("batch/v1", "cronjobs", "CronJob", True)
Job = ResourceSpec("batch/v1", "jobs", "Job", True)

CertificateSigningRequest = ResourceSpec(
    "certificates.k8s.io/v1",
    "certificatesigningrequests",
    "CertificateSigningRequest",
    False,
)

Lease = ResourceSpec("coordination.k8s.io/v1", "leases", "Lease", True)

EndpointSlice = ResourceSpec(
    "discovery.k8s.io/v1", "endpointslices", "EndpointSlice", True
)

FlowSchema = ResourceSpec(
    "flowcontrol.apiserver.k8s.io/v1beta1", "flowschemas", "FlowSchema", False
)
PriorityLevelConfiguration = ResourceSpec(
    "flowcontrol.apiserver.k8s.io/v1beta1",
    "prioritylevelconfigurations",
    "PriorityLevelConfiguration",
    False,
)

IngressClass = ResourceSpec(
    "networking.k8s.io/v1", "ingressclasses", "IngressClass", False
)
Ingress = ResourceSpec("networking.k8s.io/v1", "ingresses", "Ingress", True)
NetworkPolicy = ResourceSpec(
    "networking.k8s.io/v1", "networkpolicies", "NetworkPolicy", True
)

RuntimeClass = ResourceSpec("node.k8s.io/v1", "runtimeclasses", "RuntimeClass", False)

PodDisruptionBudget = ResourceSpec(
    "policy/v1", "poddisruptionbudgets", "PodDisruptionBudget", True
)
PodSecurityPolicy = ResourceSpec(
    "policy/v1beta1", "podsecuritypolicies", "PodSecurityPolicy", False
)

ClusterRoleBinding = ResourceSpec(
    "rbac.authorization.k8s.io/v1", "clusterrolebindings", "ClusterRoleBinding", False
)
ClusterRole = ResourceSpec(
    "rbac.authorization.k8s.io/v1", "clusterroles", "ClusterRole", False
)
RoleBinding = ResourceSpec(
    "rbac.authorization.k8s.io/v1", "rolebindings", "RoleBinding", True
)
Role = ResourceSpec("rbac.authorization.k8s.io/v1", "roles", "Role", True)

PriorityClass = ResourceSpec(
    "scheduling.k8s.io/v1", "priorityclasses", "PriorityClass", False
)

CSIDriver = ResourceSpec("storage.k8s.io/v1", "csidrivers", "CSIDriver", False)
CSINode = ResourceSpec("storage.k8s.io/v1", "csinodes", "CSINode", False)
CSIStorageCapacity = ResourceSpec(
    "storage.k8s.io/v1beta1", "csistoragecapacities", "CSIStorageCapacity", True
)
StorageClass = ResourceSpec(
    "storage.k8s.io/v1", "storageclasses", "StorageClass", False
)
VolumeAttachment = ResourceSpec(
    "storage.k8s.io/v1", "volumeattachments", "VolumeAttachment", False
)
