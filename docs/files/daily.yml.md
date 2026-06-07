# `.github/workflows/daily.yml`

Workflow de GitHub Actions que corre el alarm todos los días. Es el "trigger" que hace que el sistema sea automático.

## Estructura completa

```yaml
name: alarm

on:
  schedule:
    - cron: "0 9 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  heartbeat:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    env:
      URL_PRIMARY: ${{ secrets.URL_PRIMARY || '' }}
      URL_SECONDARY: ${{ secrets.URL_SECONDARY || '' }}
      URL_TERTIARY: ${{ secrets.URL_TERTIARY || '' }}
      SSL_PRIMARY: ${{ secrets.SSL_PRIMARY || '' }}
      SSL_SECONDARY: ${{ secrets.SSL_SECONDARY || '' }}
      BACKUP_MANIFEST: ${{ secrets.BACKUP_MANIFEST || '' }}
      BACKUP_MAX_AGE_DAYS: ${{ secrets.BACKUP_MAX_AGE_DAYS || '2' }}
      CUSTOM_API_URL: ${{ secrets.CUSTOM_API_URL || '' }}
      CHECK_TIMEOUT: ${{ secrets.CHECK_TIMEOUT || '10' }}
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          persist-credentials: false
          fetch-depth: 1

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install deps
        run: pip install -r requirements.txt

      - name: Mask secrets in logs
        run: |
          for v in URL_PRIMARY URL_SECONDARY URL_TERTIARY SSL_PRIMARY SSL_SECONDARY BACKUP_MANIFEST CUSTOM_API_URL; do
            val="${!v}"
            if [ -n "$val" ]; then
              echo "::add-mask::$val"
            fi
          done

      - name: Run alarm
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python alarm.py --quiet
```

## Triggers (`on:`)

```yaml
on:
  schedule:
    - cron: "0 9 * * *"
  workflow_dispatch:
```

Dos formas de disparar el workflow:

### 1. `schedule` (cron)

Corre automáticamente a las **09:00 UTC todos los días**.

Formato: `"M H DoM Mo DoW"` (minuto hora día-del-mes mes día-de-la-semana).
- `0 9 * * *` = minuto 0, hora 9, todos los días del mes, todos los meses, todos los días de la semana
- En UTC. **No** la hora local del runner.

**Importante:** GitHub Actions cron tiene una **cola de hasta ~15-30 minutos de delay**. A veces 09:00 UTC puede terminar corriendo a las 09:15. No es un cron en tiempo real.

Para cambiar la hora, editá esta línea. Para deshabilitar el cron pero dejar el workflow_dispatch, comentá la sección `schedule:`.

### 2. `workflow_dispatch`

Permite correr el workflow manualmente desde la UI o la CLI:

```bash
gh workflow run daily.yml
```

Útil para:
- Probar cambios sin esperar al cron
- Forzar un commit en una fecha específica
- Verificar que el setup funciona después de un cambio

## Permisos (`permissions:`)

```yaml
permissions:
  contents: write
```

Solo `contents: write` — el mínimo necesario para `git push`. **No** se otorgan:
- `packages` (no publica packages)
- `id-token` (no usa OIDC)
- `deployments` (no deploya)
- `actions` (no llama a otros workflows)

Esto limita el blast radius si el `GITHUB_TOKEN` se viera comprometido: un atacante solo podría pushear al repo.

## Job `heartbeat`

```yaml
jobs:
  heartbeat:
    runs-on: ubuntu-latest
    timeout-minutes: 5
```

- **`runs-on: ubuntu-latest`:** runner Linux. Necesario para `python` y `git` en CLI.
- **`timeout-minutes: 5`:** GitHub mata el job si pasa de 5 min. El alarm debería terminar en ~10-15 segundos, pero el timeout es defensa contra runs colgados.

### Env vars (job-level)

```yaml
env:
  URL_PRIMARY: ${{ secrets.URL_PRIMARY || '' }}
  ...
```

Estas son las env vars que `alarm.py` lee. La sintaxis `${{ secrets.X || 'default' }}` significa:
- Si el secret `X` está seteado, usá su valor
- Si no, usá el string después de `||`

**Importante:** GitHub Actions **no propaga GITHUB_TOKEN implícitamente** cuando hay un `env:` job-level. Por eso `GITHUB_TOKEN` se pasa explícitamente en el step "Run alarm" (no en el job env).

### Steps

#### 1. Checkout

```yaml
- uses: actions/checkout@v4
  with:
    persist-credentials: false
    fetch-depth: 1
```

- **Sin token:** el default usa el GITHUB_TOKEN implícito del workflow para clonar.
- **`persist-credentials: false`:** evita que el token quede en `.git/config` después del checkout. El script lo re-inyecta via `git remote set-url` solo cuando lo necesita.
- **`fetch-depth: 1`:** clona solo el último commit. Más rápido que el historial completo (que no necesitamos para este workflow).

#### 2. Setup Python

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.11"
    cache: pip
