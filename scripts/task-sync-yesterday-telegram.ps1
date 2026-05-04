param(
  [string]$BaseUrl = "http://127.0.0.1:3002",
  [string]$SyncSecret = "",
  [int]$TimeoutSeconds = 3600,
  [int]$PollSeconds = 2,
  [int]$RequestTimeoutSeconds = 45,
  [int]$ApiRetryCount = 3,
  [int]$ApiRetryDelaySeconds = 3,
  [string]$LogDir = "",
  # Se non impostato: GET /api/feed/digest usa la cache DB se esiste (come la UI senza "forza").
  # Con -ForceDigest si passa force=true e si rigenera sempre con OpenAI.
  [switch]$ForceDigest
)

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($LogDir)) {
  $LogDir = Join-Path $RepoRoot "logs"
}

$ErrorActionPreference = "Stop"
$global:TaskFailed = $false
$global:LogFile = $null

function Write-Log {
  param(
    [string]$Message,
    [ValidateSet("INFO", "WARN", "ERROR")] [string]$Level = "INFO"
  )
  $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
  $line = "[$ts][$Level] $Message"
  Write-Host $line
  if ($global:LogFile) {
    Add-Content -Path $global:LogFile -Value $line
  }
}

function Initialize-Logging {
  param([string]$Dir)
  if (-not (Test-Path -LiteralPath $Dir)) {
    New-Item -ItemType Directory -Path $Dir | Out-Null
  }
  $stamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
  $global:LogFile = Join-Path $Dir "task-sync-yesterday-telegram-$stamp.log"
  New-Item -ItemType File -Path $global:LogFile -Force | Out-Null
}

function Get-SyncSecretFromEnvFile {
  param([string]$RepoRootPath)
  $candidates = @(
    (Join-Path $RepoRootPath ".env")
    (Join-Path (Get-Location) ".env")
  )
  $EnvPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if (-not $EnvPath) {
    return ""
  }
  $line = Get-Content -Path $EnvPath | Where-Object { $_ -match '^\s*MEDIA_ADVISOR_SYNC_SECRET\s*=' } | Select-Object -First 1
  if (-not $line) {
    return ""
  }
  $value = ($line -split '=', 2)[1].Trim()
  if ($value.StartsWith('"') -and $value.EndsWith('"')) {
    $value = $value.Trim('"')
  }
  if ($value.StartsWith("'") -and $value.EndsWith("'")) {
    $value = $value.Trim("'")
  }
  return $value
}

function Get-ErrorResponseContent {
  param([System.Management.Automation.ErrorRecord]$Err)
  if ($Err.ErrorDetails -and $Err.ErrorDetails.Message) {
    return $Err.ErrorDetails.Message.Trim()
  }
  $ex = $Err.Exception
  if (-not $ex.Response) { return $null }

  # Windows PowerShell 5.x - HttpWebResponse
  try {
    if ($ex.Response -is [System.Net.HttpWebResponse]) {
      $stream = $ex.Response.GetResponseStream()
      if (-not $stream) { return $null }
      $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
      try { return $reader.ReadToEnd().Trim() } finally { $reader.Close() }
    }
  } catch {}

  # PowerShell 7+ - HttpResponseMessage
  try {
    $task = $ex.Response.Content.ReadAsStringAsync()
    return $task.GetAwaiter().GetResult().Trim()
  } catch {}

  return $null
}

function New-Headers {
  param([string]$Secret)
  $headers = @{
    "Content-Type" = "application/json; charset=utf-8"
  }
  if ($Secret -and $Secret.Trim().Length -gt 0) {
    $headers["X-Media-Advisor-Sync"] = $Secret.Trim()
  }
  return $headers
}

function ConvertTo-StableApiJson {
  param([hashtable]$Object)
  # Windows PowerShell 5.1: ConvertTo-Json breaks or truncates large strings; use JavaScriptSerializer.
  if ($PSVersionTable.PSEdition -ne "Core" -and $PSVersionTable.PSVersion.Major -lt 6) {
    Add-Type -AssemblyName System.Web.Extensions
    $jss = New-Object System.Web.Script.Serialization.JavaScriptSerializer
    $jss.MaxJsonLength = 2147483644
    $dict = New-Object "System.Collections.Generic.Dictionary[string,string]"
    foreach ($k in $Object.Keys) {
      $dict[$k] = [string]$Object[$k]
    }
    return $jss.Serialize($dict)
  }
  return ($Object | ConvertTo-Json -Compress -Depth 20)
}

