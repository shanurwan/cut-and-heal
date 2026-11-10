"""The four Kubernetes API calls the controller needs, over the pod's service account.

A full client library would be a larger dependency than the code that uses it.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from pathlib import Path

import aiohttp

SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
REGION_LABEL = "cut-and-heal/region"
ROLE_LABEL = "cut-and-heal/role"


@dataclass(frozen=True)
class PodInfo:
    name: str
    region: str
    ip: str
    node: str
    phase: str
    ready: bool
    restarts: int


class Kube:
    def __init__(self, session: aiohttp.ClientSession, base: str, namespace: str, token: str):
        self._s, self._base, self.namespace, self._token = session, base, namespace, token

    @classmethod
    def in_cluster(cls) -> Kube:
        ctx = ssl.create_default_context(cafile=str(SA / "ca.crt"))
        session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx, limit=64))
        return cls(
            session,
            "https://kubernetes.default.svc",
            (SA / "namespace").read_text().strip(),
            (SA / "token").read_text().strip(),
        )

    async def close(self) -> None:
        await self._s.close()

    async def _get(self, path: str, **params: str) -> aiohttp.ClientResponse:
        resp = await self._s.get(
            self._base + path,
            params=params,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=aiohttp.ClientTimeout(total=120),
        )
        resp.raise_for_status()
        return resp

    async def region_cidrs(self) -> dict[str, tuple[str, ...]]:
        """Pod CIDRs per region, from the nodes labelled into each region."""
        body = await (await self._get("/api/v1/nodes")).json()
        out: dict[str, list[str]] = {}
        for node in body["items"]:
            region = node["metadata"].get("labels", {}).get(REGION_LABEL)
            cidrs = node["spec"].get("podCIDRs") or [node["spec"].get("podCIDR")]
            if region and cidrs and cidrs[0]:
                out.setdefault(region, []).extend(c for c in cidrs if ":" not in c)
        return {r: tuple(sorted(c)) for r, c in out.items()}

    async def node_pods(self) -> list[PodInfo]:
        body = await (
            await self._get(f"/api/v1/namespaces/{self.namespace}/pods", labelSelector=f"{ROLE_LABEL}=node")
        ).json()
        pods = []
        for item in body["items"]:
            status = item.get("status", {})
            containers = status.get("containerStatuses", [])
            pods.append(
                PodInfo(
                    name=item["metadata"]["name"],
                    region=item["metadata"]["labels"].get(REGION_LABEL, ""),
                    ip=status.get("podIP", ""),
                    node=item["spec"].get("nodeName", ""),
                    phase=status.get("phase", ""),
                    ready=bool(containers) and all(c.get("ready") for c in containers),
                    restarts=sum(c.get("restartCount", 0) for c in containers),
                )
            )
        return pods

    async def pod_log(self, pod: str, container: str) -> bytes:
        resp = await self._get(f"/api/v1/namespaces/{self.namespace}/pods/{pod}/log", container=container)
        return await resp.read()
