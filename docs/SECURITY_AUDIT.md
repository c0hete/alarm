# Auditoría de Seguridad — alarm

**Fecha:** 2026-06-07
**Versión auditada:** 1.0 + feat: change cadence to every 6 hours
**Auditor:** mini-auditoría manual (grep + lectura completa de archivos)
**Alcance:** Todos los archivos del proyecto (excluyendo `.git/`, `__pycache__/`, `state/`)

---

## Resumen ejecutivo

| Severidad | Cantidad | Estado |
|---|---|---|
| 🔴 Muy alto | 0 | — |
| 🟠 Alto | 0 | — |
| 🟡 Medio-alto | 4 | Pendiente |
| 🟢 Medio | 3 | Pendiente |
| 🔵 Bajo / muy bajo | 11 | Pendiente (cosméticos y defense-in-depth) |

**No se encontraron secretos hardcodeados, archivos `.env` tracked, ni vulnerabilidades críticas activas.** La política de no-leak se implementa correctamente en el grueso del código. Los hallazgos pendientes son defense-in-depth, bugs de correctness, o mejoras de hardening.

---

## Tabla de findings

| # | Severidad | Archivo:línea | Descripción corta |
|---|---|---|---|
| 1 | 🟡 Medio-alto | `checks/security.py:35-43` | URL con credenciales embebidas no rechazada |
| 2 | 🟡 Medio-alto | `checks/security.py:46-66` | Sin protección contra SSRF (IPs privadas, metadata) |
| 3 | 🟡 Medio-alto | `alarm.py:126-130` | `git push` duplicado (bug de correctness) |
| 4 | 🟡 Medio-alto | `.github/workflows/daily.yml` | Sin `concurrency:` → race condition posible |
| 5 | 🟢 Medio | `.github/workflows/daily.yml:50-56` | Loop de `::add-mask::` no cubre todos los secrets |
| 6 | 🟢 Medio | `.github/workflows/daily.yml:31,39` | Actions usan Node 20 (deprecado, forzado Jun 16) |
| 7 | 🟢 Medio | `.github/workflows/daily.yml` | Sin escaneo de deps (pip-audit / Dependabot) |
| 8 | 🔵 Bajo | `checks/security.py:98` | SSL timeout hardcodeado a 10s, ignora `CHECK_TIMEOUT` |
| 9 | 🔵 Bajo | `alarm.py:1` | Docstring dice "diario" (ya es cada 6h) |
| 10 | 🔵 Bajo | `checks/http.py:13` | `__import__("os")` en vez de `import os` (code smell) |
| 11 | 🔵 Bajo | `requirements.txt` | Version pinning laxo, sin hashes |
| 12 | 🔵 Bajo | `docs/ARCHITECTURE.md:125` | PII: nombre real "Jose Alvarado" en doc público |
| 13 | 🔵 Bajo | `alarm.py:106` | Token escrito a `.git/config` durante la ejecución |
| 14 | 🔵 Bajo | `alarm.py:167` | `except Exception` muy broad silencia todo |
| 15 | 🔵 Bajo | `.env.example` | Default `URL_PRIMARY=https://iacode.cl` expone qué se monitorea |
| 16 | 🔵 Bajo | `git log` | Commits de debug en historia pública (ya aceptado por usuario) |
| 17 | 🔵 Bajo | `README.md`, `PROYECTO.md` | Mención de "iacode.cl" como default expone infra del usuario |
| 18 | 🔵 Bajo | `alarm.py` | `--verbose` imprime bits, no URLs, pero igual revela patrón |

---

## Detalle de cada finding

### 🟡 #1 — URL con credenciales embebidas no rechazada

**Archivo:** `checks/security.py:35-43`

```python
def validate_https_url(url: str) -> bool:
    if not url or not url.strip():
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except (ValueError, AttributeError):
        return False
    return parsed.scheme.lower() in _ALLOWED_SCHEMES and bool(parsed.hostname)
```

**Problema:** Una URL como `https://user:pass@iacode.cl/health` pasa la validación. El `requests.get` posterior la procesa normalmente y **envía las credenciales al servidor** (o al proxy si la red lo redirige). Si un usuario pone por error un secret real en una URL, ese secret queda en:
- El request (lo ve el server, o un atacante en ruta)
- Posibles logs del server
- Cachés de DNS / proxy

**Amenaza:** Media. El usuario controla `.env`, así que es self-inflicted. Pero un solo typo y un secret real queda expuesto.

