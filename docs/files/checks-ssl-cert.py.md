# `checks/ssl_cert.py`

Check de expiración de certificados SSL/TLS. Usado por **slots 3 y 4** del código binario.

## `check_ssl(env_var: str) -> bool`

```python
def check_ssl(env_var: str) -> bool:
    if not security.is_configured(env_var):
        return False
    import os
    return security.safe_ssl_check(os.environ[env_var])
```

Devuelve `True` si hay problema.

| Caso | Resultado |
|---|---|
| Env var vacía o no seteada | `False` (slot deshabilitado) |
| Cert expira en ≥ 14 días | `False` (OK) |
| Cert expira en < 14 días | `True` (problema) |
| No se puede conectar | `True` (problema) |
| Cert inválido / handshake fails | `True` (problema) |

## Slots que usan este check

| Slot | Env var | Default |
|---|---|---|
| 3 | `SSL_PRIMARY` | `iacode.cl` |
| 4 | `SSL_SECONDARY` | *(vacío)* |

**Importante:** la env var es un **hostname** (sin `https://`), no una URL. Ejemplo: `iacode.cl`, no `https://iacode.cl`.

## Implementación

Igual que `http.py`: delega todo en `checks/security.py::safe_ssl_check()`. La política de no-leak, el umbral de 14 días, y la lógica de parseo están todos en el helper.

```python
return security.safe_ssl_check(os.environ[env_var])
```

## El umbral de 14 días

`_MIN_SSL_DAYS = 14` está hardcodeado en `checks/security.py`. ¿Por qué 14 y no 30 o 7?

- **14 días** es un sweet spot: suficiente para renovar un cert con Let's Encrypt (que se puede automatizar) sin ser tan largo que parezca "todo bien" cuando ya está por vencer.
- Let's Encrypt recomienda renovar 30 días antes del vencimiento. 14 días te da un **margen de 16 días** para reaccionar si algo falla en la renovación automática.
- Si tu cert dura 90 días y se vence en 15, ya tenés el `1` encendido y 1 día de margen. Ajustar este valor es un trade-off.

**Si querés cambiar el umbral:** editá `_MIN_SSL_DAYS` en `checks/security.py`. No está expuesto como env var porque no es algo que el usuario normalmente quiera tocar.

## Por qué no se loguea el hostname

Cuando la conexión SSL falla (cert inválido, hostname no matchea, etc.), el mensaje de error de OpenSSL contiene el hostname. Por la política de no-leak, **no se imprime**.

Ejemplo de un mensaje que **NO** queremos ver en logs:
```
ssl.SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch (ssl_certificate_hostname_mismatch)
```

El hostname del cert y el que se pidió leakearían. Por eso `safe_ssl_check` silencia todo.

## Casos de uso típicos

### Monitorear tu dominio principal

```bash
# .env
SSL_PRIMARY=mi-dominio.com
```

### Monitorear varios subdominios

```bash
# .env
SSL_PRIMARY=mi-dominio.com
SSL_SECONDARY=api.mi-dominio.com
```

Dos slots. Si `api.mi-dominio.com` está por vencer y `mi-dominio.com` no, el código será `00010000` (bit 4).

### Monitorear un servicio de terceros

```bash
# GitHub Secrets en CI
SSL_SECONDARY=hub.algun-servicio.com
```

Si el cert de `hub.algun-servicio.com` vence en 10 días, el alarm te avisa (bit 4 = 1) **antes** de que tu servicio se rompa.

## Limitaciones

- **No chequea cadena de certificación completa** más allá de lo que hace `create_default_context()`. Si tenés un cert con chain raro, esto puede fallar de formas no obvias.
- **No chequea SNI mismatch.** El `server_hostname=host` se pasa, pero si el server devuelve un cert para otro dominio, `ssl.SSLError` se levanta. El check lo reporta como problema, lo cual es correcto.
- **No chequea revocation (CRL/OCSP).** Un cert revocado pasa este check.
- **Timeout fijo de 10s** en `safe_ssl_check`. No configurable via env var.
- **Solo puerto 443.** Si tu servicio usa un puerto no-estándar para TLS, este check no funciona.

## Testing

```bash
# OK (cert de example.com vence en mucho más de 14 días)
SSL_PRIMARY=example.com python alarm.py --dry-run
# → 00000000

# Hostname que no existe
SSL_PRIMARY=this-does-not-exist-12345.invalid python alarm.py --dry-run
# → 00001000 (bit 3 = 1)

# Hostname sin TLS (puerto 80)
SSL_PRIMARY=example.com python alarm.py --dry-run
# Esto va a tirar timeout porque intenta conectar al 443, no al 80
# → 00001000 (bit 3 = 1)
```

## Troubleshooting

### "Bit 3 = 1 pero mi cert vence en 60 días"

Probable que el `server_hostname=host` esté fallando por SNI mismatch. Verificá:
```bash
openssl s_client -connect tu-host.com:443 -servername tu-host.com
```

Si la respuesta es `verify error`, el problema es de configuración del server, no del cert.

### "Bit 3 = 1 intermitentemente"

Timeouts de conexión. Los runners de GitHub Actions pueden tener problemas para alcanzar ciertos hosts. Considerá:
- Subir el timeout (modificar `socket.create_connection(..., timeout=10)` en `safe_ssl_check`)
- Usar un endpoint diferente

### "Quiero saber cuántos días le quedan al cert"

Este check no lo revela (por diseño). Para ver el dato exacto:
```bash
openssl s_client -connect tu-host.com:443 -servername tu-host.com < /dev/null 2>/dev/null | openssl x509 -noout -dates
```
