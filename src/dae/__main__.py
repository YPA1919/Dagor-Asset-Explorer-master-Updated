import os
import sys
import traceback

LOG_NAME = "DagorAssetExplorer.log"


def logPath() -> str:
	base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))

	return os.path.join(base, LOG_NAME)


def logLine(text:str) -> None:
	from datetime import datetime

	try:
		with open(logPath(), "a", encoding = "utf-8") as fh:
			fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
	except Exception:
		pass


def runExtractCollision(argv:list[str]) -> int:
	"""Headless helper: --extract-collision <grp> <assetName> <outputDir>.

	Writes both the OBJ and the DMF for the given collision resource.  Used to
	verify the V3 collision reader without the GUI, and handy for batch jobs.
	"""
	from os import makedirs
	from parse.gameres import GameResourcePack
	from util.assetcacher import AssetCacher
	from util.py313 import fixAssetClasses

	fixAssetClasses()

	if len(argv) < 5:
		print("usage: --extract-collision <file.grp> <assetName> <output dir>", file = sys.stderr)

		return 2

	grpPath, assetName, output = argv[2], argv[3], argv[4]
	logLine(f"extract {assetName} <- {grpPath}")

	grp = GameResourcePack(grpPath)

	for i in range(grp.getRealResEntryCnt()):
		entry = grp.getRealResEntry(i)

		try:
			AssetCacher.cacheAsset(grp.getRealResource(grp.getRealResId(entry.getName())))
		except Exception:
			pass

	res = grp.getRealResource(grp.getRealResId(assetName))

	if res is None:
		print(f"asset '{assetName}' not found in {grpPath}", file = sys.stderr)

		return 1

	makedirs(output, exist_ok = True)

	mdl = res.getModel(0)
	mdl.exportObj(output, exportTexture = False)
	mdl.exportDmf(output, exportTexture = False)

	print(f"exported {assetName} to {output}")
	logLine(f"exported {assetName} to {output}")

	return 0


def runMenuCheck(argv:list[str]) -> int:
	"""Diagnostic: build the context menu of one asset without the main window.

	Proves that the GUI action descriptors (exportFormat / exportMethodName)
	resolve on this Python build, which is what the asset tree needs before it
	can offer "Export ... to DMF".  Usage: --check-menu <file.grp> <assetName>
	"""
	from os import environ

	environ.setdefault("QT_QPA_PLATFORM", "offscreen")

	from PyQt5.QtCore import QFileInfo
	from PyQt5.QtGui import QIcon
	from PyQt5.QtWidgets import QApplication, QMenu

	qapp = QApplication(argv[:1])

	from gui import customtreeview
	from parse.gameres import GameResourcePack
	from util.py313 import fixAssetClasses

	fixAssetClasses()

	if len(argv) < 4:
		print("usage: --check-menu <file.grp> <assetName>", file = sys.stderr)

		return 2

	grpPath, assetName = argv[2], argv[3]
	grp = GameResourcePack(grpPath)
	res = grp.getRealResource(grp.getRealResId(assetName))

	if res is None:
		print(f"asset '{assetName}' not found", file = sys.stderr)

		return 1

	messages = []
	customtreeview.MessageBox = type("MessageBox", (), {
		"__init__": lambda self, text: messages.append(text) or None,
		"exec_": lambda self: None,
	})

	class FakeWindow:
		clearItems = []
		treeView = None

	item = customtreeview.AssetItem(FakeWindow(), QFileInfo(grpPath), QIcon(), res, None)
	menu = QMenu()
	item.populateMenu(menu)

	print(f"asset: {assetName}")
	print("menu:")

	for action in menu.actions():
		print("  " + action.text())

	print("error dialog:", messages[0] if messages else "none")

	return 1 if messages else 0


def runGui(argv:list[str]) -> int:
	logLine("starting gui")

	try:
		from util.py313 import fixAssetClasses

		fixAssetClasses()
		logLine("class registry ok")
	except Exception:
		logLine("class registry fix failed:\n" + traceback.format_exc())

	from gui import app

	application = app.App(argv)
	logLine("application created")

	exitCode = application.exec_()
	logLine(f"application exited with {exitCode}")

	return exitCode


def pauseOnError() -> None:
	"""Keep the console window open so a startup failure stays readable."""

	if not getattr(sys, "frozen", False):
		return

	try:
		if sys.stdin is not None and sys.stdin.isatty():
			input("启动失败，按回车退出...")
	except Exception:
		pass


if __name__ == "__main__":
	exitCode = 1

	try:
		if len(sys.argv) > 1 and sys.argv[1] == "--extract-collision":
			exitCode = runExtractCollision(sys.argv)
		elif len(sys.argv) > 1 and sys.argv[1] == "--check-menu":
			exitCode = runMenuCheck(sys.argv)
		else:
			exitCode = runGui(sys.argv)
	except BaseException:
		logLine("fatal error:\n" + traceback.format_exc())
		traceback.print_exc()
		pauseOnError()

	sys.exit(exitCode)
