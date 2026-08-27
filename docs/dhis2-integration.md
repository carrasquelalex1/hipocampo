# Integración DHIS2 — Registro de Pacientes

## 1. Programa en DHIS2 (Event Program)

### 1.1 Creación del Programa

Se creó un **programa de eventos** (WITHOUT_REGISTRATION) llamado **"Registro de Pacientes"** en DHIS2 2.42.4.

| Propiedad | Valor |
|-----------|-------|
| **UID** | `oqGkNapeFer` |
| **Nombre** | Registro de Pacientes |
| **Tipo** | Evento (WITHOUT_REGISTRATION) |
| **Icono** | `clinical_fe_outline` |
| **Color** | `#00BCD4` |
| **Unidades Organizativas** | 1499 OUs del árbol VENEZUELA |
| **FormType** | DEFAULT (CUSTOM no funciona en Capture app — el JS no se ejecuta) |

**Nota:** Inicialmente se creó con UID `tY0K8QpVZah` pero tras múltiples recreaciones quedó corrupto. Se eliminó y recreó con el UID actual `oqGkNapeFer`.

### 1.2 Stage (Etapa)

| Propiedad | Valor |
|-----------|-------|
| **UID** | `eQBfKXhWDjr` |
| **Nombre** | Datos del Paciente |

### 1.3 Data Elements

| Data Element | UID | ValueType | Descripción |
|---|---|---|---|
| Nombre del paciente | `wiY1Lq4SCNl` | TEXT | Nombre completo |
| Edad | `u7QLHA0dybM` | INTEGER | Edad en años (0-100) — inicialmente AGE, cambiado a INTEGER para mejor validación |
| Sexo del paciente | `h5eqeJfubjt` | TEXT (OptionSet) | OptionSet `SEXO` (`ak9fFSzV0Lu`) |

### 1.4 OptionSet SEXO

| Código | UID | Nombre |
|--------|-----|--------|
| `1` | `NNfC6ydVNYp` | MASCULINO |
| `2` | `lB1UnLp9JjF` | FEMENINO |

### 1.5 Lecciones aprendidas

- `PUT` en `programStage` sin incluir `programStageDataElements` los **elimina**
- `PUT` en `program` sin incluir `organisationUnits` las **pierde**
- `formType: CUSTOM` **no funciona** en la DHIS2 Capture app de React — el HTML/JS se renderiza pero no se vincula al modelo de DHIS2 (los tags `{de:UID}` no se reemplazan, los `<input>` no guardan datos)

---

## 2. API de Eventos

### 2.1 Endpoint correcto

```
POST /api/tracker?async=false&importStrategy=CREATE
```

En DHIS2 2.42.4, `POST /api/tracker/events` retorna **405 Method Not Allowed**. El endpoint correcto es el importador de tracker con `events` envueltos.

### 2.2 Payload

```json
{
  "events": [{
    "program": "oqGkNapeFer",
    "programStage": "eQBfKXhWDjr",
    "orgUnit": "<OU_UID>",
    "occurredAt": "2026-06-13",
    "status": "COMPLETED",
    "dataValues": [
      {"dataElement": "wiY1Lq4SCNl", "value": "NOMBRE PACIENTE"},
      {"dataElement": "u7QLHA0dybM", "value": "30"},
      {"dataElement": "h5eqeJfubjt", "value": "1"}
    ]
  }]
}
```

- Sexo usa **códigos**: `1` = MASCULINO, `2` = FEMENINO
- `occurredAt` en lugar de `eventDate`
- **No** incluir campo `event` vacío — causa error `UID must be an alphanumeric string of 11 characters`

### 2.3 Respuesta exitosa

```json
{
  "status": "OK",
  "bundleReport": {
    "typeReportMap": {
      "EVENT": {
        "objectReports": [{"uid": "<nuevo_event_uid>"}]
      }
    }
  },
  "stats": { "created": 1 }
}
```

