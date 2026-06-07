# Operaciones

## Setup inicial (una vez)

### 1. Clonar / crear repo

El repo es `c0hete/alarm` y ya está creado en GitHub. Para volver a crearlo desde cero:

```bash
mkdir alarm && cd alarm
git init -b main
# ... copiar archivos ...
gh repo create c0hete/alarm --public --source=. --remote=origin --push
```

### 2. Configurar `.env` local (opcional)

```bash
cp .env.example .env
# editar .env con tus URLs/hosts
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

Requiere Python 3.11+.

## Uso local

### Ver el código del día (sin commit)

```bash
python alarm.py --dry-run
```

Salida: una línea con 8 caracteres, ej. `00000000`.

### Ver el código + qué bit falló

```bash
python alarm.py --verbose
```

Salida en stderr:
```
  bit 0 [0]
  bit 1 [1]
  bit 2 [0]
  ...
```

**Importante:** `--verbose` muestra qué bit falló pero **NO** muestra la URL ni el hostname asociado. Por diseño.

### Modo silencioso (mismo que CI)

```bash
python alarm.py --quiet
```

Cero output. Solo exit code:
- `0` = OK
- `1` = falló (git push falló, o algún check no se pudo ejecutar)

### Corrida completa (escribe + commitea + pushea)

```bash
python alarm.py
```

Crea `state/YYYY-MM-DD.txt`, hace commit, push.

## Correr el workflow manualmente

```bash
gh workflow run daily.yml
```

O desde la UI: https://github.com/c0hete/alarm/actions/workflows/daily.yml → "Run workflow".

Útil para:
- Verificar que el cron sigue funcionando
- Probar cambios al workflow
- Forzar un commit en una fecha específica

## Ver el historial de estados

Los archivos `state/YYYY-MM-DD.txt` son el log completo:

```bash
# En GitHub
https://github.com/c0hete/alarm/tree/main/state

# Local
ls -la state/

# Ver solo los días con problemas (bit encendido)
grep -l '1' state/*.txt

# Contar días OK vs. con problemas
echo "OK: $(grep -L '1' state/*.txt | wc -l)"
echo "Problemas: $(grep -l '1' state/*.txt | wc -l)"
```

## Debug

### Testear un check específico

```bash
# Forzar un fallo en slot 0
URL_PRIMARY="https://httpbin.org/status/500" python alarm.py --verbose

# Forzar HTTPS inválido
URL_PRIMARY="http://example.com" python alarm.py --verbose
# bit 0 debe ser 1 (rechaza http://)

# Forzar DNS inválido
URL_SECONDARY="https://this-does-not-exist-12345.invalid/" python alarm.py --verbose
# bit 1 debe ser 1

# Forzar backup viejo
BACKUP_MANIFEST="https://httpbin.org/json" python alarm.py --verbose
# bit 6: depende del JSON que devuelva httpbin
```

### Ver por qué falló el push en CI

El workflow corre con `--quiet`, así que los errores de git no se ven. Para debug:

1. Temporal: cambiar `--quiet` por `--verbose` en `.github/workflows/daily.yml`
2. Commit + push
3. Correr el workflow
4. Ver los logs en la pestaña "Actions"
5. **Revertir** el cambio a `--quiet` antes de merge

### Validar la sintaxis sin correr

```bash
python -m py_compile alarm.py checks/*.py
```

### Testear que los helpers de seguridad funcionan

```bash
python -c "
from checks import security
# HTTPS-only
print(security.validate_https_url('https://example.com'))   # True
print(security.validate_https_url('http://example.com'))    # False
print(security.validate_https_url('https://'))              # False (no host)
"
```

## Troubleshooting

### "Mi commit no aparece en GitHub"

1. ¿El workflow corrió? Ver https://github.com/c0hete/alarm/actions
2. ¿Hay un `state/YYYY-MM-DD.txt` nuevo? Ver la pestaña "Commits"
3. ¿El código es siempre `00000000`? Probable que todas las env vars están vacías en CI. Configurar secrets.

### "El código tiene muchos 1s"

Eso significa que varios checks están fallando. Posibles causas:
- **URL primaria inaccesible** desde los runners de GH Actions. Probar `python alarm.py --verbose` local con la misma URL.
- **Timeout muy bajo**. Subir `CHECK_TIMEOUT` (default 10s).
- **Cert SSL expira pronto**. Revisar con `openssl s_client -connect iacode.cl:443` o similar.

### "El push falla con 401/403"

Probable que `GITHUB_TOKEN` no esté llegando al step. Ver:
1. En `.github/workflows/daily.yml`, el step "Run alarm" tiene que tener `env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`.
2. El workflow `permissions: contents: write` está seteado.

### "El commit no dice cuál check falló"

Es **por diseño**. Ver [SECURITY.md](SECURITY.md) y [PROYECTO.md](../PROYECTO.md). El alarm es un detector, no un diagnosticador. Si necesitás saber cuál es, abrir `checks/` y revisar el código de cada slot.

### "Los archivos `state/` no se commitean"

Verificar que `state/` no esté en `.gitignore`. (Ya lo removimos en la versión actual — debería funcionar.)

### "El `state/YYYY-MM-DD.txt` se commitea pero vacío"

Probable que el script falló antes de escribir. Ver:
- `python alarm.py --verbose` local
- Logs del workflow en GitHub Actions

## Actualizar el proyecto

```bash
git pull
pip install -r requirements.txt --upgrade
```

No hay migrations. Cambios al registry de checks son compatibles hacia atrás (mientras se mantenga 8 bits).

## Cron

El workflow corre a las **09:00 UTC** todos los días. Para cambiar:

1. Editar `.github/workflows/daily.yml`, línea `cron:`.
2. Formato: `"M H * * *"` (minuto hora día-mes mes día-semana).
3. Commit + push.

GitHub Actions cron usa UTC. **No** es la hora local del runner.

## Monitoreo de la app misma

El alarm **no se monitorea a sí mismo**. Si GitHub Actions se cae o el runner falla, el commit simplemente no se hace y la racha se rompe. Esto es intencional:

- Si la racha se rompe, te das cuenta de que "algo" pasó.
- No hay un nivel más abajo que vigile al alarm. Would be turtles all the way down.

Si querés un watchdog externo, opciones:
- Un simple cron en tu PC con `gh run list` y un push manual
- Un servicio de uptime externo (UptimeRobot, etc.) que te avise por email si el repo no tiene commit en 24h