**Fix propuesto:**
```python
def validate_https_url(url: str) -> bool:
    if not url or not url.strip():
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except (ValueError, AttributeError):
        return False
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    if not parsed.hostname:
        return False
    # No aceptar credenciales embebidas en la URL
    if parsed.username or parsed.password:
        return False
    return True
```

---

### 🟡 #2 — Sin protección contra SSRF

**Archivo:** `checks/security.py:46-66, 69-85, 88-117` (todos los que hacen requests)

**Problema:** Si alguien configura `URL_PRIMARY=https://169.254.169.254/latest/meta-data/` (AWS instance metadata) o `https://192.168.1.1/admin`, el alarm hace la request sin cuestionar.

**Amenaza:**
- **Baja inmediata:** el usuario controla el `.env`. Es self-inflicted.
- **Media si viene de un PR:** Si alguien abre un PR cambiando `.env.example` o los checks, podría usar el CI runner de GH Actions para escanear la red interna de GH.
- **Media a través de `BACKUP_MANIFEST`:** el slot 6 acepta cualquier URL HTTPS, incluyendo internas. Mismo riesgo.

**Mitigación parcial actual:** HTTPS + cert validation. Si el endpoint tiene cert válido para una IP, el check funciona (lo cual es raro pero posible).

**Fix propuesto:** Añadir chequeo de IP privada / metadata en `validate_https_url` o en una función nueva `is_safe_target`:

```python
import ipaddress

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local + AWS metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

def is_safe_target(url: str) -> bool:
    if not validate_https_url(url):
        return False
    host = urllib.parse.urlparse(url).hostname
    try:
        ip = ipaddress.ip_address(host)
        return not any(ip in net for net in _PRIVATE_NETS)
    except ValueError:
        return True  # es un hostname, no una IP
```

Y usar `is_safe_target` en `safe_request` / `safe_get_json` / `safe_ssl_check`.

**Trade-off:** Bloquearía checks legítimos a infra local. El usuario decide si esto es aceptable.

---

### 🟡 #3 — `git push` duplicado (bug)

**Archivo:** `alarm.py:126-130`

```python
if git_silent("push", "origin", "HEAD").returncode != 0:
    raise SystemExit(1)
push = git_silent("push", "origin", "HEAD")
if push.returncode != 0:
    raise SystemExit(1)
```

**Problema:** El `git push` se ejecuta dos veces. El primero funciona; el segundo corre contra un remote ya actualizado. Resultado:
- Wastes un round-trip de red
- Posible confusión en logs si el segundo push da output distinto (en este caso está silenciado, pero es mala práctica)

**Amenaza:** Baja en este caso (porque `git_silent` captura todo), pero refleja código que se quedó de una iteración de debug y no se limpió. **Severidad media como correctness bug.**

**Fix:** Eliminar las líneas 128-130.

---

### 🟡 #4 — Sin `concurrency:` en workflow

**Archivo:** `.github/workflows/daily.yml`

**Problema:** Si por alguna razón un run tarda >6 horas (timeout actual: 5 min, pero podría haber lag + retry), el próximo cron dispara un run concurrente. Dos procesos haciendo `git push` al mismo tiempo pueden:
- Tener race condition en `.git/` (ambos escribiendo a `state/`)
- Hacer push simultáneo → el segundo falla con "non-fast-forward"
- Generar commits duplicados si los checks devuelven el mismo código

**Amenaza:** Baja en la práctica (timeout de 5 min garantiza que no debería pasar), pero documentado como posible.

**Fix propuesto:**
```yaml
jobs:
  heartbeat:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    concurrency:
      group: alarm-${{ github.ref }}
      cancel-in-progress: true
```

`cancel-in-progress: true` hace que el nuevo run mate al anterior si está corriendo.

---

### 🟢 #5 — Loop de `::add-mask::` no cubre todos los secrets

**Archivo:** `.github/workflows/daily.yml:50-56`

```yaml
- name: Mask secrets in logs
  run: |
    for v in URL_PRIMARY URL_SECONDARY URL_TERTIARY SSL_PRIMARY SSL_SECONDARY BACKUP_MANIFEST CUSTOM_API_URL; do
      val="${!v}"
      if [ -n "$val" ]; then
        echo "::add-mask::$val"
      fi
    done
```

**Problema:** El loop no incluye:
- `BACKUP_MAX_AGE_DAYS` (número, no sensible — pero por consistencia)
- `CHECK_TIMEOUT` (número, no sensible — pero por consistencia)
- `GITHUB_TOKEN` (sensible — pero GH Actions lo enmascara automáticamente porque su nombre contiene "TOKEN")

