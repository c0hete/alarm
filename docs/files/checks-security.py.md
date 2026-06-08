# `checks/security.py`

Helpers de bajo nivel usados por **todos** los checks. Centraliza la política de no-leak y HTTPS-only.

**Este es el módulo más importante del proyecto en términos de seguridad.** Si vas a agregar un check nuevo, usá estos helpers en vez de llamar a `requests.get` o `socket` directamente.

## Constantes

```python
_ALLOWED_SCHEMES: Final = frozenset({"https"})
_MIN_SSL_DAYS: Final = 14
_PRIVATE_NETS: Final = [ipaddress.ip_network(...) for ...]
```

- `_ALLOWED_SCHEMES`: set inmutable de schemes permitidos. Solo `https`. Cualquier otro (incluyendo `http`) se rechaza.
- `_MIN_SSL_DAYS`: días mínimos de validez del cert SSL. Si quedan menos, hay problema.
- `_PRIVATE_NETS`: lista de redes bloqueadas por el check SSRF (RFC1918, loopback, link-local, CGNAT, IPv6 ULA, multicast, reserved, etc.). Ver [SSRF protection](#ssrf-protection-opt-out) abajo.

## Supresión de warnings

```python
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
```

Al import, deshabilita los warnings de `urllib3` (incluyendo `InsecureRequestWarning` y `SubjectAltNameWarning`). Esto evita que aparezcan en stderr y potencialmente leaken info.

**Cuidado:** otros warnings de Python se suprimen en `alarm.py` con `warnings.filterwarnings("ignore")`. Este `disable_warnings` es específico de urllib3.

## `is_configured(env_var: str) -> bool`

```python
def is_configured(env_var: str) -> bool:
    return bool(os.environ.get(env_var, "").strip())
```

Devuelve `True` si la env var existe y no está vacía (después de `.strip()`).

**Patrón de uso en checks:**

```python
def check() -> bool:
    if not security.is_configured("MI_VAR"):
        return False  # slot deshabilitado
    url = os.environ["MI_VAR"].strip()
    # ... lógica ...
```

La convención es: **variable vacía = slot deshabilitado = siempre OK (`False`)**. Esto permite al usuario "apagar" un check sin tocar código.

## `validate_https_url(url: str) -> bool`

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

Devuelve `True` si la URL es HTTPS válida con hostname. **No loguea nada**, ni siquiera en error.

**Casos rechazados:**
- `""` o `None`
- `"http://example.com"` (HTTP no permitido)
- `"https://"` (sin hostname)
- `"not a url"` (formato inválido)
- Cualquier excepción de `urlparse`

**Importante:** este helper se llama **antes** de hacer la request, para evitar hacer requests a `http://` que podrían leakear o ser MITM-eadas.

## `safe_request(url: str, timeout: int) -> bool`

```python
def safe_request(url: str, timeout: int) -> bool:
    if not validate_https_url(url):
        return True
    import requests
    try:
        r = requests.get(
            url,
            timeout=timeout,
            allow_redirects=False,
            headers={"User-Agent": "alarm/1.0"},
        )
        return not (200 <= r.status_code < 300)
    except Exception:
        return True
```

GET HTTPS sin redirects. Devuelve `True` si hay problema.

| Caso | Resultado |
|---|---|
| URL vacía o no-HTTPS | `True` (problema) |
| HTTP 2xx | `False` (OK) |
| HTTP 3xx, 4xx, 5xx | `True` (problema) |
| Timeout, connection error, DNS fail | `True` (problema) |
| Cualquier otra excepción | `True` (problema) |

**Por qué `allow_redirects=False`:** un 302 podría apuntar a un host inesperado. El alarm rechaza el redirect y reporta como problema.

**Por qué `User-Agent: alarm/1.0`:** algunos servicios bloquean User-Agents genéricos de `requests`. Identificarse como `alarm/1.0` ayuda a debugging en el server-side.

**Por qué `import requests` local:** evita requerir `requests` si el check no se usa (por ejemplo, si todos los slots están deshabilitados). Si `requests` no está instalado, el import falla solo cuando se llama a `safe_request`, no al import del módulo.

## `safe_get_json(url: str, timeout: int) -> dict | None`

Igual que `safe_request` pero parsea la respuesta como JSON. Devuelve `None` si hay cualquier problema.

```python
def safe_get_json(url: str, timeout: int) -> dict | None:
    if not validate_https_url(url):
        return None
    import requests
    try:
        r = requests.get(
            url,
            timeout=timeout,
            allow_redirects=False,
            headers={"User-Agent": "alarm/1.0", "Accept": "application/json"},
        )
        if not (200 <= r.status_code < 300):
            return None
        return r.json()
    except Exception:
        return None
```

**Usado por:**
- `github_status.py` para pedir `https://www.githubstatus.com/api/v2/status.json`
- `backup.py` para pedir el `BACKUP_MANIFEST`

**Patrón de uso en el caller:**

```python
data = security.safe_get_json(url, timeout=10)
if data is None:
    return True  # problema
# ... usar data ...
```

**Por qué `Accept: application/json`:** ayuda a que el server devuelva JSON en vez de HTML. Reduce la chance de que `r.json()` falle con un parse error.

## `safe_ssl_check(host: str) -> bool`

```python
def safe_ssl_check(host: str) -> bool:
    if not host or not host.strip():
        return False
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host.strip(), 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host.strip()) as ssock:
                cert = ssock.getpeercert()
        if not cert or "notAfter" not in cert:
            return True
        raw = cert["notAfter"]
        parsed = None
        for fmt in ("%b %d  %H:%M:%S %Y %Z", "%b %d %H:%M:%S %Y %Z"):
            try:
                parsed = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        if parsed is None:
            return True
        days_left = (parsed - datetime.now(timezone.utc)).days
        return days_left < _MIN_SSL_DAYS
    except Exception:
        return True
```

Conecta por TLS al host en puerto 443. Devuelve `True` si hay problema.

| Caso | Resultado |
|---|---|
| Host vacío | `False` (slot deshabilitado) |
| Cert expira en ≥ 14 días | `False` (OK) |
| Cert expira en < 14 días | `True` (problema) |
| No se puede conectar | `True` (problema) |
| Cert inválido / handshake fails | `True` (problema) |
| Formato de fecha inesperado | `True` (problema) |
| Cualquier otra excepción | `True` (problema) |

**Por qué dos formatos de fecha:** OpenSSL devuelve `"Mon Jan  1 00:00:00 2024 GMT"` con doble espacio cuando el día es de 1 dígito, y `"Mon Jan 10 00:00:00 2024 GMT"` con un solo espacio cuando es de 2 dígitos. Probamos ambos.

**`server_hostname=host`:** SNI. Necesario para servidores que hospedan múltiples dominios en la misma IP (SNI = Server Name Indication).

**`create_default_context()`:** usa los CA bundles del sistema. Si tu host usa un cert auto-firmado, este check va a fallar. Considerá usar Let's Encrypt o agregar el CA al sistema.

**Nunca loguea el hostname** en errores. La excepción se silencia completamente.

## `parse_iso_utc(date_str: str) -> datetime | None`

```python
def parse_iso_utc(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
```

Parsea una fecha ISO 8601 con o sin timezone, devuelve un `datetime` UTC. `None` si hay problema.

**Por qué `str(...).replace("Z", "+00:00")`:** `datetime.fromisoformat` en Python <3.11 no acepta el sufijo `Z`. Reemplazamos manualmente. En Python 3.11+ también funciona, no hace daño.

**Por qué `tzinfo=None` → UTC:** si el JSON no trae timezone, asumimos UTC. Esto es una decisión: si el server que genera el manifest está en otra zona y se olvida del timezone, el alarm reporta "backup viejo" cuando no lo es. Es un trade-off conservador.

## Resumen: qué enforce este módulo

| Política | Dónde se enforce |
|---|---|
| HTTPS-only | `validate_https_url`, usado por `safe_request` y `safe_get_json` |
| No redirects | `allow_redirects=False` en `safe_request` y `safe_get_json` |
| No-leak de URLs/hostnames | `try/except Exception` en cada función, sin `print` ni `log` |
| No-leak de mensajes de error | Mismo try/except, no se imprime `exc` |
| Supresión de warnings | `urllib3.disable_warnings` al import |
| SSRF protection (opt-out) | `_ssrf_check`, llamado desde `safe_request`/`safe_get_json`/`safe_ssl_check` |

**Si vas a agregar un check nuevo:** usá estos helpers. Si necesitás algo que no está cubierto (por ejemplo, DNS lookup, ping), agregalo acá y mantene la misma política.

## SSRF protection (opt-out)

Tres helpers para defense-in-depth contra SSRF. Aplicados automaticamente por `safe_request`, `safe_get_json`, `safe_ssl_check`.

### `_PRIVATE_NETS` (constante)

Lista de `ipaddress.ip_network` que se bloquean. Incluye (no exhaustivo):

| Red | Razón |
|---|---|
| `0.0.0.0/8` | "This network" |
| `10.0.0.0/8` | RFC1918 private |
| `100.64.0.0/10` | CGNAT |
| `127.0.0.0/8` | Loopback IPv4 |
| `169.254.0.0/16` | Link-local (incluye AWS/GCP metadata `169.254.169.254`) |
| `172.16.0.0/12` | RFC1918 private |
| `192.0.0.0/24`, `192.0.2.0/24` | IETF reserved / TEST-NET-1 |
| `192.168.0.0/16` | RFC1918 private |
| `198.18.0.0/15` | Benchmarking |
| `198.51.100.0/24`, `203.0.113.0/24` | TEST-NET-2 / TEST-NET-3 |
| `224.0.0.0/4`, `240.0.0.0/4` | Multicast / Reserved |
| `::/128`, `::1/128` | IPv6 unspecified / loopback |
| `::ffff:0:0/96` | IPv4-mapped |
| `64:ff9b::/96`, `100::/64` | IPv4-IPv6 translation / discard |
| `2001::/32`, `2001:db8::/32` | Teredo / documentation |
| `fc00::/7`, `fe80::/10`, `ff00::/8` | IPv6 ULA / link-local / multicast |

### `is_private_ip(host: str) -> bool`

```python
def is_private_ip(host: str) -> bool:
    if not host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # hostname, no IP literal
    return any(ip in net for net in _PRIVATE_NETS)
```

**Comportamiento:**
- IP literal en red bloqueada → `True` (peligrosa)
- IP literal pública → `False` (segura)
- Hostname (DNS) → `False` (asume OK — no hace DNS lookup)

**Por qué no evalúa hostnames:** evitar side effects (DNS lookup). El operador es responsable de no poner hostnames que resuelvan a IPs privadas. Para entornos de máxima seguridad, correr el alarm con un egress proxy que filtre.

### `is_safe_target(url_or_host: str) -> bool`

```python
def is_safe_target(url_or_host: str) -> bool:
    if not url_or_host:
        return False
    if "://" in url_or_host:
        try:
            parsed = urllib.parse.urlparse(url_or_host)
            host = parsed.hostname
        except (ValueError, AttributeError):
            return False
    else:
        host = url_or_host.strip()
    if not host:
        return False
    return not is_private_ip(host)
```

Wrapper que acepta tanto URL (`https://10.0.0.1/foo`) como hostname (`10.0.0.1`). Devuelve `True` si el target es seguro.

### `_ssrf_check(url_or_host: str) -> bool`

```python
def _ssrf_check(url_or_host: str) -> bool:
    if _ssrf_opted_out():
        return True  # bypass explícito
    return is_safe_target(url_or_host)
```

Aplica el opt-out. Devuelve `True` si el target pasa el check (o si el usuario deshabilitó la protección).

### Opt-out: `ALLOW_PRIVATE_TARGETS`

```bash
ALLOW_PRIVATE_TARGETS=true   # permite targets privados
```

Acepta: `1`, `true`, `yes`, `on` (case-insensitive). Default: bloqueado.

**Por qué es opt-out y no opt-in:** security-by-default. El operador que necesita monitorear infra local debe ser explícito al respecto.

**Usado por:** `safe_request`, `safe_get_json`, `safe_ssl_check`. Todos llaman `_ssrf_check` antes de tocar la red.
