#!/usr/bin/env powershell
# ============================================================================
# LISTA DE VERIFICACION PRE-COMPILACION - SentinelV
# ============================================================================

$ErrorActionPreference = "Continue"
$passCount = 0
$failCount = 0

function Test-Item {
    param([string]$name, [scriptblock]$test)
    try {
        $result = & $test
        if ($result) {
            Write-Host "[PASS] $name" -ForegroundColor Green
            $script:passCount++
        } else {
            Write-Host "[FAIL] $name" -ForegroundColor Red
            $script:failCount++
        }
    } catch {
        Write-Host "[FAIL] $name - $_" -ForegroundColor Red
        $script:failCount++
    }
}

Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host "VERIFICACION PRE-COMPILACION - SENTINELV FRAMEWORK" -ForegroundColor Cyan
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host ""

# Estructura de directorios
Write-Host "1. ESTRUCTURA DE DIRECTORIOS" -ForegroundColor Yellow
Test-Item "Existe: SystemDiagnosticsFramework/" { Test-Path "SystemDiagnosticsFramework" -PathType Container }
Test-Item "Existe: SentinelV/" { Test-Path "SystemDiagnosticsFramework\SentinelV" -PathType Container }
Test-Item "Existe: juego_original/" { Test-Path "SystemDiagnosticsFramework\juego_original" -PathType Container }
Test-Item "NO existe: __pycache__" { -not (Test-Path "SystemDiagnosticsFramework\SentinelV\__pycache__" -PathType Container) }
Test-Item "NO existe: .py vacio" { -not (Test-Path "SystemDiagnosticsFramework\.py" -PathType Leaf) }

# Archivos criticos
Write-Host ""
Write-Host "2. ARCHIVOS CRITICOS" -ForegroundColor Yellow
Test-Item "SentinelV/__init__.py" { Test-Path "SystemDiagnosticsFramework\SentinelV\__init__.py" -PathType Leaf }
Test-Item "SentinelV/__main__.py" { Test-Path "SystemDiagnosticsFramework\SentinelV\__main__.py" -PathType Leaf }
Test-Item "SentinelV/Agent.py" { Test-Path "SystemDiagnosticsFramework\SentinelV\Agent.py" -PathType Leaf }
Test-Item "SentinelV/TelemetryDispatcher.py" { Test-Path "SystemDiagnosticsFramework\SentinelV\TelemetryDispatcher.py" -PathType Leaf }
Test-Item "SentinelV/CommandOrchestrator.py" { Test-Path "SystemDiagnosticsFramework\SentinelV\CommandOrchestrator.py" -PathType Leaf }
Test-Item "SentinelV/MediaSensorValidation.py" { Test-Path "SystemDiagnosticsFramework\SentinelV\MediaSensorValidation.py" -PathType Leaf }
Test-Item "SentinelV/AcousticTelemetry.py" { Test-Path "SystemDiagnosticsFramework\SentinelV\AcousticTelemetry.py" -PathType Leaf }
Test-Item "juego_original/Juego.py" { Test-Path "SystemDiagnosticsFramework\juego_original\Juego.py" -PathType Leaf }

# Archivos de build
Write-Host ""
Write-Host "3. ARCHIVOS DE COMPILACION" -ForegroundColor Yellow
Test-Item "requirements.txt" { Test-Path "requirements.txt" -PathType Leaf }
Test-Item "build.ps1" { Test-Path "build.ps1" -PathType Leaf }
Test-Item "COMPILATION_REPORT.md" { Test-Path "COMPILATION_REPORT.md" -PathType Leaf }

# Validacion de sintaxis Python
Write-Host ""
Write-Host "4. VALIDACION DE SINTAXIS PYTHON" -ForegroundColor Yellow
$pythonFiles = @(
    "SystemDiagnosticsFramework\SentinelV\__main__.py",
    "SystemDiagnosticsFramework\SentinelV\Agent.py",
    "SystemDiagnosticsFramework\SentinelV\TelemetryDispatcher.py",
    "SystemDiagnosticsFramework\SentinelV\CommandOrchestrator.py"
)

foreach ($file in $pythonFiles) {
    $fileCopy = $file
    Test-Item "Sintaxis: $(Split-Path -Leaf $fileCopy)" {
        python -m py_compile $fileCopy 2>&1 | Out-Null
        $LASTEXITCODE -eq 0
    }
}

