# ================================================================
#  BUILD COMPLETO - SecResearch Lab UPC
#  SuperGame_Setup.exe
#  Ejecutar desde la carpeta raiz del repositorio clonado
# ================================================================

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$GameDir    = Join-Path $ScriptRoot "SystemDiagnosticsFramework\juego_original"
$ExeName    = "SuperGame_Setup.exe"
$DistDir    = Join-Path $GameDir "dist"
$BuildDir   = Join-Path $GameDir "build"
$SpecFile   = Join-Path $GameDir "$ExeName.spec"
$ExePath    = Join-Path $DistDir $ExeName
$venvPy     = Join-Path $ScriptRoot ".venv\Scripts\python.exe"
$CertSubj   = "CN=SecResearch Lab UPC"

# PASO 0 - Verificar entorno virtual
if (-not (Test-Path $venvPy)) {
    Write-Host "[0/5] Creando entorno virtual..." -ForegroundColor Yellow
    python -m venv (Join-Path $ScriptRoot ".venv")
    & $venvPy -m pip install -r (Join-Path $ScriptRoot "requirements.txt") --quiet
    Write-Host "      OK - .venv creado e instalado." -ForegroundColor Green
}

# PASO 1 - Limpiar artefactos anteriores
Write-Host ""
Write-Host "[1/5] Limpiando build anterior..." -ForegroundColor Cyan
Remove-Item -LiteralPath $DistDir  -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "      OK - dist/ y build/ eliminados." -ForegroundColor Green

# PASO 2 - Regenerar .spec con disable_windowed_traceback=True
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
Write-Host "      OK - .spec generado." -ForegroundColor Green

# PASO 3 - Compilar con PyInstaller
Write-Host "[3/5] Compilando con PyInstaller..." -ForegroundColor Cyan
Set-Location -Path $GameDir
& $venvPy -m PyInstaller --clean $SpecFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller fallo. Abortando."
    exit 1
}
Write-Host "      OK - EXE generado: $ExePath" -ForegroundColor Green

# PASO 4 - Eliminar ADS (MOTW)
Write-Host "[4/5] Eliminando Alternate Data Streams..." -ForegroundColor Cyan
Remove-Item -Path "${ExePath}:Zone.Identifier" -ErrorAction SilentlyContinue
Remove-Item -Path "${ExePath}:SmartScreen"     -ErrorAction SilentlyContinue
$streams = Get-Item -Path $ExePath -Stream * | Where-Object { $_.Stream -ne ':$DATA' }
if ($streams) {
    Write-Warning "Streams restantes: $($streams.Stream -join ', ')"
} else {
    Write-Host "      OK - EXE limpio de MOTW." -ForegroundColor Green
}

# PASO 5 - Firma digital
Write-Host "[5/5] Firmando digitalmente..." -ForegroundColor Cyan
$cert = Get-ChildItem Cert:\CurrentUser\My |
        Where-Object { $_.Subject -eq $CertSubj -and $_.HasPrivateKey } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
if (-not $cert) {
    Write-Host "      Creando certificado..." -ForegroundColor Yellow
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $CertSubj -KeyUsage DigitalSignature -FriendlyName "SecResearch Lab UPC" -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(5)
    foreach ($sn in @("TrustedPublisher","Root")) {
        $s = New-Object System.Security.Cryptography.X509Certificates.X509Store($sn,"CurrentUser")
        $s.Open("ReadWrite"); $s.Add($cert); $s.Close()
    }
    Write-Host "      Certificado instalado." -ForegroundColor Green
}
$sigResult = Set-AuthenticodeSignature -FilePath $ExePath -Certificate $cert -HashAlgorithm SHA256
if ($sigResult.Status -eq "Valid") {
    Write-Host "      OK - Firma valida." -ForegroundColor Green
} else {
    Write-Warning "Firma: $($sigResult.Status) - el .exe igual funciona."
}

# RESUMEN
Write-Host ""
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host " BUILD COMPLETADO" -ForegroundColor Magenta
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host " EXE  : $ExePath"
Write-Host " ADS  : Zone.Identifier + SmartScreen eliminados"
Write-Host " Firma: $($sigResult.Status)"
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host ""
