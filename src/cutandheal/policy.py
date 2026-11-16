"""Cut a border with Kubernetes NetworkPolicies instead of netem.

This is how a partition is commonly made in a Kubernetes lab: label the two sides and apply
a policy that allows each side to talk only to itself. A policy is enforced by the cluster's
network plugin, which may treat connections that already exist differently from new ones,
and lands when the plugin has processed it rather than at a set time. Scenarios that use it
measure both.

Only whole cuts can be made this way: a policy selects every pod of a region, so a border is
either open for all of them or for none.
"""

from __future__ import annotations

from .kube import REGION_LABEL
from .model import Scenario


def _side(name: str, region: str, other: str, border_id: str) -> dict:
    # NotIn also matches pods without the label: the controller, metrics and DNS clients
    # of this namespace stay reachable, so the run can still be observed and steered.
    not_other = {"podSelector": {"matchExpressions": [{"key": REGION_LABEL, "operator": "NotIn", "values": [other]}]}}
    dns = {
        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
        "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
    }
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": name,
            "labels": {"app.kubernetes.io/part-of": "cut-and-heal", "cut-and-heal/border": border_id},
        },
        "spec": {
            "podSelector": {"matchLabels": {REGION_LABEL: region}},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [{"from": [not_other]}],
            "egress": [{"to": [not_other]}, {"to": [dns]}],
        },
    }


def border_policies(scn: Scenario, border_id: str) -> dict[str, dict]:
    """The two policies that shut one border, one for each side, keyed by name."""
    a, b = scn.borders[border_id].between
    return {
        f"cut-{border_id}-{a}": _side(f"cut-{border_id}-{a}", a, b, border_id),
        f"cut-{border_id}-{b}": _side(f"cut-{border_id}-{b}", b, a, border_id),
    }


def desired_policies(scn: Scenario, phase_idx: int) -> dict[str, dict]:
    """Every policy that should exist during a phase: those of each border that is shut."""
    phase = scn.timeline[phase_idx]
    out: dict[str, dict] = {}
    for border_id in scn.borders:
        if scn.open_count(phase, border_id) == 0:
            out.update(border_policies(scn, border_id))
    return out
