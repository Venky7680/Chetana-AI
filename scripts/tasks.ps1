# Chetana AI — common tasks on Windows / PowerShell.
#
#   .\scripts\tasks.ps1 init     one-time local setup: .env, tenants.json, users.json
#   .\scripts\tasks.ps1 demo     stub Keep + BFF + console in Docker (no Keep required)
#   .\scripts\tasks.ps1 up       BFF + console against a Keep you already run
#   .\scripts\tasks.ps1 down     stop everything
#   .\scripts\tasks.ps1 setup    install BFF and console dependencies
#   .\scripts\tasks.ps1 test     BFF unit + API tests
#   .\scripts\tasks.ps1 smoke    end-to-end checks over real HTTP
#   .\scripts\tasks.ps1 lint     ruff + tsc
#   .\scripts\tasks.ps1 secret   print a fresh JWT secret (init does this for you)

param(
    [Parameter(Position = 0)]
    [ValidateSet("init", "real", "seed", "setup", "test", "smoke", "lint", "build", "demo", "up", "down", "status", "secret", "help")]
    [string]$Task = "help",

    # init only: console password. Omit and you are prompted.
    [string]$Password
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Bff = Join-Path $Root "bff"
$Web = Join-Path $Root "web"

function Invoke-In($Path, $ScriptBlock) {
    Push-Location $Path
    try { & $ScriptBlock } finally { Pop-Location }
}

# $ErrorActionPreference = "Stop" makes PowerShell treat ANY stderr output from
# a native command as a terminating error — including purely informational lines
# like docker's "No stopped containers". Use this for commands whose stderr is
# chatter rather than failure.
function Invoke-Tolerant($ScriptBlock) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $ScriptBlock *>&1 | Out-Null } catch { } finally {
        $ErrorActionPreference = $previous
        $global:LASTEXITCODE = 0
    }
}

