# `checks/github_status.py`

Check del status page público de GitHub. Usado por **slot 5** del código binario.

## `check() -> bool`

```python
URL = "https://www.githubstatus.com/api/v2/status.json"

def check() -> bool:
    data = security.safe_get_json(URL, timeout=10)
    if data is None:
        return True
    indicator = data.get("status", {}).get("indicator", "unknown")
    return indicator != "none"
```

Devuelve `True` si hay problema.

| Caso | Resultado |
|---|---|
| `status.indicator == "none"` | `False` (todo OK) |
| `status.indicator` en `["minor", "major", "critical", "maintenance"]` | `True` (problema) |
| Cualquier error de red / parseo | `True` (problema) |

## ¿Por qué este check existe?

Si GitHub Actions está caído o GitHub tiene un outage, el **workflow del alarm no puede correr**. Pero en el slot 5, **no se chequea el status de GitHub Actions**, se chequea el status de **GitHub como producto** (la plataforma general: web, API, git operations, etc.).

En la práctica, el indicador `"none"` significa que no hay incidentes activos en la plataforma. `"minor"` es un problema menor, `"major"` es un problema serio, `"critical"` es un outage.

**Es un proxy de "GitHub está sano"**, no de "Actions puede correr". Si Actions está caído pero el resto de GitHub está OK, el bit 5 va a estar en `0` aunque no podamos commitear. Pero el resto de los slots deberían seguir funcionando (URLs externas, SSL, etc.) — eso te da la señal.

## Slots que usan este check

| Slot | Env var | Notas |
|---|---|---|
| 5 | *(ninguna)* | Siempre activo. No configurable. |

No hay env var para deshabilitar este check. Si querés apagarlo, comentá la línea en `checks/base.py::build_registry()`.

## La URL

`https://www.githubstatus.com/api/v2/status.json` es la **API pública** de GitHub Status, mantenida por Atlassian Statuspage. No requiere auth, no tiene rate limit estricto, y devuelve JSON.

**Estructura de la respuesta (relevante):**

```json
{
  "status": {
    "indicator": "none",
    "description": "All Systems Operational"
  },
  ...
}
```

El campo `indicator` puede ser:
- `"none"` — todo OK
- `"minor"` — problema menor
- `"major"` — problema mayor
- `"critical"` — outage
- `"maintenance"` — mantenimiento programado

El check rechaza `"none"` y todo lo demás cuenta como problema. Esto es **deliberadamente conservador**: si el campo no es el que esperamos, asumimos problema.

## Implementación

Igual que los otros checks: delega en `checks/security.py::safe_get_json()`. HTTPS-only, no redirects, no-leak vienen de ahí.

```python
data = security.safe_get_json(URL, timeout=10)
if data is None:
    return True  # problema (red o parseo)
indicator = data.get("status", {}).get("indicator", "unknown")
return indicator != "none"
```

**Timeout fijo de 10s.** No configurable via env var.

**Sin `GITHUB_TOKEN`:** el endpoint es público. Mandar un token no ayudaría (el rate limit es por IP, no por user).

## Limitaciones

- **No chequea el status de GitHub Actions específicamente.** Solo el status general de GitHub.
- **Timeout fijo de 10s.** Si el endpoint de status está lento, el check puede fallar por timeout (devolviendo `True` = problema).
- **Depende de que Atlassian Statuspage esté UP.** Si Statuspage se cae, el check reporta problema (lo cual es probablemente correcto).
- **No chequea status de servicios específicos** (API, web, packages, etc.). Solo el indicador global.

## ¿Por qué no deshabilitarlo?

A primera vista parece redundante — ¿qué vas a hacer si GitHub está caído? Pero el valor es **contextual**:

- Si bit 5 = 1 + todos los demás bits = 0 → GitHub está caído, todo lo demás está OK. No es tu problema.
- Si bit 5 = 1 + bit 0 = 1 → Tu URL primaria + GitHub están caídos. Posible correlación.
- Si bit 5 = 1 + bit 3 = 1 → GitHub caído + cert SSL por vencer. El cert es independiente, mirá ese.
- Si bit 5 = 0 + bit 0 = 1 → Tu URL primaria está caída, GitHub está OK. **Esto sí es tu problema.**

El slot 5 te ayuda a **descartar causas externas** cuando hay un 1 en otro slot.

## Testing

```bash
# GitHub normal
python alarm.py --dry-run
# → 00000000 (bit 5 = 0)

# Simulando un outage (no hay forma de hacerlo realmente, pero podemos forzar timeout)
# No se puede testear directamente, pero si querés verificar que el código funciona:
python -c "
import urllib.request, json
r = urllib.request.urlopen('https://www.githubstatus.com/api/v2/status.json', timeout=5)
data = json.loads(r.read())
print('indicator:', data['status']['indicator'])
"
```

Si el output es `indicator: none`, todo OK. Si es otra cosa, GitHub tiene un incidente activo.
