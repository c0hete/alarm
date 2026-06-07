# alarm

## Visión
Dead-man switch creativo: un repo que se autocommitea **todos los días** con un código binario de 8 bits.
- `0` en un bit = ese slot está OK
- `1` en un bit = ese slot tiene un problema
- **El commit NO dice cuál slot falló.** Solo el número binario y la fecha.

El doble propósito:
1. **Racha de GitHub** — commits diarios automáticos = contribution graph verde.
2. **Heartbeat silencioso** — si aparece un `1`, sabés que hay algo para mirar, pero el alarm nunca te dice qué. Vos investigás.

## Decisiones
- **Stack:** Python 3.11+, sin frameworks. Deps mínimas: `requests`, `urllib3`.
- **Trigger:** GitHub Actions cron diario (09:00 UTC). No requiere la PC encendida.
- **Output:** archivo nuevo por día en `state/YYYY-MM-DD.txt` con el código binario. Cambia siempre el archivo → siempre hay commit.
- **Longitud:** 8 bits = 1 byte. 256 combinaciones posibles. Suficiente; si se necesitan más, se rompe la compatibilidad y se migra a 16.
- **Privacidad por diseño:** la función de check nunca loguea QUÉ falló. Solo el agregado. Debug opcional con `--verbose`.
- **Repo:** público (para que el contribution graph cuente). No commitea secretos.

## Slots (bit 0 = LSB, bit 7 = MSB)
| Bit | Slot | Default | Habilitado si |
|---|---|---|---|
| 0 | URL primaria | `https://iacode.cl` | siempre |
| 1 | URL secundaria | vacío | `URL_SECONDARY` seteado |
| 2 | URL terciaria | vacío | `URL_TERTIARY` seteado |
| 3 | SSL primaria | `iacode.cl` (≥14d) | siempre |
| 4 | SSL secundaria | vacío | `SSL_SECONDARY` seteado |
| 5 | GitHub status API | público | siempre |
| 6 | Backup freshness | vacío | `BACKUP_MANIFEST` seteado |
| 7 | Custom API | vacío | `CUSTOM_API_URL` seteado |

## No-objetivos
- No es un monitor con dashboard. No hay UI.
- No alerta (email/Slack/etc.). El "alert" es el `1` en el commit.
- No dice cuál check falló. Por diseño.

## Seguridad / no-leak

El alarm corre en GitHub Actions (logs públicos si el repo es público). Por lo tanto, **nada de lo que se monitorea puede terminar en los logs, en mensajes de error, ni en stack traces**. Política explícita:

- **HTTPS-only en todas las URLs.** `http://` se rechaza antes de tocar la red.
- **No redirects.** `allow_redirects=False` para no leakear a hosts inesperados.
- **Excepciones silenciosas.** Cualquier fallo de red / parseo / SSL → `True` (= problema) sin imprimir nada. Nunca se loguea el mensaje de la excepción.
- **No se imprimen URLs ni hostnames.** Ni en modo `--verbose`. Solo `bit N [0/1]`.
- **Output mínimo por defecto.** `python alarm.py` imprime SOLO el código binario (8 chars) en stdout. En CI se usa `--quiet` (cero output).
- **Secretos enmascarados en CI.** `::add-mask::` en el workflow para que cualquier valor que se filtrara aparezca como `***` en logs.
- **`persist-credentials: false`** en `actions/checkout`. El token de push no queda en `.git/config` después del checkout.
- **Permisos mínimos:** `contents: write` solamente. Sin `packages`, sin `id-token`, sin `deployments`.
- **Repo público intencionalmente** (para contribution graph). El único dato que commitea es la fecha y un código binario sin label. Sin URLs, sin hostnames, sin stack traces.

## Estado
Vivo desde 2026-06-06.
