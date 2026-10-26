param(
    [string]$Version = "1.0.5"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

python -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
python -m unittest discover -s tests -v

$script = Join-Path $root "pet_manager.py"
$icon = Join-Path $root "assets\app.ico"
$distRoot = Join-Path $root "dist"
$buildRoot = Join-Path $root "build"
$specRoot = Join-Path $root "build\spec"
$releaseRoot = Join-Path $root "release"
$vendorRoot = Join-Path $root "vendor"
New-Item -ItemType Directory -Force -Path $distRoot, $buildRoot, $specRoot, $releaseRoot | Out-Null

$commonArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--noupx",
    "--name", "CodexPetManager",
    "--icon", $icon,
    "--add-data", "$icon;assets",
    "--hidden-import", "PIL._tkinter_finder",
    "--hidden-import", "ccl_chromium_reader.ccl_chromium_localstorage",
    "--hidden-import", "ccl_simplesnappy",
    "--paths", $vendorRoot,
    $script
)

$compatDist = Join-Path $distRoot "compat"
$compatBuild = Join-Path $buildRoot "compat"
$compatSpec = Join-Path $specRoot "compat"
New-Item -ItemType Directory -Force -Path $compatSpec | Out-Null
python -m PyInstaller @commonArgs `
    --onedir `
    --distpath $compatDist `
    --workpath $compatBuild `
    --specpath $compatSpec

$singleDist = Join-Path $distRoot "single"
$singleBuild = Join-Path $buildRoot "single"
$singleSpec = Join-Path $specRoot "single"
New-Item -ItemType Directory -Force -Path $singleSpec | Out-Null
python -m PyInstaller @commonArgs `
    --onefile `
    --distpath $singleDist `
    --workpath $singleBuild `
    --specpath $singleSpec

function Copy-ReleaseDocs {
    param([string]$Destination)

    foreach ($file in @("README.md", "LICENSE", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md")) {
        Copy-Item -LiteralPath (Join-Path $root $file) -Destination $Destination
    }
    $docs = Join-Path $Destination "docs"
    New-Item -ItemType Directory -Force -Path $docs | Out-Null
    Copy-Item -LiteralPath (Join-Path $root "docs\screenshot.png") -Destination $docs
}

$compatStage = Join-Path $releaseRoot "CodexPetManager-v$Version-windows-x64"
if (Test-Path -LiteralPath $compatStage) {
    Remove-Item -LiteralPath $compatStage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $compatStage | Out-Null
Copy-Item -Path (Join-Path $compatDist "CodexPetManager\*") -Destination $compatStage -Recurse
Copy-ReleaseDocs $compatStage

$singleStage = Join-Path $releaseRoot "CodexPetManager-v$Version-single-file-x64"
if (Test-Path -LiteralPath $singleStage) {
    Remove-Item -LiteralPath $singleStage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $singleStage | Out-Null
Copy-Item -LiteralPath (Join-Path $singleDist "CodexPetManager.exe") -Destination $singleStage
Copy-ReleaseDocs $singleStage

$compatArchive = Join-Path $releaseRoot "CodexPetManager-v$Version-windows-x64.zip"
$singleArchive = Join-Path $releaseRoot "CodexPetManager-v$Version-single-file-x64.zip"
$singleExe = Join-Path $releaseRoot "CodexPetManager-v$Version-single-file-x64.exe"
Compress-Archive -Path (Join-Path $compatStage "*") -DestinationPath $compatArchive -Force
Compress-Archive -Path (Join-Path $singleStage "*") -DestinationPath $singleArchive -Force
Copy-Item -LiteralPath (Join-Path $singleDist "CodexPetManager.exe") -Destination $singleExe -Force

$artifacts = @($compatArchive, $singleArchive, $singleExe)
$checksums = foreach ($artifact in $artifacts) {
    $hash = Get-FileHash -LiteralPath $artifact -Algorithm SHA256
    "$($hash.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($artifact))"
}
$checksums | Set-Content -Path (Join-Path $releaseRoot "SHA256SUMS.txt") -Encoding ascii

foreach ($artifact in $artifacts) {
    Write-Host "Built: $artifact"
}
