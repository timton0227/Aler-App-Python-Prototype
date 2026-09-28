"""Alert Mesh Python prototype.

A computer-only port of the core ideas in the Alert Mesh iPhone app
(alert-mesh/). Each module names the Swift file it was ported from.
"""
import sys

# The modules use `X | None` type hints, which Python 3.9 and older cannot run: they
# fail on import with a puzzling TypeError. Say what is wrong instead. (A Mac's
# built-in python3 is 3.9.)
if sys.version_info < (3, 10):
    raise ImportError(
        f"The Alert Mesh prototype needs Python 3.10 or newer; this is Python "
        f"{sys.version.split()[0]} ({sys.executable}). Install a newer Python from "
        "https://www.python.org/downloads/ and follow 'Set up' in README.md."
    )
