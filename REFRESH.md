# Cómo refrescar los datos del dashboard

Cuando actualizás cualquiera de los Excel fuente, el dashboard **no** se actualiza solo. Tenés que correr `refresh.bat` una vez para regenerar los archivos de datos.

## Uso normal (después de actualizar Excel)

1. Actualizá tu Excel en su carpeta de siempre (`OneDrive\BD\...`)
2. Doble click en **`refresh.bat`** (está en esta misma carpeta)
3. Esperá a que diga "LISTO" (5–15 segundos)
4. Recargá el dashboard en el navegador (`Ctrl+F5`)

## Excel que lee

Las rutas están fijadas en `refresh.py` (sección **CONFIGURACIÓN** al principio):

| Dataset       | Archivo Excel                                                                                  | Hojas usadas                                                          |
|---------------|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| Precios IPC   | `BD\Precios\IPC TODESCA.xlsx`                                                                  | `1. Nuevo IPC Nacional`, `4. Proyecciones`                            |
| Precios GD    | `BD\Precios\Gráficos de dispersión - copia - copia.xlsx`                                       | `Hoja3`                                                               |
| Proyección RPM| `BD\Precios\CM - DB.xlsx` *(opcional, busca la hoja con código de fecha más reciente)*         | hoja `YYMM` (ej. `2605`)                                              |
| Empleo        | `BD\Empleo\Empleo_nuevo.xlsx`                                                                  | `Tasas EPH`, `Cuadro empleo trim`, `Cuadro SIPA ext (2)`, `Hoja7`     |
| Salarios      | `BD\Empleo\Salarios.xlsx`                                                                      | `1.1 INDEC`, `1.3 Cuadro INDEC`, `1.6. Datos grafico base 21`         |

> Los Excel **no se modifican nunca** — se abren en modo lectura.

## Requisitos

- Python 3 instalado (https://www.python.org/downloads/ · marcar "Add Python to PATH" al instalar)
- `openpyxl` se instala solo la primera vez que corre el .bat

## Si cambia la ubicación de un Excel

Abrí `refresh.py` con cualquier editor, buscá la sección **CONFIGURACIÓN** y cambiá la ruta del archivo. Guardá y volvé a correr el .bat.

## Si una hoja cambia de nombre o estructura

Eso requiere que yo (Claude) ajuste el script. Avisame y lo arreglamos.

## Publicación automática en GitHub

Esta misma carpeta (`EcoGo-Dashboard`) es un clon de `github.com/EcoGoConsultora/Dashboard` — ya no depende de una carpeta puente aparte.

Al final de `refresh.py` (y de los notebooks `Actualizar_Dashboard_Clientes.ipynb` / `Actualizar_Dashboard_EcoGo.ipynb`) se agregó un paso que:

1. Hace `git add` + `git commit` de los cambios (código y datos) directo acá.
2. Trae los cambios de GitHub (`git fetch` + `git merge`) por si algo se subió desde otro lado.
3. Hace `git push` a la rama `main`.

Requisitos para que funcione:

- Tener **Git for Windows** instalado y `git` disponible en el PATH (verificar con `git --version` en una terminal). Si falta, el refresh sigue funcionando igual pero avisa que no pudo subir a GitHub.
- Esta carpeta tiene que seguir siendo un repo git válido con el remoto `origin` apuntando a `https://github.com/EcoGoConsultora/Dashboard.git` (podés verificarlo con `git remote -v` en una terminal parada acá) y con acceso de escritura ya autenticado en esta compu.
- Si algún día el push falla por conflicto (por ejemplo, alguien editó algo directo en GitHub), el mensaje de error lo va a avisar en el resumen — en ese caso conviene abrir esta carpeta con GitHub Desktop para resolverlo a mano.
