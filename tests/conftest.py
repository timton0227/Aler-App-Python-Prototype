"""Shared test set-up.

The warning app sends real packets on the local network, and a phone app running on
this computer would show them. The tests use a port of their own instead.
"""
import os
import socket


def pytest_configure(config):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("", 0))
        os.environ["ALERTMESH_LAN_PORT"] = str(s.getsockname()[1])
