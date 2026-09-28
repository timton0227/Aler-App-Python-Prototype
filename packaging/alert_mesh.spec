# PyInstaller recipe for the two Alert Mesh desktop apps, on macOS and Windows:
# the phone app ("Alert Mesh") and the warning app ("Alert Mesh Warnings").
# Run it through packaging/build_mac.sh or packaging/build_windows.ps1, which set up
# the build environment and the icon first; not by hand.
#
# This is free and unencumbered software released into the public domain.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent  # python-prototype/
SWIFT_ICONS = ROOT.parent / "alert-mesh" / "AlertMesh" / "Assets.xcassets" / "AppIcon.appiconset"
# The town list, copied into each app where alertmesh/places.py looks for it
# (DATA_FILE_CANDIDATES): the Swift folder does not travel with the apps.
SWIFT_PLACES = ROOT.parent / "alert-mesh" / "AlertMesh" / "AlertMesh" / "Utils" / "AustralianPlacesData.swift"
# The relay list, copied where alertmesh/georelays.py looks for it (CSV_CANDIDATES).
SWIFT_RELAYS = ROOT.parent / "alert-mesh" / "relays" / "online_relays_gps.csv"

if sys.platform == "darwin":
    icon = ROOT / "build" / "icon" / "AlertMesh.icns"  # made by build_mac.sh
else:
    icon = SWIFT_ICONS / "icon_256x256.png"          # PyInstaller turns it into .ico (needs Pillow)
icon = str(icon) if icon.exists() else None

# Streamlit runs the page itself, so PyInstaller cannot see what it imports: list
# every alertmesh module from the folder. (collect_submodules("alertmesh") finds nothing
# here, because it runs where alertmesh cannot be imported, and the app then fails.)
ALERTMESH = ["alertmesh"] + sorted(
    f"alertmesh.{path.stem}" for path in (ROOT / "alertmesh").glob("*.py") if path.stem != "__init__"
)
# Test and notebook tools are in the build environment but not used by the apps.
EXCLUDES = ["tkinter", "pytest", "_pytest", "IPython", "ipykernel", "nbconvert", "jupyter_client"]


def collected(packages):
    datas, binaries, imports = [], [], []
    for package in packages:  # each loads files and modules at run time
        package_datas, package_binaries, package_imports = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        imports += package_imports
    return datas, binaries, imports


def app(start, page, name, bundle_id, packages, plist, leave_out=()):
    """One app: its start file, its page, what it needs, and what it does not."""
    datas, binaries, imports = collected(packages)
    datas += [(str(ROOT / page), "."), (str(SWIFT_PLACES), "alertmesh/data"), (str(SWIFT_RELAYS), "alertmesh/data")]
    datas += copy_metadata("streamlit")  # Streamlit reads its own version at start
    a = Analysis([str(ROOT / "packaging" / start)], pathex=[str(ROOT)], datas=datas, binaries=binaries,
                 hiddenimports=[m for m in ALERTMESH if m not in leave_out] + imports,
                 excludes=EXCLUDES + list(leave_out))
    exe = EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name=name,
              console=False, icon=icon)  # a window app: no terminal window
    coll = COLLECT(exe, a.binaries, a.datas, name=name)
    if sys.platform == "darwin":
        BUNDLE(coll, name=f"{name}.app", icon=icon, bundle_identifier=bundle_id, version="1.1.0",
               info_plist={
                   "CFBundleDisplayName": name,
                   "NSHighResolutionCapable": True,
                   "NSHumanReadableCopyright": "Public domain. Place names: GeoNames, CC BY 4.0.",
                   # Without this, macOS 15 drops the warnings sent on the local network.
                   "NSLocalNetworkUsageDescription": "Alert Mesh sends and hears official warnings "
                                                     "on the local network.",
                   **plist,
               })


# The phone app keeps the bundle ID of the Phase 12 app, so a Mac that already allowed
# it keeps its permissions.
app("start_phone.py", "phone_app.py", "Alert Mesh", "au.alertmesh.prototype",
    ["streamlit", "bleak", "bless"],
    # Without this, macOS stops the app the moment it touches Bluetooth.
    {"NSBluetoothAlwaysUsageDescription": "Alert Mesh finds laptops nearby and passes messages, "
                                          "calls for help and warnings between them over Bluetooth."},
    # The simulated town and its maps belong to the warning app.
    leave_out=("alertmesh.viz", "alertmesh.world", "alertmesh.metrics", "plotly"))
app("start_warning.py", "warning_app.py", "Alert Mesh Warnings", "au.alertmesh.warnings",
    ["streamlit", "plotly"], {})
