# Cómo actualizar el dashboard desde otra PC

El tablero vive en GitHub y los datos salen de los Excel de OneDrive. **Actualizar
el Excel no publica nada**: alguien tiene que correr `refresh.py` desde una PC que
tenga esa carpeta sincronizada. Esta guía es para dejar lista esa PC.

Se hace una sola vez. Después, actualizar es un comando.

---

## Lo que hay que instalar (una vez)

### 1. OneDrive sincronizado

La carpeta `OneDrive - ECOGO S.A\BD` tiene que estar en el disco, no sólo en la nube.
En el Explorador, clic derecho sobre `BD` → **Mantener siempre en este dispositivo**.

Si los archivos muestran una nube y no un tilde verde, el código no los puede leer.

### 2. El repositorio, en el lugar correcto

El repo tiene que quedar **dentro de `BD\07 Tableros\`**, porque de ahí deduce dónde
están los Excel (dos niveles arriba).

```
cd "%USERPROFILE%\OneDrive - ECOGO S.A\BD\07 Tableros"
git clone https://github.com/EcoGoConsultora/Dashboard.git EcoGo-Dashboard
```

Hace falta permiso de escritura en el repo, porque el script sube los cambios solo.

### 3. Python y sus dependencias

Python 3.11 o superior. Después, desde la carpeta del repo:

```
python -m pip install openpyxl xlrd python-docx requests
python -m pip install -r markets_pipeline\requirements.txt
```

### 4. Node

Para la sección Internacional (Monitor mundial). Se baja de nodejs.org, versión LTS.
Si no está, esa sección conserva el dato anterior y el resto corre igual.

---

## Actualizar

Desde la carpeta del repo:

```
python refresh.py
```

Tarda unos minutos. Procesa los 18 pasos, sella las versiones y sube los cambios a
GitHub. El tablero queda actualizado unos minutos después (GitHub Pages tarda en
publicar).

---

## Leer el resultado

**El script nunca se cae**: aunque una fuente falle, termina igual. Por eso lo que
importa no es que termine, sino lo que dice el resumen del final:

```
Resumen: 15 OK - 2 warnings - 0 errores
```

- **OK** — esa sección se actualizó.
- **WARN** — no se actualizó, pero el tablero conserva el dato anterior. El mensaje
  dice por qué. El caso típico: `ultimo dato jun-26 — 3 meses de atraso`, que
  significa que el Excel de origen no se actualizó, no que el código falle.
- **FAIL** — algo se rompió de verdad. Ahí sí hay que mirar.

Los warnings de atraso son el motivo por el que existe ese resumen: sin ellos, una
sección se queda vieja y nadie se entera hasta que alguien mira el gráfico semanas
después.

---

## Qué se actualiza solo y qué no

| | Se actualiza solo | Cómo |
|---|---|---|
| Internacional, Mercados | sí, todos los días a las 17:00 | GitHub Actions, sin PC |
| Las otras 16 secciones | no | hay que correr `refresh.py` |

El workflow de GitHub (`.github/workflows/actualizar-online.yml`) corre en una máquina
en la nube, que no tiene los Excel de OneDrive. Por eso sólo puede actualizar las dos
secciones que bajan de fuentes públicas.

---

## Problemas frecuentes

**`ModuleNotFoundError: No module named 'openpyxl'`**
Python está corriendo en un entorno sin las dependencias. Verificar con
`python -c "import sys; print(sys.executable)"` que sea el mismo donde se instalaron.
En Jupyter, revisar qué kernel está seleccionado.

**`No se encontró: ...\Precios\IPC TODESCA.xlsx`**
OneDrive no está sincronizado, o el repo no quedó dentro de `BD\07 Tableros\`.

**El push falla por "non-fast-forward"**
Otra persona (o el workflow de GitHub) subió algo antes. Se arregla con `git pull`
y volver a correr.

**Un Excel abierto en Excel**
No es problema: el script sabe leer archivos bloqueados.
