# PyInstaller build spec:  pyinstaller --noconfirm ScreenStocksTradingBot.spec
# Produces dist/ScreenStocksTradingBot/ (one-folder build, used by the Inno Setup installer).

import os
import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = Path(SPECPATH)
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"',
                    (ROOT / "screenstocks" / "__init__.py").read_text(encoding="utf-8-sig")).group(1)
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

a = Analysis(
    ["main.py"],
    pathex=[],
    datas=[("assets/icon.ico", "assets"), ("assets/icon.png", "assets"),
           ("screenstocks/web/static", "screenstocks/web/static")],
    # the web UI is imported lazily in main.py; pywebview's own hook collects its .NET/WebView2 files
    hiddenimports=["screenstocks.web.app", "screenstocks.web.bridge", "webview", "webview.platforms.edgechromium",
                   "webview.platforms.winforms", "clr"],
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
    icon="assets/icon.ico",
    version=version_file,
    console=False,
    upx=False,  # UPX-packed executables are flagged far more often
)
coll = COLLECT(exe, a.binaries, a.datas, name="ScreenStocksTradingBot", upx=False)
