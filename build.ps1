# ================================================================
#  BUILD COMPLETO - SecResearch Lab UPC
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
$venvPy     = Join-Path $ScriptRoot ".venv\Scripts\python.exe"
$CertSubj   = "CN=SecResearch Lab UPC"

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
Write-Host "      OK - .spec generado con disable_windowed_traceback=True." -ForegroundColor Green

# PASO 3 - Compilar con PyInstaller
Write-Host "[3/5] Compilando con PyInstaller..." -ForegroundColor Cyan
Set-Location -Path $GameDir
$pyExe = (Resolve-Path $venvPy -ErrorAction SilentlyContinue)
if ($pyExe) {
    & $pyExe -m PyInstaller --clean $SpecFile
} else {
    pyinstaller --clean $SpecFile
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller fallo. Abortando."
    exit 1
}
Write-Host "      OK - EXE generado: $ExePath" -ForegroundColor Green

# PASO 4 - Eliminar AMBOS ADS (Zone.Identifier + SmartScreen)
Write-Host "[4/5] Eliminando Alternate Data Streams (MOTW)..." -ForegroundColor Cyan
Remove-Item -Path "${ExePath}:Zone.Identifier" -ErrorAction SilentlyContinue
Remove-Item -Path "${ExePath}:SmartScreen"     -ErrorAction SilentlyContinue
$streams = Get-Item -Path $ExePath -Stream * | Where-Object { $_.Stream -ne ':$DATA' }
if ($streams) {
    Write-Warning "Streams restantes: $($streams.Stream -join ', ')"
} else {
    Write-Host "      OK - Sin ADS residual. EXE limpio de MOTW." -ForegroundColor Green
}

# PASO 5 - Firma digital con certificado autofirmado
Write-Host "[5/5] Firmando digitalmente el ejecutable..." -ForegroundColor Cyan
$cert = Get-ChildItem Cert:\CurrentUser\My |
        Where-Object { $_.Subject -eq $CertSubj -and $_.HasPrivateKey } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
if (-not $cert) {
    Write-Host "      Creando certificado nuevo..." -ForegroundColor Yellow
    $cert = New-SelfSignedCertificate `
        -Type              CodeSigningCert `
        -Subject           $CertSubj `
        -KeyUsage          DigitalSignature `
        -FriendlyName      "SecResearch Lab UPC Code Signing" `
        -CertStoreLocation Cert:\CurrentUser\My `
        -NotAfter          (Get-Date).AddYears(5)
    foreach ($storeName in @("TrustedPublisher", "Root")) {
        $s = New-Object System.Security.Cryptography.X509Certificates.X509Store($storeName, "CurrentUser")
        $s.Open("ReadWrite")
        $s.Add($cert)
        $s.Close()
    }
    Write-Host "      Certificado instalado." -ForegroundColor Green
}
$sigResult = Set-AuthenticodeSignature `
    -FilePath    $ExePath `
    -Certificate $cert `
    -HashAlgorithm SHA256
if ($sigResult.Status -eq "Valid") {
    Write-Host "      OK - Firma valida aplicada." -ForegroundColor Green
} else {
    Write-Warning "Firma estado: $($sigResult.Status) - el .exe igual funciona."
}

# RESUMEN FINAL
Write-Host ""
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host " BUILD COMPLETADO EXITOSAMENTE" -ForegroundColor Magenta
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host " EXE  : $ExePath"
Write-Host " ADS  : Zone.Identifier + SmartScreen eliminados"
Write-Host " Firma: $($sigResult.Status)"
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host ""
