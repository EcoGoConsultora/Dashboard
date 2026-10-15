# Crédito y mora: supermercados + electrodomésticos

Extiende `Credito_Supermercados.xlsx` (Drive: `Sistema financiero/Crédito supermercados/output/`)
con la mora de las cadenas de electrodomésticos y el conjunto de ambos segmentos.

Entregable: `Credito_Supermercados_Electro.xlsx`. Hojas nuevas:

| Hoja | Contenido |
|---|---|
| Resumen electro y conjunto | Saldo, variación real, mora y mora temprana por entidad de electro, y agregados super / electro / conjunto |
| Super + Electro | Series mensuales oct-22 a ago-26: saldo en pesos constantes de sep-26, mora y mora temprana por segmento y del conjunto. Tres gráficos |
| Electro crédito | Saldo por entidad, pesos corrientes y constantes |
| Electro mora | Mora (sit. 3+4+5) y situación 2 por entidad |

Las hojas originales no cambian (se verificó celda por celda); a Metodología se le agregan filas.

## Universo electro

| Código BCRA | Entidad | Cadena |
|---|---|---|
| 55027 | Electrónica Megatone S.R.L. | Megatone |
| 55041 | Naldo Lombardi S.A. | Naldo |
| 55011 | Cetrogar S.A. | Cetrogar |
| 55030 | Frávega S.A.C.I. e I. | Frávega |
| 55028 | Favanet S.A. | según taxonomía del ranking |
| 55009 | Carsa S.A. | Musimundo (supuesto no verificado) |

## Cómo correrlo

```bash
python 05_electro_conjunto.py <Credito_Supermercados.xlsx> <PNFC.xlsx> <carpeta hechos/> <salida.xlsx>
```

Requiere `openpyxl` >= 3.1 (conserva los gráficos del Excel de entrada), `pandas` y `pyarrow`.

## Fuentes y criterios

- Saldo y mora de electro: `PNFC.xlsx` (hojas Carteras e Irregularidad, Central de Deudores,
  miles de millones de $). Coincide con la tabla de hechos mensual y reproduce las series de
  supermercados del Excel.
- Mora temprana (situación 2): tablas `hechos_<periodo>.parquet` del ranking de crédito.
  En esta versión hay 22 de 47 meses (sep-23 a feb-24, mar-25, may-25 a jul-26). Para completarla,
  agregar las seis entidades a `ENTIDADES` en `procesos/config.py` y correr `02_cendeu.py`.
- Pesos constantes: el mismo deflactor de la hoja "Crédito mensual" (IPC INDEC, sep-26).
- Tasas del conjunto ponderadas por saldo.
