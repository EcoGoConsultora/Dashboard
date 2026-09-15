import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const dataFile = path.join(ROOT, "data", "monitor-data.js");

const text = await fs.readFile(dataFile, "utf8");
const match = text.match(/window\.MONITOR_DATA\s*=\s*([\s\S]*?);\s*$/);
if (!match) fail("data/monitor-data.js no define window.MONITOR_DATA");

const data = JSON.parse(match[1]);
if (!Array.isArray(data.countries) || data.countries.length < 19) fail("faltan paises");
if (!Array.isArray(data.indicators) || data.indicators.length < 5) fail("faltan indicadores");
if (!data.series || typeof data.series !== "object") fail("falta series");
if (!Array.isArray(data.calendar)) fail("falta calendar");

for (const country of data.countries) {
  if (!data.series[country.iso3]) fail(`falta series para ${country.iso3}`);
  for (const indicator of data.indicators) {
    const metric = data.series[country.iso3][indicator.id];
    if (!metric || !metric.latest) continue;
    if (!Number.isFinite(metric.latest.value)) fail(`valor invalido ${indicator.id} para ${country.iso3}`);
    if (!metric.latest.period || !metric.sourceName || !metric.frequency) fail(`metadata incompleta ${indicator.id} para ${country.iso3}`);
    if ("change" in metric.latest && metric.latest.change !== null && !Number.isFinite(metric.latest.change)) {
      fail(`variacion invalida ${indicator.id} para ${country.iso3}`);
    }
  }
}

console.log(`Contrato valido: ${data.countries.length} paises, ${data.indicators.length} indicadores, ${data.calendar.length} eventos.`);

function fail(message) {
  console.error(`Validacion fallida: ${message}`);
  process.exit(1);
}
