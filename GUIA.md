# Eco Go — Dashboard Maestro

Dashboard consolidado que unifica todos los monitores e indicadores de Eco Go en una sola aplicación HTML modular.

---

## 1. Cómo abrirlo

Como es una app multipágina HTML con assets (JS, CSS, fuentes, dashboards embebidos), conviene servirla con un mini server local en lugar de hacer doble click en `index.html` — algunos navegadores bloquean `iframe` y `fetch` cuando se abren con protocolo `file://`.

Opciones:

- **Python (más simple).** Desde una terminal parada en la carpeta `EcoGo-Dashboard/`:
  ```
  python -m http.server 8000
  ```
  Después abrir `http://localhost:8000/` en el navegador.

- **VS Code.** Instalar la extensión *Live Server* y hacer click derecho sobre `index.html` → *Open with Live Server*.

- **Node.** `npx serve .` en la carpeta del proyecto.

---

## 2. Estructura de carpetas

```
EcoGo-Dashboard/
├── index.html                    ← Página de inicio (KPIs + tarjetas, sin sidebar)
├── GUIA.md                       ← Este archivo
├── assets/
│   ├── css/
│   │   └── theme.css             ← Sistema de diseño centralizado
│   ├── js/
│   │   ├── layout.js             ← Sidebar, header y registro de secciones
│   │   └── precios-charts.js     ← Gráficos de la sección Precios (Chart.js)
│   ├── data/
│   │   ├── precios.json          ← Dataset Precios (consolidado de los Excel)
│   │   └── precios.js            ← Mismo dataset como variable global
│   ├── img/                      ← Logos Eco Go
│   └── fonts/                    ← HK Grotesk (familia tipográfica oficial)
├── pages/                        ← Una página por sección temática
│   ├── actividad.html
│   ├── empleo.html
│   ├── precios.html              ← Página con gráficos nativos (Chart.js)
│   ├── deuda.html
│   ├── sector-externo.html
│   ├── fiscal.html
│   ├── monetario.html
│   ├── tipo-cambio.html
│   └── internacional.html
└── dashboards/                   ← Dashboards originales, embebidos por iframe
    ├── actividad-monitor.html
    ├── actividad-proyecciones.html
    ├── empleo-mercado-laboral.html
    ├── deuda-monitor.html
    ├── sector-externo-liquidaciones.html
    ├── fiscal-rigi.html
    └── internacional-proyecciones.html
```

> Nota: La página de inicio (`index.html`) usa `data-no-sidebar="true"` en
> `<body>` para ocultar el menú lateral (sería redundante con las tarjetas).
> Cualquier futura página puede activar el mismo modo del mismo modo.

**Principio:** los dashboards originales se preservan tal cual en `dashboards/`. Cada `pages/*.html` los embebe vía `<iframe>`. Así se puede actualizar cualquier dashboard reemplazando solo su archivo, sin tocar el resto.

---

## 3. Identidad visual

Definida en `assets/css/theme.css`. Todas las decisiones de marca están en variables CSS al principio del archivo:

| Variable          | Color    | Uso                                   |
|-------------------|----------|---------------------------------------|
| `--eg-teal`       | #3C9794  | Títulos, color principal              |
| `--eg-teal-dark`  | #1B5F5E  | Sidebar, headings fuertes             |
| `--eg-teal-light` | #8FCCCA  | Acentos suaves, bordes                |
| `--eg-charcoal`   | #333333  | Texto principal                       |
| `--eg-red`        | #DA4531  | Alertas, valores negativos            |
| `--eg-orange`     | #FE8B5F  | Acentos secundarios                   |
| `--eg-green`      | #89C442  | Valores positivos, crecimiento        |

Tipografía: **HK Grotesk** (cargada localmente desde `assets/fonts/`, sin depender de CDN).

Para cambiar la paleta a futuro, solo hay que editar los valores en el bloque `:root` de `theme.css` — todo el dashboard se actualiza automáticamente.

---

## 4. Componentes reutilizables

Disponibles como clases CSS:

