"""Shared test set-up.

The warning app sends real packets on the local network, and a phone app running on
this computer would show them. The tests use a port of their own instead.

The internet link would reach public relays. The tests name a relay address where
nothing listens (tests that need a relay start their own, see fake_relay.py).
"""
import os
import socket


def pytest_configure(config):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("", 0))
        os.environ["ALERTMESH_LAN_PORT"] = str(s.getsockname()[1])
    os.environ["ALERTMESH_NOSTR_RELAYS"] = "ws://127.0.0.1:9"