function Invoke-JsonRequestUtf8 {
  param(
    [ValidateSet("GET", "POST")] [string]$Method,
    [string]$Url,
    [hashtable]$Headers,
    [byte[]]$PostBody,
    [int]$TimeoutSec
  )
  # Avoid Invoke-RestMethod: on Windows PowerShell 5.x JSON response is decoded with system ANSI code page,
  # corrupting UTF-8 text (e.g. digest_raw: arrow becomes mojibake, accents break).
  $req = [System.Net.HttpWebRequest]::Create($Url)
  $req.Method = $Method
  $req.Accept = "application/json"
  $req.Timeout = $TimeoutSec * 1000
  foreach ($key in $Headers.Keys) {
    $name = [string]$key
    $val = [string]$Headers[$key]
    if ($name -eq "Content-Type" -and ($Method -eq "GET" -or $null -eq $PostBody)) { continue }
    $lname = $name.ToLowerInvariant()
    if ($lname -eq "accept") { $req.Accept = $val; continue }
    if ($lname -eq "host") { continue }
    if ($lname -eq "content-type") { continue }
    try {
      $req.Headers.Add($name, $val)
    } catch {
      # Restricted header - skip
    }
  }
  if ($Method -eq "POST" -and $null -ne $PostBody) {
    $req.ContentType = "application/json; charset=utf-8"
    $req.ContentLength = $PostBody.Length
    $ws = $req.GetRequestStream()
    $ws.Write($PostBody, 0, $PostBody.Length)
    $ws.Flush()
    $ws.Close()
  }
  $resp = $req.GetResponse()
  $sr = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.UTF8Encoding]::new($false))
  $text = $sr.ReadToEnd()
  $sr.Close()
  if ([string]::IsNullOrWhiteSpace($text)) { return $null }
  return ($text | ConvertFrom-Json)
}

