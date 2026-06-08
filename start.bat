@echo off
REM 启动 Stream Dashboard (独立版), 浏览器打开 http://127.0.0.1:5111
REM 幂等: 已在运行则只打开浏览器. 关闭本窗口即停止 dashboard.
REM 监控的目标 repo 默认 F:\zx\multifactors_beta, 可设环境变量 DASHBOARD_REPO_ROOT 覆盖.
cd /d "%~dp0"

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5111 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 (
  echo Dashboard already running on http://127.0.0.1:5111 . Opening browser...
  start "" http://127.0.0.1:5111
  goto :eof
)

echo Starting Stream Dashboard on http://127.0.0.1:5111 ...
echo (Close this window to STOP the dashboard.)
start "" /min cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5111"
"C:/ProgramData/Anaconda3/python" app.py
