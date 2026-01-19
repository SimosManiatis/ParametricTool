
$ErrorActionPreference = "Stop"

$pythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
$getPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$runtimeDir = Join-Path $PSScriptRoot "python_runtime"
$zipPath = Join-Path $PSScriptRoot "python.zip"
$getPipPath = Join-Path $runtimeDir "get-pip.py"

Write-Host "--- Setting up Portable Python 3.11 ---"

# 1. Clean previous runtime
if (Test-Path $runtimeDir) {
    Write-Host "Removing existing runtime directory..."
    Remove-Item -Path $runtimeDir -Recurse -Force
}
New-Item -ItemType Directory -Path $runtimeDir | Out-Null

# 2. Download Python Embeddable
Write-Host "Downloading Python 3.11..."
Invoke-WebRequest -Uri $pythonUrl -OutFile $zipPath

# 3. Extract
Write-Host "Extracting..."
Expand-Archive -Path $zipPath -DestinationPath $runtimeDir -Force
Remove-Item $zipPath

# 4. Configure ._pth file to allow site-packages (CRITICAL)
# We need to uncomment "import site" to allow pip to work
$pthFile = Get-ChildItem -Path $runtimeDir -Filter "*._pth" | Select-Object -First 1
if ($pthFile) {
    Write-Host "Configuring $($pthFile.Name) for pip support..."
    $content = Get-Content $pthFile.FullName
    $newContent = $content -replace "#import site", "import site"
    Set-Content -Path $pthFile.FullName -Value $newContent
}

# 5. Install PIP
Write-Host "Downloading get-pip.py..."
Invoke-WebRequest -Uri $getPipUrl -OutFile $getPipPath

Write-Host "Installing pip..."
& "$runtimeDir\python.exe" $getPipPath --no-warn-script-location

# 6. Install Requirements
Write-Host "Installing project requirements..."
& "$runtimeDir\python.exe" -m pip install -r (Join-Path $PSScriptRoot "requirements.txt") --no-warn-script-location

Write-Host "--- Setup Complete ---"
Write-Host "Python location: $runtimeDir\python.exe"
