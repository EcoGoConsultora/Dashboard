import fs from "node:fs/promises";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const TZ = "America/Argentina/Buenos_Aires";
const START_YEAR = 2010;
const END_YEAR = new Date().getUTCFullYear();

const paths = {
  countries: path.join(ROOT, "config", "countries.json"),
  indicators: path.join(ROOT, "config", "indicators.json"),
  sources: path.join(ROOT, "config", "sources.json"),
  calendarSources: path.join(ROOT, "config", "calendar_sources.json"),
  dataFile: path.join(ROOT, "data", "monitor-data.js"),
  logFile: path.join(ROOT, "logs", "update.log")
};

const warnings = [];

async function main() {
  await ensureDirs();
  log("Inicio de actualizacion");

  const [countries, indicators, sources, calendarConfig, previous] = await Promise.all([
    readJson(paths.countries),
    readJson(paths.indicators),
    readJson(paths.sources),
    readJson(paths.calendarSources),
    readPreviousData()
  ]);

  const series = initializeSeries(countries, indicators);

  await loadWorldBankIndicators({ countries, indicators, sources, series, previous });
  await loadIlostatUnemployment({ countries, indicators, sources, series, previous });
  await loadBisPolicyRates({ countries, indicators, sources, series, previous });
  await loadBcraArgentinaTamar({ indicators, sources, series, previous });
  await loadOecdG20Prices({ countries, indicators, sources, series, previous });
  await loadOecdG20Gdp({ countries, indicators, sources, series, previous });
  await loadOecdMonthlyUnemployment({ countries, indicators, sources, series, previous });
  await loadArgentinaOfficialSeries({ indicators, sources, series, previous });
  await loadBlsOfficialSeries({ indicators, sources, series, previous });
  await loadBeaGdpMirror({ indicators, sources, series, previous });
  await loadEurostatSeries({ indicators, sources, series, previous });
  await loadBrazilIbgeInflation({ indicators, sources, series, previous });
  await loadOnsOfficialSeries({ indicators, sources, series, previous });
  await loadRbaOfficialSeries({ indicators, sources, series, previous });
  await loadJapanOfficialSeries({ indicators, sources, series, previous });
  applyPreviousFallbacks({ countries, indicators, series, previous });

  const calendar = enrichCalendarWithPrevious(await loadCalendar({ countries, sources, calendarConfig }), series, indicators);

  const generatedAt = new Date().toISOString();
  const output = {
    metadata: {
      generatedAt,
      timezone: TZ,
      status: warnings.some((warning) => warning.level === "error") ? "updated_with_warnings" : "updated",
      countryScope: "G20 soberano con Argentina destacada",
      sourcePolicy: "Fuentes oficiales gratuitas; Banco Mundial queda como fallback anual cuando no hay fuente coyuntural configurada. Para Argentina se usa TAMAR BCRA como tasa de referencia."
    },
    countries,
    indicators: indicators.map(stripSourceConfig),
    series,
    calendar,
    warnings
  };

  await writeDataFile(output);
  log(`Actualizacion completa: ${countries.length} paises, ${calendar.length} eventos, ${warnings.length} alertas`);
}

