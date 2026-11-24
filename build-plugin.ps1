param(
    [switch]$SkipPackage
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$projectFile = Join-Path $projectRoot "ScheduledShutdown.csproj"
$localDotnet = Join-Path $projectRoot ".dotnet\dotnet.exe"

if (Test-Path -LiteralPath $localDotnet) {
    $dotnet = $localDotnet
}
else {
    $dotnetCommand = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($null -eq $dotnetCommand) {
        throw "No .NET SDK was found. Install the .NET 8 SDK and try again."
    }
    $dotnet = $dotnetCommand.Source
}

& $dotnet build $projectFile -c Release -v:minimal
if ($LASTEXITCODE -ne 0) {
    throw "Plugin build failed."
}

if ($SkipPackage) {
    return
}

$publishDirectory = Join-Path $projectRoot "cipx\publish"
$packagePath = Join-Path $projectRoot "cipx\ScheduledShutdown.cipx"

& $dotnet publish $projectFile `
    -c Release `
    -o $publishDirectory `
    -p:UseAppHost=false `
    -v:minimal
if ($LASTEXITCODE -ne 0) {
    throw "Plugin publish failed."
}

$temporaryZip = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    ("ScheduledShutdown-" + [guid]::NewGuid().ToString("N") + ".zip")

Compress-Archive -Path (Join-Path $publishDirectory "*") `
    -DestinationPath $temporaryZip
Move-Item -LiteralPath $temporaryZip `
    -Destination $packagePath `
    -Force

Write-Host "Plugin package created: $packagePath"
