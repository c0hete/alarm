# alarm — Documentación

Heartbeat diario que ejecuta 8 checks y commitea un código binario de 8 bits. Si hay un `1`, hay un problema (sin revelar cuál).

## Tabla de contenidos

| Doc | Para qué sirve |
|---|---|
| [README.md](README.md) | Este archivo. Overview y navegación. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Diseño, componentes, flujo de datos. |
| [CONFIGURATION.md](CONFIGURATION.md) | Todas las variables de entorno y slots. |
| [OPERATIONS.md](OPERATIONS.md) | Cómo correr, debug, troubleshooting. |
| [SECURITY.md](SECURITY.md) | Modelo de seguridad y política de no-leak. |
| [files/](files/) | Documentación por archivo de código. |

## Qué es alarm

`alarm` es un **heartbeat silencioso** que se autocommitea todos los días en GitHub con un string de 8 caracteres (`0` o `1`). Cada carácter representa el resultado de un check de salud. El sistema:

1. Corre 8 checks (HTTP, SSL, GitHub status, backup, etc.)
2. Cada check devuelve `True` (problema) o `False` (OK)
3. Combina los 8 resultados en un código binario, ej. `00010000`
4. Escribe el código en `state/YYYY-MM-DD.txt`
5. Commitea y pushea al repo
6. El commit queda visible en el contribution graph de GitHub

## Por qué existe

Dos razones simultáneas:

1. **Racha de GitHub.** Commits diarios automáticos = contribution graph verde. Mantiene el streak vivo incluso en semanas tranquilas.
2. **Dead-man switch creativo.** Si aparece un `1` en un commit, sabés que algo falló. **El commit no dice qué** — tenés que ir a investigar. Es la divergencia intencional entre "tener señal" y "tener diagnóstico".

## Cómo se ve

```
state/2026-06-07.txt   →   00000000
state/2026-06-08.txt   →   00010000   ← bit 4 prendido = algo pasó
state/2026-06-09.txt   →   00000000
```

Commit message: `alarm: 2026-06-08 = 00010000`. Sin más.

## Quick start

```bash
# 1. Instalar
pip install -r requirements.txt

# 2. Configurar (opcional)
cp .env.example .env
# editar .env con las URLs/hosts a monitorear

# 3. Probar localmente
python alarm.py --dry-run        # solo calcula el código
python alarm.py --verbose        # muestra qué bit falló
python alarm.py                  # escribe state/ y commitea
```

Para correr en CI: el workflow `daily.yml` ya está configurado para correr a las 09:00 UTC.

## Slots (mapa del código binario)

```
bit 0  →  URL primaria
bit 1  →  URL secundaria
bit 2  →  URL terciaria
bit 3  →  SSL primaria
bit 4  →  SSL secundaria
bit 5  →  GitHub status API
bit 6  →  Backup freshness
bit 7  →  Custom API
```

El string se lee **izquierda-a-derecha** = bit 0 a bit 7. Por ejemplo, `00000010` significa "URL secundaria tiene problema".

Slots con la env var vacía quedan deshabilitados (devuelven `0`).

## Conceptos clave

- **Binario, no etiquetas.** El commit dice `00000010`, no "URL secundaria caída". La investigación es humana.
- **No-leak por diseño.** URLs, hostnames, mensajes de error y stack traces NUNCA aparecen en logs, ni en commits, ni en stderr público. Ver [SECURITY.md](SECURITY.md).
- **HTTPS-only.** Cualquier `http://` se rechaza antes de tocar la red.
- **Sin redirects.** Evita leakear a hosts inesperados.
- **8 bits = 256 estados.** Suficiente. Si se necesitan más, se rompe compatibilidad y se migra a 16.

## Estado del proyecto

- **Versión:** 1.0
- **Estado:** Vivo
- **URL:** https://github.com/c0hete/alarm
- **Trigger:** GitHub Actions cron 09:00 UTC
- **Lenguaje:** Python 3.11+
- **Dependencias:** `requests`, `urllib3` (todo lo demás es stdlib)

## Licencia

Privado. No es un proyecto open source.