**Amenaza:** Baja. `GITHUB_TOKEN` está protegido por el masking automático. Los otros son números.

**Fix propuesto:** Agregar todos al loop para que el patrón sea uniforme:
```yaml
for v in URL_PRIMARY URL_SECONDARY URL_TERTIARY SSL_PRIMARY SSL_SECONDARY BACKUP_MANIFEST BACKUP_MAX_AGE_DAYS CUSTOM_API_URL CHECK_TIMEOUT; do
```

---

### 🟢 #6 — Actions usan Node 20 (deprecado)

**Archivo:** `.github/workflows/daily.yml:31, 39`

```yaml
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
```

**Problema:** GitHub deprecó Node 20 en Actions. A partir del **16 de junio de 2026** (9 días después de este audit), GH fuerza Node 24. **16 de septiembre de 2026**: Node 20 se elimina completamente.

El workflow ya emite este warning en cada run.

**Amenaza:** Baja a corto plazo. Media a 3 meses cuando se elimine Node 20. Compliance/forward-compat.

**Fix propuesto (opción A — más simple):** Setear la env var para forzar Node 24 ahora:
```yaml
env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"
```

**Fix propuesto (opción B — más limpio):** Buscar versiones v5+ de las actions. A la fecha de este audit no se conoce si existen versiones stables; el warning sugiere que están en camino.

---

### 🟢 #7 — Sin escaneo de dependencias

**Archivo:** `requirements.txt`, sin workflow adicional

**Problema:** No hay:
- `pip-audit` o `safety` corriendo en CI
- Dependabot config
- Revisión periódica de CVEs en `requests` o `urllib3`

**Amenaza:** Baja ahora (las versiones mínimas son razonables), pero el proyecto depende de libs de red y debería tener monitoreo continuo de CVEs.

**Fix propuesto:** Agregar un workflow `.github/workflows/audit.yml`:
```yaml
name: audit
on:
  schedule:
    - cron: "0 6 * * 1"  # semanal, lunes
  workflow_dispatch:
permissions: {}
jobs:
  pip-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install pip-audit
      - run: pip-audit --strict
```

Y opcionalmente `.github/dependabot.yml`:
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

---

### 🔵 #8 — SSL timeout hardcodeado

**Archivo:** `checks/security.py:98`

```python
with socket.create_connection((host.strip(), 443), timeout=10) as sock:
```

**Problema:** `CHECK_TIMEOUT` (env var) afecta los requests HTTP pero no el SSL check. Inconsistencia. Si el usuario quiere timeouts más largos, no puede aplicarlos al SSL check.

**Amenaza:** Muy baja. Funcional, no seguridad.

**Fix:** Pasar `timeout` como parámetro a `safe_ssl_check` y leerlo de `CHECK_TIMEOUT` en el caller.

---

### 🔵 #9 — Docstring dice "diario"

**Archivo:** `alarm.py:1`

```python
"""alarm — heartbeat diario. Ejecuta 8 checks y commitea el código binario.
```

**Problema:** El header del módulo dice "diario" pero el cron es cada 6h. Cosmético.

**Fix:** Cambiar "diario" → "cada 6h".

---

### 🔵 #10 — `__import__("os")` en vez de `import os`

**Archivo:** `checks/http.py:13`

```python
return security.safe_request(
    __import__("os").environ[env_var].strip(), timeout
)
```

**Problema:** Quirk. `os` ya está importado transitivamente (vía `security`). El `__import__` es un workaround feo. No es seguridad, es code smell.

**Fix:** Agregar `import os` al top, usar `os.environ[env_var].strip()`.

---

### 🔵 #11 — Version pinning laxo, sin hashes

**Archivo:** `requirements.txt`

```
requests>=2.31.0
urllib3>=2.0.0
```

**Problema:**
- `>=` permite versiones futuras que pueden tener breaking changes o vulns nuevas
- Sin `--hash` ni `requirements.lock` → no hay verificación de integridad
- En el contexto de supply chain, las mejores prácticas piden lock files o pip install con `--require-hashes`

**Amenaza:** Baja a media en 2026 (supply chain attacks están en aumento). Defense-in-depth.

**Fix propuesto:** Generar `requirements.lock` con `pip freeze` y usar `pip install --require-hashes -r requirements.lock`. O usar `pipenv` / `uv` que manejan lock files automáticamente.

---

### 🔵 #12 — PII: nombre real en doc público

**Archivo:** `docs/ARCHITECTURE.md:125`

