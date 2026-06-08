# `alarm.py`

Entry point del proyecto. Es el único archivo que se ejecuta directamente. Hace de pegamento entre los checks, el filesystem, y git.

## Propósito

Tomar la salida de los 8 checks, ensamblarla en un código binario, escribirlo a disco, y commitearlo al repo. Nada más.

## CLI

```bash
python alarm.py [opciones]
```

| Flag | Default | Descripción |
|---|---|---|
| `--verbose` | off | Imprime en stderr qué bit falló. **No** muestra URLs ni hostnames. |
| `--quiet` | off | Cero output. Solo exit code. Usado por el workflow de CI. |
| `--dry-run` | off | Imprime el código y termina. No escribe archivos, no commitea. |
| `--only SLOTS` | (none) | Corre solo los slots indicados. Mismo formato que env var `CHECKS`. Override de CLI. |

**Combinaciones:**
- (sin flags) → imprime el código en stdout, escribe `state/YYYY-MM-DD.txt`, commitea, pushea
- `--verbose` → como arriba + `bit N [0/1]` en stderr
- `--quiet` → no imprime, hace todo el flujo
- `--dry-run` → solo imprime código
- `--only=0,3 --verbose` → corre solo slots 0 y 3, muestra bits en stderr

## Funciones

### `load_dotenv() -> None`

Carga variables desde `.env` (si existe). **No** pisa variables ya seteadas en `os.environ` (prioridad al process env).

```python
def load_dotenv() -> None:
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
        ...
        if key and key not in os.environ:
            os.environ[key] = value
```

**Notas de seguridad:**
- `OSError` atrapado → no leak del path del archivo
- No se loguea qué vars se cargaron
- En CI, el archivo no existe, así que la función es un no-op

### `assemble_code(results: list[bool]) -> str`

Convierte `[bit0, bit1, ..., bit7]` en `"ABCDEFGH"`. Bit 0 va a la izquierda.

```python
def assemble_code(results: list[bool]) -> str:
    return "".join("1" if r else "0" for r in results)
```

**Nota:** Con el env var `CHECKS` o `--only`, el registry puede tener menos de 8 checks. En ese caso, `assemble_code` paddea con `0` por `bit_index` (no por orden de iteración). Los slots no seleccionados quedan en `0` ("no se ejecutó", no "OK").

### `write_state(code: str) -> Path`

Escribe `state/YYYY-MM-DD.txt` con el código. Crea el directorio si no existe.

```python
def write_state(code: str) -> Path:
    STATE_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = STATE_DIR / f"{today}.txt"
    out.write_text(code + "\n", encoding="utf-8")
    return out
```

**Notas:**
- Fecha en **UTC** (consistente con el workflow que también corre en UTC)
- `\n` final para que el archivo se vea bien en `cat`
- `mkdir(exist_ok=True)` es seguro incluso si el directorio ya existe

### `git_silent(*args: str) -> subprocess.CompletedProcess`

Wrapper sobre `subprocess.run` que captura stdout/stderr y deshabilita el prompt de credenciales.

```python
def git_silent(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
```

**Por qué `os.environ.copy()`:** heredar el env completo (incluyendo `GITHUB_TOKEN` en CI) sin perder nada. El `GIT_TERMINAL_PROMPT=0` override evita que git se cuelgue pidiendo credenciales si la auth falla.

### `configure_push_auth() -> None`

Si `GITHUB_TOKEN` está en env, lo inyecta en la URL del remote `origin` para que `git push` lo use. **Silencioso** si el token no está (caso local: usa las credenciales del usuario).

```python
def configure_push_auth() -> None:
    git_silent("config", "--local", "--unset-all", "http.https://github.com/.extraheader")
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return
    current = git_silent("config", "--get", "remote.origin.url")
    if current.returncode != 0 or not current.stdout.strip():
        return
    url = current.stdout.strip()
    if "github.com/" in url and "x-access-token" not in url:
        new_url = url.replace(
            "https://github.com/",
            f"https://x-access-token:{token}@github.com/",
            1,
        )
        git_silent("remote", "set-url", "origin", new_url)
```

**Por qué el `unset` del extraheader:** `actions/checkout@v4` deja un header `AUTHORIZATION: basic ***` en `.git/config` que usa basic auth. GitHub ya no acepta basic auth para git operations. Hay que removerlo antes del push.

**Por qué `git remote set-url` y no `git config url...insteadOf`:** el segundo usa caracteres especiales en la URL que `git config` no maneja bien via CLI. El primero es el patrón documentado por GitHub Actions y funciona siempre.

### `commit_and_push(code: str, dry_run: bool) -> None`

Hace el ciclo completo de git: config user, configure auth, add, commit, push.

```python
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

    if git_silent("commit", "-m", msg).returncode != 0:
        raise SystemExit(1)
    if git_silent("push", "origin", "HEAD").returncode != 0:
        raise SystemExit(1)
```

**Idempotencia:** si el archivo de hoy ya está commiteado, `git diff --cached --quiet` retorna 0 (sin cambios) y la función termina sin hacer commit duplicado.

**Exit codes:** `SystemExit(1)` se propaga si el commit o el push fallan. Esto hace que el step de GitHub Actions falle con código 1, marcándose como error en el dashboard.

### `main() -> int`

Parsea args, carga dotenv, ejecuta checks, decide el flujo según los flags.

```python
def main() -> int:
    parser = argparse.ArgumentParser(description="alarm — heartbeat cada 6h")
    parser.add_argument("--verbose", action="store_true", ...)
    parser.add_argument("--dry-run", action="store_true", ...)
    parser.add_argument("--quiet", action="store_true", ...)
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
        print(code)

    if args.verbose and not args.quiet:
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
```

**Exit codes:**
- `0` = todo OK
- `1` = git falló (commit o push)

**`except Exception` final:** atrapa cualquier excepción del flujo de git y la convierte en exit 1 silencioso. `SystemExit` (de `commit_and_push`) NO es `Exception`, así que se propaga. Esto está bien porque es exit 1 de todas formas.

## Side effects globales

Al import, el módulo ejecuta:

```python
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
```

Esto **silencia TODOS los warnings de Python y logs de librerías** antes de cualquier otro import. Crítico para la política de no-leak: librerías como `urllib3` o `requests` pueden emitir warnings a stderr que contendrían URLs.

## Constantes

```python
ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
ENV_FILE = ROOT / ".env"
```

`ROOT` es el directorio del archivo. `STATE_DIR` y `ENV_FILE` se derivan de él. Esto hace al script **portable** — funciona sin importar desde qué directorio se llame.

## Dependencias

- **Stdlib:** `argparse`, `logging`, `os`, `subprocess`, `sys`, `warnings`, `datetime`, `pathlib`
- **Proyecto:** `from checks import build_registry`
- **Externas (transitivas via checks):** `requests`, `urllib3`

## Testing manual

```bash
# 1. Dry-run con todo OK
python alarm.py --dry-run
# → 00000000

# 2. Dry-run con fallo forzado
URL_PRIMARY="https://httpbin.org/status/500" python alarm.py --dry-run
# → 10000000

# 3. Verbose para ver bits
python alarm.py --verbose
# stdout: 00000000
# stderr:
#   bit 0 [0]
#   bit 1 [0]
#   ...

# 4. Quiet (modo CI)
python alarm.py --quiet
# (cero output)
```
