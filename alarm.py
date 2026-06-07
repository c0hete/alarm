"""alarm — heartbeat diario. Ejecuta 8 checks y commitea el código binario.

Uso:
    python alarm.py                # silencioso, escribe state/, commitea y pushea
    python alarm.py --verbose      # muestra qué slot falló (sin URLs ni hosts)
    python alarm.py --dry-run      # solo imprime el código, no toca git
    python alarm.py --quiet        # cero output, solo exit code

Política de no-leak:
- No se imprimen URLs, hostnames, ni mensajes de error de librerías externas.
- Cualquier excepción se silencia: el check devuelve True (= problema) sin detalles.
- En modo no-verbose, el único stdout es el código binario de 8 bits.
- En CI (GitHub Actions), se aplica --quiet por defecto vía el workflow.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

# Silenciar warnings de Python (urllib3, requests, etc.) ANTES de cualquier import
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from checks import build_registry  # noqa: E402  (debe ir tras el disable)

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
ENV_FILE = ROOT / ".env"


def load_dotenv() -> None:
    """Carga .env si existe. No pisa vars ya seteadas (prioridad al process env)."""
    if not ENV_FILE.exists():
        return
    try:
        content = ENV_FILE.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def assemble_code(results: list[bool]) -> str:
    return "".join("1" if r else "0" for r in results)


def write_state(code: str) -> Path:
    STATE_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = STATE_DIR / f"{today}.txt"
    out.write_text(code + "\n", encoding="utf-8")
    return out


def git_silent(*args: str) -> subprocess.CompletedProcess:
    """Ejecuta git capturando TODO el output. No se imprime nada en stdout/stderr
    a menos que la llamada falle Y se llame explícitamente con check=True.
    """
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"  # nunca colgar esperando credenciales
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def configure_push_auth() -> None:
    """Si GITHUB_TOKEN está en env, configura un rewrite de URL para que
    `git push origin` use el token efímero. Silencioso si el token no está.

    Importante: el checkout de actions/checkout deja un `extraheader` de basic
    auth en .git/config que GitHub ya no acepta. Hay que removerlo o el push
    sigue intentando usar basic auth.
    """
    # Limpiar cualquier credencial básica que dejó actions/checkout
    git_silent("config", "--local", "--unset-all", "http.https://github.com/.extraheader")
    git_silent("config", "--local", "--remove-section", "http.https://github.com/")

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return
    # DEBUG: print config state
    import subprocess
    print(f"DEBUG: extraheader unset, token length={len(token)}", file=sys.stderr)
    rewrite = f'url."https://x-access-token:{token}@github.com/".insteadOf "https://github.com/"'
    git_silent("config", "--local", rewrite)
    # DEBUG: verify
    r = subprocess.run(["git", "config", "--local", "--get-regexp", r"^url\."], cwd=ROOT, capture_output=True, text=True)
    print(f"DEBUG: url config after set: {r.stdout!r} stderr={r.stderr!r}", file=sys.stderr)


def commit_and_push(code: str, dry_run: bool) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    msg = f"alarm: {today} = {code}"
    if dry_run:
        return

    git_silent("config", "user.email", "alarm@users.noreply.github.com")
    git_silent("config", "user.name", "alarm")
    configure_push_auth()

    git_silent("add", "state/")
    diff = git_silent("diff", "--cached", "--quiet")
    if diff.returncode == 0:
        return  # sin cambios (mismo día re-ejecutado)

    commit = git_silent("commit", "-m", msg)
    if commit.returncode != 0:
        print(f"commit failed: {commit.stderr}", file=sys.stderr)
        raise SystemExit(1)
    push = git_silent("push", "origin", "HEAD")
    if push.returncode != 0:
        print(f"push failed: {push.stderr}", file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="alarm — heartbeat diario")
    parser.add_argument("--verbose", action="store_true", help="muestra qué slot falló (sin URLs)")
    parser.add_argument("--dry-run", action="store_true", help="no escribe ni commitea")
    parser.add_argument("--quiet", action="store_true", help="cero output, solo exit code")
    args = parser.parse_args()

    load_dotenv()
    try:
        timeout = int(os.environ.get("CHECK_TIMEOUT", "10"))
    except ValueError:
        timeout = 10

    registry = build_registry(timeout=timeout)
    results = [c.execute() for c in registry]
    code = assemble_code(results)

    if not args.quiet:
        # Única línea a stdout: el código binario. Nada más.
        # En dry-run también se imprime (es su razón de ser).
        print(code)

    if args.verbose and not args.quiet:
        # En verbose, mostramos bit index + nombre genérico. NUNCA URLs ni hosts.
        for check, result in zip(registry, results):
            mark = "1" if result else "0"
            print(f"  bit {check.bit_index} [{mark}]", file=sys.stderr)

    if args.dry_run:
        return 0

    try:
        write_state(code)
        commit_and_push(code, dry_run=False)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
