# PyInstaller build spec:  pyinstaller --noconfirm ScreenStocksTradingBot.spec
# Produces dist/ScreenStocksTradingBot/ (one-folder build, used by the Inno Setup installer).

a = Analysis(
    ["main.py"],
    pathex=[],
    datas=[("assets/icon.ico", "assets"), ("assets/icon.png", "assets")],
    hiddenimports=[],
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
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ScreenStocksTradingBot", upx=False)
