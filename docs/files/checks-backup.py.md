# `checks/backup.py`

Check de freshness de backups. Usado por **slot 6** del código binario.

## `check() -> bool`

```python
_DEFAULT_MAX_AGE_DAYS = 2

def check() -> bool:
    if not security.is_configured("BACKUP_MANIFEST"):
        return False
    url = os.environ["BACKUP_MANIFEST"].strip()
    data = security.safe_get_json(url, timeout=10)
    if data is None:
        return True
    date_str = data.get("date") or data.get("last_backup")
    last = security.parse_iso_utc(date_str) if isinstance(date_str, str) else None
    if last is None:
        return True
    try:
        max_age = int(os.environ.get("BACKUP_MAX_AGE_DAYS", str(_DEFAULT_MAX_AGE_DAYS)))
    except ValueError:
        max_age = _DEFAULT_MAX_AGE_DAYS
    age_days = (datetime.now(timezone.utc) - last).days
    return age_days > max_age
```

Devuelve `True` si hay problema.

| Caso | Resultado |
|---|---|
| `BACKUP_MANIFEST` vacío o no seteado | `False` (slot deshabilitado) |
| Manifest tiene fecha ≤ `BACKUP_MAX_AGE_DAYS` días atrás | `False` (OK) |
| Manifest tiene fecha > `BACKUP_MAX_AGE_DAYS` días atrás | `True` (problema) |
| Error de red / parseo / formato | `True` (problema) |

## Configuración

| Env var | Default | Descripción |
|---|---|---|
| `BACKUP_MANIFEST` | *(vacío)* | URL HTTPS a un JSON con campo `date` o `last_backup`. |
| `BACKUP_MAX_AGE_DAYS` | `2` | Días máximos de antigüedad. Default conservador: 2 días. |

## El formato esperado del manifest

El manifest es un JSON servido por HTTPS. La fecha puede estar en cualquiera de estos campos:

```json
{"date": "2026-06-06"}
```

```json
{"last_backup": "2026-06-06T03:00:00Z"}
```

```json
{
  "date": "2026-06-06",
  "other_metadata": "irrelevante"
}
```

La fecha puede ser:
- `"YYYY-MM-DD"` (solo fecha, se asume 00:00:00 UTC)
- `"YYYY-MM-DDTHH:MM:SS"` (con hora, naive → se asume UTC)
- `"YYYY-MM-DDTHH:MM:SSZ"` (con hora y timezone Z)
- `"YYYY-MM-DDTHH:MM:SS+00:00"` (con timezone explícito)

`parse_iso_utc()` maneja todas estas variantes.

## Cómo generar el manifest

La idea es que tu sistema de backup **escriba un archivo JSON con la fecha del último backup** y lo sirva por HTTPS. Opciones comunes:

### Opción A: S3 + CloudFront

1. Después de cada backup, subir un archivo `last-backup.json` a S3:
   ```bash
   aws s3 cp - "s3://mi-bucket/last-backup.json" <<< "{\"date\": \"$(date -u +%Y-%m-%d)\"}"
   ```
2. Exponer el bucket o un prefix por HTTPS (S3 website endpoint, CloudFront, etc.).
3. Setear `BACKUP_MANIFEST=https://mi-cdn.com/last-backup.json`.

### Opción B: Tu propio endpoint

Si tenés un server que corre el backup, agregale un endpoint que devuelva el JSON:

```python
@app.route("/backup-status")
def backup_status():
    return {"date": last_backup_time.isoformat()}
```

Setear `BACKUP_MANIFEST=https://mi-server.com/backup-status`.

### Opción C: GitHub gist (truco)

1. Crear un gist público con un solo archivo `last-backup.json`.
2. Después de cada backup, actualizar el gist:
   ```bash
   gh gist edit <gist-id> last-backup.json -c "{\"date\": \"$(date -u +%Y-%m-%d)\"}"
   ```
3. Setear `BACKUP_MANIFEST=https://gist.githubusercontent.com/.../raw/last-backup.json`.

**No recomendado para producción** (gist es para código, no para state) pero sirve para prototipos.

## Implementación

Igual que los otros checks: usa `checks/security.py::safe_get_json()` y `parse_iso_utc()`. HTTPS-only, no redirects, no-leak vienen de ahí.

```python
data = security.safe_get_json(url, timeout=10)
if data is None:
    return True  # problema
date_str = data.get("date") or data.get("last_backup")
last = security.parse_iso_utc(date_str) if isinstance(date_str, str) else None
if last is None:
    return True  # problema
```

**`data.get("date") or data.get("last_backup")`:** prioriza el campo `date` (más común), fallback a `last_backup`. Si ninguno existe, devuelve `None` → problema.

**`isinstance(date_str, str)`:** protege contra el caso donde el JSON tiene `{"date": null}` o `{"date": 12345}`. En esos casos, devuelve `True` (problema).

## Casos de uso típicos

### Backup diario de base de datos

```bash
# .env
BACKUP_MANIFEST=https://mi-server.com/db-backup-status
BACKUP_MAX_AGE_DAYS=2
```

Si el backup diario falla, el manifest no se actualiza, y en 2 días el bit 6 se prende.

### Backup semanal de archivos

```bash
# .env
BACKUP_MANIFEST=https://mi-cdn.com/weekly-backup-status
BACKUP_MAX_AGE_DAYS=8
```

8 días le da 1 día de margen sobre el ciclo semanal de 7 días.

### Múltiples backups

Si tenés varios sistemas de backup, podés poner el más reciente en el manifest:

```python
# Tu script de orquestación
last_backup = min(
    get_db_backup_time(),
    get_files_backup_time(),
    get_config_backup_time(),
)
return {"date": last_backup.isoformat()}
```

Si **alguno** falla, el manifest tiene la fecha del más viejo, y eventualmente el bit 6 se prende.

## Limitaciones

- **No chequea que el archivo de backup exista.** Solo lee un manifest que dice cuándo fue el último backup. Un manifest mentiroso pasa este check.
- **No chequea tamaño ni integridad.** Un backup de 0 bytes pasa.
- **Un solo manifest.** No podés chequear múltiples sistemas de backup por separado. (Si necesitás eso, agregá un slot nuevo.)
- **Timeout fijo de 10s.** Si tu endpoint de manifest es lento, falla por timeout.

## Testing

```bash
# OK (fecha de hoy)
BACKUP_MANIFEST="https://gist.githubusercontent.com/.../raw/last.json" python alarm.py --dry-run
# Asumiendo que el JSON tiene "date": "<hoy>", bit 6 = 0

# Backup viejo (forzando manifest con fecha vieja)
# Subir un gist con "date": "2020-01-01"
# → bit 6 = 1

# Manifest malformado
BACKUP_MANIFEST="https://httpbin.org/html" python alarm.py --dry-run
# → bit 6 = 1 (no es JSON válido)
```