El UID del evento se encuentra en: `bundleReport.typeReportMap.EVENT.objectReports[0].uid`

---

## 3. Formulario PHP (DHISForm)

### 3.1 Archivos

| Archivo | Descripción |
|---|---|
| `/var/www/html/shopix/dhisform/index.php` | Formulario principal |
| `/var/www/html/shopix/dhisform/ou_hierarchy.json` | Jerarquía de OUs (335 municipios, 1138 parroquias) |
| `/tmp/build_hierarchy.py` | Script para regenerar jerarquía desde DHIS2 API |

### 3.2 Funcionalidades

- **Selects anidados**: Estado → Municipio → Parroquia (cascading, vía JavaScript)
- **Auto-mayúsculas**: El campo Nombre se convierte a mayúsculas (CSS + JS)
- **Validación Edad**: Solo números enteros 0-100 (HTML5 + PHP + JS)
- **Sexo**: Select con opciones MASCULINO / FEMENINO (OptionSet codes)
- **PRG (Post-Redirect-Get)**: Evita reenvío al refrescar (F5)
- **Bootstrap 5**: Diseño responsive con iconos
- **Mensajes**: Alertas de éxito/error con UID del evento creado

### 3.3 Flujo de envío

```
Usuario → Formulario HTML → POST → PHP valida → cURL POST /api/tracker → DHIS2
                                       ↓ éxito                    ↓ error
                              header('Location: ?success=UID')   header('Location: ?error=msg')
                                       ↓
                              GET recarga → muestra alerta
```

### 3.4 Jerarquía OU

- **Root**: VENEZUELA (`S6nJBBxS64e`) — level 1
- **25 estados** — level 2
- **335 municipios** — level 3
- **1138 parroquias** — level 4

La jerarquía se genera desde DHIS2 API con el script `/tmp/build_hierarchy.py` y se cachea en `ou_hierarchy.json`.

### 3.5 Historial de bugs corregidos

1. **API 405** — Endpoint incorrecto `POST /api/tracker/events` → `POST /api/tracker?async=false&importStrategy=CREATE`
2. **Reenvío F5** — Agregado PRG pattern: redirect GET en lugar de `$_POST = []`
3. **Jerarquía incompleta** — El JSON original solo tenía 160 municipios/194 parroquias; faltaba ALTO ORINOCO (Amazonas) y muchas parroquias. Regenerado con script Python → 335/1138
4. **Anidación rota** — `array_column()` no funcionaba con el nuevo JSON (que usa UIDs como keys). Corregido con `array_map()` que preserva keys

---

## 4. URLs

| Recurso | URL |
|---|---|
| Formulario | `http://localhost/shopix/dhisform/` |
| DHIS2 API | `http://localhost:8081/Dhis2-Venezuela/api` |
| DHIS2 Login (proxy) | `https://shopix.dpdns.org/Dhis2-Venezuela` |
| Usuario API | admin / district |

---

## 5. Comandos útiles

```bash
# Probar creación de evento
curl -s -u admin:district -X POST "http://localhost:8081/Dhis2-Venezuela/api/tracker?async=false&importStrategy=CREATE" \
  -H "Content-Type: application/json" \
  -d '{"events":[{"program":"oqGkNapeFer","programStage":"eQBfKXhWDjr","orgUnit":"<OU_UID>","occurredAt":"2026-06-13","status":"COMPLETED","dataValues":[{"dataElement":"wiY1Lq4SCNl","value":"TEST"},{"dataElement":"u7QLHA0dybM","value":"25"},{"dataElement":"h5eqeJfubjt","value":"1"}]}]}'

# Regenerar jerarquía OU
python3 /tmp/build_hierarchy.py

# Ver eventos recientes
curl -s --globoff -u admin:district "http://localhost:8081/Dhis2-Venezuela/api/tracker/events?program=oqGkNapeFer&pageSize=5&order=occurredAt:desc"
```

---

