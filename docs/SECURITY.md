# Seguridad

Este documento describe el **modelo de seguridad** del alarm y la política de **no-leak** que se aplica de forma consistente. Si vas a modificar el código, lee esto primero.

## El problema

El alarm corre en GitHub Actions con el repo **público**. Eso significa:

- **Los logs de CI son públicos** (cualquiera con el link puede verlos).
- **El contribution graph es público**.
- **Los commits son públicos** (mensaje, autor, contenido del diff).

Cualquiera de estos canales podría leakear:
- URLs de infraestructura interna
- Nombres de host
- Mensajes de error que contienen paths, tokens, o versiones
- Identidad del owner (si commitea con su email real)

## La política: no-leak

**Por diseño, nada de lo que el alarm monitorea puede aparecer en logs, commits, ni stderr público.**

| Canal | Política | Cómo se enforce |
|---|---|---|
| Logs de CI | Cero output por default. | `--quiet` en el workflow. |
| Commits | Solo fecha + código binario. | `alarm.py` escribe solo `state/YYYY-MM-DD.txt`. |
| `stderr` | Vacío en default. `--verbose` solo dice `bit N [0/1]`. | Filtrado en `alarm.py`. |
| Excepciones de librerías | Silenciadas, no se loguean. | `try/except Exception: return True` en cada check. |
| Env vars | Nunca se imprimen. | `alarm.py` no tiene `print(env)` ni equivalente. |
| URL en errores | Nunca aparece. | `git_silent()` captura stderr; el script no lo imprime. |

## HTTPS-only

**Toda URL chequeada debe ser HTTPS.** `http://` se rechaza antes de tocar la red.

Implementado en `checks/security.py::validate_https_url()`:

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

Por qué:
- Previene MITM en redes inseguras
- Evita que un atacante downgrade-e a `http://` para ver el contenido
- TLS da garantía de que la respuesta viene del host correcto

**Importante:** Si tu infra es HTTP plano (no HTTPS), no la metas en el alarm. Conseguí un cert o usá un proxy HTTPS frente a ella.

## No redirects

**Todos los requests tienen `allow_redirects=False`.**

Implementado en `checks/security.py::safe_request()` y `safe_get_json()`:

```python
r = requests.get(url, timeout=timeout, allow_redirects=False, ...)
```

Por qué:
- Un 302 podría apuntar a un host inesperado (atacante o proxy mal configurado)
- Si el destino del redirect está caído, no hay manera de saber a dónde "debía" ir
- Es un canal de leak pequeño pero real

Si un endpoint que necesitás monitorear hace redirect, eso es **una señal de que el endpoint está mal configurado**. Reportalo al owner del servicio en vez de bypassear la seguridad.

## SSRF protection (opt-out)

**Por defecto, las requests a IPs privadas / loopback / link-local / metadata se bloquean.**

Implementado en `checks/security.py::is_private_ip()` y aplicado via `_ssrf_check()` en `safe_request()`, `safe_get_json()` y `safe_ssl_check()`.

### Qué se bloquea

- Privadas RFC1918: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- Loopback: `127.0.0.0/8`, `::1`
- Link-local: `169.254.0.0/16` (**incluye AWS metadata en 169.254.169.254 y GCP**)
- CGNAT: `100.64.0.0/10`
- IPv6 ULA: `fc00::/7`
- ~10 redes más (reserved, multicast, etc.)

Ver lista completa en `checks/security.py::_PRIVATE_NETS`.

### Por qué

Si alguien pone `URL_PRIMARY=https://169.254.169.254/latest/meta-data/iam/security-credentials/`, el alarm intentaría robar credenciales IAM de AWS. En GitHub Actions los runners tienen acceso a metadata services. Esto lo previene.

### Opt-out para infra local

```bash
ALLOW_PRIVATE_TARGETS=true
```

Acepta: `1`, `true`, `yes`, `on` (case-insensitive). Cualquier otro valor = bloqueado.

**Cuándo usar:** Si necesitás monitorear infra local o de una VPN (e.g., `https://192.168.1.1/router-admin`). El operador decide conscientemente exponer esto.

### Limitaciones

- **No evalúa hostnames.** `https://iacode.cl/admin` pasa el check. Para protección contra DNS rebinding, correr el alarm en un entorno con DNS confiable.
- **Es defense-in-depth, no garantía absoluta.** El operador debe revisar las URLs que configura.

## Excepciones silenciosas

**Cualquier excepción en un check se reporta como `1` (problema) sin imprimir nada.**

Patrón en todos los checks:

```python
def check() -> bool:
    try:
        # ... lógica ...
    except Exception:
        return True
```