function Invoke-Api {
  param(
    [ValidateSet("GET", "POST")] [string]$Method,
    [string]$Url,
    [hashtable]$Headers,
    [object]$Body = $null,
    [int]$RetryCount = 3,
    [int]$RetryDelaySeconds = 3,
    [int]$TimeoutSec = 45
  )

  $attempt = 1
  while ($true) {
    try {
      if ($Method -eq "GET") {
        return Invoke-JsonRequestUtf8 -Method GET -Url $Url -Headers $Headers -PostBody $null -TimeoutSec $TimeoutSec
      }

      if ($null -eq $Body) {
        return Invoke-JsonRequestUtf8 -Method POST -Url $Url -Headers $Headers -PostBody $null -TimeoutSec $TimeoutSec
      }

      $json = ConvertTo-StableApiJson -Object $Body
      $utf8 = New-Object System.Text.UTF8Encoding $false
      $jsonBytes = $utf8.GetBytes($json)
      return Invoke-JsonRequestUtf8 -Method POST -Url $Url -Headers $Headers -PostBody $jsonBytes -TimeoutSec $TimeoutSec
    } catch {
      $statusCode = $null
      try {
        $r = $_.Exception.Response
        if ($r -is [System.Net.HttpWebResponse]) {
          $statusCode = [int]$r.StatusCode
        } elseif ($null -ne $r -and $r.StatusCode) {
          $statusCode = [int]$r.StatusCode
        }
      } catch {}
      $errMsg = if ($_.Exception.Message) { $_.Exception.Message } else { "unknown API error" }
      $body = Get-ErrorResponseContent -Err $_

      # 409 is meaningful for sync trigger (already running), return caller-handled failure.
      if ($statusCode -eq 409) {
        throw
      }

      # Retry transient failures only (network / timeout / overload). Never retry 401/403/404/422/500.
      $isRetryable = (
        ($null -eq $statusCode) -or `
        (($statusCode -ge 502) -and ($statusCode -lt 600))
      )
      if (-not $isRetryable -or $attempt -ge $RetryCount) {
        $suffix = ""
        if ($statusCode -and $body -and ($body.Trim().Length -gt 0)) {
          $suffix = " Body: $($body.Trim())"
        }
        throw "API call failed [$Method $Url] HTTP $statusCode after $attempt attempt(s): $errMsg$suffix"
      }

      Write-Log "API transient error on attempt $attempt/${RetryCount}: $Method $Url -> $errMsg. Retrying in ${RetryDelaySeconds}s..." "WARN"
      Start-Sleep -Seconds $RetryDelaySeconds
      $attempt += 1
    }
  }
}

function Wait-ForSyncCompletion {
  param(
    [string]$Base,
    [hashtable]$Headers,
    [datetime]$Deadline
  )

  while ($true) {
    if ((Get-Date) -gt $Deadline) {
      throw "Sync timeout after $TimeoutSeconds seconds."
    }

    $status = Invoke-Api -Method GET -Url "$Base/api/sync/status" -Headers $Headers -RetryCount $ApiRetryCount -RetryDelaySeconds $ApiRetryDelaySeconds -TimeoutSec $RequestTimeoutSeconds
    $state = "$($status.status)"

    if ($state -eq "done") {
      Write-Log "Sync completed."
      return
    }
    if ($state -eq "error") {
      $errText = if ($status.error) { $status.error } else { "unknown sync error" }
      throw "Sync failed: $errText"
    }

    Start-Sleep -Seconds $PollSeconds
  }
}

$base = $BaseUrl.TrimEnd("/")
$resolvedSecret = if ($SyncSecret -and $SyncSecret.Trim().Length -gt 0) { $SyncSecret.Trim() } else { Get-SyncSecretFromEnvFile -RepoRootPath $RepoRoot }
$secretSource = if ($resolvedSecret) { if ($SyncSecret) { "parameter" } else { ".env" } } else { "none" }
$headers = New-Headers -Secret $resolvedSecret
$targetDate = (Get-Date).Date.AddDays(-1).ToString("yyyy-MM-dd")

try {
  Initialize-Logging -Dir $LogDir
  Write-Log "Task started."
  Write-Log "RepoRoot=$RepoRoot LogDir=$LogDir"
  Write-Log "BaseUrl=$base TargetDate=$targetDate Timeout=${TimeoutSeconds}s Poll=${PollSeconds}s SecretSource=$secretSource"

  Write-Log "[0/4] Health check..."
  $health = Invoke-Api -Method GET -Url "$base/api/health/ready" -Headers $headers -RetryCount $ApiRetryCount -RetryDelaySeconds $ApiRetryDelaySeconds -TimeoutSec $RequestTimeoutSeconds
  if ($health.status -ne "ok") {
    throw "Health check failed: unexpected response."
  }
  Write-Log "Health check OK."

  Write-Log "[1/4] Starting sync recent..."
  try {
    $syncStart = Invoke-Api -Method POST -Url "$base/api/sync/recent" -Headers $headers -RetryCount $ApiRetryCount -RetryDelaySeconds $ApiRetryDelaySeconds -TimeoutSec $RequestTimeoutSeconds
    Write-Log "Sync trigger response: $($syncStart.status)"
  } catch {
    $statusCode = $null
    try { $statusCode = $_.Exception.Response.StatusCode.value__ } catch {}
    if ($statusCode -ne 409) {
      throw
    }
    Write-Log "Sync already running (409). Waiting for completion..." "WARN"
  }

  Write-Log "[2/4] Waiting sync completion..."
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  Wait-ForSyncCompletion -Base $base -Headers $headers -Deadline $deadline

  $digestQs = "date=$targetDate"
  if ($ForceDigest) {
    $digestQs += "&force=true"
    Write-Log "[3/4] Loading digest for $targetDate (force=true - rigenerazione OpenAI)..."
  } else {
    Write-Log "[3/4] Loading digest for $targetDate (cache DB se presente, altrimenti generazione)..."
  }
  $digestRes = Invoke-Api -Method GET -Url "$base/api/feed/digest?$digestQs" -Headers $headers -RetryCount $ApiRetryCount -RetryDelaySeconds $ApiRetryDelaySeconds -TimeoutSec $RequestTimeoutSeconds

  if ($digestRes.cached -eq $true) {
    Write-Log "Digest da cache (gia salvato per $targetDate), nessuna nuova chiamata LLM."
  } elseif ($digestRes.cached -eq $false) {
    Write-Log "Digest appena generato o aggiornato (cached=false)."
  }

  $digestRaw = $digestRes.digest_raw
  if (-not $digestRaw) {
    $msg = if ($digestRes.message) { $digestRes.message } else { "digest_raw empty" }
    throw "Digest generation failed: $msg"
  }
  if ($digestRaw -isnot [string]) {
    $digestRaw = [string]$digestRaw
  }

  Write-Log "[4/4] Publishing digest to Telegram..."
  $publishBody = @{
    digest = $digestRaw
    date   = $targetDate
  }
  $publishRes = Invoke-Api -Method POST -Url "$base/api/feed/digest/publish-telegram" -Headers $headers -Body $publishBody -RetryCount $ApiRetryCount -RetryDelaySeconds $ApiRetryDelaySeconds -TimeoutSec $RequestTimeoutSeconds

  if (-not $publishRes.published) {
    throw "Telegram publish failed."
  }

  Write-Log "DONE: Telegram published for $targetDate."
  Write-Log ("Chunks sent: " + $publishRes.chunks_sent)
  Write-Log ("Message IDs: " + (($publishRes.message_ids -join ", ")))
  exit 0
} catch {
  $global:TaskFailed = $true
  $message = if ($_.Exception.Message) { $_.Exception.Message } else { "$_" }
  Write-Log "FAILED: $message" "ERROR"
  exit 1
} finally {
  if ($global:LogFile) {
    if ($global:TaskFailed) {
      Write-Host "Task failed. Log file: $global:LogFile"
    } else {
      Write-Host "Task completed successfully. Log file: $global:LogFile"
    }
  }
}
