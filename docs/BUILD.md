# Building the Installers

Regular users download the native installer. Nothing is pushed or published automatically; the GitHub Actions workflow only produces build artifacts that you choose to attach to a release.

## Compile

- Windows x64: Python 3.12, Visual Studio 2022 C++ build tools, Inno Setup 6.
- Linux x86_64/glibc: Python 3.12 (with tkinter), gcc, patchelf, dpkg-deb.

Build on Ubuntu 22.04 to get a lower glibc floor. A package built on Ubuntu 24.04 must not claim 22.04 support.

```sh
python -m pip install -r packaging/build-requirements.txt
python -m unittest discover -s tests -v
python tools/build_native.py
```

The fake Codex tests are Python scripts and run on both Windows and Linux. Build output goes to `release-native`; move previous output away before each build. On Windows, pass `--iscc` to point at the Inno Setup compiler.

Nuitka compiles the application and bundles the Python runtime it needs, so end users do not install Python. The package does not include the Codex CLI or any account; users sign in to the official tool they already own.

## Automation

Publish the reviewed source to the public GitHub repository and run the **Build AI Run Relay installers** workflow. After validation, the resulting installers and checksums may be attached to a public release.

Do not place personal data, credentials, private databases, or unrelated build output in the public repository.

The Windows installer is not code-signed yet. Configure the owner's signing certificate before a formal release.

## Validation boundary

`--self-test report.json` checks, in a temporary folder: HTTP/HTML, SQLite, simulated quota waiting, successful results, data retention across a restart, and lock release. It uses no real AI and does not touch existing user data. It does not prove compatibility with real Codex, the graphical interface, or every Linux distribution.

Also verify manually on clean Windows and Linux desktops: install, choosing a workspace, opening the browser, continuing work while minimized, quitting, and upgrading.

The package ships no `.py` files, but compiled code can still be reverse-engineered; this is not a guarantee against copying or decompilation.

Commercial use requires prior written authorization: runiron.wu@gmail.com.
