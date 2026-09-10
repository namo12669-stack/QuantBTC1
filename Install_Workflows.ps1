$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Destination = Join-Path $Root '.github\workflows'
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Get-ChildItem -LiteralPath (Join-Path $Root 'WORKFLOW_COPIES') -Filter '*.yml.txt' | ForEach-Object {
    $Name = $_.Name.Substring(0, $_.Name.Length - 4)
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Destination $Name) -Force
}
Write-Host 'Workflows restored locally under .github/workflows. Commit or upload that directory to the repository default branch.'
Write-Host 'No GitHub credentials were requested and no remote files were changed.'
