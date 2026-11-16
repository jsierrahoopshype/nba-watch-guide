@echo off
rem Deploys the how-to-watch-live Worker (worker\ in this repo).
rem Double-click it. It pulls the latest main, then runs worker\scripts\deploy.mjs,
rem which uses your normal "wrangler login" (no tokens, no secrets) and ends
rem with "IT WORKS." when hoopsmatic.com/how-to-watch/live/ is serving.
setlocal
title Deploy how-to-watch-live

rem The repo this file sits in; if it was copied somewhere else, the usual clone.
set "REPO=%~dp0.."
if not exist "%REPO%\.git" set "REPO=%USERPROFILE%\Documents\nba-watch-guide"
if not exist "%REPO%\.git" (
  echo No nba-watch-guide clone found, cloning it into "%REPO%"...
  git clone https://github.com/jsierrahoopshype/nba-watch-guide.git "%REPO%" || goto :fail
)
cd /d "%REPO%" || goto :fail
echo Repo: %CD%

echo.
echo == Getting the latest main
git fetch origin main || goto :fail
git checkout main || goto :fail
git pull --ff-only origin main || goto :fail

cd worker || goto :fail
node scripts\deploy.mjs || goto :fail

echo.
pause
exit /b 0

:fail
echo.
echo Something went wrong (see the message above). Nothing else was changed.
pause
exit /b 1
