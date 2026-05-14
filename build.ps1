# ================================================================
#  BUILD COMPLETO — SecResearch Lab UPC
#  SuperGame_Setup.exe
#  Incluye: compilacion PyInstaller + limpieza MOTW/ADS
#           + firma digital automatica con cert autofirmado
#  Sin SmartScreen al ejecutar en la segunda PC del laboratorio
# ================================================================

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$GameDir    = Join-Path $ScriptRoot "SystemDiagnosticsFramework\juego_original"
$ExeName    = "SuperGame_Setup.exe"
$DistDir    = Join-Path $GameDir "dist"
$BuildDir   = Join-Path $GameDir "build"
$SpecFile   = Join-Path $GameDir "$ExeName.spec"
$ExePath    = Join-Path $DistDir $ExeName
$venvPy     = Join-Path $ScriptRoot "..\\.venv\\Scripts\\python.exe"
$CertSubj   = "CN=SecResearch Lab UPC"

# ----------------------------------------------------------------
# PASO 1 — Limpiar artefactos anteriores
# ----------------------------------------------------------------
Write-Host ""
Write-Host "[1/5] Limpiando build anterior..." -ForegroundColor Cyan
Remove-Item -LiteralPath $DistDir  -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "      OK — dist/ y build/ eliminados." -ForegroundColor Green

# ----------------------------------------------------------------
# PASO 2 — Regenerar .spec con disable_windowed_traceback=True
# ----------------------------------------------------------------
Write-Host "[2/5] Generando .spec..." -ForegroundColor Cyan

$specContent = @"
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['Juego.py'],
    pathex=['..'],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SuperGame_Setup.exe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"@

Set-Content -Path $SpecFile -Value $specContent -Encoding UTF8
Write-Host "      OK — .spec generado con disable_windowed_traceback=True." -ForegroundColor Green

# ----------------------------------------------------------------
# PASO 3 — Compilar con PyInstaller
# ----------------------------------------------------------------
Write-Host "[3/5] Compilando con PyInstaller..." -ForegroundColor Cyan
Set-Location -Path $GameDir

$pyExe = (Resolve-Path $venvPy -ErrorAction SilentlyContinue)
if ($pyExe) {
    & $pyExe -m PyInstaller --clean $SpecFile
} else {
    pyinstaller --clean $SpecFile
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller fallo con codigo $LASTEXITCODE. Abortando."
    exit 1
}
Write-Host "      OK — Ejecutable generado en: $ExePath" -ForegroundColor Green

# ----------------------------------------------------------------
# PASO 4 — Eliminar AMBOS ADS (Zone.Identifier + SmartScreen)
#           Esto evita el warning en cualquier maquina destino
# ----------------------------------------------------------------
Write-Host "[4/5] Eliminando Alternate Data Streams (MOTW)..." -ForegroundColor Cyan

# Stream principal que activa SmartScreen
Remove-Item -Path "${ExePath}:Zone.Identifier" -ErrorAction SilentlyContinue

# Stream secundario que Unblock-File NO elimina por defecto
Remove-Item -Path "${ExePath}:SmartScreen"     -ErrorAction SilentlyContinue

# Verificacion: solo debe quedar ::$DATA
$streams = Get-Item -Path $ExePath -Stream * |
           Where-Object { $_.Stream -ne ':$DATA' }

if ($streams) {
    Write-Warning "Streams restantes detectados: $($streams.Stream -join ', ')"
    Write-Warning "Ejecuta manualmente: Remove-Item -Path '${ExePath}:<nombre_stream>'"
} else {
    Write-Host "      OK — Ningun ADS residual. El .exe esta limpio de MOTW." -ForegroundColor Green
}

# ----------------------------------------------------------------
# PASO 5 — Firma digital con certificado autofirmado
#           Si el cert no existe lo crea e instala en esta maquina
# ----------------------------------------------------------------
Write-Host "[5/5] Firmando digitalmente el ejecutable..." -ForegroundColor Cyan

# Buscar cert existente en el store del usuario
$cert = Get-ChildItem Cert:\CurrentUser\My |
        Where-Object { $_.Subject -eq $CertSubj -and $_.HasPrivateKey } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1

if (-not $cert) {
    Write-Host "      Certificado no encontrado. Creando uno nuevo..." -ForegroundColor Yellow

    $cert = New-SelfSignedCertificate `
        -Type          CodeSigningCert `
        -Subject       $CertSubj `
        -KeyUsage      DigitalSignature `
        -FriendlyName  "SecResearch Lab UPC — Code Signing" `
        -CertStoreLocation Cert:\CurrentUser\My `
        -NotAfter      (Get-Date).AddYears(5)

    # Instalar en TrustedPublisher y Root para que esta maquina confie en el
    foreach ($store in @("TrustedPublisher","Root")) {
        $s = New-Object System.Security.Cryptography.X509Certificates.X509Store(
                 $store, "LocalMachine")
        $s.Open("ReadWrite")
        $s.Add($cert)
        $s.Close()
    }
    Write-Host "      Certificado creado e instalado en TrustedPublisher + Root." -ForegroundColor Green
}

# Firmar el .exe con timestamp publico de DigiCert
$sigResult = Set-AuthenticodeSignature `
    -FilePath    $ExePath `
    -Certificate $cert `
    -TimestampServer "http://timestamp.digicert.com" `
    -HashAlgorithm SHA256

if ($sigResult.Status -eq "Valid") {
    Write-Host "      OK — Firma valida aplicada al ejecutable." -ForegroundColor Green
} else {
    Write-Warning "Firma aplicada con estado: $($sigResult.Status)"
    Write-Warning "El .exe aun funciona pero SmartScreen puede seguir activo en otras PCs."
}

# ----------------------------------------------------------------
# RESUMEN FINAL
# ----------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host " BUILD COMPLETADO EXITOSAMENTE" -ForegroundColor Magenta
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host " EXE listo en: $ExePath"
Write-Host " Streams ADS : eliminados (Zone.Identifier + SmartScreen)"
Write-Host " Firma digital: $($sigResult.Status)"
Write-Host " Sin popup SmartScreen en esta maquina de laboratorio."
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host ""
