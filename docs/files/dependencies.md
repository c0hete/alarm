# Archivos de dependencias y configuración

Este documento cubre los archivos de configuración del proyecto que no son código Python ni YAML de Actions: `.env.example`, `requirements.txt`, y `.gitignore`.

## `.env.example`

Template con las variables de entorno que el alarm reconoce. **No se commitea el `.env` real** (está en `.gitignore`).

### Contenido

```bash
# alarm config — copiar a .env y editar. NO commitear .env real.
# Vacío = slot deshabilitado (bit queda en 0).

# Bit 0: URL primaria (default iacode.cl)
URL_PRIMARY=https://iacode.cl

# Bit 1: URL secundaria
URL_SECONDARY=

# Bit 2: URL terciaria
URL_TERTIARY=

# Bit 3: SSL primaria (hostname sin https://)
SSL_PRIMARY=iacode.cl

# Bit 4: SSL secundaria
SSL_SECONDARY=

# Bit 5: GitHub status API (siempre activo, no requiere config)

# Bit 6: Backup freshness
# JSON con {"date":"YYYY-MM-DD"} o {"last_backup":"YYYY-MM-DD"}
BACKUP_MANIFEST=
BACKUP_MAX_AGE_DAYS=2

# Bit 7: Custom API (cualquier endpoint que devuelva 2xx)
CUSTOM_API_URL=

# Timeout de checks HTTP (segundos)
CHECK_TIMEOUT=10
```

### Uso

```bash
cp .env.example .env
# editar .env
python alarm.py --dry-run
```

### Comentarios y convenciones

- Cada variable está comentada con su **bit** y su **significado**
- "Vacío = deshabilitado" — convención para slots opcionales
- `URL_PRIMARY` y `SSL_PRIMARY` tienen defaults razonables apuntando a `iacode.cl` (la app principal del usuario)
- Los demás slots arrancan vacíos, indicando que el usuario tiene que decidir qué monitorear

### Por qué los defaults son `iacode.cl`

El usuario tiene una app llamada `iacode` corriendo en `https://iacode.cl`. Es un default razonable para `URL_PRIMARY` y `SSL_PRIMARY`: el alarm siempre tiene ALGO que monitorear out of the box. El usuario puede cambiarlo a lo que quiera.

### Seguridad

- El archivo **no contiene secrets reales**. Solo defaults públicos.
- Está en el repo a propósito — es la documentación de la configuración esperada.
- El `.env` real (con valores sensibles) está en `.gitignore`.

---

## `requirements.txt`

Dependencias Python del proyecto.

### Contenido

```
requests>=2.31.0
urllib3>=2.0.0
```

### `requests`

HTTP client. Usado por `checks/security.py::safe_request()` y `safe_get_json()`.

- **Versión mínima:** 2.31.0 (de agosto 2023). Es la primera que tiene el fix para CVE-2023-32681.
- **Por qué pinned a `>=` y no `==`:** queremos fixes de seguridad automáticos.
- **Por qué no usar `urllib.request` de stdlib:** `requests` tiene mejor API, mejor manejo de SSL, y más fácil de mockear para testing.

### `urllib3`

HTTP client底层 (la lib sobre la que `requests` se apoya). Lo listamos **explícitamente** porque:

1. `urllib3.disable_warnings()` se llama desde `checks/security.py`. Si en el futuro `requests` cambia a otra lib, queremos control sobre este import.
2. Para tener un piso de versión que sepa silenciar los warnings que necesitamos.

### ¿Por qué no más deps?

El proyecto deliberadamente usa **solo lo mínimo**:

| Necesidad | Lib usada |
|---|---|
| HTTP | `requests` |
| SSL check | stdlib `ssl`, `socket` |
| Date parsing | stdlib `datetime` |
| URL parsing | stdlib `urllib.parse` |
| CLI args | stdlib `argparse` |
| Subprocess | stdlib `subprocess` |
| Logging | stdlib `logging` |
| Env files | Custom parser (no `python-dotenv`) |

**Por qué no `python-dotenv`:** es una dep más para algo que son 10 líneas de código. Ver `alarm.py::load_dotenv()`.

**Por qué no `cryptography`:** stdlib `ssl` es suficiente para el check de cert expiry. `cryptography` agregaría una dep pesada para nada.

**Por qué no `httpx` o `aiohttp`:** no necesitamos async. El alarm corre una vez al día, no hay concurrencia.

### Instalar

```bash
pip install -r requirements.txt
```

### Actualizar

```bash
pip install --upgrade -r requirements.txt
```

Si hay breaking changes, ajustar el código correspondiente (probablemente en `checks/security.py`).

---

## `.gitignore`

Archivos y directorios que git no trackea.

### Contenido

```
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.env
.DS_Store
Thumbs.db
```

### Por qué cada entrada

| Patrón | Razón |
|---|---|
| `__pycache__/` | Cache de Python. Se regenera automáticamente. No aporta al repo. |
| `*.py[cod]` | `.pyc`, `.pyd`, `.pyo` — bytecode compilado. |
| `*.egg-info/` | Metadata de paquetes. Generada por setuptools al instalar. |
| `.venv/`, `venv/` | Entornos virtuales. Pesados, específicos a la máquina. |
| `.env` | **Secrets y config local.** Crítico que NO se commitee. |
| `.DS_Store` | Metadata de macOS. |
| `Thumbs.db` | Metadata de Windows. |

### El caso especial de `.env`

```gitignore
.env
```

El `.env` contiene las env vars reales, que pueden incluir URLs privadas, hostnames, o paths a manifests con URLs firmadas. **Nunca** debe commiteare.

**`alarm.py::load_dotenv()` lo busca en `ROOT / ".env"`.** Si no existe, no hace nada (caso normal en CI).

### El caso especial de `state/`

**Importante:** `state/` **NO** está en `.gitignore`. Es el directorio que el alarm commitea con los códigos binarios diarios. Si lo ignoráramos, el `git add state/` no stagearía nada y no habría commit. (Esto fue un bug temprano del proyecto que ya está arreglado.)

### Verificar que `.env` no se commitea

```bash
git check-ignore .env
# → .env  (si dice esto, está bien ignorado)
```

Si devuelve código 0 y el path, está ignorado. Si no devuelve nada, hay un problema.

### Si commiteaste `.env` por accidente

1. **Inmediato:** rotar TODOS los secrets que estaban en ese `.env` (URLs firmadas, etc.).
2. `git rm --cached .env` para sacarlo del tracking.
3. Verificar que `.env` está en `.gitignore`.
4. `git commit -m "fix: untrack .env"`.
5. `git push`.
6. **Importante:** el archivo sigue en el historial de git. Para purgarlo, usar `git filter-repo` o BFG Repo-Cleaner. Es una operación destructiva — pedir ayuda si no estás seguro.

---

## Archivos no documentados individualmente

- `PROYECTO.md` (raíz) — visión y decisiones del proyecto. Ver [../PROYECTO.md](../../PROYECTO.md).
- `README.md` (raíz) — quick start. Ver [../README.md](../../README.md).
