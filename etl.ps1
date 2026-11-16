<#
.SYNOPSIS
Capture ETL coverage or compare full, file and line test runs with TestMind.
.EXAMPLE
./etl.ps1 baseline -EtlRepo "C:\projects\ETL_Customer"
./etl.ps1 compare -EtlRepo "C:\projects\ETL_Customer"
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("baseline", "compare")]
    [string]$Action = "compare",

    [ValidateNotNullOrEmpty()]
    [string]$EtlRepo = (Join-Path $HOME "ETL_Customer"),

    [ValidateNotNullOrEmpty()]
    [string]$Base = "8c8ff5414f808642394566a96f4e8a877313663a",

    [ValidateNotNullOrEmpty()]
    [string]$Database = (Join-Path $PSScriptRoot ".testmind/etl.sqlite"),

    [string]$Report,

    [ValidateSet("file", "line", "both")]
    [string]$Strategy = "both",

    [string]$Target,
    [string]$Python
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
# Handle native failures explicitly, including when the caller enabled this option.
$PSNativeCommandUseErrorActionPreference = $false

try {
    # PowerShell validation is case-insensitive; Python's CLI choices are not.
    $Action = $Action.ToLowerInvariant()
    $Strategy = $Strategy.ToLowerInvariant()
    if ($Action -eq "baseline" -and $Target) {
        throw "-Target applies only to compare. Baseline captures -Base."
    }
    if (-not $Report) {
        $name = if ($Action -eq "baseline") { "etl-baseline.json" } else { "etl-comparison.json" }
        $Report = Join-Path $PSScriptRoot ".testmind/$name"
    }

    # Resolve caller-supplied relative paths before changing to the tool directory.
    $EtlRepo = (Resolve-Path -LiteralPath $EtlRepo).ProviderPath
    $Database = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Database)
    $Report = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Report)

    if (-not $Python) {
        foreach ($candidate in @(".venv/Scripts/python.exe", ".venv/bin/python")) {
            $path = Join-Path $PSScriptRoot $candidate
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                $Python = $path
                break
            }
        }
        if (-not $Python) { $Python = "python" }
    }
    $Python = (Get-Command -Name $Python -CommandType Application -ErrorAction Stop).Source

    $arguments = @("-m", "experiments.run_experiment", $Action,
        "--repo", $EtlRepo, "--base", $Base, "--db", $Database, "--output", $Report)
    if ($Action -eq "compare") {
        $arguments += @("--strategy", $Strategy)
        if ($Target) { $arguments += @("--target", $Target) }
    }

    Push-Location -LiteralPath $PSScriptRoot
    try {
        & $Python @arguments
        $runExitCode = $LASTEXITCODE
        if ($runExitCode -ne 0) { exit $runExitCode }

        # Read a report only after a successful command; never display a stale result.
        $result = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
        if ($Action -eq "baseline") {
            Write-Host ("Baseline captured: {0} test items ({1:F2}s)" -f $result.test_count, $result.baseline_seconds)
        } else {
            Write-Host ("Full: {0} tests, {1} failures ({2:F2}s)" -f
                $result.full.count, @($result.full.failed).Count, $result.full.duration)
            foreach ($run in $result.strategies.PSObject.Properties) {
                Write-Host ("`n{0}: {1} tests, {2} failures" -f
                    $run.Name, $run.Value.count, @($run.Value.failed).Count)
                $run.Value.metrics | Format-List
            }
            Write-Host ("Entire comparison: {0:F2}s" -f $result.comparison_seconds)
        }
        Write-Host "Report: $Report"
    } finally {
        Pop-Location
    }
} catch {
    [Console]::Error.WriteLine("etl.ps1: " + $_.Exception.Message)
    exit 1
}
exit 0
