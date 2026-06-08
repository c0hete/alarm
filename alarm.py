"""alarm — heartbeat cada 6h. Ejecuta 8 checks y commitea el código binario.

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


def assemble_code(checks, problems: list[bool]) -> str:
    """Compone el código binario de 8 bits.

    Si el registry fue filtrado (CHECKS env var), los slots no seleccionados
    quedan en 0. Esto significa "no se ejecutó", no "OK" — la diferencia
    importa para leer el historial. El padding se hace por bit_index, no por
    orden de iteración, para que la posición en el string refleje el slot.
    """
    bits = {c.bit_index: "1" if p else "0" for c, p in zip(checks, problems)}
    return "".join(bits.get(i, "0") for i in range(8))


def write_state(code: str) -> Path:
    STATE_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    out = STATE_DIR / f"{stamp}.txt"
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
    """Si GITHUB_TOKEN está en env, inyecta el token en la URL del remote `origin`
    para que `git push` use el token. Silencioso si el token no está.

    También limpia el `extraheader` de basic auth que deja actions/checkout
    y que GitHub ya no acepta.
    """
    # Limpiar credenciales básicas que dejó actions/checkout
    git_silent("config", "--local", "--unset-all", "http.https://github.com/.extraheader")

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return

    # Leer URL actual del remote y reescribir con token inline
    current = git_silent("config", "--get", "remote.origin.url")
    if current.returncode != 0 or not current.stdout.strip():
        return
    url = current.stdout.strip()
    # Reemplazar https://github.com/ por https://x-access-token:TOKEN@github.com/
    if "github.com/" in url and "x-access-token" not in url:
        new_url = url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/", 1)
        git_silent("remote", "set-url", "origin", new_url)


def commit_and_push(code: str, dry_run: bool) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    msg = f"alarm: {stamp} = {code}"
    if dry_run:
        return

    git_silent("config", "user.email", "alarm@users.noreply.github.com")
    git_silent("config", "user.name", "alarm")
    configure_push_auth()

    git_silent("add", "state/")
    diff = git_silent("diff", "--cached", "--quiet")
    if diff.returncode == 0:
        return  # sin cambios (mismo archivo re-escrito con mismo contenido)

    if git_silent("commit", "-m", msg).returncode != 0:
        raise SystemExit(1)
    if git_silent("push", "origin", "HEAD").returncode != 0:
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="alarm — heartbeat cada 6h")
    parser.add_argument("--verbose", action="store_true", help="muestra qué slot falló (sin URLs)")
    parser.add_argument("--dry-run", action="store_true", help="no escribe ni commitea")
    parser.add_argument("--quiet", action="store_true", help="cero output, solo exit code")
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        metavar="SLOTS",
        help="corre solo los slots indicados (ej: '0,3' o 'URL,SSL'). Mismo formato que env var CHECKS.",
    )
    args = parser.parse_args()

    # --only tiene prioridad sobre CHECKS (override de CLI)
    if args.only is not None:
        os.environ["CHECKS"] = args.only

    load_dotenv()
    try:
        timeout = int(os.environ.get("CHECK_TIMEOUT", "10"))
    except ValueError:
        timeout = 10

    registry = build_registry(timeout=timeout)
    results = [c.execute() for c in registry]
    code = assemble_code(registry, results)

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
