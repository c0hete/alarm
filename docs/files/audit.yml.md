# `.github/workflows/audit.yml`

Workflow de GitHub Actions que audita las dependencias Python del proyecto en busca de vulnerabilidades conocidas. Corre semanalmente y reporta (falla el build) si hay vulns con fix disponible.

## Estructura

```yaml
name: audit

on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:

permissions: {}

jobs:
  pip-audit:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    env:
      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          persist-credentials: false
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Install pip-audit
        run: pip install pip-audit
      - name: Audit dependencies
        run: pip-audit --strict --requirement requirements.txt
```

## Triggers (`on:`)

### 1. `schedule` (cron)

```yaml
- cron: "0 6 * * 1"
```

Corre **cada lunes a las 06:00 UTC**.

- `0 6 * * 1` = minuto 0, hora 6, todos los días del mes, todos los meses, solo lunes
- En UTC (no la hora local del runner)

### 2. `workflow_dispatch`

Permite correr el audit manualmente:

```bash
gh workflow run audit.yml
```

Útil para:
- Auditar deps después de un cambio en `requirements.txt`
- Verificar el estado de seguridad antes de un deploy

## Permisos

```yaml
permissions: {}
```

**Cero permisos.** El workflow solo lee el repo (lo hace el checkout action con sus permisos default) y reporta. No necesita push ni ningún otro permiso.

## Pasos

### 1. Checkout

```yaml
- uses: actions/checkout@v4
  with:
    persist-credentials: false
```

Baja el código. `persist-credentials: false` porque este workflow no hace push.

### 2. Setup Python

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.11"
    cache: pip
```

Instala Python 3.11 y configura cache de pip.

### 3. Install pip-audit

```yaml
- run: pip install pip-audit
```

Instala la herramienta de auditoría. `pip-audit` consulta la base de datos de [PyPI Security Advisory](https://github.com/pypa/advisory-database) (alimentada por OSV.dev).

### 4. Audit dependencies

```yaml
- run: pip-audit --strict --requirement requirements.txt
```

**Flags:**
- `--strict`: exit code 1 si hay vulns con fix conocido. Sin este flag, solo reporta.
- `--requirement requirements.txt`: audita solo las deps listadas en `requirements.txt`. **No** audita transitive dependencies.

**Para auditar transitive deps también:**
```yaml
- run: pip-audit --strict
```

(sin `--requirement`)

## ¿Qué reporta?

`pip-audit` agrupa por paquete vulnerable y muestra:
- Nombre del paquete
- Versión instalada
- Versión con fix (si existe)
- ID del advisory (GHSA, CVE, etc.)
- Severidad (si está catalogada)

**Salida ejemplo:**
```
Name          Version  ID                  Fix Versions
------------  -------  ------------------  ------------
requests      2.25.0   PYSEC-2023-74      2.31.0
...
```

Si hay vulns con fix, exit 1 → workflow falla → email/notificación al owner.

## Diferencia con `daily.yml`

| Aspecto | `daily.yml` | `audit.yml` |
|---|---|---|
| Frecuencia | Cada 6h | Semanal (lunes) |
| Trigger primario | `schedule` + `workflow_dispatch` | `schedule` + `workflow_dispatch` |
| Permisos | `contents: write` (push) | `{}` (read-only) |
| Acción | Correr el alarm | Auditar deps |
| Frecuencia de costo | 4 runs/día | 1 run/semana |
| Output | Commit en el repo | Reporte en el run de Actions |

## Troubleshooting

### El workflow falla con vulns

1. Ver el log de la corrida específica
2. Identificar el paquete vulnerable
3. Opción A: actualizar a la versión con fix (`pip install --upgrade`)
4. Opción B: si no hay fix todavía, evaluar si la vuln aplica (algunas son de bajo impacto)
5. Commit + push

### Quiero que NO falle el workflow

Quitar `--strict`:
```yaml
- run: pip-audit --requirement requirements.txt
```

Pero entonces el audit solo reporta, no bloquea. **No recomendado** — el silenciamiento del audit es un anti-patrón.

### Quiero auditar transitive deps

Quitar `--requirement`:
```yaml
- run: pip-audit --strict
```

Más exhaustivo, pero más lento y más ruido.

## Cuándo actualizar `requirements.txt`

- Cuando `pip-audit` reporta una vuln
- Periódicamente (ej: mensual): `pip install --upgrade -r requirements.txt` y verificar que nada se rompe
- Antes de releases importantes

## Recursos

- [pip-audit docs](https://pypi.org/project/pip-audit/)
- [PyPI Advisory Database](https://github.com/pypa/advisory-database)
- [OSV.dev](https://osv.dev/) — fuente upstream de las advisories