# Verificacion de imports - CORREGIDO: manejo de output mixto
Write-Host ""
Write-Host "5. VERIFICACION DE IMPORTS" -ForegroundColor Yellow
Test-Item "Imports del paquete SentinelV" {
    $output = python -c @"
import sys
sys.path.append('SystemDiagnosticsFramework')
from SentinelV import TelemetryDispatcher, CommandOrchestrator, SentinelVAgent
from SentinelV import take_screenshot, capture_audio_segment, record_diagnostic_video
print('OK')
"@ 2>&1
    $text = ($output | Where-Object { $_ -is [string] }) -join ""
    $LASTEXITCODE -eq 0 -and $text -match "OK"
}

# Verificacion de dependencias - CORREGIDO: nombres reales de paquetes
Write-Host ""
Write-Host "6. DEPENDENCIAS REQUERIDAS" -ForegroundColor Yellow

$pipList = pip list 2>&1 | Out-String

$packageMap = [ordered]@{
    "requests"      = "requests"
    "cryptography"  = "cryptography"
    "pygame"        = "pygame"
    "Pillow"        = "pillow"
    "opencv-python" = "opencv-python"
    "discord.py"    = "discord"
    "PyAudio"       = "pyaudio"
}

foreach ($entry in $packageMap.GetEnumerator()) {
    $pkgName  = $entry.Key
    $pkgLabel = $entry.Value
    Test-Item "Paquete: $pkgLabel" {
        $pipList -match "(?i)$pkgName"
    }
}

# Verificacion de threading en Juego.py - CORREGIDO: patron multilinea
Write-Host ""
Write-Host "7. INTEGRACION DE THREADING" -ForegroundColor Yellow
Test-Item "Juego.py: import threading" {
    $content = Get-Content "SystemDiagnosticsFramework\juego_original\Juego.py" -Raw
    $content -match "import threading"
}

Test-Item "Juego.py: threading.Thread daemon" {
    $content = Get-Content "SystemDiagnosticsFramework\juego_original\Juego.py" -Raw
    $content -match "threading\.Thread" -and ($content -match "daemon\s*=\s*True")
}

# Verificacion de configuracion en __main__.py
Write-Host ""
Write-Host "8. CONFIGURACION SEGURA EN __main__.py" -ForegroundColor Yellow
Test-Item "__main__.py: load_discord_credentials()" {
    $content = Get-Content "SystemDiagnosticsFramework\SentinelV\__main__.py" -Raw
    $content -match "load_discord_credentials"
}

Test-Item "__main__.py: LAB_HARDCODED_CONFIG" {
    $content = Get-Content "SystemDiagnosticsFramework\SentinelV\__main__.py" -Raw
    $content -match "LAB_HARDCODED_CONFIG"
}

Test-Item "__main__.py: Fallback a archivo de config" {
    $content = Get-Content "SystemDiagnosticsFramework\SentinelV\__main__.py" -Raw
    $content -match "discord_config\.json"
}

# Resumen
Write-Host ""
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host "RESUMEN" -ForegroundColor Cyan
Write-Host "===============================================================" -ForegroundColor Cyan

$total = $passCount + $failCount
$percentage = if ($total -gt 0) { [Math]::Round(($passCount / $total) * 100) } else { 0 }

Write-Host ""
Write-Host "Verificaciones pasadas: $passCount" -ForegroundColor Green
Write-Host "Verificaciones fallidas: $failCount" -ForegroundColor $(if ($failCount -gt 0) { "Red" } else { "Green" })
Write-Host "Tasa de aprobacion: $percentage%" -ForegroundColor $(if ($percentage -eq 100) { "Green" } else { "Yellow" })
Write-Host ""

if ($failCount -eq 0) {
    Write-Host "FRAMEWORK LISTO PARA COMPILACION" -ForegroundColor Green
    Write-Host ""
    Write-Host "Proximo paso: Ejecutar .\build.ps1" -ForegroundColor Cyan
    exit 0
} else {
    Write-Host "X VERIFICACIONES FALLIDAS - Revise los errores arriba" -ForegroundColor Red
    exit 1
}