import importlib.metadata
import plistlib
import shutil
import sys
from pathlib import Path

app = Path(sys.argv[1])
info = {
    "CFBundleExecutable": "Hoist",
    "CFBundleIdentifier": "app.hoist.mac",
    "CFBundleName": "Hoist",
    "CFBundleDisplayName": "Hoist",
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": "0.1.0",
    "CFBundleVersion": "1",
    "CFBundleIconFile": "Hoist",
    "LSUIElement": True,
    "LSMinimumSystemVersion": "13.0",
    "NSHighResolutionCapable": True,
    "NSLocalNetworkUsageDescription": "Hoist finds Google Cast screens on your Wi-Fi and streams the media files you choose to them.",
    "NSBonjourServices": ["_googlecast._tcp"],
    "NSPrincipalClass": "NSApplication",
    "NSHumanReadableCopyright": "Copyright © 2026 Andres Martinez. MIT License.",
}
(app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
licenses = app / "Contents/Resources/Licenses"
licenses.mkdir(exist_ok=True)
shutil.copyfile("LICENSE", licenses / "Hoist.txt")
python_license = Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"
shutil.copyfile(python_license, licenses / "Python.txt")
for name in ["pychromecast", "casttube", "zeroconf", "protobuf", "requests", "urllib3", "certifi", "charset-normalizer", "idna", "ifaddr"]:
    dist = importlib.metadata.distribution(name)
    target = licenses / name
    target.mkdir(exist_ok=True)
    (target / "metadata.txt").write_text(dist.read_text("METADATA") or name, encoding="utf-8")
    for file in dist.files or []:
        if any(word in str(file).lower() for word in ["license", "copying", "notice"]):
            source = Path(dist.locate_file(file))
            if source.is_file():
                shutil.copyfile(source, target / source.name)
