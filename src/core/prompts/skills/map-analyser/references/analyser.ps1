param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$map_name
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$csPath = Join-Path $scriptDir "analyser.cs"

if (-not (Test-Path -LiteralPath $csPath)) {
    throw "analyser.cs not found: $csPath"
}

$code = [System.IO.File]::ReadAllText($csPath)
$code = $code.Replace("###MAP_NAME###", $map_name)

$body = @{ code = $code } | ConvertTo-Json -Compress

$response = Invoke-RestMethod `
    -Uri "http://127.0.0.1:30033/api/csharpscript/run/code" `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body))

if ($response -is [string]) {
    Write-Output $response
} else {
    $response | ConvertTo-Json -Depth 20
}