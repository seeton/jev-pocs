$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Install requirements-drive.txt in a .venv first. See DRIVING.md.' }
$previousKey = $env:TYPESAFE_API_KEY
$secureKey = $null
$pointer = [IntPtr]::Zero
try {
    if ($args -notcontains 'baseline' -and $args -notcontains '--help') {
        Import-Module "$PSHOME\Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1" -ErrorAction Stop
        $keyFile = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'jev\typesafe-api-key.dpapi'
        if (-not (Test-Path -LiteralPath $keyFile)) { throw 'Run .\jev.cmd -ConfigureKey first.' }
        $secureKey = ConvertTo-SecureString ([IO.File]::ReadAllText($keyFile))
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        # Passed only to the child process; never put in command arguments or output.
        $env:TYPESAFE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim()
    }
    & $python (Join-Path $PSScriptRoot 'driving.py') @args
    $code = $LASTEXITCODE
} finally {
    $env:TYPESAFE_API_KEY = $previousKey
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($secureKey) { $secureKey.Dispose() }
}
exit $code
