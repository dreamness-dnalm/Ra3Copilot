import os
from pathlib import Path


_appdata = os.environ.get("APPDATA")
if not _appdata:
    _appdata = str(Path.home() / "AppData" / "Roaming")

user_data_path = os.path.join(_appdata, 'Ra3Copilot')
