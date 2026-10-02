import sys

if sys.version_info < (3, 10):
    sys.exit(f"AI Run Relay requires Python 3.10 or later; this is {sys.version.split()[0]}. "
             "(The python3 bundled with macOS is often 3.9; install a newer Python.)")

from .server import main

main()
