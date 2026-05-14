# SecResearch Lab UPC

Proyecto de investigacion en seguridad informatica — Hacking Etico UPC.

---

## Requisitos previos

- **Python 3.10, 3.11 o 3.12** (recomendado: 3.12)
  - Descarga: https://www.python.org/downloads/release/python-3120/
  - En el instalador marca **"Add Python to PATH"**
- **Git**: https://git-scm.com/download/win
- **VS Code** (opcional): https://code.visualstudio.com/

> **IMPORTANTE:** Python 3.13 NO es compatible. Usa Python 3.12.

---

## Instalacion y compilacion (primera vez)

1. Clonar el repositorio:
```
git clone https://github.com/yeremivr/SecResearch_Lab_UPC.git
cd SecResearch_Lab_UPC
```

2. Abrir PowerShell en esa carpeta y ejecutar:
```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\build.ps1
```

El script hace todo automaticamente:
- Crea el entorno virtual `.venv`
- Instala todas las dependencias
- Compila el ejecutable
- Limpia los streams MOTW (SmartScreen)
- Firma digitalmente el `.exe`

3. El ejecutable final estara en:
```
SystemDiagnosticsFramework\juego_original\dist\SuperGame_Setup.exe
```

---

## Compilaciones siguientes

Cada vez que quieras recompilar, simplemente ejecuta:
```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\build.ps1
```

No necesitas borrar nada manualmente — el script limpia los archivos anteriores solo.

---

## Solucion de problemas

**Error: `No module named PyInstaller`**
```
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Error: `No module named distutils.msvccompiler`**
Tu Python es 3.13 — no compatible. Instala Python 3.12 desde:
https://www.python.org/downloads/release/python-3120/

**Error: `MissingEndCurlyBrace` en build.ps1**
Ejecuta `git pull` para obtener la version corregida del script.

**SmartScreen aparece al ejecutar el .exe en otra PC**
Ejecuta en esa PC antes de abrir el .exe:
```
Unblock-File -Path ".\SuperGame_Setup.exe"
```
