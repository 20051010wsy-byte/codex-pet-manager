param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

python -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
python -m unittest discover -s tests -v

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "CodexPetManager" `
    --icon "assets\app.ico" `
    --add-data "assets\app.ico;assets" `
    --hidden-import "PIL._tkinter_finder" `
    "pet_manager.py"

$stage = Join-Path $root "release\CodexPetManager-v$Version-windows-x64"
if (Test-Path $stage) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item "dist\CodexPetManager.exe" $stage
Copy-Item "README.md" $stage
Copy-Item "LICENSE" $stage
New-Item -ItemType Directory -Force -Path (Join-Path $stage "docs") | Out-Null
Copy-Item "docs\screenshot.png" (Join-Path $stage "docs")

$archive = Join-Path $root "release\CodexPetManager-v$Version-windows-x64.zip"
if (Test-Path $archive) {
    Remove-Item -LiteralPath $archive -Force
}
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $archive
$hash = Get-FileHash $archive -Algorithm SHA256
"$($hash.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($archive))" |
    Set-Content -Path "release\SHA256SUMS.txt" -Encoding ascii

Write-Host "Built: $archive"
