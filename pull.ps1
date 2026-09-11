<#
.SYNOPSIS
    Script rapido para ir buscar (fetch) e descarregar (pull/download) as alteracoes do GitHub (TSGouveia/Behavior).
.DESCRIPTION
    Executa git fetch origin e git pull origin main para atualizar a pasta local com o repositorio remoto.
#>

# Garante que estamos na pasta do repositorio
Set-Location -Path $PSScriptRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "      Download/Pull - TSGouveia/Behavior  " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Fetch: ir buscar informacao de novos commits e branches ao GitHub
Write-Host ""
Write-Host "[1/2] A verificar novidades no GitHub (git fetch origin)..." -ForegroundColor Yellow
git fetch origin

# 2. Pull: descarregar os ficheiros atualizados para a maquina local
Write-Host ""
Write-Host "[2/2] A descarregar e atualizar ficheiros locais (git pull origin main)..." -ForegroundColor Yellow
git pull origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] Repositorio local atualizado com sucesso a partir do GitHub!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[AVISO] Se tiveres alteracoes locais por guardar que entrem em conflito, faz commit primeiro (ou usa o push.ps1)." -ForegroundColor Red
}
