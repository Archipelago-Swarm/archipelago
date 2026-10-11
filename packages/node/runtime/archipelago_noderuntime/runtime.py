"""Assemble node + control server + peer server + telemetry shipper into one process."""

from __future__ import annotations

from .config import Config
from .node import Node
from .peering import GatedPeerServer
from .server import ControlServer
from .telemetry import Shipper


class Runtime:
    def __init__(self, cfg: Config, ckpt_io=None):
        self.cfg = cfg
        self.node = Node(cfg, ckpt_io=ckpt_io)
        links = {(a, b) for a in cfg.node_ids for b in cfg.node_ids if a != b}
        self.peer = GatedPeerServer(
            cfg.node_id,
            links,
            cfg.bind_host,
            cfg.peer_port,
            urls=dict(cfg.peer_urls),
            token=cfg.peer_token,
            allowed_src=set(cfg.node_ids) - {cfg.node_id},
            gate=lambda src: self.node.link_cut(src),
            on_cut=self._on_cut,
            on_info=lambda env: self.node.receive_summary(env),
            on_info_cut=self._on_info_cut,
        )
        self.node.peer = self.peer
        self.control = ControlServer(self.node, cfg.bind_host, cfg.control_port)
        self.shipper: Shipper | None = None
        if cfg.telemetry_url:
            self.shipper = Shipper(
                self.node.spool, cfg.telemetry_url, cfg.node_id, self.node.boot_id,
                self.node.telemetry_context, cfg.telemetry_token,
                cfg.ship_batch, cfg.ship_interval, cfg.ship_timeout,
            )  # fmt: skip

    def _on_cut(self, src: str) -> None:
        self.node.counters["received_cut"] += 1

    def _on_info_cut(self, src: str) -> None:
        self.node._bump("summaries_received")
        self.node._bump("summaries_received_cut")  # a summary is not a model offer: own counters

    @property
    def control_url(self) -> str:
        return self.control.url

    @property
    def peer_url(self) -> str:
        return self.peer.url

    def set_peer_urls(self, urls: dict[str, str]) -> None:
        self.node.peer_urls = dict(urls)

    def start(self) -> Runtime:
        self.control.start()
        if self.shipper is not None:
            self.shipper.start()
        self.node.ready = True  # model exists (constructed) and the peer server is listening
        return self

    def stop(self, checkpoint: bool = True) -> None:
        self.node.ready = False
        if checkpoint:
            try:
                self.node.checkpoint()
            except Exception:  # shutdown must complete; the last complete generation still stands
                pass
        if self.shipper is not None:
            self.shipper.stop()
        self.control.close()
        self.peer.close()
        self.node.close()
