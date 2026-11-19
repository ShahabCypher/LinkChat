$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    $PyInstaller = Join-Path $RepoRoot ".venv\Scripts\pyinstaller.exe"
    if (-not (Test-Path $PyInstaller)) {
        throw "PyInstaller not found at $PyInstaller. Run: .\.venv\Scripts\pip.exe install -e `".[dev,windows,build]`""
    }

    & $PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "linkchat.spec")
    $ExePath = Join-Path $RepoRoot "dist\LinkChat.exe"
    if (-not (Test-Path $ExePath)) {
        throw "Expected executable not found at $ExePath"
    }
    Write-Host "Built Windows app: $ExePath"
}
finally {
    Pop-Location
}
