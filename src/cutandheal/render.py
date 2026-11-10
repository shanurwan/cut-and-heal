"""Render a scenario into Kubernetes manifests. Pure: same inputs, same YAML.

Regions map to Kubernetes nodes through a node label. Every node owns a pod CIDR, so a
region's pods share an address range that the shaper can match, the way a country's
networks share prefixes. Nothing here knows pod IPs; the controller reads those at run time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources

import yaml

from .kube import REGION_LABEL, ROLE_LABEL
from .model import Scenario

# The system under test is the DST team's own gossipsub regression node, pinned by digest.
# The bootstrap tag really is `v.2.4.0`: that is how it is published.
NODE_IMAGE = (
    "albertodst/regression-node-amd64:v2.4.0@sha256:fee857220664d269792f360734b9a819f0317dcfceeaa3edc3abd9c531a33988"
)
BOOTSTRAP_IMAGE = (
    "albertodst/regression-bootstrap-amd64:v.2.4.0"
    "@sha256:d136b5f44cfd315a68e2e9680cd2b1eb7489b8566f9bfedba5349046f000d944"
)
VM_IMAGE = "victoriametrics/victoria-metrics:v1.156.0"
GRAFANA_IMAGE = "grafana/grafana:11.4.0"
CONTROL_LABEL = "cut-and-heal/control"


@dataclass(frozen=True)
class RenderOptions:
    namespace: str
    run_id: str
    seed: int
    controller_image: str
    node_image: str = NODE_IMAGE
    bootstrap_image: str = BOOTSTRAP_IMAGE
    vm_image: str = VM_IMAGE
    grafana_image: str = GRAFANA_IMAGE
    metrics: bool = True
    grafana: bool = False
    settle_s: int = 45
    lead_s: int = 20


def _meta(name: str, ns: str, **labels: str) -> dict:
    return {"name": name, "namespace": ns, "labels": {"app.kubernetes.io/part-of": "cut-and-heal", **labels}}


def _region_selector(region: str) -> dict:
    return {REGION_LABEL: region}


def _node_statefulset(scn: Scenario, region: str, opt: RenderOptions) -> dict:
    labels = {ROLE_LABEL: "node", REGION_LABEL: region}
    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": _meta(region, opt.namespace, **labels),
        "spec": {
            "serviceName": "nodes",
            "replicas": scn.regions[region].nodes,
            # Parallel: an ordered rollout of hundreds of pods takes longer than the run.
            "podManagementPolicy": "Parallel",
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "nodeSelector": _region_selector(region),
                    "terminationGracePeriodSeconds": 5,
                    "automountServiceAccountToken": False,
                    "enableServiceLinks": False,
                    "containers": [
                        {
                            "name": "node",
                            "image": opt.node_image,
                            "env": [
                                {"name": "SERVICE", "value": "bootstrap"},
                                {"name": "MUXER", "value": "yamux"},
                            ],
                            "ports": [
                                {"name": "libp2p", "containerPort": 5000},
                                {"name": "metrics", "containerPort": 8008},
                                {"name": "publish", "containerPort": 8645},
                            ],
                            "resources": {"requests": {"cpu": "10m", "memory": "24Mi"}},
                        },
                        {
                            "name": "shaper",
                            # Same image as the node: it already ships tc, bash and curl,
                            # so a pod pulls nothing extra.
                            "image": opt.node_image,
                            "command": ["/usr/bin/bash", "/shaper/shaper.sh"],
                            "env": [
                                {"name": "POD_NAME", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
                                {"name": "CAH_CONTROLLER", "value": "http://controller:8080"},
                            ],
                            "securityContext": {"capabilities": {"add": ["NET_ADMIN"]}},
                            "volumeMounts": [{"name": "shaper", "mountPath": "/shaper"}],
                            # Within a pod the shaper outranks the node for CPU: it runs for
                            # milliseconds per phase and must not wait behind gossip to do so.
                            "resources": {"requests": {"cpu": "15m", "memory": "8Mi"}},
                        },
                    ],
                    "volumes": [{"name": "shaper", "configMap": {"name": "shaper"}}],
                },
            },
        },
    }


def _bootstrap(scn: Scenario, opt: RenderOptions) -> list[dict]:
    labels = {ROLE_LABEL: "bootstrap", REGION_LABEL: scn.bootstrap_region}
    return [
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": _meta("bootstrap", opt.namespace),
            "spec": {"clusterIP": "None", "selector": labels, "ports": [{"name": "libp2p", "port": 5000}]},
        },
        {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": _meta("bootstrap", opt.namespace, **labels),
            "spec": {
                "serviceName": "bootstrap",
                "replicas": 1,
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "nodeSelector": _region_selector(scn.bootstrap_region),
                        "terminationGracePeriodSeconds": 5,
                        "automountServiceAccountToken": False,
                        "enableServiceLinks": False,
                        "containers": [
                            {
                                "name": "bootstrap",
                                "image": opt.bootstrap_image,
                                "ports": [{"name": "libp2p", "containerPort": 5000}],
                                "resources": {"requests": {"cpu": "20m", "memory": "24Mi"}},
                            }
                        ],
                    },
                },
            },
        },
    ]


def _controller(scn: Scenario, opt: RenderOptions, scenario_yaml: str) -> list[dict]:
    ns = opt.namespace
    images = {"node": opt.node_image, "bootstrap": opt.bootstrap_image, "controller": opt.controller_image}
    env = {
        "CAH_RUN_ID": opt.run_id,
        "CAH_SEED": str(opt.seed),
        "CAH_SETTLE_S": str(opt.settle_s),
        "CAH_LEAD_S": str(opt.lead_s),
        "CAH_IMAGES": json.dumps(images, sort_keys=True),
        "CAH_VM_URL": "http://metrics:8428" if opt.metrics else "",
    }
    return [
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": _meta("controller", ns)},
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "Role",
            "metadata": _meta("controller", ns),
            "rules": [{"apiGroups": [""], "resources": ["pods", "pods/log"], "verbs": ["get", "list"]}],
        },
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": _meta("controller", ns),
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "controller"},
            "subjects": [{"kind": "ServiceAccount", "name": "controller", "namespace": ns}],
        },
        # Pod CIDRs live on Node objects, which are cluster-scoped: read-only, nodes only.
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": f"cut-and-heal-{ns}"},
            "rules": [{"apiGroups": [""], "resources": ["nodes"], "verbs": ["get", "list"]}],
        },
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": f"cut-and-heal-{ns}"},
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": f"cut-and-heal-{ns}"},
            "subjects": [{"kind": "ServiceAccount", "name": "controller", "namespace": ns}],
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": _meta("scenario", ns),
            "data": {"scenario.yaml": scenario_yaml},
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": _meta("shaper", ns),
            "data": {
                "shaper.sh": resources.files("cutandheal.assets").joinpath("shaper.sh").read_text(encoding="utf-8")
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": _meta("controller", ns),
            "spec": {"selector": {ROLE_LABEL: "controller"}, "ports": [{"port": 8080}]},
        },
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": _meta("controller", ns, **{ROLE_LABEL: "controller"}),
            "spec": {
                "serviceAccountName": "controller",
                "restartPolicy": "Never",
                "nodeSelector": {CONTROL_LABEL: "true"},
                "enableServiceLinks": False,
                "containers": [
                    {
                        "name": "controller",
                        "image": opt.controller_image,
                        "imagePullPolicy": "IfNotPresent",
                        "command": ["python", "-m", "cutandheal.controller"],
                        "env": [{"name": k, "value": v} for k, v in env.items()],
                        "ports": [{"containerPort": 8080}],
                        "readinessProbe": {"httpGet": {"path": "/v1/status", "port": 8080}, "periodSeconds": 2},
                        "volumeMounts": [
                            {"name": "scenario", "mountPath": "/config"},
                            {"name": "results", "mountPath": "/results"},
                        ],
                        "resources": {"requests": {"cpu": "500m", "memory": "256Mi"}},
                    }
                ],
                "volumes": [
                    {"name": "scenario", "configMap": {"name": "scenario"}},
                    {"name": "results", "emptyDir": {}},
                ],
            },
        },
    ]


def _metrics(opt: RenderOptions) -> list[dict]:
    ns = opt.namespace
    scrape = {
        "global": {"scrape_interval": "5s", "scrape_timeout": "4s"},
        "scrape_configs": [
            {
                "job_name": "nodes",
                "kubernetes_sd_configs": [{"role": "pod", "namespaces": {"names": [ns]}}],
                "relabel_configs": [
                    {
                        "source_labels": ["__meta_kubernetes_pod_label_cut_and_heal_role"],
                        "regex": "node",
                        "action": "keep",
                    },
                    {
                        "source_labels": ["__meta_kubernetes_pod_container_port_name"],
                        "regex": "metrics",
                        "action": "keep",
                    },
                    {"source_labels": ["__meta_kubernetes_pod_label_cut_and_heal_region"], "target_label": "region"},
                    {"source_labels": ["__meta_kubernetes_pod_name"], "target_label": "pod"},
                ],
            }
        ],
    }
    labels = {ROLE_LABEL: "metrics"}
    return [
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": _meta("metrics", ns)},
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "Role",
            "metadata": _meta("metrics", ns),
            "rules": [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "watch"]}],
        },
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": _meta("metrics", ns),
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "metrics"},
            "subjects": [{"kind": "ServiceAccount", "name": "metrics", "namespace": ns}],
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": _meta("metrics", ns),
            "data": {"scrape.yaml": yaml.safe_dump(scrape, sort_keys=False)},
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": _meta("metrics", ns),
            "spec": {"selector": labels, "ports": [{"port": 8428}]},
        },
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": _meta("metrics", ns, **labels),
            "spec": {
                "serviceAccountName": "metrics",
                "nodeSelector": {CONTROL_LABEL: "true"},
                "enableServiceLinks": False,
                "containers": [
                    {
                        "name": "victoria-metrics",
                        "image": opt.vm_image,
                        "args": [
                            "-promscrape.config=/config/scrape.yaml",
                            "-storageDataPath=/data",
                            "-retentionPeriod=1",
                            "-search.latencyOffset=1s",
                        ],
                        "ports": [{"containerPort": 8428}],
                        "volumeMounts": [
                            {"name": "config", "mountPath": "/config"},
                            {"name": "data", "mountPath": "/data"},
                        ],
                        "resources": {"requests": {"cpu": "200m", "memory": "256Mi"}},
                    }
                ],
                "volumes": [
                    {"name": "config", "configMap": {"name": "metrics"}},
                    {"name": "data", "emptyDir": {}},
                ],
            },
        },
    ]


DASHBOARD_PANELS = [
    ("Mesh peers per node, mean", "avg by (region) (libp2p_gossipsub_peers_per_topic_mesh)", "short"),
    ("Mesh peers per node, lowest", "min by (region) (libp2p_gossipsub_peers_per_topic_mesh)", "short"),
    ("Nodes with no mesh peers", "sum by (region) (libp2p_gossipsub_no_peers_topics)", "short"),
    ("Connected peers per node, mean", "avg by (region) (libp2p_peers)", "short"),
    ("Bytes sent", 'sum by (region) (rate(libp2p_network_bytes_total{direction="out"}[20s]))', "Bps"),
    ("Busiest sender", 'max by (region) (rate(libp2p_network_bytes_total{direction="out"}[20s]))', "Bps"),
    ("Dial attempts", "sum by (region) (rate(libp2p_total_dial_attempts_total[20s]))", "ops"),
    ("Failed dials", "sum by (region) (rate(libp2p_failed_dials_total[20s]))", "ops"),
]


def dashboard() -> dict:
    """One panel per question a run raises: is the mesh whole, who carries the traffic, who is redialling."""
    panels = []
    for i, (title, expr, unit) in enumerate(DASHBOARD_PANELS):
        panels.append(
            {
                "id": i + 1,
                "type": "timeseries",
                "title": title,
                "datasource": {"type": "prometheus", "uid": "metrics"},
                "gridPos": {"h": 7, "w": 12, "x": 12 * (i % 2), "y": 7 * (i // 2)},
                "fieldConfig": {"defaults": {"unit": unit, "min": 0, "custom": {"lineWidth": 2, "fillOpacity": 0}}},
                "targets": [{"expr": expr, "legendFormat": "{{region}}", "refId": "A"}],
            }
        )
    return {
        "uid": "cut-and-heal",
        "title": "cut-and-heal",
        "timezone": "utc",
        "refresh": "5s",
        "time": {"from": "now-45m", "to": "now"},
        "schemaVersion": 39,
        "panels": panels,
    }


def _grafana(opt: RenderOptions) -> list[dict]:
    ns = opt.namespace
    labels = {ROLE_LABEL: "grafana"}
    datasource = {
        "apiVersion": 1,
        "datasources": [
            {"name": "metrics", "uid": "metrics", "type": "prometheus", "url": "http://metrics:8428", "isDefault": True}
        ],
    }
    provider = {
        "apiVersion": 1,
        "providers": [{"name": "cut-and-heal", "type": "file", "options": {"path": "/dashboards"}}],
    }
    mounts = [
        ("/etc/grafana/provisioning/datasources/datasource.yaml", "datasource.yaml"),
        ("/etc/grafana/provisioning/dashboards/provider.yaml", "provider.yaml"),
        ("/dashboards/cut-and-heal.json", "cut-and-heal.json"),
    ]
    env = {
        # A read-only viewer on a cluster-internal service; reach it with a port-forward.
        "GF_AUTH_ANONYMOUS_ENABLED": "true",
        "GF_AUTH_ANONYMOUS_ORG_ROLE": "Viewer",
        "GF_AUTH_DISABLE_LOGIN_FORM": "true",
        "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH": "/dashboards/cut-and-heal.json",
    }
    return [
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": _meta("grafana", ns),
            "data": {
                "datasource.yaml": yaml.safe_dump(datasource, sort_keys=False),
                "provider.yaml": yaml.safe_dump(provider, sort_keys=False),
                "cut-and-heal.json": json.dumps(dashboard(), indent=1),
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": _meta("grafana", ns),
            "spec": {"selector": labels, "ports": [{"port": 3000}]},
        },
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": _meta("grafana", ns, **labels),
            "spec": {
                "nodeSelector": {CONTROL_LABEL: "true"},
                "enableServiceLinks": False,
                "automountServiceAccountToken": False,
                "containers": [
                    {
                        "name": "grafana",
                        "image": opt.grafana_image,
                        "env": [{"name": k, "value": v} for k, v in env.items()],
                        "ports": [{"containerPort": 3000}],
                        "volumeMounts": [{"name": "config", "mountPath": m, "subPath": f} for m, f in mounts],
                        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}},
                    }
                ],
                "volumes": [{"name": "config", "configMap": {"name": "grafana"}}],
            },
        },
    ]


def render(scn: Scenario, opt: RenderOptions, scenario_yaml: str) -> list[dict]:
    """Manifests in apply order: control plane first, so shapers find the controller."""
    docs: list[dict] = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": opt.namespace}}]
    docs += _controller(scn, opt, scenario_yaml)
    if opt.metrics:
        docs += _metrics(opt)
        if opt.grafana:
            docs += _grafana(opt)
    docs += _bootstrap(scn, opt)
    docs.append(
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": _meta("nodes", opt.namespace),
            "spec": {
                "clusterIP": "None",
                "selector": {ROLE_LABEL: "node"},
                "ports": [{"name": "libp2p", "port": 5000}],
            },
        }
    )
    docs += [_node_statefulset(scn, region, opt) for region in sorted(scn.regions)]
    return docs


def to_yaml(docs: list[dict]) -> str:
    return "---\n".join(yaml.safe_dump(d, sort_keys=False) for d in docs)