async function ensureDirs() {
  await fs.mkdir(path.join(ROOT, "data"), { recursive: true });
  await fs.mkdir(path.join(ROOT, "logs"), { recursive: true });
}

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}`;
  console.log(line);
  fs.mkdir(path.dirname(paths.logFile), { recursive: true })
    .then(() => fs.appendFile(paths.logFile, `${line}\n`, "utf8"))
    .catch(() => {});
}

function warn(level, source, message) {
  warnings.push({ level, source, message });
  log(`${level.toUpperCase()} ${source}: ${message}`);
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

async function readPreviousData() {
  try {
    const text = await fs.readFile(paths.dataFile, "utf8");
    const match = text.match(/window\.MONITOR_DATA\s*=\s*([\s\S]*?);\s*$/);
    return match ? JSON.parse(match[1]) : null;
  } catch {
    return null;
  }
}

function initializeSeries(countries, indicators) {
  const series = {};
  for (const country of countries) {
    series[country.iso3] = {};
    for (const indicator of indicators) {
      series[country.iso3][indicator.id] = null;
    }
  }
  return series;
}

async function loadWorldBankIndicators({ countries, indicators, sources, series, previous }) {
  const worldBankIndicators = indicators.filter((indicator) => indicator.primarySource?.type === "worldBank");
  const fallbackIndicators = indicators.filter((indicator) => indicator.fallbackSource?.type === "worldBank");
  const uniqueRequests = new Map();

  for (const indicator of [...worldBankIndicators, ...fallbackIndicators]) {
    const config = indicator.primarySource?.type === "worldBank" ? indicator.primarySource : indicator.fallbackSource;
    uniqueRequests.set(config.indicator, { indicator, config });
  }

  for (const { indicator, config } of uniqueRequests.values()) {
    try {
      const rows = await fetchWorldBankRows(countries, sources.worldBank, config.indicator);
      const grouped = groupWorldBankRows(rows);

      for (const country of countries) {
        const values = grouped.get(country.iso3) || [];
        const metric = buildMetric({
          indicator,
          values,
          source: "worldBank",
          sourceName: sources.worldBank.name,
          frequency: "Anual",
          sourceUrl: sources.worldBank.url
        });

        if (indicator.primarySource?.indicator === config.indicator) {
          series[country.iso3][indicator.id] = metric || getPreviousMetric(previous, country.iso3, indicator.id, "World Bank sin dato actual");
        } else if (!series[country.iso3][indicator.id] && metric) {
          series[country.iso3][indicator.id] = metric;
        }
      }
    } catch (error) {
      warn("error", sources.worldBank.name, `No se pudo descargar ${config.indicator}: ${error.message}`);
      for (const country of countries) {
        if (indicator.primarySource?.indicator === config.indicator) {
          series[country.iso3][indicator.id] = getPreviousMetric(previous, country.iso3, indicator.id, "Fallo World Bank");
        }
      }
    }
  }
}

async function fetchWorldBankRows(countries, source, indicatorCode) {
  const countryCodes = countries.map((country) => country.worldBankCode).join(";");
  const url = `${source.baseUrl}/country/${countryCodes}/indicator/${indicatorCode}?format=json&per_page=20000&date=${START_YEAR}:${END_YEAR}`;
  const payload = await fetchJson(url, 45000);
  if (!Array.isArray(payload) || !Array.isArray(payload[1])) {
    throw new Error("Respuesta inesperada");
  }
  return payload[1];
}

function groupWorldBankRows(rows) {
  const grouped = new Map();
  for (const row of rows) {
    const value = parseNumberCell(row.value);
    if (!Number.isFinite(value)) continue;
    const iso3 = row.countryiso3code;
    if (!grouped.has(iso3)) grouped.set(iso3, []);
    grouped.get(iso3).push({
      period: row.date,
      date: `${row.date}-12-31`,
      value
    });
  }
  for (const values of grouped.values()) {
    values.sort((a, b) => a.date.localeCompare(b.date));
  }
  return grouped;
}

async function loadIlostatUnemployment({ countries, indicators, sources, series, previous }) {
  const indicator = indicators.find((item) => item.id === "unemployment");
  if (!indicator) return;

  try {
    const text = await fetchText(sources.ilostat.indicatorUrl, 90000);
    const grouped = parseIlostatQuarterly(text, new Set(countries.map((country) => country.iloCode)));

    for (const country of countries) {
      const values = grouped.get(country.iloCode) || [];
      const metric = buildMetric({
        indicator,
        values,
        source: "ilostat",
        sourceName: sources.ilostat.name,
        frequency: "Trimestral",
        sourceUrl: sources.ilostat.url
      });
      if (metric) {
        series[country.iso3][indicator.id] = metric;
      } else if (!series[country.iso3][indicator.id]) {
        series[country.iso3][indicator.id] = getPreviousMetric(previous, country.iso3, indicator.id, "ILOSTAT sin dato actual");
      }
    }
  } catch (error) {
    warn("error", sources.ilostat.name, `No se pudo descargar desempleo trimestral: ${error.message}`);
    for (const country of countries) {
      if (!series[country.iso3][indicator.id]) {
        series[country.iso3][indicator.id] = getPreviousMetric(previous, country.iso3, indicator.id, "Fallo ILOSTAT");
      }
    }
  }
}

function parseIlostatQuarterly(text, countryCodes) {
  const grouped = new Map();
  const lines = text.split(/\r?\n/);
  const header = parseCsvLine(lines[0]);
  const index = headerIndex(header);

  for (let lineIndex = 1; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex];
    if (!line) continue;
    const row = parseCsvLine(line);
    const country = row[index.ref_area];
    if (!countryCodes.has(country)) continue;
    if (row[index.sex] !== "SEX_T") continue;
    if (row[index.classif1] !== "AGE_YTHADULT_YGE15") continue;

    const value = parseNumberCell(row[index.obs_value]);
    if (!Number.isFinite(value)) continue;
    const period = parseIloPeriod(row[index.time]);
    if (!period) continue;

    if (!grouped.has(country)) grouped.set(country, new Map());
    grouped.get(country).set(period.period, {
      period: period.label,
      date: period.date,
      value
    });
  }

  const normalized = new Map();
  for (const [country, byPeriod] of grouped.entries()) {
    normalized.set(country, Array.from(byPeriod.values()).sort((a, b) => a.date.localeCompare(b.date)));
  }
  return normalized;
}

async function loadBisPolicyRates({ countries, indicators, sources, series, previous }) {
  const indicator = indicators.find((item) => item.id === "policyRate");
  if (!indicator) return;

  try {
    const buffer = await fetchBuffer(sources.bis.bulkCsvZipUrl, 90000);
    const csv = extractFirstCsvFromZip(buffer);
    const neededAreas = new Set(countries.map((country) => country.policyRateArea));
    const grouped = parseBisPolicyCsv(csv, neededAreas);

    for (const country of countries) {
      const values = grouped.get(country.policyRateArea) || [];
      const metric = buildMetric({
        indicator,
        values,
        source: "bis",
        sourceName: country.policyRateArea === "XM" ? `${sources.bis.name} (euro area)` : sources.bis.name,
        frequency: "Mensual",
        sourceUrl: sources.bis.url
      });
      series[country.iso3][indicator.id] = metric || getPreviousMetric(previous, country.iso3, indicator.id, "BIS sin dato actual");
    }
  } catch (error) {
    warn("error", sources.bis.name, `No se pudo descargar tasas BIS: ${error.message}`);
    for (const country of countries) {
      series[country.iso3][indicator.id] = getPreviousMetric(previous, country.iso3, indicator.id, "Fallo BIS");
    }
  }
}

function parseBisPolicyCsv(csv, neededAreas) {
  const grouped = new Map();
  const lines = csv.split(/\r?\n/).filter(Boolean);
  const header = parseCsvLine(lines[0]);
  const dateIndexes = header
    .map((name, index) => ({ name, index }))
    .filter((item) => /^\d{4}-\d{2}$/.test(item.name) && Number(item.name.slice(0, 4)) >= START_YEAR);

  for (let lineIndex = 1; lineIndex < lines.length; lineIndex += 1) {
    const row = parseCsvLine(lines[lineIndex]);
    const frequency = row[0];
    const area = row[2];
    if (frequency !== "M" || !neededAreas.has(area)) continue;

    const values = [];
    for (const item of dateIndexes) {
      const value = parseNumberCell(row[item.index]);
      if (!Number.isFinite(value)) continue;
      values.push({
        period: item.name,
        date: monthEndDate(item.name),
        value
      });
    }
    grouped.set(area, values.sort((a, b) => a.date.localeCompare(b.date)));
  }
  return grouped;
}

async function loadBcraArgentinaTamar({ indicators, sources, series, previous }) {
  const source = sources.bcraTamar;
  if (!source) return;
  const indicator = getIndicatorConfig(indicators, "policyRate");
  const startDate = `${END_YEAR - 2}-01-01`;
  const endDate = todayIsoInZone(TZ);
  const variableId = source.series.tamarNominalAnnualPublicPrivate;

  try {
    const payload = await fetchJson(`${source.baseUrl}/${variableId}?desde=${startDate}&hasta=${endDate}&limit=2000`, 45000);
    const rows = payload.results?.[0]?.detalle || [];
    const values = rows.map((row) => ({
      period: row.fecha,
      date: row.fecha,
      value: parseNumberCell(row.valor)
    })).filter((point) => Number.isFinite(point.value));

    setMetricIfNewer(series, "ARG", "policyRate", buildMetric({
      indicator,
      values,
      source: "bcraTamar",
      sourceName: source.name,
      frequency: "Diaria",
      sourceUrl: source.url,
      note: "TAMAR de bancos publicos y privados, TNA. Argentina opera con tasa endogena; se usa TAMAR como tasa de referencia."
    }) || getPreviousMetric(previous, "ARG", "policyRate", "BCRA sin TAMAR actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar TAMAR Argentina: ${error.message}`);
  }
}

async function loadOecdG20Prices({ countries, indicators, sources, series, previous }) {
  const source = sources.oecdDbnomics;
  if (!source) return;
  const hicpCountries = new Set(["DEU", "FRA", "GBR", "ITA", "TUR"]);

  await Promise.all(countries.map(async (country) => {
    const methodology = hicpCountries.has(country.iso3) ? "HICP.CPI" : "N.CPI";
    const label = methodology === "HICP.CPI" ? "HICP all-items" : "CPI nacional all-items";

    try {
      const [yoyValues, momValues] = await Promise.all([
        fetchDbnomicsSeriesValues(source, "OECD", source.datasets.g20Prices, `${country.iso3}.M.${methodology}.PA._T.N.GY`, "Mensual"),
        fetchDbnomicsSeriesValues(source, "OECD", source.datasets.g20Prices, `${country.iso3}.M.${methodology}.PC._T.N.G1`, "Mensual")
      ]);

      setMetricIfNewer(series, country.iso3, "inflationYoy", buildMetric({
        indicator: getIndicatorConfig(indicators, "inflationYoy"),
        values: yoyValues || [],
        source: "oecdG20Prices",
        sourceName: `${source.name} (G20 prices)`,
        frequency: "Mensual",
        sourceUrl: source.url,
        note: `${label}, variacion interanual.`
      }) || getPreviousMetric(previous, country.iso3, "inflationYoy", "OECD G20 sin inflacion actual"));

      setMetricIfNewer(series, country.iso3, "inflationMom", buildMetric({
        indicator: getIndicatorConfig(indicators, "inflationMom"),
        values: momValues || [],
        source: "oecdG20Prices",
        sourceName: `${source.name} (G20 prices)`,
        frequency: "Mensual",
        sourceUrl: source.url,
        note: `${label}, variacion mensual.`
      }) || getPreviousMetric(previous, country.iso3, "inflationMom", "OECD G20 sin inflacion mensual"));
    } catch (error) {
      warn("warn", source.name, `No se pudo descargar inflacion OECD para ${country.iso3}: ${error.message}`);
    }
  }));
}

