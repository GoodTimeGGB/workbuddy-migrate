@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "diagnose.ps1"
