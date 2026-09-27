# PyInstaller recipe for the Alert Mesh desktop app, on macOS and Windows.
# Run it through packaging/build_mac.sh or packaging/build_windows.ps1, which set up
# the build environment and the icon first; not by hand.
#
# This is free and unencumbered software released into the public domain.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent  # python-prototype/
SWIFT_ICONS = ROOT.parent / "alert-mesh" / "AlertMesh" / "Assets.xcassets" / "AppIcon.appiconset"
# The town list, copied into the app where alertmesh/places.py looks for it
# (DATA_FILE_CANDIDATES): the Swift folder does not travel with the app.
SWIFT_PLACES = ROOT.parent / "alert-mesh" / "AlertMesh" / "AlertMesh" / "Utils" / "AustralianPlacesData.swift"

if sys.platform == "darwin":
    icon = ROOT / "build" / "icon" / "AlertMesh.icns"  # made by build_mac.sh
else:
    icon = SWIFT_ICONS / "icon_256x256.png"          # PyInstaller turns it into .ico (needs Pillow)

datas = [(str(ROOT / "app.py"), "."), (str(SWIFT_PLACES), "alertmesh/data")]
binaries = []
# Streamlit runs app.py itself, so PyInstaller cannot see what app.py imports: list
# every alertmesh module from the folder. (collect_submodules("alertmesh") finds nothing
# here, because it runs where alertmesh cannot be imported, and the app then fails.)
hiddenimports = ["alertmesh"] + sorted(
    f"alertmesh.{path.stem}" for path in (ROOT / "alertmesh").glob("*.py") if path.stem != "__init__"
)
for package in ("streamlit", "plotly"):  # both load files and modules at run time
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata("streamlit")  # Streamlit reads its own version at start

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    # Test and notebook tools are in the build environment but not used by the app.
    excludes=["tkinter", "pytest", "_pytest", "IPython", "ipykernel", "nbconvert", "jupyter_client"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Alert Mesh",
    console=False,  # a window app: no terminal window
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Alert Mesh")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Alert Mesh.app",
        icon=str(icon) if icon.exists() else None,
        bundle_identifier="au.alertmesh.prototype",
        version="1.0.0",
        info_plist={
            "CFBundleDisplayName": "Alert Mesh",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "Public domain. Place names: GeoNames, CC BY 4.0.",
        },
    )
