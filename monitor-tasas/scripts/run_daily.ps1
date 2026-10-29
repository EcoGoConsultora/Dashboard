param([string]$MarketDate, [switch]$Force)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $repoRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd_HH-mm-ss'
# Con el nombre de la PC: la carpeta de OneDrive la comparten la PC de la oficina y la notebook.
$logPath = Join-Path $logDir "daily_${stamp}_$env:COMPUTERNAME.log"

Push-Location $repoRoot
try {
    $now = Get-Date
    $todayKey = $now.ToString('yyyy-MM-dd')
    if (-not $MarketDate) {
        # Última rueda cerrada. La tarea puede correr tarde (StartWhenAvailable: la PC estaba
        # apagada a las 17:30) o antes del cierre; nunca se procesa una rueda que no terminó.
        $calendarPath = Join-Path $repoRoot 'config\calendars\ar_market_calendar_2025_2026.csv'
        $closedDays = @(Import-Csv -LiteralPath $calendarPath | Where-Object { $_.trading_closed -match '^(?i:true|1|yes)$' } | ForEach-Object { $_.date })
        $isTrading = { param($d) ($d.DayOfWeek -notin @('Saturday', 'Sunday')) -and ($closedDays -notcontains $d.ToString('yyyy-MM-dd')) }
        $day = $now.Date
        if ($now.TimeOfDay -lt [TimeSpan]'17:00:00') { $day = $day.AddDays(-1) }
        while (-not (& $isTrading $day)) { $day = $day.AddDays(-1) }
        $MarketDate = $day.ToString('yyyy-MM-dd')
    }
    "Rueda a procesar: $MarketDate (corrida $($now.ToString('yyyy-MM-dd HH:mm')))" | Tee-Object -FilePath $logPath
    # En PowerShell 5.1 cada línea de stderr de py es un ErrorRecord; con 'Stop' un simple
    # warning de pandas cortaría la corrida. El resultado se juzga por el código de salida.
    $ErrorActionPreference = 'Continue'

    # Si la otra PC ya publicó esta rueda (llegó por OneDrive), no se rehace: evita conflictos
    # de sincronización. -Force la recalcula igual.
    $snapshotPath = Join-Path $repoRoot "output\history\$MarketDate.json"
    $latestPath = Join-Path $repoRoot 'output\latest.json'
    $published = $false
    if (-not $Force -and (Test-Path $snapshotPath) -and (Test-Path $latestPath)) {
        $snapshotMeta = (Get-Content -Raw -Encoding UTF8 -LiteralPath $snapshotPath | ConvertFrom-Json).meta
        $latestDate = (Get-Content -Raw -Encoding UTF8 -LiteralPath $latestPath | ConvertFrom-Json).meta.market_date
        $published = (-not $snapshotMeta.backfill) -and ($latestDate -ge $MarketDate)
    }

    if (-not $published) {
        # Primero se completa la historia que el HTML incrusta al publicar la rueda actual.
        $gapStart = ([datetime]$MarketDate).AddDays(-14).ToString('yyyy-MM-dd')
        $gapEnd = ([datetime]$MarketDate).AddDays(-1).ToString('yyyy-MM-dd')
        & py -3.14 -m src.backfill --start $gapStart --end $gapEnd --only-missing 2>&1 | Tee-Object -FilePath $logPath -Append

        # Rava puede entregar a las 17:30 cierres parciales. Al día siguiente se recuperan
        # sólo las especies con cierre exacto faltante, conservando tasas A3/BCRA originales.
        $previous = Get-ChildItem -LiteralPath (Join-Path $repoRoot 'output\history') -Filter '*.json' |
            Where-Object { $_.BaseName -lt $MarketDate } | Sort-Object Name -Descending | Select-Object -First 1
        if ($previous) {
            & py -3.14 -m src.backfill --start $previous.BaseName --end $previous.BaseName --repair-existing 2>&1 | Tee-Object -FilePath $logPath -Append
        }
    }

    if ($published) {
        "Rueda $MarketDate ya publicada (generada $($snapshotMeta.generated_at)); no se rehace." | Tee-Object -FilePath $logPath -Append
        $global:LASTEXITCODE = 0
    }
    elseif ($MarketDate -eq $todayKey) {
        # Rueda de hoy ya cerrada: el cierre vigente de Rava es el del día. Si a esta hora Rava
        # todavía no consolidó el cierre de algunas especies, reintenta y republica hasta las 19:00.
        & py -3.14 -m src.monitor --date $MarketDate --retry-until 19:00 2>&1 | Tee-Object -FilePath $logPath -Append
    }
    else {
        # Recuperación de una rueda anterior: el precio vigente de Rava puede ser ya de otra
        # rueda, así que se valúa con el cierre histórico de esa fecha y se publica.
        & py -3.14 -m src.backfill --start $MarketDate --end $MarketDate --force --publish 2>&1 | Tee-Object -FilePath $logPath -Append
    }
    $exitCode = $LASTEXITCODE
    exit $exitCode
}
catch {
    # Sin esto, una falla previa a la corrida (calendario ilegible, py ausente) no deja rastro.
    "ERROR: $($_ | Out-String)" | Out-File -FilePath $logPath -Append -Encoding utf8
    exit 1
}
finally {
    Pop-Location
}
