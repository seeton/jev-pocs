$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$previousKey = $env:TYPESAFE_API_KEY
$secureKey = $null
$pointer = [IntPtr]::Zero
Push-Location -LiteralPath $repoRoot
try {
    if ($args -notcontains '--replay' -and $args -notcontains '--help') {
        Import-Module "$PSHOME\Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1" -ErrorAction Stop
        $keyFile = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'jev\typesafe-api-key.dpapi'
        if (Test-Path -LiteralPath $keyFile) {
            $secureKey = ConvertTo-SecureString ([IO.File]::ReadAllText($keyFile))
            $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
            $env:TYPESAFE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim()
        }
    }
    & $python -m pocs.inspection.app @args
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    $env:TYPESAFE_API_KEY = $previousKey
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($secureKey) { $secureKey.Dispose() }
}
exit $code