```
- Claridad: si commiteás a mano a este repo, el autor real (`Jose Alvarado`) no se mezcla con el bot (`alarm`).
```

**Problema:** El nombre real está en un doc público de un repo público. Cualquiera puede hacer un `git blame` y confirmar el owner.

**Amenaza:** Baja (el usuario controla el repo, eligió esto). Pero es PII.

**Fix opcional:** Quitar el nombre real, dejar solo "el autor real" sin nombre:
```
- Claridad: si commiteás a mano a este repo, el autor real no se mezcla con el bot (`alarm`).
```

---

### 🔵 #13 — Token escrito a `.git/config` durante ejecución

**Archivo:** `alarm.py:106`

```python
new_url = url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/", 1)
git_silent("remote", "set-url", "origin", new_url)
```

**Problema:** El `GITHUB_TOKEN` queda escrito en `.git/config` (formato URL con user:pass) durante la ejecución. Si el runner es comprometido mid-run, el token es legible por cualquier proceso con acceso al filesystem.

**Amenaza:** Baja. El runner es ephemeral (se destruye al terminar el job). Pero en ese momento, otros procesos del mismo runner (si los hay) podrían leer el config.

**Mitigación:** El runner de GH Actions está aislado. No hay otros tenants en el mismo runner. Por lo tanto, riesgo real ≈ 0.

**Fix opcional (si se quiere más seguridad):** Usar un credential helper o `http.<URL>.extraheader` en vez de la URL inline. Más complejo, marginalmente más seguro.

---

### 🔵 #14 — `except Exception` broad en `main()`

**Archivo:** `alarm.py:167`

```python
try:
    write_state(code)
    commit_and_push(code, dry_run=False)
except Exception:
    return 1
```

**Problema:** Captura todo silenciosamente. El usuario (en local) no sabe qué falló. Es un trade-off: en CI, el silencio es por diseño (no-leak), pero en local debugging es molesto.

**Amenaza:** Ninguna. Es UX.

**Fix opcional:** Distinguir entre modo `--quiet` y modo normal. En modo normal, loguear la excepción. En `--quiet`, no loguear nada.

---

### 🔵 #15 — Default `URL_PRIMARY=https://iacode.cl`

**Archivo:** `.env.example`, `PROYECTO.md`, varios docs

**Problema:** El default expone que el usuario tiene infraestructura en `iacode.cl`. Combinado con el repo público, un atacante sabe que ese dominio está asociado al usuario.

**Amenaza:** Baja. `iacode.cl` es público de todas formas. Pero es información que el usuario eligió hacer pública.

**Fix opcional:** Cambiar el default a algo neutro como `https://example.com` y forzar al usuario a configurar.

**Por qué no lo recomiendo:** El default útil (`iacode.cl`) hace que el alarm funcione out of the box. Es parte del valor. No cambiar.

---

### 🔵 #16 — Commits de debug en historia pública

**Archivo:** `git log` (ya en el remote)

**Problema:** Hay 8 commits de debug/fix intermedios. Ya aceptado por el usuario; no se reescribirá historia.

**Amenaza:** Ninguna directamente. El contenido de los commits es código y mensajes, no secrets.

**Fix:** Ninguno. Es trade-off aceptado.

---

### 🔵 #17 — Mención de `iacode.cl` en docs

**Archivos:** `PROYECTO.md`, `README.md`, `docs/*`

**Problema:** Mismo concepto que #15 — el dominio `iacode.cl` aparece en la documentación como ejemplo y default. Es disclosure by documentation.

**Amenaza:** Baja. Es info pública de todas formas.

