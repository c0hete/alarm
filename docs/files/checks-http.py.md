# `checks/http.py`

Check genérico de URL. Usado por **slots 0, 1, 2, y 7** del código binario.

## `check_url(env_var: str, timeout: int) -> bool`

```python
def check_url(env_var: str, timeout: int) -> bool:
    if not security.is_configured(env_var):
        return False
    return security.safe_request(
        __import__("os").environ[env_var].strip(), timeout
    )
```

Devuelve `True` si hay problema.

| Caso | Resultado |
|---|---|
| Env var vacía o no seteada | `False` (slot deshabilitado) |
| HTTP 2xx | `False` (OK) |
| HTTP 3xx, 4xx, 5xx | `True` (problema) |
| Timeout, connection error, DNS fail | `True` (problema) |
| URL no-HTTPS | `True` (problema) |

## Slots que usan este check

| Slot | Env var | Default |
|---|---|---|
| 0 | `URL_PRIMARY` | `https://iacode.cl` |
| 1 | `URL_SECONDARY` | *(vacío)* |
| 2 | `URL_TERTIARY` | *(vacío)* |
| 7 | `CUSTOM_API_URL` | *(vacío)* |

Los 4 slots comparten la misma función pero con diferentes env vars. Esto se hace con un `lambda` en `checks/base.py::build_registry()`:

```python
Check(0, "URL primaria", lambda: http.check_url("URL_PRIMARY", timeout)),
Check(1, "URL secundaria", lambda: http.check_url("URL_SECONDARY", timeout)),
Check(2, "URL terciaria", lambda: http.check_url("URL_TERTIARY", timeout)),
Check(7, "Custom API", lambda: http.check_url("CUSTOM_API_URL", timeout)),
```

## Implementación

La función es **delgada**: delega todo el trabajo en `checks/security.py::safe_request()`. La política de HTTPS, no-redirects, y no-leak viene de ahí.

```python
return security.safe_request(
    __import__("os").environ[env_var].strip(), timeout
)
```

**El `__import__("os")` en vez de `import os` arriba:** quirk menor. Como el módulo es muy corto, evito un import top-level. Es más por estética que por rendimiento. Se podría refactorizar a un `import os` normal.

## Diferencia entre `URL_PRIMARY` y `CUSTOM_API_URL`

Conceptualmente son lo mismo: una URL a la que hacer GET. La diferencia es **semántica**:

- `URL_PRIMARY`, `URL_SECONDARY`, `URL_TERTIARY` están pensados para monitorear **tu propia infra** (tus servers, tus servicios). El default `URL_PRIMARY=https://iacode.cl` es la app iacode del usuario.
- `CUSTOM_API_URL` está pensado para monitorear **APIs externas** (Stripe, GitHub, lo que sea). El nombre en el bit 7 ("Custom API") refleja esto.

En la práctica, el código es idéntico. La separación es solo para claridad en `PROYECTO.md` y para que el slot 7 no se confunda con los slots 0-2.

## Casos de uso típicos

### Monitorear tu web

```bash
# .env
URL_PRIMARY=https://mi-sitio.com
URL_SECONDARY=https://api.mi-sitio.com/health
```

Si `mi-sitio.com` devuelve 500, bit 0 = 1. Si la API está caída, bit 1 = 1.

### Monitorear una API externa

```bash
# GitHub Secrets en CI
CUSTOM_API_URL=https://api.stripe.com/v1/charges?limit=1
```

Necesitás auth en el header, pero este check no soporta headers custom. Si necesitás auth, este check no te sirve. **Workaround:** apuntá a un endpoint público de la API que devuelva 2xx sin auth. Si no existe, no metas esa API en el alarm.

### Monitorear el status page de un servicio

```bash
URL_SECONDARY=https://status.stripe.com
```

El status page suele ser HTML (no JSON). El check solo verifica HTTP 2xx, no parsea el contenido. Si el status page está verde pero el servicio está rojo, no te enterás.

## Limitaciones

- **No soporta headers custom.** No podés mandar `Authorization` ni `X-API-Key`. Si lo necesitás, escribí un check custom en `checks/` (y agregalo al registry).
- **No soporta POST.** Solo GET. Si tu health check necesita POST, este no te sirve.
- **No parsea la respuesta.** Solo verifica el status code. Un 200 con `{"status": "degraded"}` se reporta como OK.
- **No soporta `Content-Type: application/json` enforcement.** Pide cualquier 2xx, JSON o no.

Si necesitás alguna de esas features, escribí un check custom y agregalo al registry.

## Testing

```bash
# OK
URL_PRIMARY="https://example.com" python alarm.py --dry-run
# → 00000000 (o el código según el resto de los checks)

# 500
URL_PRIMARY="https://httpbin.org/status/500" python alarm.py --dry-run
# → 10000000 (bit 0 = 1)

# HTTP rechazado
URL_PRIMARY="http://example.com" python alarm.py --dry-run
# → 10000000 (http:// rechazado por HTTPS-only)

# DNS inválido
URL_PRIMARY="https://this-does-not-exist-12345.invalid" python alarm.py --dry-run
# → 10000000 (DNS fail)

# Vacío (deshabilitado)
URL_PRIMARY="" python alarm.py --dry-run
# → 00000000 (slot deshabilitado)
```
