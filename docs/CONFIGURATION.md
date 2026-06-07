# Configuración

Toda la configuración del alarm viene de **variables de entorno**. El archivo `.env` (local) o GitHub Secrets (CI) son las dos fuentes. Si una variable está vacía, su slot queda deshabilitado (devuelve `0`).

## Variables de entorno

### Slots de URL (0, 1, 2, 7)

| Variable | Default | Slot | Descripción |
|---|---|---|---|
| `URL_PRIMARY` | `https://iacode.cl` | 0 | URL primaria a monitorear. Devuelve `1` si no responde 2xx. |
| `URL_SECONDARY` | *(vacío)* | 1 | URL secundaria. Vacío = deshabilitado. |
| `URL_TERTIARY` | *(vacío)* | 2 | URL terciaria. Vacío = deshabilitado. |
| `CUSTOM_API_URL` | *(vacío)* | 7 | API arbitraria. Mismo comportamiento que las URLs. |

**Comportamiento:**
- HTTP 2xx (200-299) → `0` (OK)
- HTTP 3xx, 4xx, 5xx → `1` (problema)
- Timeout, connection error, DNS fail → `1` (problema)
- URL vacía o no-HTTPS → `1` (problema) **o** `0` si la env var está vacía (slot deshabilitado)

### Slots de SSL (3, 4)

| Variable | Default | Slot | Descripción |
|---|---|---|---|
| `SSL_PRIMARY` | `iacode.cl` | 3 | Hostname (sin `https://`) cuyo cert se valida. |
| `SSL_SECONDARY` | *(vacío)* | 4 | Idem. |

**Comportamiento:**
- Cert expira en ≥ 14 días → `0`
- Cert expira en < 14 días → `1`
- No se puede conectar / cert inválido → `1`
- Hostname vacío → `0` (slot deshabilitado)

### Otros slots

| Variable | Default | Slot | Descripción |
|---|---|---|---|
| *(ninguna)* | — | 5 | GitHub status API. Siempre activo. Devuelve `1` si indicator ≠ `none`. |
| `BACKUP_MANIFEST` | *(vacío)* | 6 | URL HTTPS a un JSON con `"date"` o `"last_backup"`. |
| `BACKUP_MAX_AGE_DAYS` | `2` | 6 | Días máximos de antigüedad del backup. |
| `GITHUB_TOKEN` | *(auto en CI)* | — | Token para `git push`. Solo lo usa el script en CI. |

### Globales

| Variable | Default | Descripción |
|---|---|---|
| `CHECK_TIMEOUT` | `10` | Timeout en segundos para todos los checks de red. |

## Asignación de bits

El string binario se lee **izquierda a derecha = bit 0 a bit 7**:

```
Posición:  0  1  2  3  4  5  6  7
           │  │  │  │  │  │  │  │
           ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼
          URL URL URL SSL SSL GH BK CUSTOM
          P   S   T   P   S   S  M  API
```

Ejemplo: `00000010` = bit 1 prendido = "URL secundaria tiene problema".

## Cómo agregar un nuevo check

1. Crear `checks/<nombre>.py` con una función:
   ```python
   def check() -> bool:
       """True = problema."""
       # lógica
       return False
   ```
2. Importar y registrar en `checks/base.py::build_registry()` con un `bit_index` único:
   ```python
   from . import mi_nuevo_check
   return [
       # ... checks existentes ...
       Check(8, "Mi nuevo check", mi_nuevo_check.check),  # ⚠️ bit 8 no entra en 1 byte
   ]
   ```
3. **Si superás 8 bits**, hay que migrar el formato a 2 bytes:
   - Cambiar `assemble_code` para producir 16 chars
   - Cambiar todos los `int` a 2 bytes
   - Actualizar el slot map en `PROYECTO.md` y `docs/CONFIGURATION.md`
4. Si el check usa URLs/SSL, **usar los helpers de `checks/security.py`** (HTTPS-only, no-leak).

## Cómo deshabilitar un check

Borrar o comentar la línea correspondiente en `checks/base.py::build_registry()`. **No** dejar la línea con un check que devuelva siempre `False` — eso ocupa un bit para nada y confunde al leer el código.

Si querés deshabilitar temporalmente sin tocar el registry: vaciar la env var correspondiente. La mayoría de los checks ya devuelven `0` cuando la env var está vacía.

## GitHub Secrets (CI)

Para que el workflow use configuración privada, setear en https://github.com/c0hete/alarm/settings/secrets/actions:

```bash
gh secret set URL_SECONDARY --body "https://hub.tu-dominio.cl"
gh secret set SSL_SECONDARY --body "hub.tu-dominio.cl"
gh secret set BACKUP_MANIFEST --body "https://s3.../last.json"
gh secret set CUSTOM_API_URL --body "https://api.x.com/health"
gh secret set CHECK_TIMEOUT --body "15"
```

`GITHUB_TOKEN` **no** se setea manualmente — GitHub Actions lo provee automáticamente al step que lo referencia con `${{ secrets.GITHUB_TOKEN }}`.

## `.env` local

Para desarrollo local, copiar `.env.example` a `.env` y editar:

```bash
cp .env.example .env
# editar .env
python alarm.py --dry-run
```

`.env` está en `.gitignore`, así que nunca se commitea.
