# Arquitectura

## Vista de componentes

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions (cron 09:00 UTC)          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  .github/workflows/daily.yml                         │   │
│  │  1. Checkout                                         │   │
│  │  2. Setup Python                                     │   │
│  │  3. Install deps                                     │   │
│  │  4. Mask secrets in logs                             │   │
│  │  5. Run alarm.py --quiet  ◄────────────────────┐    │   │
│  │  6. Cleanup                                    │    │   │
│  └────────────────────────────────────────────────┼────┘   │
└─────────────────────────────────────────────────┼───────┘
                                                  │
                                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                      alarm.py (entry)                        │
│                                                              │
│  load_dotenv()                                               │
│       │                                                      │
│       ▼                                                      │
│  build_registry(timeout)  ◄── checks/base.py                 │
│       │                                                      │
│       ▼                                                      │
│  for each Check: execute()  ◄── checks/<each>.py             │
│       │                       (delegan en                    │
│       ▼                        checks/security.py)          │
│  assemble_code()  → "ABCDEFGH"                               │
│       │                                                      │
│       ▼                                                      │
│  write_state()  → state/YYYY-MM-DD.txt                       │
│       │                                                      │
│       ▼                                                      │
│  configure_push_auth()  (si GITHUB_TOKEN en env)             │
│       │                                                      │
│       ▼                                                      │
│  git_silent("add")                                           │
│  git_silent("commit")                                        │
│  git_silent("push")                                          │
└─────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                          ┌───────────────┐
                          │ GitHub remote │
                          │  (commit)     │
                          └───────────────┘
```

## Módulos

```
alarm/
├── alarm.py              # Entry point. CLI, glue, git, main loop.
├── checks/
│   ├── __init__.py       # Re-exports Check + build_registry
│   ├── base.py           # Check dataclass + build_registry()
│   ├── security.py       # Helpers de bajo nivel (HTTPS, no-leak)
│   ├── http.py           # check_url() → slots 0, 1, 2, 7
│   ├── ssl_cert.py       # check_ssl() → slots 3, 4
│   ├── github_status.py  # check() → slot 5
│   └── backup.py         # check() → slot 6
└── .github/workflows/
    └── daily.yml         # GitHub Actions cron
```

### Dependencias entre módulos

```
alarm.py
  └─→ checks (paquete)
       ├─→ checks.base
       │    └─→ checks.http, checks.ssl_cert, checks.github_status, checks.backup
       ├─→ checks.security  (usado por todos los checks de arriba)
       └─→ checks.__init__  (re-exports)
```

`checks/security.py` es la **única dependencia compartida** entre todos los checks. Centraliza la política de no-leak y HTTPS.

## Flujo de datos (happy path)

1. **Cron dispara el workflow** a las 09:00 UTC.
2. **Checkout** baja el repo en un runner limpio (Ubuntu + Python 3.11).
3. **Install deps** instala `requests` + `urllib3`.
4. **Mask secrets** corre `::add-mask::` para que cualquier secret que aparezca en logs se muestre como `***`.
5. **Run alarm** ejecuta `python alarm.py --quiet` con `GITHUB_TOKEN` en env.
6. **`alarm.py` carga `.env`** (en CI no existe, así que usa solo process env).
7. **Build registry** arma 8 checks. Cada uno es un `Check` con `bit_index`, `name`, y una función `run()`.
8. **Execute** corre las 8 funciones en orden. Cada una devuelve `True` (problema) o `False` (OK). Cualquier excepción se silencia y se cuenta como problema.
9. **Assemble** convierte la lista de bools en un string de 8 chars: `0` o `1`.
10. **Write state** escribe `state/YYYY-MM-DD.txt` con el código.
11. **Configure push auth** reescribe la URL del remote para incluir el `GITHUB_TOKEN` (CI only). También limpia el `extraheader` de basic auth que deja `actions/checkout`.
12. **Git add** stagea `state/`.
13. **Git commit** con mensaje `alarm: YYYY-MM-DD = CODE`.
14. **Git push** al remote.
15. El commit aparece en https://github.com/c0hete/alarm y en el contribution graph.

## Decisiones de diseño

### Por qué 8 bits y no más

- Suficiente para las 5 categorías del requirement original (URLs, SSL, status, backup, custom).
- 1 byte es fácil de leer, copiar, y verificar a ojo.
- Migrar a 16 bits es solo cambiar `_MIN_DAYS`, la longitud del string, y la cantidad de `Check`s en el registry.

### Por qué GitHub Actions y no Windows Task Scheduler

- **No requiere la PC encendida.** El contribution graph cuenta igual.
- **Cero mantenimiento de infraestructura.** GitHub provee Python, runner, cron, secrets, logs.
- **Repo público = streak visible.** Si estuviera en una VM privada, el streak no contaría para GitHub.
- **Costo cero** para repos públicos (Actions minutes ilimitadas en plan free).

### Por qué commits por día y no por check

- Si cada check fuera un commit separado, en un día con todo OK tendrías 8 commits. Eso es **spam visual** y nadie lo quiere.
- Un commit por día con un código compacto preserva el streak sin inflar el log.
- El código binario es **autocontenido**: leyendo solo el archivo de hoy ya sabés el estado.

### Por qué `noreply.github.com` como autor

- Privacidad: el commit no lleva tu email personal.
- Claridad: si commiteás a mano a este repo, el autor real (`Jose Alvarado`) no se mezcla con el bot (`alarm`).
- `git log` muestra claramente "este commit lo hizo el alarm".

### Por qué no decir cuál check falló

Es la decisión central del producto. Razones:

- **Diseño intencional.** El alarm es un **detector**, no un **diagnosticador**. Si querés diagnóstico, abrí los archivos en `checks/`.
- **Evita leak en logs públicos.** El binario es lo único que se commitea. Si en el futuro se commitea más info, hay que re-pensar la privacidad.
- **Fuerza la disciplina de leer el código.** Si querés saber qué hace el slot 3, tenés que abrir `checks/ssl_cert.py`. Eso es bueno: te asegurás de que cada check sigue siendo relevante.

## Ciclo de vida de un commit

```
09:00 UTC  →  cron dispara el workflow
09:00:01   →  checkout + setup Python
09:00:05   →  install deps
09:00:10   →  mask secrets
09:00:11   →  python alarm.py --quiet
            ├─ load_dotenv (no hace nada en CI)
            ├─ build_registry → 8 checks
            ├─ execute 8 checks (~ 0.5-2s total)
            ├─ assemble "00000000"
            ├─ write state/2026-06-07.txt
            ├─ configure push auth (rewrite remote URL)
            ├─ git add state/
            ├─ git commit -m "alarm: ..."
            └─ git push
09:00:13   →  workflow done
            └─ commit visible en GitHub
```

Tiempo total: ~10-15 segundos. Dentro del budget de 5 min del `timeout-minutes`.