Por qué:
- Un stack trace leakearía paths internos, versiones de libs, y a veces datos de la request
- El alarm no necesita saber **por qué** falló — solo que falló
- Si querés debug, abrí los logs localmente con `--verbose`

Excepciones **no silenciadas** (deliberadamente):
- `KeyboardInterrupt`, `SystemExit` (propagan para que el script termine limpio)
- `MemoryError`, `RecursionError` (heredan de `BaseException`, no de `Exception`)

## Output mínimo

| Modo | stdout | stderr |
|---|---|---|
| default | Código binario (8 chars) | vacío |
| `--verbose` | Código binario | `bit N [0/1]` por check (sin URL/host) |
| `--quiet` | vacío | vacío |
| `--dry-run` | Código binario | vacío |

El modo default es **deliberadamente minimalista**. Si querés más detalle, usá `--verbose`. La idea es que en CI (que es `--quiet`) no haya NADA que leakear.

## Secretos

### Qué se commitea

- `state/YYYY-MM-DD.txt`: 8 caracteres (`0` o `1`) + newline
- Mensaje del commit: `alarm: YYYY-MM-DD = ABCDEFGH`
- Autor: `alarm <alarm@users.noreply.github.com>` (noreply, no tu email)

### Qué NO se commitea

- URLs, hostnames, ni paths
- Mensajes de error, stack traces, ni logs
- Variables de entorno ni valores de secrets
- Tu identidad real (la del usuario `c0hete` está asociada solo a los commits manuales, no a los del alarm)

### Mask en CI

El workflow tiene un step explícito de mask:

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

Si por algún bug el script imprimiera un secret, GitHub Actions lo reemplaza por `***` en el log. Es **defense-in-depth**, no un fix de root cause. La causa real es que el script nunca debería imprimir el valor.

## Permisos del workflow

```yaml
permissions:
  contents: write
```

Solo `contents: write` — lo mínimo necesario para `git push`. **No** se otorgan:
- `packages` (no publica packages)
- `id-token` (no usa OIDC)
- `deployments` (no deploya)
- `actions` (no workflow-a-otro-workflow)

Esto limita el blast radius si el `GITHUB_TOKEN` se viera comprometido: un atacante solo podría pushear al repo, no leer otros secrets ni ejecutar código en otros runners.

## Persistencia de credenciales

```yaml
- uses: actions/checkout@v4
  with:
    persist-credentials: false
```

Esto evita que el `GITHUB_TOKEN` quede en `.git/config` después del checkout. El script luego lo re-inyecta via `git remote set-url` solo cuando lo necesita para el push. La URL con el token solo vive en `.git/config` durante la ejecución del script y se pierde cuando el runner se destruye.

## ¿Por qué el repo es público?

- Para que el **contribution graph cuente**. Si fuera privado, los commits no aparecerían en tu perfil público.
- El contenido committeado es **deliberadamente opaco**: solo la fecha y un código binario sin label. Sin contexto, no hay info útil para un atacante.
- El código fuente está público, pero no revela **qué** se monitorea en producción. Solo el owner lo sabe (por las env vars / secrets).

Si en el futuro decidís hacer el repo privado:
- El streak de contribution graph **se va a romper** (los commits de repos privados no cuentan)
- El alarm sigue funcionando
- Tendrías que reconsiderar el modelo de no-leak: ahora el código fuente + los commits están protegidos, así que podés relajar la política

## Qué hacer si descubrís un leak

1. **Inmediato:** borrar el commit o el log que tiene el leak. `git rebase` en local + force-push (cuidado, esto puede romper la racha).
2. **Rotar** cualquier credencial que se haya leakado.
3. **Investigar** la causa raíz. ¿Por qué el código imprimió esa info? ¿Por qué pasó el filtro?
4. **Patch** el código y agregar un test que verifique que no se repita.
5. **Documentar** el incidente en el journal o donde corresponda.

## Auditoría de seguridad

Antes de cada cambio significativo, correr mentalmente esta checklist:

- [ ] ¿Algún `print()` o `log` nuevo podría leakear URLs, hostnames, o env vars?
- [ ] ¿Algún check nuevo usa requests sin `allow_redirects=False`?
- [ ] ¿Algún check nuevo usa requests sin validar HTTPS primero?
- [ ] ¿Alguna excepción se loguea con `print(exc)` o `traceback.print_exc()`?
- [ ] ¿El workflow tiene solo `contents: write` y nada más?
- [ ] ¿`persist-credentials: false` sigue en el checkout?
- [ ] ¿`--quiet` sigue siendo el default en CI?
- [ ] ¿Los nuevos secrets están en el loop de `::add-mask::`?

Si la respuesta a cualquiera es "no sé", **revisar antes de pushear**.