```

Instala Python 3.11 y configura cache de pip (acelera runs subsiguientes).

#### 3. Install deps

```yaml
- run: pip install -r requirements.txt
```

Instala `requests` y `urllib3`. Toma ~5-10 segundos la primera vez, <1s con cache.

#### 4. Mask secrets in logs

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

Para cada env var que tenga un valor, emite un comando `::add-mask::VALUE`. GitHub Actions registra ese valor y **lo reemplaza por `***`** en cualquier log que se imprima después.

**Defense-in-depth:** si por algún bug el script imprimiera un secret, queda enmascarado en el log público.

**Limitación:** solo enmascara valores **completos**. Si el script imprimiera un substring o una variante del secret, no se enmascara. Por eso la política real es **nunca imprimir secrets**, no confiar en el mask.

#### 5. Run alarm

```yaml
- name: Run alarm
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: python alarm.py --quiet
```

- **Step-level `env: GITHUB_TOKEN:`** pasa el token al script.
- **`--quiet`:** cero output. El script hace todo el trabajo (checks, write state, commit, push) sin imprimir nada.

## Variables de entorno disponibles para el script

Al ejecutar `python alarm.py --quiet`, las env vars que el script ve son:

| Variable | Origen | Descripción |
|---|---|---|
| `URL_PRIMARY` | `secrets.URL_PRIMARY \|\| ''` | Slot 0 |
| `URL_SECONDARY` | `secrets.URL_SECONDARY \|\| ''` | Slot 1 |
| `URL_TERTIARY` | `secrets.URL_TERTIARY \|\| ''` | Slot 2 |
| `SSL_PRIMARY` | `secrets.SSL_PRIMARY \|\| ''` | Slot 3 |
| `SSL_SECONDARY` | `secrets.SSL_SECONDARY \|\| ''` | Slot 4 |
| `BACKUP_MANIFEST` | `secrets.BACKUP_MANIFEST \|\| ''` | Slot 6 |
| `BACKUP_MAX_AGE_DAYS` | `secrets.BACKUP_MAX_AGE_DAYS \|\| '2'` | Default 2 |
| `CUSTOM_API_URL` | `secrets.CUSTOM_API_URL \|\| ''` | Slot 7 |
| `CHECK_TIMEOUT` | `secrets.CHECK_TIMEOUT \|\| '10'` | Default 10s |
| `GITHUB_TOKEN` | `${{ secrets.GITHUB_TOKEN }}` | Para `git push` |
| `GITHUB_REPOSITORY` | (implícito) | `c0hete/alarm` |
| `GITHUB_ACTIONS` | (implícito) | `true` |
| `RUNNER_OS` | (implícito) | `Linux` |

## Configurar secrets

Para setear las env vars en CI:

```bash
gh secret set URL_SECONDARY --body "https://hub.tu-dominio.cl"
gh secret set SSL_SECONDARY --body "hub.tu-dominio.cl"
gh secret set BACKUP_MANIFEST --body "https://s3.../last.json"
gh secret set BACKUP_MAX_AGE_DAYS --body "2"
gh secret set CUSTOM_API_URL --body "https://api.x.com/health"
gh secret set CHECK_TIMEOUT --body "15"
```

O desde la UI: https://github.com/c0hete/alarm/settings/secrets/actions → "New repository secret".

**GITHUB_TOKEN no se setea manualmente** — GitHub Actions lo provee automáticamente.

## Cambiar el schedule

```yaml
schedule:
  - cron: "0 9 * * *"   # ← cambiar esto
```

Formato cron de GitHub Actions:
```
*    *    *    *    *
│    │    │    │    │
│    │    │    │    └─ día de la semana (0-6, 0=domingo)
│    │    │    └────── mes (1-12)
│    │    └─────────── día del mes (1-31)
│    └──────────────── hora (0-23)
└───────────────────── minuto (0-59)
```

**Siempre en UTC.** Para Chile (UTC-3 / UTC-4 con DST):
- 09:00 UTC = 06:00 CLT (invierno) o 05:00 CLST (verano)
- 12:00 UTC = 09:00 CLT (invierno) o 08:00 CLST (verano)

## Troubleshooting

### El workflow no corre a la hora

- Verificar: https://github.com/c0hete/alarm/actions
- Cron puede tener delay de 15-30 min. No es un cron en tiempo real.
- Si está deshabilitado (Actions deshabilitadas en Settings), no corre.

### El step "Run alarm" falla

- Ver los logs de la corrida específica
- Temporalmente cambiar `--quiet` por `--verbose` para ver el error
- Recordar **revertir** el cambio antes de commitear de nuevo

### El commit se hace localmente pero no se pushea

- **GITHUB_TOKEN ausente:** verificar que el step "Run alarm" tiene `env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`
- **Permisos insuficientes:** verificar que el workflow tiene `permissions: contents: write`
- **Token expirado:** los GITHUB_TOKEN expiran al final de cada job. No debería ser un problema dentro de un job, pero si se usan en steps muy largos, podrían expirar.