async function loadOecdG20Gdp({ countries, indicators, sources, series, previous }) {
  const source = sources.oecdDbnomics;
  if (!source) return;
  const indicator = getIndicatorConfig(indicators, "gdpGrowth");

  await Promise.all(countries.map(async (country) => {
    try {
      const values = await fetchDbnomicsSeriesValues(
        source,
        "OECD",
        source.datasets.g20Gdp,
        `Q.Y.${country.iso3}.S1.S1.B1GQ._Z._Z._Z.PC.L.G1.T0102`,
        "Trimestral"
      );

      setMetricIfNewer(series, country.iso3, "gdpGrowth", buildMetric({
        indicator,
        values: values || [],
        source: "oecdG20Gdp",
        sourceName: `${source.name} (QNA G20)`,
        frequency: "Trimestral",
        sourceUrl: source.url,
        note: "PIB real, cambio contra trimestre anterior, desestacionalizado."
      }) || getPreviousMetric(previous, country.iso3, "gdpGrowth", "OECD G20 sin PIB actual"));
    } catch (error) {
      warn("warn", source.name, `No se pudo descargar PIB OECD para ${country.iso3}: ${error.message}`);
    }
  }));
}

async function loadOecdMonthlyUnemployment({ countries, indicators, sources, series, previous }) {
  const source = sources.oecdDbnomics;
  if (!source) return;
  const indicator = getIndicatorConfig(indicators, "unemployment");

  await Promise.all(countries.map(async (country) => {
    const candidates = [
      `${country.iso3}.UNE_LF_M.PT_LF_SUB._Z.Y._T.Y_GE15._Z.M`,
      `${country.iso3}.UNE_LF_M.PT_LF_SUB._Z.N._T.Y_GE15._Z.M`
    ];

    try {
      let values = null;
      for (const seriesCode of candidates) {
        values = await fetchDbnomicsSeriesValues(source, "OECD", source.datasets.monthlyUnemployment, seriesCode, "Mensual");
        if (values?.length) break;
      }

      setMetricIfNewer(series, country.iso3, "unemployment", buildMetric({
        indicator,
        values: values || [],
        source: "oecdMonthlyUnemployment",
        sourceName: `${source.name} (monthly unemployment)`,
        frequency: "Mensual",
        sourceUrl: source.url,
        note: "Tasa de desempleo mensual, total 15+."
      }) || getPreviousMetric(previous, country.iso3, "unemployment", "OECD sin desempleo mensual"));
    } catch (error) {
      warn("warn", source.name, `No se pudo descargar desempleo OECD para ${country.iso3}: ${error.message}`);
    }
  }));
}

async function loadArgentinaOfficialSeries({ indicators, sources, series, previous }) {
  const source = sources.argentinaSeries;
  if (!source) return;

  try {
    const cpiRows = await fetchArgentinaSeries(source, source.series.cpiIndex, "2018-01-01");
    const cpiIndex = cpiRows.map(([date, value]) => ({
      period: date.slice(0, 7),
      date: monthEndDate(date.slice(0, 7)),
      value: parseNumberCell(value)
    })).filter((point) => Number.isFinite(point.value));

    setMetric(series, "ARG", "inflationYoy", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationYoy"),
      values: rateFromIndex(cpiIndex, 12),
      source: "argentinaSeries",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "IPC Nacional, variacion contra igual mes del ano anterior."
    }) || getPreviousMetric(previous, "ARG", "inflationYoy", "INDEC sin IPC actual"));

    setMetric(series, "ARG", "inflationMom", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationMom"),
      values: rateFromIndex(cpiIndex, 1),
      source: "argentinaSeries",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "IPC Nacional, variacion contra mes anterior."
    }) || getPreviousMetric(previous, "ARG", "inflationMom", "INDEC sin IPC actual"));
  } catch (error) {
    warn("error", source.name, `No se pudo descargar IPC Argentina: ${error.message}`);
  }

  try {
    const emaeRows = await fetchArgentinaSeries(source, source.series.emaeSeasonallyAdjustedMom, "2022-01-01");
    const values = emaeRows.map(([date, value]) => ({
      period: date.slice(0, 7),
      date: monthEndDate(date.slice(0, 7)),
      value: scaleArgentinaRate(value)
    })).filter((point) => Number.isFinite(point.value));

    setMetric(series, "ARG", "gdpGrowth", buildMetric({
      indicator: getIndicatorConfig(indicators, "gdpGrowth"),
      values,
      source: "argentinaSeries",
      sourceName: `${source.name} (EMAE s.e.)`,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "Proxy mensual de actividad economica: EMAE desestacionalizado, variacion mensual."
    }) || getPreviousMetric(previous, "ARG", "gdpGrowth", "INDEC sin EMAE actual"));
  } catch (error) {
    warn("error", source.name, `No se pudo descargar EMAE Argentina: ${error.message}`);
  }

  try {
    const rows = await fetchArgentinaSeries(source, source.series.unemployment, "2022-01-01");
    const values = rows.map(([date, value]) => ({
      period: quarterLabelFromDate(date),
      date: quarterEndDateFromDate(date),
      value: scaleArgentinaRate(value)
    })).filter((point) => Number.isFinite(point.value));

    setMetric(series, "ARG", "unemployment", buildMetric({
      indicator: getIndicatorConfig(indicators, "unemployment"),
      values,
      source: "argentinaSeries",
      sourceName: `${source.name} (EPH)`,
      frequency: "Trimestral",
      sourceUrl: source.url
    }) || getPreviousMetric(previous, "ARG", "unemployment", "INDEC sin desempleo actual"));
  } catch (error) {
    warn("error", source.name, `No se pudo descargar desempleo Argentina: ${error.message}`);
  }
}

async function fetchArgentinaSeries(source, seriesId, startDate) {
  // limit explicito: la API de datos.gob.ar devuelve solo 100 filas por defecto.
  // Sin esto, una serie mensual arrancada en 2018 se cortaba en abril de 2026
  // (la fila 100) y arrastraba ese dato como si fuera el ultimo publicado.
  const url = `${source.baseUrl}?ids=${encodeURIComponent(seriesId)}&start_date=${startDate}&format=json&limit=5000`;
  const payload = await fetchJson(url, 45000);
  if (!Array.isArray(payload.data)) throw new Error(`Respuesta inesperada para ${seriesId}`);
  return payload.data;
}

