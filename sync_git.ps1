<#
.SYNOPSIS
    Script utilitario para sincronizar automaticamente com o repositorio GitHub (TSGouveia/Behavior).
.DESCRIPTION
    Executa git fetch, git pull com rebase, adiciona ficheiros alterados, cria commit (com mensagem opcional) e faz git push.
#>

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [string]$CommitMessage = ""
)

$ErrorActionPreference = "Stop"

# Garante que estamos na pasta onde esta o script
Set-Location -Path $PSScriptRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Sincronizacao Git - TSGouveia/Behavior  " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Fetch
Write-Host ""
Write-Host "[1/5] A verificar atualizacoes remotas (git fetch origin)..." -ForegroundColor Yellow
git fetch origin

# 2. Pull das alteracoes remotas mais recentes
Write-Host ""
Write-Host "[2/5] A atualizar alteracoes do repositorio (git pull origin main --rebase)..." -ForegroundColor Yellow
git pull origin main --rebase

# 3. Adicionar alteracoes locais
Write-Host ""
Write-Host "[3/5] A adicionar ficheiros locais (git add .)..." -ForegroundColor Yellow
git add .

# 4. Verificar alteracoes por commitar
$status = git status --porcelain
if ($status) {
    if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $CommitMessage = "Update $timestamp"
    }
    Write-Host ""
    Write-Host "[4/5] A criar commit: '$CommitMessage'..." -ForegroundColor Yellow
    git commit -m "$CommitMessage"
} else {
    Write-Host ""
    Write-Host "[4/5] Nenhuma alteracao pendente para commit." -ForegroundColor Green
}

# 5. Push para o GitHub
Write-Host ""
Write-Host "[5/5] A enviar para o GitHub (git push origin main)..." -ForegroundColor Yellow
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] Repositorio sincronizado com sucesso no GitHub (TSGouveia/Behavior)!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[ERRO] Ocorreu um problema no git push." -ForegroundColor Red
}
