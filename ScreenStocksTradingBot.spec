# PyInstaller build spec:  pyinstaller --noconfirm ScreenStocksTradingBot.spec
# Produces dist/ScreenStocksTradingBot/ (one-folder build, used by the Inno Setup installer on Windows),
# plus dist/ScreenStocksTradingBot.app on macOS.

import os
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"',
                    (ROOT / "screenstocks" / "__init__.py").read_text(encoding="utf-8-sig")).group(1)

# the web UI is imported lazily in main.py; pywebview's own hook collects its .NET/WebView2 files
hiddenimports = ["screenstocks.web.app", "screenstocks.web.bridge", "webview"]
exe_options = {}

if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)

    nums = tuple((int(x) for x in re.findall(r"\d+", VERSION)[:4]))
    nums = nums + (0,) * (4 - len(nums))

    # Windows version resource (Explorer > Properties > Details). Executables without any
    # metadata look more suspicious to antivirus heuristics.
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1,
                          subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "ScreenStocksTradingBot contributors"),
                StringStruct("FileDescription", "ScreenStocks Trading Bot"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "ScreenStocksTradingBot"),
                StringStruct("LegalCopyright", "Apache License 2.0 - github.com/DvTJ/ScreenStocksTradingUI"),
                StringStruct("OriginalFilename", "ScreenStocksTradingBot.exe"),
                StringStruct("ProductName", "ScreenStocks Trading Bot"),
                StringStruct("ProductVersion", VERSION),
                StringStruct("Comments", "Unofficial companion app for the game Screen Stocks"),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
    os.makedirs(workpath, exist_ok=True)
    version_file = os.path.join(workpath, "version_info.txt")
    with open(version_file, "w", encoding="utf-8") as fh:
        fh.write(str(version_info))

    hiddenimports += ["webview.platforms.edgechromium", "webview.platforms.winforms", "clr"]
    exe_options = {"icon": "assets/icon.ico", "version": version_file}
elif sys.platform == "darwin":
    hiddenimports += ["webview.platforms.cocoa"]
else:
    # Linux builds bundle pywebview's Qt backend with PySide6 (pip install "pywebview[pyside6]")
    hiddenimports += ["webview.platforms.qt", "qtpy"]

a = Analysis(
    ["main.py"],
    pathex=[],
    datas=[("assets/icon.ico", "assets"), ("assets/icon.png", "assets"),
           ("screenstocks/web/static", "screenstocks/web/static")],
    hiddenimports=hiddenimports,
    excludes=["unittest", "pydoc", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ScreenStocksTradingBot",
    console=False,
    upx=False,  # UPX-packed executables are flagged far more often
    **exe_options,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ScreenStocksTradingBot", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ScreenStocksTradingBot.app",
        icon="assets/icon.png",  # converted to .icns (needs Pillow)
        bundle_identifier="io.github.dvtj.screenstockstradingbot",
        version=VERSION,
        info_plist={"CFBundleDisplayName": "ScreenStocks Trading Bot", "NSHighResolutionCapable": True},
    )
