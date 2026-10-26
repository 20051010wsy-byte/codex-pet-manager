param(
    [string]$Version = "1.0.6"
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

$compatArchive = Join-Path $releaseRoot "CodexPetManager-v$Version-windows-x64.zip"
Compress-Archive -Path (Join-Path $compatStage "*") -DestinationPath $compatArchive -Force
$hash = Get-FileHash -LiteralPath $compatArchive -Algorithm SHA256
Write-Host "Built: $compatArchive"
Write-Host "SHA256: $($hash.Hash.ToLowerInvariant())"