## 6. App Instalable DHIS2 (SPA JavaScript)

### 6.1 Archivos

| Archivo | Descripción |
|---|---|
| `manifest.webapp` | Metadata obligatoria (nombre, versión, icono, launch_path) |
| `index.html` | Shell Bootstrap 5 con formulario |
| `app.js` | Lógica: carga OU dinámica + envío API |
| `icon.png` | Icono 48px (color #00BCD4) |

### 6.2 Cómo se creó

```bash
# 1. Crear directorio
mkdir -p /tmp/dhis2-app

# 2. Crear manifest.webapp
cat > /tmp/dhis2-app/manifest.webapp << 'EOF'
{
  "name": "Registro de Pacientes",
  "version": "1.0.0",
  "description": "Formulario de registro de pacientes con jerarquía OU",
  "icons": { "48": "icon.png", "128": "icon.png" },
  "developer": { "name": "Hipocampo MCP" },
  "launch_path": "index.html",
  "default_locale": "es",
  "activities": { "dhis": { "href": "*" } },
  "manifest_version": "1.0"
}
EOF

# 3. Crear index.html — Bootstrap 5, selects anidados, auto-mayúsculas
# 4. Crear app.js — lógica principal
# 5. Generar icono PNG (Python PIL o manual)
# 6. Empaquetar
cd /tmp/dhis2-app && zip -r /tmp/registro-pacientes.zip *

# 7. Instalar en DHIS2 via API
curl -s -u admin:district -X POST "http://localhost:8081/Dhis2-Venezuela/api/apps" \
  -F "file=@/tmp/registro-pacientes.zip"

# 8. Reinstalar (requiere borrar primero)
curl -X DELETE -u admin:district "http://localhost:8081/Dhis2-Venezuela/api/apps/Registro-de-Pacientes"
curl -X POST -u admin:district "http://localhost:8081/Dhis2-Venezuela/api/apps" -F "file=@/tmp/registro-pacientes.zip"
```

### 6.3 Diferencias con el PHP form

| Aspecto | PHP Form | App DHIS2 |
|---|---|---|
| **Jerarquía OU** | JSON cacheado (335 municipios, 1138 parroquias) | **Dinámico**: consulta API por niveles |
| **Backend** | PHP + cURL | JavaScript puro (fetch) |
| **Autenticación** | Basic auth hardcoded | Herencia de sesión DHIS2 (iframe) |
| **URL API** | `http://localhost:8081/Dhis2-Venezuela/api` | Relativa `../../` (desde `/api/apps/Registro-de-Pacientes/`) |
| **Reenvío F5** | PRG (PHP redirect) | No aplica (SPA sin POST nativo) |

### 6.4 Carga dinámica de OU (app.js)

```javascript
// Nivel 1: cargar estados
/api/organisationUnits?filter=level:eq:2&fields=id,name&pageSize=200

// Nivel 2-3: cargar hijos al seleccionar
/api/organisationUnits/{parentId}?fields=children[id,name,level]
```

### 6.5 Estructura del manifest.webapp

| Campo | Valor |
|---|---|
| `name` | Registro de Pacientes |
| `version` | 1.0.0 |
| `launch_path` | index.html |
| `default_locale` | es |
| `activities.dhis.href` | `*` (aplica a cualquier página DHIS2) |
| `appStorageSource` | JCLOUDS (almacenamiento interno DHIS2) |

### 6.6 Notas importantes

- La app se sirve desde `http://localhost:8081/Dhis2-Venezuela/api/apps/Registro-de-Pacientes/index.html`
- El path base de API es `../../` (sube 2 niveles de `/api/apps/Registro-de-Pacientes/` → `/api/`)
- La app corre dentro del shell de DHIS2 (header + menú lateral)
- No requiere credenciales — hereda la sesión del usuario logueado
- Para distribuir: compartir el archivo `.zip` → instalarlo en App Management → `+` → seleccionar zip
```