# Windows PowerShell 5.1's `Set-Content -Encoding UTF8` writes a BOM, which
# json.loads rejects. Always write config files as UTF-8 without one.
function Write-Utf8NoBom($Path, $Content) {
    if ($Content -is [array]) { $Content = ($Content -join "`r`n") }
    [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-JwtSecret {
    Invoke-In $Bff { (python -m app.cli new-secret) | Select-Object -First 1 }
}

function Get-PasswordHash($Plain) {
    Invoke-In $Bff { (python -m app.cli hash-password $Plain) | Select-Object -First 1 }
}

function Assert-Configured {
    $envPath = Join-Path $Root ".env"
    if (-not (Test-Path $envPath)) {
        throw "No .env yet. Run:  .\scripts\tasks.ps1 init"
    }
    $line = Select-String -Path $envPath -Pattern '^CHETANA_JWT_SECRET=(.+)$' -ErrorAction SilentlyContinue
    if (-not $line) {
        throw "CHETANA_JWT_SECRET is empty in .env. Run:  .\scripts\tasks.ps1 init"
    }
    foreach ($name in @("tenants.json", "users.json")) {
        $path = Join-Path $Root "config\$name"
        if (-not (Test-Path $path)) { throw "config\$name is missing. Run:  .\scripts\tasks.ps1 init" }
        if ((Get-Content $path -Raw) -match 'REPLACE') {
            throw "config\$name still has placeholder values. Run:  .\scripts\tasks.ps1 init"
        }
    }
}

function Invoke-Init {
    # --- .env -------------------------------------------------------------
    $envPath = Join-Path $Root ".env"
    if (-not (Test-Path $envPath)) {
        Copy-Item (Join-Path $Root ".env.example") $envPath
    }

    $existing = Select-String -Path $envPath -Pattern '^CHETANA_JWT_SECRET=(.+)$' -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  .env            already has a JWT secret, keeping it" -ForegroundColor DarkGray
    }
    else {
        $secret = Get-JwtSecret
        $lines = Get-Content $envPath | ForEach-Object {
            if ($_ -match '^CHETANA_JWT_SECRET=') { "CHETANA_JWT_SECRET=$secret" } else { $_ }
        }
        if (-not ($lines -match '^CHETANA_JWT_SECRET=')) { $lines += "CHETANA_JWT_SECRET=$secret" }
        Write-Utf8NoBom $envPath $lines
        Write-Host "  .env            JWT secret generated and written" -ForegroundColor Green
    }

    # --- password ---------------------------------------------------------
    if (-not $Password) {
        $secure = Read-Host "  Console password for the demo users" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $Password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    }
    if (-not $Password) { throw "A password is required." }
    $hash = Get-PasswordHash $Password

    # Single-quoted here-string: no interpolation, so the '$' in a bcrypt hash
    # is safe. .Replace() is literal, unlike -replace.
    $usersTemplate = @'
[
  {
    "email": "operator@intertecsys.com",
    "password_hash": "__HASH__",
    "role": "operator",
    "tenants": ["*"]
  },
  {
    "email": "approver@intertecsys.com",
    "password_hash": "__HASH__",
    "role": "approver",
    "tenants": ["*"]
  },
  {
    "email": "admin@intertecsys.com",
    "password_hash": "__HASH__",
    "role": "admin",
    "tenants": ["*"]
  },
  {
    "email": "viewer@intertecsys.com",
    "password_hash": "__HASH__",
    "role": "viewer",
    "tenants": ["demo"]
  }
]
'@
    Write-Utf8NoBom (Join-Path $Root "config\users.json") $usersTemplate.Replace("__HASH__", $hash)
    Write-Host "  config\users.json   4 users written (operator, approver, admin, viewer)" -ForegroundColor Green

    # --- tenants ----------------------------------------------------------
    # Two tenants with different ceilings, so the approval gate is visible:
    # on 'demo' (R1) running a workflow parks for approval; on 'demo-ksa' (R2)
    # the same click executes.
    $tenantsPath = Join-Path $Root "config\tenants.json"
    if ((Test-Path $tenantsPath) -and -not ((Get-Content $tenantsPath -Raw) -match 'REPLACE')) {
        Write-Host "  config\tenants.json already configured, keeping it" -ForegroundColor DarkGray
    }
    else {
        $tenants = @'
[
  {
    "id": "demo",
    "name": "Demo Client",
    "keep_base_url": "http://stub-keep:8080",
    "keep_api_key": "stub-ignores-this",
    "max_autonomy_tier": 1,
    "tags": ["uae", "demo"],
    "enabled": true
  },
  {
    "id": "demo-ksa",
    "name": "Demo Client (KSA)",
    "keep_base_url": "http://stub-keep:8080",
    "keep_api_key": "stub-ignores-this",
    "max_autonomy_tier": 2,
    "tags": ["ksa", "demo"],
    "enabled": true
  }
]
'@
        Write-Utf8NoBom $tenantsPath $tenants
        Write-Host "  config\tenants.json 2 demo tenants written, pointed at the stub Keep" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Ready. Next:  .\scripts\tasks.ps1 demo" -ForegroundColor Cyan
    Write-Host "Then sign in at http://localhost:3100 as operator@intertecsys.com"
    Write-Host "with the password you just set. Approve as approver@intertecsys.com."
    Write-Host ""
    Write-Host "To point at a real Keep instead, edit config\tenants.json:" -ForegroundColor DarkGray
    Write-Host "  keep_base_url http://keep-backend:8080 and a real keep_api_key," -ForegroundColor DarkGray
    Write-Host "  then run:  .\scripts\tasks.ps1 up   (or 'demo' swapped for --profile keep)" -ForegroundColor DarkGray
}

function Invoke-Real {
    Assert-Configured

    # Point the tenant at the real Keep container rather than the stub.
    $tenantsPath = Join-Path $Root "config\tenants.json"
    $tenants = @'
[
  {
    "id": "live",
    "name": "Live estate",
    "keep_base_url": "http://keep-backend:8080",
    "keep_api_key": "chetana-local-dev-key",
    "max_autonomy_tier": 1,
    "tags": ["prod-uae", "live"],
    "enabled": true
  }
]
'@
    Write-Utf8NoBom $tenantsPath $tenants
    Write-Host "  config\tenants.json pointed at the real Keep (tenant 'live', ceiling R1)" -ForegroundColor Green

    # Keep stores its SQLite database and secrets here. It must exist before the
    # bind mount is made, and it must be writable by the non-root user inside
    # Keep's image — which is why this is a bind mount and not a named volume.
    $statePath = Join-Path $Root "state"
    New-Item -ItemType Directory -Force -Path $statePath | Out-Null

    # Drop the stub if a previous `demo` run left it behind; two Keeps on one
    # network is only confusing. Harmless when there is nothing to remove.
    Invoke-Tolerant { Invoke-In $Root { docker compose rm -sf stub-keep } }

    Invoke-In $Root { docker compose --profile real up -d --build }

    Write-Host ""
    Write-Host "Up. What is now running:" -ForegroundColor Cyan
    Write-Host "  console       http://localhost:3100   (sign in as operator@intertecsys.com)"
    Write-Host "  Keep's own UI http://localhost:3000"
    Write-Host "  Prometheus    http://localhost:9090/alerts"
    Write-Host "  Alertmanager  http://localhost:9093"
    Write-Host "  payments-api  http://localhost:8001/metrics"
    Write-Host ""
    Write-Host "Give it 3-6 minutes. The load generator ramps on a 7-minute cycle, the" -ForegroundColor DarkGray
    Write-Host "rules need 1-3 minutes of sustained breach, then Alertmanager groups and" -ForegroundColor DarkGray
    Write-Host "posts to Keep. Watch them arrive at http://localhost:9090/alerts first." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "To force a hard outage immediately:" -ForegroundColor DarkGray
    Write-Host "  docker compose stop ledger-worker     # TargetDown + LedgerUnreachable, ~60s" -ForegroundColor DarkGray
    Write-Host "  docker compose start ledger-worker    # recovery, and resolved events" -ForegroundColor DarkGray
}

function Invoke-Seed {
    # Writes real configuration into Keep through Keep's own API. A fresh Keep
    # has alerts and nothing else, which is why most console pages are honestly
    # empty until this runs.
    Invoke-In $Bff { python (Join-Path $Root "ops\seed_keep.py") --url http://localhost:8080 --api-key chetana-local-dev-key }
}

function Invoke-Status {
    Invoke-In $Root { docker compose --profile real --profile demo ps }
}

switch ($Task) {
    "init" { Invoke-Init }
    "real" { Invoke-Real }
    "seed" { Invoke-Seed }
    "status" { Invoke-Status }
    "setup" {
        Invoke-In $Bff { pip install -r requirements-dev.txt }
        Invoke-In $Web { npm install }
    }
    "test"   { Invoke-In $Bff { python -m pytest -q } }
    "smoke"  { Invoke-In $Bff { python tools/smoke_test.py } }
    "lint" {
        Invoke-In $Bff { python -m ruff check app tools }
        Invoke-In $Web { npm run typecheck }
    }
    "build"  { Invoke-In $Web { npm run build } }
    "demo"   { Assert-Configured; Invoke-In $Root { docker compose --profile demo up -d --build } }
    "up"     { Assert-Configured; Invoke-In $Root { docker compose up -d --build } }
    "down"   { Invoke-In $Root { docker compose --profile demo --profile keep --profile real down } }
    "secret" { Get-JwtSecret }
    default  { Get-Content $PSCommandPath -TotalCount 13 | ForEach-Object { $_ -replace '^# ?', '' } }
}
