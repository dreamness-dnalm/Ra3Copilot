param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SrcRoot = Join-Path $ProjectRoot "src"

Push-Location $SrcRoot
try {
    if ($Clean) {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
            (Join-Path $SrcRoot "build"), `
            (Join-Path $SrcRoot "dist")
    }

    uv run --extra build pyinstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onefile `
        --name Ra3Copilot `
        --collect-submodules pystray `
        --collect-submodules PIL `
        --add-data "desktop/web;desktop/web" `
        --add-data "core/prompts;core/prompts" `
        desktop\app.py

    Write-Host "EXE generated at: $(Join-Path $SrcRoot 'dist\Ra3Copilot.exe')"
}
finally {
    Pop-Location
}
