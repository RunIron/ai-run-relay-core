import sys

if sys.version_info < (3, 10):
    sys.exit(f"AI Run Relay 需要 Python 3.10 以上，目前是 {sys.version.split()[0]}。"
             "（macOS 內建的 python3 常為 3.9，請另行安裝新版 Python。）")

from .server import main

main()
