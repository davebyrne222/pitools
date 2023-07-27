import PyInstaller.__main__

PyInstaller.__main__.run([
    "--console",
    "--name",
    "pitools",
    "--add-data=config.json:.",
    "--add-data=.env:.",
    "--add-data=LICENSE.txt:.",
    "pitools/pi_tools.py"
])
