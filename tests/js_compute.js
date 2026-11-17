// Runs the live page's metrics (site/metrics.js) on a data.json file and prints
// the results for every period button as JSON. Used by tests/test_parity.py.
//   node tests/js_compute.js path/to/data.json
const fs = require("fs");
const path = require("path");
const M7 = require(path.join(__dirname, "..", "site", "metrics.js"));

const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = {};
for (const [name, years] of [["1Y", 1], ["2Y", 2], ["3Y", 3], ["MAX", null]]) {
  const v = M7.compute(data, M7.startIndex(data.dates, years));
  out[name] = {
    start: v.dates[0], days: v.days, metrics: v.metrics, corr: v.corrM,
    honesty: v.honesty, noise: v.noise, rfAvg: v.rfAvg,
    growthEnd: Object.fromEntries(v.all.map(k => [k, v.growth[k][v.growth[k].length - 1]])),
  };
}
process.stdout.write(JSON.stringify(out));
