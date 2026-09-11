<#
.SYNOPSIS
    Script rapido para dar push para o GitHub (TSGouveia/Behavior).
.DESCRIPTION
    Adiciona todos os ficheiros alterados, cria commit (com mensagem opcional) e faz git push.
#>

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [string]$CommitMessage = ""
)

# Garante que estamos na pasta do repositorio
Set-Location -Path $PSScriptRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "       Git Push - TSGouveia/Behavior      " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Adicionar ficheiros locais
Write-Host ""
Write-Host "[1/3] A preparar ficheiros (git add .)..." -ForegroundColor Yellow
git add .

# 2. Criar commit se existirem alteracoes
$status = git status --porcelain
if ($status) {
    if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $CommitMessage = "Update $timestamp"
    }
    Write-Host ""
    Write-Host "[2/3] A criar commit: '$CommitMessage'..." -ForegroundColor Yellow
    git commit -m "$CommitMessage"
} else {
    Write-Host ""
    Write-Host "[2/3] Nenhuma alteracao pendente para commit." -ForegroundColor Green
}

# 3. Push para o GitHub
Write-Host ""
Write-Host "[3/3] A enviar para o GitHub (git push origin main)..." -ForegroundColor Yellow
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] Push concluido com sucesso para https://github.com/TSGouveia/Behavior!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[ERRO] Falha ao enviar para o GitHub." -ForegroundColor Red
}
