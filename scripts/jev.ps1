[CmdletBinding()]
param(
    [switch]$ConfigureKey,
    [switch]$Check,
    [switch]$DryRun,
    [switch]$SelfTest,
    [string]$RequestFile
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$ProgressPreference = 'SilentlyContinue'
# Load the module that belongs to this PowerShell runtime before asking for a key.
Import-Module "$PSHOME\Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1" -ErrorAction Stop

if ($SelfTest) {
    # Synthetic data only: never read or replace the user's saved credential.
    $testSecure = ConvertTo-SecureString 'jev-offline-dpapi-test' -AsPlainText -Force
    $testRestored = $null
    $testPointer = [IntPtr]::Zero
    try {
        $testEncrypted = ConvertFrom-SecureString $testSecure
        $testRestored = ConvertTo-SecureString $testEncrypted
        $testPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($testRestored)
        if ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($testPointer) -ne 'jev-offline-dpapi-test') {
            throw 'DPAPI roundtrip failed.'
        }
        Write-Output 'PASS: security module loaded and DPAPI encryption/decryption verified. No API call or saved-key access.'
    } finally {
        if ($testPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($testPointer) }
        if ($testRestored) { $testRestored.Dispose() }
        $testSecure.Dispose()
    }
    exit 0
}
if (-not $RequestFile) { $RequestFile = Join-Path $repoRoot 'examples\support-ticket.json' }
$keyDirectory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'jev'
$keyFile = Join-Path $keyDirectory 'typesafe-api-key.dpapi'

if ($ConfigureKey) {
    Write-Host 'Create a TypeSafe key: https://console.typesafe.ai/settings/keys'
    Write-Host 'Input is masked. Do not paste your key into chat.'
    $secureKey = Read-Host 'TypeSafe API key' -AsSecureString
    try {
        if ($secureKey.Length -eq 0) { throw 'The key is empty. Nothing was saved.' }
        $encrypted = ConvertFrom-SecureString -SecureString $secureKey
        [void][IO.Directory]::CreateDirectory($keyDirectory)
        [IO.File]::WriteAllText($keyFile, $encrypted, [Text.Encoding]::ASCII)
        Write-Host 'Key saved using Windows DPAPI encryption for your Windows user.'
        Write-Host 'Next: .\jev.cmd -Check'
        Write-Host 'Demo: .\jev.cmd'
    } finally {
        if ($secureKey) { $secureKey.Dispose() }
        $encrypted = $null
    }
    exit 0
}

try {
    if (-not $Check) {
        $requestText = [IO.File]::ReadAllText($RequestFile, [Text.Encoding]::UTF8)
        $request = ConvertFrom-Json -InputObject $requestText
        if (-not $request.model -or $null -eq $request.state -or -not $request.questions) {
            throw 'Request must contain model, state and questions.'
        }
        if ($DryRun) {
            Write-Output 'Valid JSON request. No API request was sent; no key was loaded.'
            Write-Output ($request | ConvertTo-Json -Depth 30)
            exit 0
        }
    } elseif ($DryRun) {
        throw 'Choose either -Check or -DryRun.'
    }

    if (-not (Test-Path -LiteralPath $keyFile)) {
        throw 'No saved key. Run .\jev.cmd -ConfigureKey in your own terminal first.'
    }
    $secureKey = ConvertTo-SecureString -String ([IO.File]::ReadAllText($keyFile))
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try {
        $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer).Trim()
        $headers = @{ Authorization = ('Bearer ' + $plainKey) }
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        try {
            if ($Check) {
                $response = Invoke-WebRequest -UseBasicParsing -Method Get -Uri 'https://api.typesafe.ai/v1/models' -Headers $headers -TimeoutSec 30
            } else {
                $body = [Text.Encoding]::UTF8.GetBytes($requestText)
                $response = Invoke-WebRequest -UseBasicParsing -Method Post -Uri 'https://api.typesafe.ai/v1/systemone' -Headers $headers -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 30
            }
        } catch {
            # Never print raw HTTP errors, request headers or credentials.
            $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
            $hint = switch ($status) {
                401 { 'Authentication failed. Run .\jev.cmd -ConfigureKey to replace the key.' }
                403 { 'Access denied. Check your TypeSafe account access.' }
                402 { 'Check your TypeSafe account balance or billing.' }
                429 { 'Rate limit or quota reached. Try later or check your account.' }
                400 { 'Invalid request. Check your request JSON against the API documentation.' }
                0 { 'Connection failed or timed out. Check your network and try again.' }
                default { 'Request failed. Check the TypeSafe service and API documentation.' }
            }
            throw "TypeSafe API error (HTTP $status). $hint"
        }
        # Windows PowerShell 5.1 may assume the wrong encoding for JSON without a charset.
        $response.RawContentStream.Position = 0
        $reader = [IO.StreamReader]::new($response.RawContentStream, [Text.Encoding]::UTF8)
        try {
            $result = ConvertFrom-Json -InputObject $reader.ReadToEnd()
        } finally {
            $reader.Dispose()
        }
        # Redact the credential even if a remote response unexpectedly includes it.
        $output = $result | ConvertTo-Json -Depth 50
        Write-Output ($output.Replace($plainKey, '[REDACTED]'))
    } finally {
        if ($headers) { $headers.Clear() }
        $plainKey = $null
        if ($keyPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer) }
        if ($secureKey) { $secureKey.Dispose() }
    }
} catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
}
