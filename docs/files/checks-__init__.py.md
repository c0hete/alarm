# `checks/__init__.py`

Punto de entrada del paquete `checks`. Re-exporta las clases y funciones que `alarm.py` necesita.

## Contenido

```python
"""Re-exports para checks/."""

from .base import Check, build_registry

__all__ = ["Check", "build_registry"]
```

Solo dos exports:
- `Check` — la dataclass que representa un check individual (ver [checks-base.py.md](checks-base.py.md))
- `build_registry` — la función que arma la lista de 8 checks (ver [checks-base.py.md](checks-base.py.md))

## Por qué este archivo existe

Patrón estándar de paquetes Python: el `__init__.py` define la **API pública** del paquete. El usuario del paquete (en este caso, `alarm.py`) hace:

```python
from checks import build_registry
```

Y no necesita saber en qué submódulo vive (`checks.base`). Esto permite **refactorizar** la estructura interna del paquete sin tocar a los callers.

Por ejemplo, si en el futuro querés mover `Check` y `build_registry` a un módulo `registry.py`, solo cambiás este `__init__.py`:

```python
from .registry import Check, build_registry
```

Y `alarm.py` sigue intacto.

## `__all__`

```python
__all__ = ["Check", "build_registry"]
```

Define qué se exporta con `from checks import *`. En este proyecto no se usa `import *`, pero `__all__` es documentación implícita de la API pública. También afecta a los linters (mypy, pyright, ruff) que usan `__all__` para resolver imports.

## Submódulos del paquete

Este `__init__.py` **no importa los submódulos directamente** (no hay `from . import http`). Los submódulos se importan **perezosamente** dentro de `build_registry()` en `base.py`:

```python
def build_registry(timeout: int) -> list[Check]:
    from . import http, ssl_cert, github_status, backup
    ...
```

**Razón:** si un submódulo tiene un import roto (por ejemplo, falta una dep), el error se levanta cuando se llama a `build_registry()`, no cuando se importa el paquete. Esto permite que `alarm.py` se importe (y se ejecute) aunque haya un problema con un check específico.

## Testing

```python
# Verificar imports
from checks import Check, build_registry
print(Check)        # <class 'checks.base.Check'>
print(build_registry)  # <function build_registry at ...>

# Verificar que registry tiene 8 checks
registry = build_registry(timeout=10)
assert len(registry) == 8
assert [c.bit_index for c in registry] == list(range(8))
```

## ¿Por qué no un `__init__.py` más rico?

En algunos paquetes, el `__init__.py` ejecuta lógica al import (por ejemplo, leer un archivo de config, registrar handlers, etc.). **En este proyecto no se hace** por dos razones:

1. **Side effects al import son sorpresa.** Si importás `checks`, ¿qué se ejecuta? Mejor que sea explícito: llamás a `build_registry()` y se ejecuta.
2. **Los warnings se suprimen en `alarm.py`, no en `checks`.** El módulo `checks/security.py` sí tiene un side effect (`urllib3.disable_warnings`), pero ese es tolerable y específico a la lib que estamos silenciando.
