// Every number on the live page, computed in the browser from data.json so the
// period filter works without a server. Mirrors src/m7/metrics.py;
// tests/test_parity.py runs this file in Node and checks the two agree.
(function (root) {
  "use strict";

  const RISK_FREE_FALLBACK = 0.04;  // used only if data.json has no T-bill series
  const TRADING_DAYS = 252;
  const PORT = "M7";

  const mean = a => a.reduce((s, v) => s + v, 0) / a.length;
  const std = a => { const m = mean(a); return Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / (a.length - 1)); };
  const corr = (a, b) => {
    const ma = mean(a), mb = mean(b);
    let sab = 0, saa = 0, sbb = 0;
    for (let i = 0; i < a.length; i++) { const da = a[i] - ma, db = b[i] - mb; sab += da * db; saa += da * da; sbb += db * db; }
    return sab / Math.sqrt(saa * sbb);
  };
  const parseDate = s => new Date(s + "T00:00:00Z");

  // Index of the first date on or after the last date minus `years` (null = all data).
  function startIndex(dates, years) {
    if (!years) return 0;
    const cut = parseDate(dates[dates.length - 1]);
    cut.setUTCFullYear(cut.getUTCFullYear() - years);
    return Math.max(0, dates.findIndex(d => parseDate(d) >= cut));
  }

  function compute(data, startIdx) {
    const TICKERS = data.tickers, BENCH = data.benchmark;
    const dates = data.dates.slice(startIdx);
    const ret = {};
    for (const k of [...TICKERS, BENCH]) {
      const p = data.prices[k].slice(startIdx);
      ret[k] = p.slice(1).map((v, i) => v / p[i] - 1);
    }
    ret[PORT] = ret[TICKERS[0]].map((_, i) => mean(TICKERS.map(t => ret[t][i])));
    // Daily risk-free return for each return day (return i ends on dates[i + 1]).
    const rfDaily = data.riskFree
      ? data.riskFree.slice(startIdx + 1).map(y => y / TRADING_DAYS)
      : ret[PORT].map(() => RISK_FREE_FALLBACK / TRADING_DAYS);

    const all = [...TICKERS, PORT, BENCH];
    const growth = {}, drawdown = {}, metrics = {};
    const years = ret[PORT].length / TRADING_DAYS;
    for (const k of all) {
      let g = 100, peak = 100;
      const gs = [100], ds = [0];
      for (const r of ret[k]) { g *= 1 + r; peak = Math.max(peak, g); gs.push(g); ds.push(g / peak - 1); }
      growth[k] = gs; drawdown[k] = ds;
      const total = gs[gs.length - 1] / 100 - 1;
      const cagr = Math.pow(1 + total, 1 / years) - 1;
      const vol = std(ret[k]) * Math.sqrt(TRADING_DAYS);
      const excess = ret[k].map((r, i) => r - rfDaily[i]);
      const sharpe = mean(excess) / std(excess) * Math.sqrt(TRADING_DAYS);
      metrics[k] = {
        total, cagr, vol, sharpe,
        maxdd: Math.min(...ds), best: Math.max(...ret[k]), worst: Math.min(...ret[k]),
      };
    }
    const corrM = TICKERS.map(a => TICKERS.map(b => corr(ret[a], ret[b])));

    // Honesty check: momentum rule ("tomorrow goes the way today went") vs always guessing up.
    const honesty = {};
    for (const t of TICKERS) {
      const up = ret[t].map(r => r > 0);
      let alwaysUp = 0, momentum = 0;
      for (let i = 1; i < up.length; i++) { alwaysUp += up[i]; momentum += up[i] === up[i - 1]; }
      const n = up.length - 1;
      honesty[t] = { alwaysUp: alwaysUp / n, momentum: momentum / n };
    }
    const noise = 2 * Math.sqrt(0.25 / (ret[PORT].length - 1));
    const rfAvg = mean(rfDaily) * TRADING_DAYS;
    return { dates, growth, drawdown, metrics, corrM, honesty, noise, all, rfAvg, days: ret[PORT].length };
  }

  const api = { compute, startIndex, RISK_FREE_FALLBACK, TRADING_DAYS, PORT };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.M7 = api;
})(this);
