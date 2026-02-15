@echo off
set CURRENT_DIR=%CD%
echo ***** Current directory: %CURRENT_DIR% *****
set PYTHONPATH=%CURRENT_DIR%

"C:\Users\deroh\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m streamlit run .\webui\Main.py --browser.gatherUsageStats=False --server.enableCORS=True --server.port 8502 --server.address 127.0.0.1
pause