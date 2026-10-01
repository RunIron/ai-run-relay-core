@echo off
cd /d "%~dp0"
py -3 -m relay --open %*
pause
