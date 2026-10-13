# Registro de uso del tablero

Anota en una planilla de Google qué hace cada cliente en el tablero: qué secciones abre, cuánto tiempo las tiene a la vista y qué descarga.

## Cómo funciona

```
WordPress (con el cliente logueado)
  │  1. le agrega al iframe del tablero: ?u=<ID de usuario de WordPress>
  │  2. le manda a la planilla nombre, email y empresa de ese ID  ──────────┐
  ▼                                                                         │
Tablero (GitHub Pages) · assets/js/layout.js                                │
  │  recuerda el ID en la sesión y avisa cada vista, tiempo y descarga ──┐  │
  ▼                                                                      ▼  ▼
                                 Planilla de Google + Apps Script (seguimiento/apps-script.gs)
                                 pestañas Resumen · Eventos · Usuarios
```

- El mail viaja solo de servidor a servidor (de WordPress a Google). Al tablero y a la URL llega únicamente el número de usuario.
- Los visitantes sin sesión también quedan registrados, como "Público" y sin ID.
- Las pruebas locales (`localhost`, `127.0.0.1`, `file://`) no se registran.
- Mientras `REGISTRO_URL` esté vacío en `layout.js`, no se manda nada.

## Instalación (una sola vez)

### 1. Planilla y Apps Script

1. Con una cuenta de Google de Eco Go (conviene una compartida, no una personal), crear una planilla nueva. Por ejemplo, "Registro tablero Eco Go".
2. En la planilla: **Extensiones → Apps Script**. Borrar lo que haya y pegar todo el contenido de `seguimiento/apps-script.gs`. Guardar.
3. Arriba, elegir la función **`configurar`** y tocar **Ejecutar**. Google pide autorización: aceptar con la misma cuenta.
   - Esto crea las pestañas Resumen, Eventos y Usuarios.
   - En el **Registro de ejecución** (abajo) aparece la **clave para WordPress**. Copiarla.
4. **Implementar → Nueva implementación** → tipo **Aplicación web**:
   - Ejecutar como: **Yo**
   - Quién tiene acceso: **Cualquier usuario**
   - Implementar y copiar la **URL de la aplicación web** (termina en `/exec`).

### 2. Tablero

En `assets/js/layout.js`, pegar la URL en:

```js
const REGISTRO_URL = 'https://script.google.com/macros/s/.../exec';
```

y subir el cambio a GitHub como siempre.

### 3. WordPress

1. Instalar el plugin **Code Snippets** ("Fragmentos de código"), si no está.
2. Crear un fragmento PHP nuevo, pegar `seguimiento/wordpress-snippet.php` (sin la primera línea `<?php`) y completar:
   - `$registro_url` → la URL `/exec` del paso 1 (ya viene puesta).
   - `$registro_clave` → la clave del paso 1, entre comillas simples. **Va solo en WordPress, nunca en GitHub.**
3. Activarlo en modo "Ejecutar el fragmento en todas partes".

No hay que tocar las entradas. El iframe del tablero vive en un campo de JetEngine que muestra la plantilla de Elementor de la categoría Tableros, y el fragmento le agrega `?u=<ID>` a cualquier URL del tablero (`ecogoconsultora.github.io/Dashboard/...`) en la página que ve un usuario logueado. Por eso Elementor muestra esas entradas vacías: **no publicar desde ahí**, porque se pisaría el contenido.

> El sitio está en Kinsta, que por defecto no cachea páginas para usuarios logueados. Eso es necesario: si se cachearan, todos los clientes verían el ID del primero.

### 4. Probar

Entrar a la página de clientes con un usuario de prueba, abrir un par de secciones y descargar algo. En la planilla:

- **Usuarios**: aparece el usuario con nombre y email.
- **Eventos**: aparece una fila por sección vista y una por descarga. La columna Segundos se completa al cambiar de sección o cerrar la pestaña.

## Qué hay en la planilla

| Pestaña | Contenido |
|---|---|
| **Resumen** | Por cliente: secciones vistas, descargas, minutos y última actividad. Además, las secciones más vistas (cliente vs. público) y las descargas por archivo. Se actualiza sola. |
| **Eventos** | Una fila por cosa que pasó: fecha, cliente, empresa, sección, evento (`vista` / `descarga`), detalle (archivo descargado o "Bloqueada" si alguien sin sesión intentó entrar a una sección de clientes), segundos a la vista, dispositivo y sesión. Para filtrar o armar tablas dinámicas. |
| **Usuarios** | ID, nombre, email, empresa y alta de cada cliente que entró. La columna **Empresa** se puede completar a mano: si WordPress no la manda, no se pisa. |

En la planilla hay un menú **Eco Go → Completar nombres en Eventos**. Sirve para rellenar el nombre en las filas que quedaron sin él, por ejemplo las de antes de que el usuario apareciera en Usuarios.

## Cambios posteriores

- **Si se modifica `apps-script.gs`:** pegarlo de nuevo en el editor y hacer **Implementar → Administrar implementaciones → editar (lápiz) → Versión: nueva**. Así la URL `/exec` sigue siendo la misma. Si se hace "Nueva implementación", cambia la URL y hay que actualizar `layout.js` y WordPress.
- **Para registrar otro evento desde una página** (por ejemplo, un cambio de pestaña):

  ```js
  EcoGo.track('pestana', 'Proyecciones · mensual');
  ```

  El nombre del evento va en minúsculas, sin espacios ni tildes.

## Límites a tener en cuenta

- **Es medición, no seguridad.** El tablero es público y el `?u=` se puede escribir a mano, así que el registro sirve para ver el uso, no como auditoría.
- **El tiempo cuenta solo con la página a la vista:** si la pestaña queda en segundo plano, no suma.
- **Datos personales.** La planilla guarda qué hace cada cliente identificado, así que conviene avisarlo en los términos o en la política de privacidad del sitio (Ley 25.326) y compartir la planilla solo con quien la necesite.
