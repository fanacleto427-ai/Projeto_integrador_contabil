@echo off
setlocal
cd /d "%~dp0"
echo Importador Dominio - candidata NAO HOMOLOGADA
echo Este comando instala dependencias Python e gera arquivos na pasta generated-artifacts.
echo A referencia v1.12 e os leitores nao serao alterados.
echo.
where py >nul 2>&1
if errorlevel 1 goto usar_python
py -3 windows\build_windows.py
set "RESULTADO=%ERRORLEVEL%"
goto terminar
:usar_python
where python >nul 2>&1
if errorlevel 1 goto sem_python
python windows\build_windows.py
set "RESULTADO=%ERRORLEVEL%"
goto terminar
:sem_python
echo Instale Python 3.11 ou superior de 64 bits, com Tcl/Tk e opcao PATH.
set "RESULTADO=1"
:terminar
if not "%RESULTADO%"=="0" echo A geracao falhou. Leia o erro acima. Nenhum pacote deve ser considerado aprovado.
pause
exit /b %RESULTADO%
