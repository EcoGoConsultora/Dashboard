# ============================================================
#  EcoGo Dashboard — Setup inicial de Git + GitHub Pages
#  Ejecutar desde PowerShell en la carpeta del dashboard
# ============================================================

$DASHBOARD = "C:\Users\fscalise\OneDrive - ECOGO S.A\BD\07 Tableros\EcoGo-Dashboard"
Set-Location $DASHBOARD

Write-Host ""
Write-Host "=== EcoGo Dashboard — Setup GitHub ===" -ForegroundColor Cyan
Write-Host ""

# Verificar que git está instalado
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Git no está instalado." -ForegroundColor Red
    Write-Host "Bajalo de https://git-scm.com/download/win e instalalo primero." -ForegroundColor Yellow
    exit 1
}

# Pedir la URL del repo de GitHub
Write-Host "Paso 1: Creá el repo en https://github.com/new" -ForegroundColor Yellow
Write-Host "  - Nombre: ecogo-dashboard (o el que prefieras)"
Write-Host "  - Public, SIN README ni .gitignore"
Write-Host ""
$REMOTE_URL = Read-Host "Pegá la URL del repo (ej: https://github.com/usuario/ecogo-dashboard.git)"
if (-not $REMOTE_URL) {
    Write-Host "URL vacía. Saliendo." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Inicializando repositorio..." -ForegroundColor Green

# Init
git init
git branch -M main

# Config
git config user.email "fscalise@ecogo.com.ar"
git config user.name "Fiore Scalise"

# Agregar todo
Write-Host "Agregando archivos..." -ForegroundColor Green
git add .

# Primer commit
git commit -m "Initial commit: EcoGo Dashboard v1.0"

# Remote y push
Write-Host "Conectando con GitHub y subiendo..." -ForegroundColor Green
git remote add origin $REMOTE_URL
git push -u origin main

Write-Host ""
Write-Host "=== Listo! ===" -ForegroundColor Cyan
Write-Host ""

# Extraer nombre de usuario y repo de la URL para armar el link de GitHub Pages
if ($REMOTE_URL -match "github\.com/([^/]+)/([^/\.]+)") {
    $GH_USER = $Matches[1]
    $GH_REPO = $Matches[2] -replace "\.git$", ""
    Write-Host "Tu dashboard estara disponible en:" -ForegroundColor Yellow
    Write-Host "  https://$GH_USER.github.io/$GH_REPO/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Paso final: activar GitHub Pages" -ForegroundColor Yellow
    Write-Host "  1. Ir a https://github.com/$GH_USER/$GH_REPO/settings/pages"
    Write-Host "  2. Source: Deploy from a branch"
    Write-Host "  3. Branch: main / folder: / (root)"
    Write-Host "  4. Save"
    Write-Host ""
    Write-Host "En ~2 minutos el sitio queda online." -ForegroundColor Green
}
