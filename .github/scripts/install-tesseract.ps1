# Upstream Windows installer, pinned to the release asset's published SHA-256.
# https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3
$ErrorActionPreference = 'Stop'
$url = 'https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe'
$expected = 'bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4'
$installer = Join-Path $env:RUNNER_TEMP 'tesseract-5.5.3-setup.exe'
$destination = Join-Path $env:RUNNER_TEMP 'scriptor-tesseract-5.5.3'
if (Test-Path $destination) {
    throw "Refusing to install over an existing directory: $destination"
}
Invoke-WebRequest -Uri $url -OutFile $installer
$actual = (Get-FileHash -Path $installer -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'Upstream Tesseract installer checksum mismatch' }
# /D must be last for NSIS; RUNNER_TEMP is a fresh CI-owned destination.
$process = Start-Process -FilePath $installer -ArgumentList @('/S', "/D=$destination") -PassThru -Wait
if ($process.ExitCode -ne 0) { throw "Tesseract installer failed: $($process.ExitCode)" }
$executable = Join-Path $destination 'tesseract.exe'
$version = @(& $executable --version)
$engineStatus = $LASTEXITCODE
$version | Write-Output
if ($engineStatus -ne 0 -or $version[0] -notmatch '^tesseract v?5\.5\.3(?:[.\s-]|$)') {
    throw 'Installed Tesseract engine version does not match the pin'
}
$destination | Out-File -FilePath $env:GITHUB_PATH -Append -Encoding utf8
