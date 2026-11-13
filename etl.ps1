param(
    [ValidateSet("baseline", "compare")]
    [string]$Action = "compare"
)

# Your experiment settings
$EtlRepo  = "C:\Users\PRERAK PATEL\Desktop\ETLProject"
$Base     = "2cfec204956d9a3349a424accfd713753a720a21"
$Database = ".testmind\etl.sqlite"
$Strategy = "both"
$Report   = ".testmind\etl-comparison.json"

Push-Location $PSScriptRoot
try {
    $common = @("--repo", $EtlRepo, "--base", $Base, "--db", $Database)

    if ($Action -eq "baseline") {
        python -m experiments.run_experiment baseline @common
    } else {
        python -m experiments.run_experiment compare @common --strategy $Strategy --output $Report

        if ($LASTEXITCODE -eq 0) {
            $result = Get-Content $Report -Raw | ConvertFrom-Json
            foreach ($run in $result.strategies.PSObject.Properties) {
                Write-Host "`n$($run.Name) selection"
                $run.Value.metrics | Format-List
            }
        }
    }
} finally {
    Pop-Location
}