async function loadBlsOfficialSeries({ indicators, sources, series, previous }) {
  const source = sources.blsPublic;
  if (!source) return;

  try {
    const payload = await postJson(source.timeseriesUrl, {
      seriesid: [
        source.series.cpiAllItemsNsa,
        source.series.cpiAllItemsSa,
        source.series.unemploymentRate
      ],
      startyear: String(Math.max(START_YEAR, END_YEAR - 8)),
      endyear: String(END_YEAR)
    }, 45000);
    const byId = new Map((payload.Results?.series || []).map((item) => [item.seriesID, item.data || []]));

    const cpiNsa = parseBlsMonthlyIndex(byId.get(source.series.cpiAllItemsNsa) || []);
    const cpiSa = parseBlsMonthlyIndex(byId.get(source.series.cpiAllItemsSa) || []);
    const unemployment = parseBlsRateSeries(byId.get(source.series.unemploymentRate) || []);

    setMetric(series, "USA", "inflationYoy", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationYoy"),
      values: rateFromIndex(cpiNsa, 12),
      source: "blsPublic",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "CPI all urban consumers, all items, variacion interanual."
    }) || getPreviousMetric(previous, "USA", "inflationYoy", "BLS sin CPI actual"));

    setMetric(series, "USA", "inflationMom", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationMom"),
      values: rateFromIndex(cpiSa, 1),
      source: "blsPublic",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "CPI all urban consumers, all items, desestacionalizado, variacion mensual."
    }) || getPreviousMetric(previous, "USA", "inflationMom", "BLS sin CPI actual"));

    setMetric(series, "USA", "unemployment", buildMetric({
      indicator: getIndicatorConfig(indicators, "unemployment"),
      values: unemployment,
      source: "blsPublic",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url
    }) || getPreviousMetric(previous, "USA", "unemployment", "BLS sin desempleo actual"));
  } catch (error) {
    warn("error", source.name, `No se pudo descargar BLS: ${error.message}`);
  }
}

function parseBlsMonthlyIndex(rows) {
  return rows
    .map((row) => {
      const period = parseBlsPeriod(row);
      const value = parseNumberCell(row.value);
      return period && Number.isFinite(value) ? { ...period, value } : null;
    })
    .filter(Boolean)
    .sort((a, b) => a.date.localeCompare(b.date));
}

function parseBlsRateSeries(rows) {
  return parseBlsMonthlyIndex(rows);
}

function parseBlsPeriod(row) {
  const match = String(row.period || "").match(/^M(\d{2})$/);
  if (!match || match[1] === "13") return null;
  const yearMonth = `${row.year}-${match[1]}`;
  return {
    period: yearMonth,
    date: monthEndDate(yearMonth)
  };
}

