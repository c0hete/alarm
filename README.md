# alarm

Heartbeat cada 6h. Cada corrida deja un commit con un código binario de 8 bits. Si hay un `1`, hay un problema. **El repo no dice cuál.**

## Setup (una vez)

```bash
# 1. Crear repo en GitHub (público, para que cuente el contribution graph)
gh repo create c0hete/alarm --public --source=. --remote=origin --push

# 2. Habilitar Actions
# Settings → Actions → Allow all actions

# 3. (Opcional) Setear secretos si querés checks privados
gh secret set URL_SECONDARY --body "https://hub.tu-dominio.cl"
gh secret set SSL_SECONDARY --body "hub.tu-dominio.cl"
gh secret set BACKUP_MANIFEST --body "https://..."
gh secret set CUSTOM_API_URL  --body "https://api.example.com/health"

# 4. (Opcional) Forzar la primera corrida
gh workflow run daily.yml
```

## Cómo se ve

Cada día se commitea un archivo:

```
state/2026-06-06.txt   →   00000000
state/2026-06-07.txt   →   00000010   ← bit 1 prendido = algo pasó
state/2026-06-08.txt   →   00000000
```

El commit message es `alarm: 2026-06-07 = 00000010`.

**No hay log, no hay tabla, no hay "qué falló".** Si ves un `1`, abrís `checks/` y revisás a mano.

## Uso local

```bash
pip install -r requirements.txt
cp .env.example .env       # editar valores

# Corrida normal: imprime solo el código binario en stdout
python alarm.py

# Corrida silenciosa (mismo comportamiento que en CI)
python alarm.py --quiet

# Corrida con debug (muestra qué bit falló, sin URLs ni hosts)
python alarm.py --verbose

# Solo ver el código, sin commit
python alarm.py --dry-run
```

## Configuración (`.env` o GitHub Secrets)

| Var | Ejemplo | Qué hace |
|---|---|---|
| `URL_PRIMARY` | `https://iacode.cl` | HTTP 2xx = OK |
| `URL_SECONDARY` | `https://hub.tu-dominio.cl` | HTTP 2xx = OK |
| `URL_TERTIARY` | `https://...` | HTTP 2xx = OK |
| `SSL_PRIMARY` | `iacode.cl` | cert válido ≥14 días = OK |
| `SSL_SECONDARY` | `hub.tu-dominio.cl` | idem |
| `BACKUP_MANIFEST` | `https://s3.../last.json` | JSON con `{"date":"2026-06-05"}`, <N días = OK |
| `BACKUP_MAX_AGE_DAYS` | `2` | default 2 |
| `CUSTOM_API_URL` | `https://api.x.com/health` | HTTP 2xx = OK |
| `GITHUB_TOKEN` | (auto en CI) | opcional, para subir rate limit en status API |

Variables vacías → bit correspondiente queda en `0` (slot deshabilitado).

## Cron

`.github/workflows/daily.yml` corre **cada 6 horas** (00:00, 06:00, 12:00, 18:00 UTC). Editable.

## Filosofía

> El sistema vigila por vos. Cuando algo se rompe, no te dice qué — te avisa que algo se rompió.
> La investigación es humana.

Inspirado en alarm clocks, canaries in coal mines, y el contribution graph de GitHub.

## Seguridad

El alarm corre en GitHub Actions y el repo es público (para que el contribution graph cuente). Por diseño, **nada de lo que monitorea puede terminar en los logs públicos**:

- **HTTPS-only.** `http://` se rechaza sin tocar la red.
- **No redirects.** Evita leakear a hosts inesperados.
- **Excepciones silenciosas.** Todo fallo se reporta como `1` sin imprimir URL, hostname, ni mensaje de error.
- **Output mínimo.** Por defecto, el único stdout es el código binario (8 chars). En CI se usa `--quiet` (cero output).
- **Modo `--verbose`:** muestra qué bit falló (`bit 3 [1]`), pero nunca la URL ni el hostname asociado.
- **Secretos enmascarados** con `::add-mask::` en `.github/workflows/daily.yml` (defense-in-depth).
- **`persist-credentials: false`** en el checkout: el token de push no queda persistido.
- **Permisos mínimos del workflow:** `contents: write` solamente.

### Qué se commitea

- El archivo `state/YYYY-MM-DD.txt` con un string de 8 caracteres (`0` o `1`).
- El mensaje `alarm: YYYY-MM-DD = 00000000`.

### Qué NO se commitea

- URLs, hostnames, ni paths de los recursos chequeados.
- Mensajes de error, stack traces, ni logs de librerías.
- Valores de variables de entorno ni secretos.
- Identidad del commit author: usa `alarm@users.noreply.github.com` (noreply).