**Fix opcional:** Cambiar a `https://example.com` en docs. No lo recomiendo (mismo razonamiento que #15).

---

### 🔵 #18 — `--verbose` imprime bits

**Archivo:** `alarm.py:155-159`

**Problema:** `--verbose` muestra `bit N [0/1]`. Esto es **por diseño** (debug mode) y no leakear URLs. Pero alguien que vea el output puede inferir el patrón (cuántos checks, etc.).

**Amenaza:** Muy baja. Es debug opt-in.

**Fix:** Ninguno. Es feature.

---

## Hallazgos NO encontrados (validación negativa)

Para que quede registro, estos patrones fueron buscados y **no se encontraron**:

- ✅ **API keys hardcodeadas** (OpenAI, Anthropic, AWS, Google, GitHub PAT, GitLab, Slack, Mailgun)
- ✅ **Tokens genéricos en variables `api_key`/`secret`/`token`/`password`**
- ✅ **Private keys PEM** (RSA, EC, OpenSSH)
- ✅ **Seed phrases / mnemonics / BIP39**
- ✅ **Connection strings con credenciales** (postgres://user:pass@...)
- ✅ **`.env` tracked** (solo `.env.example` está en el repo; `.env` está en `.gitignore`)
- ✅ **Personal email leaks** (solo `alarm@users.noreply.github.com` aparece; el `jose.alvarado.mazzei@gmail.com` está en git config global pero no en archivos del proyecto)
- ✅ **Hardcoded paths personales** (no hay `C:\Users\JoseA\...` en código)
- ✅ **Stack traces en código** (todos los `try/except` silencionan correctamente)
- ✅ **URLs impresas en logs** (la política de no-leak se implementa consistentemente)

---

## Recomendaciones priorizadas

### Hacer ahora (5-10 min)
1. **#3**: Eliminar el `git push` duplicado en `alarm.py:128-130`.
2. **#4**: Agregar `concurrency:` al workflow.
3. **#5**: Extender el loop de `::add-mask::` para incluir todos los secrets.
4. **#9**: Actualizar docstring de `alarm.py:1`.
5. **#10**: Cambiar `__import__("os")` por `import os` en `checks/http.py`.

### Hacer esta semana
6. **#1**: Bloquear credenciales embebidas en URL.
7. **#6**: Setear `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` o actualizar a actions v5+ cuando existan.
8. **#7**: Agregar `pip-audit` como workflow semanal.

### Hacer eventualmente (cuando duela)
9. **#2**: Evaluar si vale la pena bloquear IPs privadas. (Trade-off: ¿querés monitorear infra local o no?)
10. **#8**: Hacer configurable el SSL timeout.
11. **#11**: Lock file + hashes.
12. **#12**: Limpiar el nombre real de `docs/ARCHITECTURE.md`.

### No hacer
- **#13, #14, #15, #17, #18**: Trade-offs aceptados. Documentados en este audit, no requieren cambio.

---

## Actualizaciones

### 2026-06-07: Round 2 de fixes aplicados

Después del audit inicial, el usuario pidió que los pendientes "que se cierre algo que puede ser que sea limitante" se implementen como **opciones de elegir** (granularidad). Se aplicaron los siguientes:

**#2 — SSRF protection (ahora con opt-out granular):**
- Implementado `is_private_ip()`, `is_safe_target()`, `_ssrf_check()` en `security.py`
- Default seguro: bloquea RFC1918, loopback, link-local (incluye metadata AWS/GCP), CGNAT, IPv6 ULA, etc.
- Opt-out: `ALLOW_PRIVATE_TARGETS=true` para los que necesiten monitorear infra local
- El check evalúa IPs literales (no hostnames, documentado)

**#7 — pip-audit semanal:**
- Nuevo workflow `.github/workflows/audit.yml`
- Corre lunes 06:00 UTC, modo `workflow_dispatch` para trigger manual
- `--strict --requirement requirements.txt` (falla si hay vulns con fix)

**Extras (granularidad):**
- `CHECKS` env var: corre solo slots específicos (formato: `0,3` o `URL,SSL`)
- `--only` CLI flag: override de CHECKS para tests
- `assemble_code()` ahora paddea por `bit_index` (no por orden de iteración)

**Severidad actualizada tras round 2:**
- 0 muy altos, 0 altos
- 0 medio-altos (los 4 estaban pendientes; #1 #3 #4 cerrados en round 1, #2 cerrado en round 2)
- 2 medios (#5 #6 cerrados en round 1, #7 cerrado en round 2)
- 11 bajos (sin cambios)
- 0 nuevos

---

## Cómo se hizo este audit

1. **Inventario:** listado de todos los archivos del proyecto (excluyendo `.git/`, `__pycache__/`).
2. **Greps de patrones sensibles:** API keys (10 patrones), tokens genéricos, private keys PEM, connection strings, `.env` tracked, paths absolutos, emails.
3. **Lectura completa** de cada `.py`, `.yml`, `.md`, `.txt`, `.example`.
4. **Cross-check** de claims en `docs/SECURITY.md` contra código real.
5. **Revisión de git log** buscando mensajes o diffs sospechosos.
6. **Revisión de git config** local y global buscando leaks.

**No ejecutado (fuera de scope):** gitleaks, trufflehog, escaneo de historial completo, auditoría de runtime, fuzzing.

**No aplica a este proyecto:** XSS, SQLi, CSRF, auth bypass (no hay user-facing surface).
