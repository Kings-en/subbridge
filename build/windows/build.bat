@echo off
REM SubBridge Windows 本地打包脚本（one-folder 模式）
REM 要求：Python 3.11+、已安装 requirements.txt、网络可用（PyInstaller 下载 bootloader 如需）
setlocal
cd /d %~dp0..\..

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller build\windows\SubBridge.spec --noconfirm

echo.
echo 打包完成：dist\SubBridge\SubBridge.exe
echo 如需随包分发 ffmpeg，请把 ffmpeg\bin 解压到 dist\SubBridge\ffmpeg\bin
endlocal