- `.eg-page-header` — Header de página con título, subtítulo y acciones.
- `.eg-kpi-grid` + `.eg-kpi` — Grilla de KPIs. Variantes: `.is-positive`, `.is-negative`, `.is-accent`.
- `.eg-card` — Tarjeta genérica.
- `.eg-grid--2` / `.eg-grid--3` — Grillas responsive de 2/3 columnas.
- `.eg-embed` — Wrapper para dashboards embebidos (iframe).
- `.eg-placeholder` — Bloque "Próximamente" con ícono y lista.
- `.eg-btn` / `.eg-btn--primary` — Botones.
- `.eg-tag` / `.eg-tag--soon` — Etiquetas.
- `.eg-table` — Tabla con estilo Eco Go.
- `.eg-section-card` — Tarjetas de acceso (usadas en el home).

Todas las clases usan el prefijo `eg-` para evitar colisiones con CSS de los dashboards embebidos.

---

## 5. Cómo agregar una nueva sección

Tres pasos:

**a) Registrar la sección** en `assets/js/layout.js`, agregando una entrada al array `SECTIONS`:

```js
{
  id: 'mi-nueva-seccion',
  label: 'Mi Nueva Sección',
  href: 'pages/mi-nueva-seccion.html',
  group: 'Fiscal',                // o el grupo que corresponda
  icon: 'pie-chart',              // ver mapa `ICONS` en layout.js
  desc: 'Breve descripción para la tarjeta del home.'
}
```

**b) Crear `pages/mi-nueva-seccion.html`** copiando cualquier página existente como template y ajustando:
- el `<title>`
- los atributos `data-active-section="mi-nueva-seccion"` y `data-depth="1"` en `<body>`
- el contenido del `<main class="eg-main">`

**c) Listo.** El sidebar y la grilla del home se actualizan automáticamente.

---

## 6. Cómo agregar un dashboard a una sección existente

1. Copiar el archivo HTML nuevo a `dashboards/` con un nombre descriptivo, por ejemplo `precios-ipc.html`.
2. Editar la página de la sección y agregar un bloque `eg-embed`:

```html
<h2>IPC INDEC</h2>
<div class="eg-embed">
  <iframe src="../dashboards/precios-ipc.html"
          title="IPC INDEC" loading="lazy"></iframe>
</div>
```

3. Si la sección estaba en estado *Próximamente*, actualizar el `status` del objeto `status` en `index.html`.

---

## 7. Cómo agregar KPIs estáticos a una página

```html
<div class="eg-kpi-grid">
  <div class="eg-kpi is-positive">
    <div class="eg-kpi__label">PIB i.a.</div>
    <div class="eg-kpi__value">+3.2%</div>
    <div class="eg-kpi__delta is-up">+0.4 pp vs trim anterior</div>
  </div>
</div>
```

Variantes: `.is-positive` (borde verde), `.is-negative` (rojo), `.is-accent` (naranja). El `__delta` puede llevar `.is-up` o `.is-down` para colorearse.

---

## 8. Mantenimiento y escalabilidad

- **Una fuente de verdad para la navegación:** el array `SECTIONS` en `layout.js`.
- **Una fuente de verdad para el diseño:** las variables CSS en `theme.css`.
- **Páginas autocontenidas:** cada `pages/*.html` declara su `data-active-section` y su `data-depth`. El layout las decora.
- **Convención de paths:** todas las páginas dentro de `pages/` usan `../` para acceder a assets y dashboards. El index queda en la raíz y no necesita prefijo.
- **Iframes:** los dashboards embebidos mantienen su CSS y JS aislado. No se contaminan entre sí ni con el shell.

---

## 9. Estado de las secciones (v1.0)

| Sección                | Estado               | Origen                                              |
|------------------------|----------------------|-----------------------------------------------------|
| Actividad              | Disponible           | Monitor de Actividad + Proyecciones                 |
| Empleo                 | Disponible           | Mercado Laboral                                     |
| Precios                | Próximamente         | Pendiente de incorporación                          |
| Deuda                  | Disponible           | Monitor de Deuda en Pesos 2026                      |
| Sector Externo         | Disponible           | Liquidaciones del Agro & BCRA                       |
| Fiscal                 | Disponible (parcial) | RIGI Dashboard (faltan resultado primario, etc.)    |
| Monetario y Financiero | Próximamente         | Pendiente                                           |
| Tipo de Cambio         | Próximamente         | Pendiente                                           |
| Internacional          | Disponible           | Proyecciones Internacionales                        |

---

Eco Go Consultores · Dashboard Maestro v1.0
