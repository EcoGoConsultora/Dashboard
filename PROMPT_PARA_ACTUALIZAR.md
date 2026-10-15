# Prompt para actualizar el tablero

Esto se le pega a Claude Code, en la PC de quien vaya a actualizar. Claude arranca
sin saber nada de este proyecto, así que el texto de abajo tiene que ir **entero**:
no sirve mandar "actualizá el tablero".

Quien lo corra necesita OneDrive sincronizado con la carpeta `BD` y permiso de
escritura en el repo de GitHub.

---

## Copiá desde acá

> Necesito actualizar el dashboard de Eco Go. Corré el pipeline y contame cómo salió.
>
> **Dónde está todo.** El repositorio es `EcoGoConsultora/Dashboard` y tiene que vivir
> dentro de mi OneDrive, en `OneDrive - ECOGO S.A\BD\07 Tableros\EcoGo-Dashboard`.
> Esa ubicación importa: el script deduce de ahí dónde están los Excel (dos niveles
> arriba, en `BD`). Si la carpeta no existe, cloná el repo ahí:
>
> ```
> cd "%USERPROFILE%\OneDrive - ECOGO S.A\BD\07 Tableros"
> git clone https://github.com/EcoGoConsultora/Dashboard.git EcoGo-Dashboard
> ```
>
> **Antes de correr**, verificá que estas dependencias estén en el mismo intérprete de
> Python que vas a usar, e instalá sólo las que falten:
> `openpyxl`, `xlrd`, `python-docx`, `requests`, y las de `markets_pipeline\requirements.txt`.
> Node es opcional: si no está, la sección Internacional conserva su dato anterior y el
> resto corre igual.
>
> **El comando**, desde la carpeta del repo:
>
> ```
> python refresh.py
> ```
>
> Tarda varios minutos. Usá un timeout largo y no lo cortes. Hace los 18 pasos, sella
> las versiones de los archivos y sube los cambios a GitHub solo.
>
> **Qué mirar cuando termine.** El script está hecho para no romperse nunca: termina
> diciendo LISTO aunque una fuente se haya apagado. Así que lo importante no es que
> termine, sino qué dice el resumen. Contame:
>
> 1. La línea final `Resumen: N OK - N warnings - N errores`.
> 2. **Cada warning y cada error, con su texto completo.** Los warnings de atraso
>    (`ultimo dato <mes> — N meses de atraso`) son el punto: significan que un Excel de
>    origen no se actualizó, o que a una hoja le cambiaron el nombre o el rango. Para
>    cada uno decime qué sección es y qué archivo habría que revisar.
> 3. Si el push salió bien. Confirmalo con `git log --oneline -1` y `git status --short`.
>
> **Reglas, importantes:**
>
> - **No toques ningún Excel de la carpeta BD, por ningún motivo.** Son los archivos de
>   trabajo del equipo. El pipeline sólo los lee. Si uno tiene un dato raro, decímelo,
>   no lo corrijas.
> - No cambies el código ni el diseño del tablero. Esta tarea es correr y reportar.
> - Si el push falla por "non-fast-forward", hacé `git pull` y volvé a pushear; eso pasa
>   cuando otra persona o la tarea automática subió algo antes.
> - Si algo falla de verdad, explicá qué pasó y qué habría que hacer, pero no lo
>   resuelvas sin preguntarme.
>
> **Contexto para interpretar los avisos:**
>
> - Internacional y Mercados se actualizan solos todos los días a las 17:00 por GitHub
>   Actions, así que esos rara vez necesitan esta corrida.
> - La sección Monitor de tasas sale de `BD\Mercados\Monitor tasas`, que tiene su propia
>   tarea programada a las 17:30. Si avisa atraso en días, el problema está ahí.
> - Varios Excel viven en OneDrive y pueden estar abiertos en Excel; el pipeline ya sabe
>   leerlos igual.
> - El resumen en castellano, por favor. Un párrafo corto y después la lista de lo que
>   quedó atrasado, un renglón por cosa.

## Hasta acá

---

## Si algo no funciona

**`ModuleNotFoundError: No module named 'openpyxl'`**
Python está corriendo en un entorno sin las dependencias. Que Claude verifique con
`python -c "import sys; print(sys.executable)"` cuál intérprete está usando e instale
ahí. En Jupyter, revisar qué kernel está seleccionado.

**`No se encontró: ...\Precios\IPC TODESCA.xlsx`**
OneDrive no está sincronizado (los archivos muestran una nube en vez de un tilde verde),
o el repo no quedó dentro de `BD\07 Tableros\`.

**El push es rechazado por permisos**
Esa cuenta no tiene acceso de escritura al repo. Hay que pedirlo, o que la corrida la
haga alguien que lo tenga.

Para el detalle de la instalación, ver [COMO_ACTUALIZAR.md](COMO_ACTUALIZAR.md).
