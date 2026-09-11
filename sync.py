"""
Script utilitario em Python para sincronizar/descarregar alteracoes do GitHub (TSGouveia/Behavior).
Executa git fetch origin e git pull origin main.
"""

import subprocess
import sys
from pathlib import Path


def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, check=True, text=True, capture_output=True)
        if res.stdout:
            print(res.stdout.strip())
        return True
    except subprocess.CalledProcessError as e:
        if e.stdout:
            print(e.stdout.strip())
        if e.stderr:
            print(e.stderr.strip(), file=sys.stderr)
        return False
    except FileNotFoundError:
        print("Erro: Git nao foi encontrado no PATH. Instala o Git para continuar.", file=sys.stderr)
        return False


def main():
    repo_root = Path(__file__).resolve().parent
    print("=" * 45)
    print("   Sync Git (Download) - TSGouveia/Behavior  ")
    print("=" * 45)

    print("\n[1/2] A verificar novidades no GitHub (git fetch origin)...")
    fetch_ok = run_cmd(["git", "-C", str(repo_root), "fetch", "origin"])

    if not fetch_ok:
        print("\n[ERRO] Nao foi possivel ligar ao GitHub para verificar novidades.")
        sys.exit(1)

    print("\n[2/2] A descarregar alteracoes (git pull origin main)...")
    pull_ok = run_cmd(["git", "-C", str(repo_root), "pull", "origin", "main"])

    if pull_ok:
        print("\n[OK] Repositorio local atualizado com sucesso a partir do GitHub!")
    else:
        print("\n[AVISO] Ocorreu um problema ao atualizar os ficheiros.")
        sys.exit(1)


if __name__ == "__main__":
    main()
