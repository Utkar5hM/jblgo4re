# Read-only Windows host probe. Run in PowerShell 5.1 or newer.
param(
    [double]$IntervalSeconds = 5,
    [double]$DurationSeconds = 0,
    [string]$Output = "captures\windows.jsonl"
)

if ($IntervalSeconds -lt 0 -or $DurationSeconds -lt 0) {
    throw "IntervalSeconds and DurationSeconds must be nonnegative"
}

$directory = Split-Path -Parent $Output
if ($directory -and !(Test-Path $directory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

$started = Get-Date
do {
    $devices = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Class -in @('AudioEndpoint', 'Media', 'USB') -or
            ($_.Class -eq 'Bluetooth' -and $_.FriendlyName -match 'JBL|Go 4|ZGMICRO|VIMICRO')
        } |
        Select-Object Class, FriendlyName, Status, InstanceId)

    $soundDevices = @(Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue |
        Select-Object Name, Status, PNPDeviceID)

    $sample = [ordered]@{
        time_utc = (Get-Date).ToUniversalTime().ToString('o')
        pnp_devices = $devices
        sound_devices = $soundDevices
    }
    $sample | ConvertTo-Json -Depth 5 -Compress | Add-Content -Path $Output -Encoding UTF8
    if ($IntervalSeconds -eq 0 -or ($DurationSeconds -gt 0 -and ((Get-Date) - $started).TotalSeconds -ge $DurationSeconds)) {
        break
    }
    Start-Sleep -Milliseconds ([int]($IntervalSeconds * 1000))
} while ($true)

Write-Host "Saved samples to $Output"