async function loadBeaGdpMirror({ indicators, sources, series, previous }) {
  const source = sources.beaDbnomics;
  if (!source) return;

  try {
    const payload = await fetchJson(source.gdpSeriesUrl, 45000);
    const doc = payload.series?.docs?.[0];
    if (!doc || !Array.isArray(doc.period) || !Array.isArray(doc.value)) throw new Error("Respuesta inesperada");
    const values = doc.period.map((period, index) => ({
      period,
      date: doc.period_start_day?.[index] || quarterEndDate(period),
      value: parseNumberCell(doc.value[index])
    })).filter((point) => Number.isFinite(point.value) && Number(point.period.slice(0, 4)) >= START_YEAR);

    setMetric(series, "USA", "gdpGrowth", buildMetric({
      indicator: getIndicatorConfig(indicators, "gdpGrowth"),
      values,
      source: "beaDbnomics",
      sourceName: source.name,
      frequency: "Trimestral",
      sourceUrl: source.url,
      note: "PIB real, cambio trimestral anualizado. El endpoint directo BEA requiere UserID; DBnomics replica la tabla NIPA."
    }) || getPreviousMetric(previous, "USA", "gdpGrowth", "BEA mirror sin dato actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar PIB EE.UU.: ${error.message}`);
  }
}

async function loadEurostatSeries({ indicators, sources, series, previous }) {
  const source = sources.eurostat;
  if (!source) return;
  const geoToIso = new Map([["DE", "DEU"], ["FR", "FRA"], ["IT", "ITA"]]);
  const geoParams = Array.from(geoToIso.keys()).map((geo) => `geo=${geo}`).join("&");

  await loadEurostatMetric({
    url: `${source.baseUrl}/prc_hicp_minr?${geoParams}&coicop18=TOTAL&unit=RCH_A&sinceTimePeriod=${END_YEAR - 3}-01`,
    source,
    geoToIso,
    indicator: getIndicatorConfig(indicators, "inflationYoy"),
    indicatorId: "inflationYoy",
    series,
    previous,
    frequency: "Mensual",
    note: "HICP all-items, variacion interanual."
  });

  await loadEurostatMetric({
    url: `${source.baseUrl}/prc_hicp_minr?${geoParams}&coicop18=TOTAL&unit=RCH_M&sinceTimePeriod=${END_YEAR - 3}-01`,
    source,
    geoToIso,
    indicator: getIndicatorConfig(indicators, "inflationMom"),
    indicatorId: "inflationMom",
    series,
    previous,
    frequency: "Mensual",
    note: "HICP all-items, variacion mensual."
  });

  await loadEurostatMetric({
    url: `${source.baseUrl}/namq_10_gdp?${geoParams}&na_item=B1GQ&s_adj=SCA&unit=CLV_PCH_PRE&sinceTimePeriod=${END_YEAR - 3}-Q1`,
    source,
    geoToIso,
    indicator: getIndicatorConfig(indicators, "gdpGrowth"),
    indicatorId: "gdpGrowth",
    series,
    previous,
    frequency: "Trimestral",
    note: "PIB real, cambio contra trimestre anterior, desestacionalizado."
  });

  await loadEurostatMetric({
    url: `${source.baseUrl}/une_rt_m?${geoParams}&sex=T&age=TOTAL&s_adj=SA&unit=PC_ACT&sinceTimePeriod=${END_YEAR - 3}-01`,
    source,
    geoToIso,
    indicator: getIndicatorConfig(indicators, "unemployment"),
    indicatorId: "unemployment",
    series,
    previous,
    frequency: "Mensual",
    note: "Tasa de desempleo armonizada, desestacionalizada."
  });
}

async function loadEurostatMetric({ url, source, geoToIso, indicator, indicatorId, series, previous, frequency, note }) {
  try {
    const payload = await fetchJson(url, 45000);
    const grouped = jsonStatToGeoSeries(payload);
    for (const [geo, values] of grouped.entries()) {
      const iso3 = geoToIso.get(geo);
      if (!iso3) continue;
      setMetric(series, iso3, indicatorId, buildMetric({
        indicator,
        values,
        source: "eurostat",
        sourceName: source.name,
        frequency,
        sourceUrl: source.url,
        note
      }) || getPreviousMetric(previous, iso3, indicatorId, "Eurostat sin dato actual"));
    }
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar ${indicatorId}: ${error.message}`);
  }
}

async function loadBrazilIbgeInflation({ indicators, sources, series, previous }) {
  const source = sources.ibgeSidra;
  if (!source) return;

  try {
    const payload = await fetchJson(source.ipcaMonthlyUrl, 45000);
    if (!Array.isArray(payload)) throw new Error("Respuesta inesperada");
    const momValues = payload.slice(1)
      .filter((row) => row.D2C === "63")
      .map((row) => {
        const period = `${String(row.D3C).slice(0, 4)}-${String(row.D3C).slice(4, 6)}`;
        return {
          period,
          date: monthEndDate(period),
          value: parseNumberCell(row.V)
        };
      })
      .filter((point) => Number.isFinite(point.value))
      .sort((a, b) => a.date.localeCompare(b.date));

    const yoyValues = compoundRollingRates(momValues, 12);
    setMetric(series, "BRA", "inflationMom", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationMom"),
      values: momValues,
      source: "ibgeSidra",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "IPCA, variacion mensual."
    }) || getPreviousMetric(previous, "BRA", "inflationMom", "IBGE sin IPCA actual"));

    setMetric(series, "BRA", "inflationYoy", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationYoy"),
      values: yoyValues,
      source: "ibgeSidra",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "IPCA, acumulado compuesto de los ultimos 12 meses a partir de variaciones mensuales SIDRA."
    }) || getPreviousMetric(previous, "BRA", "inflationYoy", "IBGE sin IPCA actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar IPCA Brasil: ${error.message}`);
  }
}

async function loadOnsOfficialSeries({ indicators, sources, series, previous }) {
  const source = sources.onsDbnomics;
  if (!source) return;

  try {
    const yoyValues = await fetchConfiguredDbnomicsSeries(source, source.series.inflationYoy, "Mensual");
    setMetricIfNewer(series, "GBR", "inflationYoy", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationYoy"),
      values: yoyValues || [],
      source: "onsDbnomics",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "CPI all-items, variacion interanual."
    }) || getPreviousMetric(previous, "GBR", "inflationYoy", "ONS sin CPI actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar inflacion interanual Reino Unido: ${error.message}`);
  }

  try {
    const momValues = await fetchConfiguredDbnomicsSeries(source, source.series.inflationMom, "Mensual");
    setMetricIfNewer(series, "GBR", "inflationMom", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationMom"),
      values: momValues || [],
      source: "onsDbnomics",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "CPI all-items, variacion mensual."
    }) || getPreviousMetric(previous, "GBR", "inflationMom", "ONS sin CPI actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar inflacion mensual Reino Unido: ${error.message}`);
  }

  try {
    const values = await fetchConfiguredDbnomicsSeries(source, source.series.gdpGrowth, "Trimestral");
    setMetricIfNewer(series, "GBR", "gdpGrowth", buildMetric({
      indicator: getIndicatorConfig(indicators, "gdpGrowth"),
      values: values || [],
      source: "onsDbnomics",
      sourceName: source.name,
      frequency: "Trimestral",
      sourceUrl: source.url,
      note: "PIB real, cambio contra trimestre anterior, desestacionalizado."
    }) || getPreviousMetric(previous, "GBR", "gdpGrowth", "ONS sin PIB actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar PIB Reino Unido: ${error.message}`);
  }

  try {
    const values = await fetchConfiguredDbnomicsSeries(source, source.series.unemployment, "Mensual");
    setMetricIfNewer(series, "GBR", "unemployment", buildMetric({
      indicator: getIndicatorConfig(indicators, "unemployment"),
      values: values || [],
      source: "onsDbnomics",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "Tasa de desempleo 16+, desestacionalizada."
    }) || getPreviousMetric(previous, "GBR", "unemployment", "ONS sin desempleo actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar desempleo Reino Unido: ${error.message}`);
  }
}

async function loadRbaOfficialSeries({ indicators, sources, series, previous }) {
  const source = sources.rbaDbnomics;
  if (!source) return;

  try {
    const yoyValues = await fetchConfiguredDbnomicsSeries(source, source.series.inflationYoy, "Mensual");
    setMetricIfNewer(series, "AUS", "inflationYoy", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationYoy"),
      values: yoyValues || [],
      source: "rbaDbnomics",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "Inflacion year-ended de la coleccion mensual CPI; RBA publica la serie derivada de ABS."
    }) || getPreviousMetric(previous, "AUS", "inflationYoy", "RBA sin CPI actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar inflacion interanual Australia: ${error.message}`);
  }

  try {
    const momValues = await fetchConfiguredDbnomicsSeries(source, source.series.inflationMom, "Mensual");
    setMetricIfNewer(series, "AUS", "inflationMom", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationMom"),
      values: momValues || [],
      source: "rbaDbnomics",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "Inflacion mensual de la coleccion mensual CPI; RBA publica la serie derivada de ABS."
    }) || getPreviousMetric(previous, "AUS", "inflationMom", "RBA sin CPI actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar inflacion mensual Australia: ${error.message}`);
  }

  try {
    const values = await fetchConfiguredDbnomicsSeries(source, source.series.unemployment, "Mensual");
    setMetricIfNewer(series, "AUS", "unemployment", buildMetric({
      indicator: getIndicatorConfig(indicators, "unemployment"),
      values: values || [],
      source: "rbaDbnomics",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "Tasa de desempleo mensual, desestacionalizada."
    }) || getPreviousMetric(previous, "AUS", "unemployment", "RBA sin desempleo actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar desempleo Australia: ${error.message}`);
  }
}

async function loadJapanOfficialSeries({ indicators, sources, series, previous }) {
  const source = sources.statJapanDbnomics;
  if (!source) return;

  try {
    const cpiIndex = await fetchConfiguredDbnomicsSeries(source, source.series.cpiAllItems, "Mensual");
    const cpiSaIndex = await fetchConfiguredDbnomicsSeries(source, source.series.cpiAllItemsSa, "Mensual");

    setMetricIfNewer(series, "JPN", "inflationYoy", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationYoy"),
      values: rateFromIndex(cpiIndex || [], 12),
      source: "statJapanDbnomics",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "CPI all-items, variacion contra igual mes del ano anterior."
    }) || getPreviousMetric(previous, "JPN", "inflationYoy", "Statistics Japan sin CPI actual"));

    setMetricIfNewer(series, "JPN", "inflationMom", buildMetric({
      indicator: getIndicatorConfig(indicators, "inflationMom"),
      values: rateFromIndex(cpiSaIndex || [], 1),
      source: "statJapanDbnomics",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "CPI all-items desestacionalizado, variacion mensual."
    }) || getPreviousMetric(previous, "JPN", "inflationMom", "Statistics Japan sin CPI actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar CPI Japon: ${error.message}`);
  }

  try {
    const values = await fetchConfiguredDbnomicsSeries(source, source.series.unemployment, "Mensual");
    setMetricIfNewer(series, "JPN", "unemployment", buildMetric({
      indicator: getIndicatorConfig(indicators, "unemployment"),
      values: values || [],
      source: "statJapanDbnomics",
      sourceName: source.name,
      frequency: "Mensual",
      sourceUrl: source.url,
      note: "Tasa de desempleo mensual, ambos sexos, desestacionalizada."
    }) || getPreviousMetric(previous, "JPN", "unemployment", "Statistics Japan sin desempleo actual"));
  } catch (error) {
    warn("warn", source.name, `No se pudo descargar desempleo Japon: ${error.message}`);
  }
}

function compoundRollingRates(points, windowSize) {
  const output = [];
  for (let index = windowSize - 1; index < points.length; index += 1) {
    const window = points.slice(index - windowSize + 1, index + 1);
    if (window.length !== windowSize || window.some((point) => !Number.isFinite(point.value))) continue;
    const compounded = window.reduce((product, point) => product * (1 + point.value / 100), 1);
    output.push({
      period: points[index].period,
      date: points[index].date,
      value: (compounded - 1) * 100
    });
  }
  return output;
}

function jsonStatToGeoSeries(payload) {
  const order = payload.id || [];
  const sizes = payload.size || [];
  const value = payload.value || {};
  const dimensions = payload.dimension || {};
  const codeByPosition = new Map();

  for (const dimensionId of order) {
    const index = dimensions[dimensionId]?.category?.index || {};
    const reverse = [];
    for (const [code, position] of Object.entries(index)) {
      reverse[position] = code;
    }
    codeByPosition.set(dimensionId, reverse);
  }

  const grouped = new Map();
  for (const [flatIndex, rawValue] of Object.entries(value)) {
    const coords = coordinatesForIndex(Number(flatIndex), sizes, order, codeByPosition);
    const geo = coords.geo;
    const time = coords.time;
    const parsedValue = parseNumberCell(rawValue);
    if (!geo || !time || !Number.isFinite(parsedValue)) continue;
    if (!grouped.has(geo)) grouped.set(geo, []);
    grouped.get(geo).push({
      period: time,
      date: time.includes("Q") ? quarterEndDate(time) : monthEndDate(time),
      value: parsedValue
    });
  }

  for (const values of grouped.values()) {
    values.sort((a, b) => a.date.localeCompare(b.date));
  }
  return grouped;
}

function coordinatesForIndex(flatIndex, sizes, order, codeByPosition) {
  const coords = {};
  let remaining = flatIndex;

  for (let index = order.length - 1; index >= 0; index -= 1) {
    const dimensionId = order[index];
    const size = sizes[index] || 1;
    const position = remaining % size;
    coords[dimensionId] = codeByPosition.get(dimensionId)?.[position];
    remaining = Math.floor(remaining / size);
  }
  return coords;
}

async function loadCalendar({ countries, sources, calendarConfig }) {
  const events = [];
  const countryByIso = new Map(countries.map((country) => [country.iso3, country]));
  const startIso = todayIsoInZone(TZ);
  const endIso = addDaysIso(startIso, (calendarConfig.windowDays || 7) - 1);

  if (calendarConfig.imfDsbb?.enabled) {
    try {
      events.push(...await loadImfWeekAhead({ sources, calendarConfig, countryByIso, startIso, endIso }));
    } catch (error) {
      warn("error", sources.imfDsbb.name, `No se pudo descargar calendario IMF DSBB: ${error.message}`);
    }
  }

  if (calendarConfig.bls?.enabled) {
    try {
      events.push(...await loadBlsCalendar({ sources, calendarConfig, countryByIso, startIso, endIso }));
    } catch (error) {
      warn("error", sources.bls.name, `No se pudo descargar calendario BLS: ${error.message}`);
    }
  }

  return dedupeEvents(events)
    .filter((event) => event.date >= startIso && event.date <= endIso)
    .sort((a, b) => `${a.date}${a.timeLocal || ""}${a.title}`.localeCompare(`${b.date}${b.timeLocal || ""}${b.title}`));
}

async function loadImfWeekAhead({ sources, calendarConfig, countryByIso, startIso, endIso }) {
  const rows = await fetchJson(sources.imfDsbb.weekAheadUrl, 45000);
  if (!Array.isArray(rows)) throw new Error("Respuesta inesperada");
  const include = new Set(calendarConfig.imfDsbb.includeCountryCodes);
  const events = [];

  for (const row of rows) {
    if (!include.has(row.CountryCode)) continue;
    const date = isoFromParts(row.AdYear, row.AdMonth, row.AdDate);
    if (date < startIso || date > endIso) continue;
    const rule = matchRule(row.CategoryDes, calendarConfig.imfDsbb.categoryRules);
    if (!rule) continue;
    const country = countryByIso.get(row.CountryCode);

    events.push({
      id: `imf-${row.CountryCode}-${date}-${slug(row.CategoryDes)}-${slug(row.AdPeriod)}`,
      date,
      timeLocal: null,
      countryIso3: row.CountryCode,
      countryName: country?.name || row.CountryName,
      title: row.CategoryDes,
      indicator: rule.indicator,
      importance: rule.importance,
      period: row.AdPeriod || "",
      sourceName: sources.imfDsbb.name,
      url: row.NSDPUrl || sources.imfDsbb.url
    });
  }
  return events;
}

async function loadBlsCalendar({ sources, calendarConfig, countryByIso, startIso, endIso }) {
  const text = await fetchText(sources.bls.icsUrl, 45000);
  const items = parseIcsEvents(text);
  const country = countryByIso.get(calendarConfig.bls.countryIso3);
  const events = [];

  for (const item of items) {
    const rule = matchRule(item.summary, calendarConfig.bls.keywordRules);
    if (!rule || !item.start) continue;
    const dateTime = parseIcsDateTime(item.start);
    if (!dateTime) continue;
    const instant = zonedDateTimeToUtc(dateTime, "America/New_York");
    const date = formatDateInZone(instant, TZ);
    if (date < startIso || date > endIso) continue;

    events.push({
      id: `bls-${date}-${slug(item.summary)}`,
      date,
      timeLocal: formatTimeInZone(instant, TZ),
      countryIso3: calendarConfig.bls.countryIso3,
      countryName: country?.name || "Estados Unidos",
      title: item.summary,
      indicator: rule.indicator,
      importance: rule.importance,
      period: "",
      sourceName: sources.bls.name,
      url: sources.bls.url
    });
  }
  return events;
}

function enrichCalendarWithPrevious(events, series, indicators) {
  return events.map((event) => {
    if (String(event.title || "").toLowerCase().includes("producer price")) {
      return {
        ...event,
        previous: {
          available: false,
          note: "PPI no esta configurado todavia en la V2; se conserva el evento oficial."
        }
      };
    }

    const indicatorId = event.indicator === "inflation" ? "inflationYoy" : event.indicator;
    const metric = series?.[event.countryIso3]?.[indicatorId];
    const indicator = indicators.find((item) => item.id === indicatorId);
    if (!metric?.latest || !indicator) {
      return {
        ...event,
        previous: {
          available: false,
          note: "Dato previo no configurado para este pais/variable."
        }
      };
    }

    return {
      ...event,
      indicator: indicatorId,
      previous: {
        available: true,
        value: metric.latest.value,
        period: metric.latest.period,
        change: metric.latest.change,
        previousValue: metric.latest.previousValue,
        previousPeriod: metric.latest.previousPeriod,
        unit: metric.unit,
        precision: indicator.precision,
        sourceName: metric.sourceName,
        status: metric.status
      }
    };
  });
}

function applyPreviousFallbacks({ countries, indicators, series, previous }) {
  for (const country of countries) {
    for (const indicator of indicators) {
      if (series[country.iso3][indicator.id]) continue;
      series[country.iso3][indicator.id] = getPreviousMetric(previous, country.iso3, indicator.id, "Sin fuente configurada o sin dato");
    }
  }
}

function setMetric(series, iso3, indicatorId, metric) {
  if (!metric || !series[iso3]) return;
  series[iso3][indicatorId] = metric;
}

function setMetricIfNewer(series, iso3, indicatorId, metric) {
  if (!metric || !series[iso3]) return;
  const current = series[iso3][indicatorId];
  if (metric.status === "cached" && current?.status !== "cached") return;
  if (!current?.latest?.date) {
    series[iso3][indicatorId] = metric;
    return;
  }
  if (metric.latest?.date && metric.latest.date >= current.latest.date) {
    series[iso3][indicatorId] = metric;
    return;
  }
  if (current.source === "worldBank" && metric.status === "current") {
    series[iso3][indicatorId] = metric;
  }
}

function getIndicatorConfig(indicators, id) {
  return indicators.find((indicator) => indicator.id === id) || { id, unit: "%", precision: 1, staleAfterMonths: 12 };
}

function getPreviousMetric(previous, iso3, indicatorId, reason) {
  const metric = previous?.series?.[iso3]?.[indicatorId];
  if (!metric || !metric.latest) return null;
  return {
    ...metric,
    status: "cached",
    warning: reason
  };
}

function buildMetric({ indicator, values, source, sourceName, frequency, sourceUrl, note = "" }) {
  const cleanValues = values
    .filter((point) => Number.isFinite(point.value) && point.date)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-160);
  if (!cleanValues.length) return null;
  const latest = cleanValues[cleanValues.length - 1];
  const previous = cleanValues.length > 1 ? cleanValues[cleanValues.length - 2] : null;
  const enrichedLatest = {
    ...latest,
    previousValue: previous?.value ?? null,
    previousPeriod: previous?.period ?? null,
    change: previous ? latest.value - previous.value : null,
    changeUnit: "pp"
  };
  return {
    id: indicator.id,
    source,
    sourceName,
    sourceUrl,
    frequency,
    note,
    unit: indicator.unit,
    latest: enrichedLatest,
    status: computeStatus(latest.date, indicator.staleAfterMonths),
    values: cleanValues
  };
}

function computeStatus(dateIso, staleAfterMonths) {
  if (!dateIso) return "missing";
  const latestDate = new Date(`${dateIso}T12:00:00Z`);
  if (Number.isNaN(latestDate.getTime())) return "missing";
  const staleDate = new Date();
  staleDate.setUTCMonth(staleDate.getUTCMonth() - staleAfterMonths);
  return latestDate < staleDate ? "stale" : "current";
}

async function fetchText(url, timeoutMs) {
  const response = await fetchWithTimeout(url, timeoutMs);
  return response.text();
}

async function fetchJson(url, timeoutMs) {
  const response = await fetchWithTimeout(url, timeoutMs);
  return response.json();
}

async function postJson(url, body, timeoutMs) {
  const response = await fetchWithTimeout(url, timeoutMs, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "User-Agent": "ECOGO-Monitor-Mundial/2.0",
      "Accept": "application/json"
    },
    body: JSON.stringify(body)
  });
  return response.json();
}

async function fetchConfiguredDbnomicsSeries(source, config, frequency) {
  return fetchDbnomicsSeriesValues(source, config.provider, config.dataset, config.code, frequency);
}

async function fetchDbnomicsSeriesValues(source, provider, dataset, seriesCode, frequency) {
  const url = `${source.baseUrl}/${provider}/${encodeURIComponent(dataset)}/${encodeURIComponent(seriesCode)}?observations=1`;
  const payload = await fetchJsonOptional(url, 45000);
  if (!payload) return null;
  const doc = payload.series?.docs?.[0];
  if (!doc || !Array.isArray(doc.period) || !Array.isArray(doc.value)) return null;
  return dbnomicsDocToValues(doc, frequency);
}

async function fetchJsonOptional(url, timeoutMs) {
  try {
    return await fetchJson(url, timeoutMs);
  } catch (error) {
    if (String(error.message || "").includes("HTTP 404")) return null;
    throw error;
  }
}

function dbnomicsDocToValues(doc, frequency) {
  return doc.period.map((period, index) => {
    const normalized = normalizeDbnomicsPeriod(period, doc.period_start_day?.[index], frequency);
    const value = parseNumberCell(doc.value[index]);
    return normalized && Number.isFinite(value) ? { ...normalized, value } : null;
  }).filter(Boolean).sort((a, b) => a.date.localeCompare(b.date));
}

function normalizeDbnomicsPeriod(period, startDay, frequency) {
  const rawPeriod = String(period || "");
  if (/^\d{4}-Q[1-4]$/.test(rawPeriod)) {
    return {
      period: rawPeriod.replace("-Q", " T"),
      date: quarterEndDate(rawPeriod)
    };
  }
  if (/^\d{4}-\d{2}$/.test(rawPeriod)) {
    return {
      period: rawPeriod,
      date: monthEndDate(rawPeriod)
    };
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(rawPeriod)) {
    return {
      period: periodLabelForFrequency(rawPeriod, frequency),
      date: rawPeriod
    };
  }
  if (startDay && /^\d{4}-\d{2}-\d{2}$/.test(String(startDay))) {
    return {
      period: rawPeriod || periodLabelForFrequency(startDay, frequency),
      date: frequency === "Mensual" ? monthEndDate(String(startDay).slice(0, 7)) : String(startDay)
    };
  }
  return null;
}

function periodLabelForFrequency(dateIso, frequency) {
  if (frequency === "Mensual") return dateIso.slice(0, 7);
  if (frequency === "Trimestral") return quarterLabelFromDate(dateIso);
  return dateIso.slice(0, 4);
}

async function fetchBuffer(url, timeoutMs) {
  const response = await fetchWithTimeout(url, timeoutMs);
  return Buffer.from(await response.arrayBuffer());
}

async function fetchWithTimeout(url, timeoutMs, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        "User-Agent": "ECOGO-Monitor-Mundial/1.0",
        "Accept": "*/*",
        ...(options.headers || {})
      }
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response;
  } finally {
    clearTimeout(timer);
  }
}

function extractFirstCsvFromZip(buffer) {
  const eocdOffset = findEndOfCentralDirectory(buffer);
  const totalEntries = buffer.readUInt16LE(eocdOffset + 10);
  const centralDirectoryOffset = buffer.readUInt32LE(eocdOffset + 16);
  let cursor = centralDirectoryOffset;

  for (let entryIndex = 0; entryIndex < totalEntries; entryIndex += 1) {
    if (buffer.readUInt32LE(cursor) !== 0x02014b50) {
      throw new Error("ZIP central directory invalido");
    }

    const method = buffer.readUInt16LE(cursor + 10);
    const compressedSize = buffer.readUInt32LE(cursor + 20);
    const fileNameLength = buffer.readUInt16LE(cursor + 28);
    const extraLength = buffer.readUInt16LE(cursor + 30);
    const commentLength = buffer.readUInt16LE(cursor + 32);
    const localHeaderOffset = buffer.readUInt32LE(cursor + 42);
    const fileName = buffer.subarray(cursor + 46, cursor + 46 + fileNameLength).toString("utf8");

    if (fileName.toLowerCase().endsWith(".csv")) {
      const localNameLength = buffer.readUInt16LE(localHeaderOffset + 26);
      const localExtraLength = buffer.readUInt16LE(localHeaderOffset + 28);
      const dataStart = localHeaderOffset + 30 + localNameLength + localExtraLength;
      const compressed = buffer.subarray(dataStart, dataStart + compressedSize);
      const inflated = method === 8 ? zlib.inflateRawSync(compressed) : compressed;
      return inflated.toString("utf8");
    }

    cursor += 46 + fileNameLength + extraLength + commentLength;
  }
  throw new Error("No se encontro CSV en ZIP");
}

function findEndOfCentralDirectory(buffer) {
  const min = Math.max(0, buffer.length - 65557);
  for (let index = buffer.length - 22; index >= min; index -= 1) {
    if (buffer.readUInt32LE(index) === 0x06054b50) return index;
  }
  throw new Error("ZIP sin end of central directory");
}

function parseCsvLine(line) {
  const cells = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      if (quoted && line[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      cells.push(cell);
      cell = "";
    } else {
      cell += char;
    }
  }
  cells.push(cell);
  return cells;
}

function parseNumberCell(value) {
  if (value === null || value === undefined) return NaN;
  const text = String(value).trim();
  if (!text) return NaN;
  return Number(text);
}

function headerIndex(header) {
  return Object.fromEntries(header.map((name, index) => [name, index]));
}

function parseIloPeriod(value) {
  const quarter = String(value).match(/^(\d{4})Q([1-4])$/);
  if (quarter) {
    const year = quarter[1];
    const q = Number(quarter[2]);
    const endMonth = q * 3;
    return {
      period: `${year}Q${q}`,
      label: `${year} T${q}`,
      date: monthEndDate(`${year}-${String(endMonth).padStart(2, "0")}`)
    };
  }
  const month = String(value).match(/^(\d{4})M(\d{1,2})$/);
  if (month) {
    return {
      period: `${month[1]}M${month[2].padStart(2, "0")}`,
      label: `${month[1]}-${month[2].padStart(2, "0")}`,
      date: monthEndDate(`${month[1]}-${month[2].padStart(2, "0")}`)
    };
  }
  return null;
}

function rateFromIndex(points, periodsBack) {
  const byPeriod = new Map(points.map((point) => [point.period, point]));
  return points.map((point) => {
    const previousPeriod = shiftPeriod(point.period, -periodsBack);
    const previous = byPeriod.get(previousPeriod);
    if (!previous || !Number.isFinite(previous.value) || previous.value === 0) return null;
    return {
      period: point.period,
      date: point.date,
      value: ((point.value / previous.value) - 1) * 100
    };
  }).filter(Boolean);
}

function shiftPeriod(period, months) {
  const [year, month] = String(period).split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1 + months, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function scaleArgentinaRate(value) {
  const number = parseNumberCell(value);
  if (!Number.isFinite(number)) return NaN;
  return Math.abs(number) <= 1 ? number * 100 : number;
}

function quarterLabelFromDate(dateIso) {
  const [year, month] = String(dateIso).split("-").map(Number);
  const quarter = Math.floor((month - 1) / 3) + 1;
  return `${year} T${quarter}`;
}

function quarterEndDateFromDate(dateIso) {
  const [year, month] = String(dateIso).split("-").map(Number);
  const quarter = Math.floor((month - 1) / 3) + 1;
  return monthEndDate(`${year}-${String(quarter * 3).padStart(2, "0")}`);
}

function quarterEndDate(period) {
  const match = String(period).match(/^(\d{4})-?Q([1-4])$/);
  if (!match) return "";
  return monthEndDate(`${match[1]}-${String(Number(match[2]) * 3).padStart(2, "0")}`);
}

function monthEndDate(yearMonth) {
  const [year, month] = yearMonth.split("-").map(Number);
  const end = new Date(Date.UTC(year, month, 0));
  return end.toISOString().slice(0, 10);
}

function isoFromParts(year, month, day) {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function todayIsoInZone(timeZone) {
  return formatDateInZone(new Date(), timeZone);
}

function addDaysIso(iso, days) {
  const date = new Date(`${iso}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatDateInZone(date, timeZone) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(date);
  return `${part(parts, "year")}-${part(parts, "month")}-${part(parts, "day")}`;
}

function formatTimeInZone(date, timeZone) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).formatToParts(date);
  return `${part(parts, "hour")}:${part(parts, "minute")}`;
}

function part(parts, type) {
  return parts.find((item) => item.type === type)?.value;
}

function parseIcsEvents(text) {
  const unfolded = text.replace(/\r?\n[ \t]/g, "");
  const blocks = unfolded.split("BEGIN:VEVENT").slice(1);
  return blocks.map((block) => {
    const fields = {};
    for (const rawLine of block.split(/\r?\n/)) {
      const separator = rawLine.indexOf(":");
      if (separator === -1) continue;
      const key = rawLine.slice(0, separator).split(";")[0];
      const value = rawLine.slice(separator + 1);
      fields[key] = unescapeIcs(value);
    }
    return {
      summary: fields.SUMMARY,
      start: fields.DTSTART,
      uid: fields.UID
    };
  });
}

function parseIcsDateTime(value) {
  const match = String(value).match(/^(\d{4})(\d{2})(\d{2})T?(\d{2})?(\d{2})?/);
  if (!match) return null;
  return {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: Number(match[4] || 0),
    minute: Number(match[5] || 0)
  };
}

function zonedDateTimeToUtc(parts, timeZone) {
  let utcMs = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute);
  for (let iteration = 0; iteration < 3; iteration += 1) {
    const offset = getTimeZoneOffsetMs(new Date(utcMs), timeZone);
    utcMs = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute) - offset;
  }
  return new Date(utcMs);
}

function getTimeZoneOffsetMs(date, timeZone) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).formatToParts(date);
  const asUtc = Date.UTC(
    Number(part(parts, "year")),
    Number(part(parts, "month")) - 1,
    Number(part(parts, "day")),
    Number(part(parts, "hour")),
    Number(part(parts, "minute")),
    Number(part(parts, "second"))
  );
  return asUtc - date.getTime();
}

function unescapeIcs(value) {
  return String(value)
    .replace(/\\n/g, " ")
    .replace(/\\,/g, ",")
    .replace(/\\;/g, ";")
    .replace(/\\\\/g, "\\")
    .trim();
}

function matchRule(text, rules) {
  const normalized = String(text || "").toLowerCase();
  return rules.find((rule) => normalized.includes(rule.contains.toLowerCase()));
}

function dedupeEvents(events) {
  const seen = new Set();
  const output = [];
  for (const event of events) {
    const key = `${event.date}|${event.countryIso3}|${event.indicator}|${event.title}`.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(event);
  }
  return output;
}

function slug(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
}

function stripSourceConfig(indicator) {
  const { primarySource, fallbackSource, ...publicIndicator } = indicator;
  return publicIndicator;
}

async function writeDataFile(output) {
  const serialized = `window.MONITOR_DATA = ${JSON.stringify(output, null, 2)};\n`;
  await fs.writeFile(paths.dataFile, serialized, "utf8");
}

main().catch((error) => {
  warn("error", "Actualizador", error.stack || error.message);
  process.exitCode = 1;
});
