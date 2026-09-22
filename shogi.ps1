$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$previousKey = $env:TYPESAFE_API_KEY
$secureKey = $null
$pointer = [IntPtr]::Zero
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
    & $python (Join-Path $PSScriptRoot 'shogi_app.py') @args
    $code = $LASTEXITCODE
} finally {
    $env:TYPESAFE_API_KEY = $previousKey
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($secureKey) { $secureKey.Dispose() }
}
exit $code
