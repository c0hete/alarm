# `checks/base.py`

Define la clase `Check` y la función `build_registry()`. Es el **punto de extensión** del proyecto: agregar un check nuevo = agregar una entrada al registry.

## `Check` (dataclass)

```python
@dataclass
class Check:
    bit_index: int
    name: str
    run: Callable[[], bool]
```

Un check individual del registry.

| Campo | Tipo | Descripción |
|---|---|---|
| `bit_index` | `int` | Posición en el código binario (0 = LSB a la izquierda, 7 = MSB a la derecha). |
| `name` | `str` | Nombre humano, **solo se muestra en modo `--verbose`**. No debe contener URLs ni hostnames. |
| `run` | `() -> bool` | Función que ejecuta el check. Devuelve `True` si hay problema, `False` si OK. |

### Método `execute()`

```python
def execute(self) -> bool:
    try:
        return bool(self.run())
    except Exception:
        return True
```

Envuelve la ejecución del check con un try/except amplio. **Cualquier excepción** → `True` (= problema). Esto enforce la política de no-leak: un error en un check se reporta como problema, no como stack trace.

**Excepciones no atrapadas:** `KeyboardInterrupt`, `SystemExit`, `MemoryError`, `RecursionError` (heredan de `BaseException`, no de `Exception`). Estas se propagan para terminar el script limpio.

### Uso típico

```python
def check_disk_space() -> bool:
    # lógica
    return False  # OK

registry.append(Check(bit_index=0, name="Espacio en disco", run=check_disk_space))
```

## `build_registry(timeout: int) -> list[Check]`

Construye la lista de checks en orden de bit. Cada entrada es un `Check` con su `bit_index`, `name`, y `run`. Aplica el filtro de la env var `CHECKS` (si está seteada) antes de devolver.

```python
def build_registry(timeout: int) -> list[Check]:
    from . import http, ssl_cert, github_status, backup

    all_checks = [
        Check(0, f"URL primaria (timeout={timeout}s)", lambda: http.check_url("URL_PRIMARY", timeout)),
        Check(1, "URL secundaria", lambda: http.check_url("URL_SECONDARY", timeout)),
        Check(2, "URL terciaria", lambda: http.check_url("URL_TERTIARY", timeout)),
        Check(3, "SSL primaria (>=14d)", lambda: ssl_cert.check_ssl("SSL_PRIMARY")),
        Check(4, "SSL secundaria", lambda: ssl_cert.check_ssl("SSL_SECONDARY")),
        Check(5, "GitHub status API", github_status.check),
        Check(6, "Backup freshness", backup.check),
        Check(7, "Custom API", lambda: http.check_url("CUSTOM_API_URL", timeout)),
    ]
    return _filter_by_env(all_checks)
```

### Por qué `from . import ...` dentro de la función

Para hacer los imports **perezosos**. Si un módulo de check tiene un import roto (por ejemplo, falta `requests`), el error se levanta solo cuando `build_registry` se llama, no cuando se importa el módulo. Esto permite que `alarm.py` se importe aunque haya un problema con un check específico.

### Por qué lambdas

Cada check tiene una firma distinta:
- `http.check_url(env_var, timeout)` → 2 args
- `ssl_cert.check_ssl(env_var)` → 1 arg
- `github_status.check()` → 0 args

Los lambdas normalizan la firma a `() -> bool` para que `Check.run` sea uniforme.

### Orden = posición en el código

La lista está ordenada por `bit_index` ascendente. El orden es importante porque `assemble_code()` en `alarm.py` itera la lista y mapea posición 0 → carácter 0 del string, etc.

## Extensibilidad

### Agregar un check nuevo

1. Crear `checks/mi_check.py`:
   ```python
   def check() -> bool:
       """True = problema."""
       return False
   ```

2. Agregar al registry en `build_registry()`:
   ```python
   from . import mi_check
   return [
       # ... existentes ...
       Check(8, "Mi check", mi_check.check),  # ⚠️ bit 8 no entra en 1 byte
   ]
   ```

3. **Si superás 8 bits**, hay que migrar el formato a 2 bytes. Ver [CONFIGURATION.md](../CONFIGURATION.md#cómo-agregar-un-nuevo-check).

### Reordenar bits

Cambiar el orden en la lista. **Cuidado:** esto cambia el significado de los códigos. Si ya hay commits en producción, los códigos antiguos van a significar cosas diferentes.

Recomendación: mantener el orden estable. Si necesitás reasignar, hacerlo en un commit aislado y documentarlo en el journal.

### Deshabilitar temporalmente

Borrar (no comentar) la línea del Check. Dejarla comentada confunde al lector. Para "apagar" el check sin tocar el registry, vaciar la env var correspondiente (la mayoría de los checks devuelven `False` cuando su env var está vacía).

### Filtrar subset (`CHECKS` env var)

`build_registry()` aplica `_filter_by_env()` antes de devolver. Esto permite correr solo un subset de checks sin tocar código.

**Env var `CHECKS`:**
- `0,3` → solo slots 0 y 3
- `URL,SSL` → todos los checks cuyo name contenga "URL" o "SSL"
- `backup` → solo el check de backup
- Vacío → todos los 8 (default)

**CLI override `--only=...`:** tiene prioridad sobre la env var. El script setea `os.environ["CHECKS"]` antes de llamar a `build_registry()`.

**Casos de uso:**
- Reducir requests: `CHECKS=0,3` para correr solo URL + SSL
- Testing: `python alarm.py --only=0 --verbose` para ver solo el slot 0
- Debugging: aislar un check problemático

## Constantes y dependencias

- **Imports:** `dataclasses.dataclass`, `typing.Callable`
- **Imports lazy (dentro de `build_registry`):** `checks.http`, `checks.ssl_cert`, `checks.github_status`, `checks.backup`

## Testing

```python
# Test manual del Check dataclass
from checks.base import Check

def test_check_returns_true_for_problem():
    c = Check(0, "test", lambda: True)
    assert c.execute() is True

def test_check_returns_false_for_ok():
    c = Check(0, "test", lambda: False)
    assert c.execute() is False

def test_check_swallows_exception():
    def boom():
        raise ValueError("nope")
    c = Check(0, "test", boom)
    assert c.execute() is True  # Exception → True (problema)
```
