param(
    [string]$Unit = 'PD60',
    [string]$InputDir = '',
    [string]$IdfDir = '',
    [string]$WeldTable = '',
    [string]$Pipeline = '',
    [int]$Workers = 2,
    [string]$OutDir = '',
    [string]$ManagementTablesDir = '',
    [switch]$NoManagement,
    [switch]$ListUnits
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$taskArgs = @((Join-Path $PSScriptRoot 'run_beihai.py'), '--unit', $Unit, '--workers', $Workers)
if ($ListUnits) {
    & python (Join-Path $PSScriptRoot 'run_beihai.py') --list-units
    exit $LASTEXITCODE
}
if ($InputDir) { $taskArgs += @('--input-dir', $InputDir) }
if ($IdfDir) { $taskArgs += @('--idf-dir', $IdfDir) }
if ($WeldTable) { $taskArgs += @('--weld-table', $WeldTable) }
if ($Pipeline) { $taskArgs += @('--pipeline', $Pipeline) }
if ($OutDir) { $taskArgs += @('--out-dir', $OutDir) }
if ($ManagementTablesDir) { $taskArgs += @('--management-tables-dir', $ManagementTablesDir) }
if ($NoManagement) { $taskArgs += '--no-management' }
& python @taskArgs
exit $LASTEXITCODE
