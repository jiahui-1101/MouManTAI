@echo off
title MouManTAI Backend
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_backend.ps1" %*
pause
