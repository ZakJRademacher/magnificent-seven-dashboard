"""The static one-page dashboard image (the README picture).

Same design as the live page: a trading-terminal look with a near-black surface,
an amber accent for headings only, monospaced figures, and one fixed color per
stock. Text is never colored; a dot, line or arrow beside it carries the color,
and gains and losses always come with an arrow so meaning never rests on color.
"""

import numpy as np

from . import __version__
from .config import BENCHMARK, COLORS, PORTFOLIO, TICKERS, label

SURFACE = "#0b0e11"
PANEL = "#12161b"
GRID = "#232a32"
TEXT = "#eef1f4"
TEXT_2 = "#b6bec8"
TEXT_3 = "#7d8792"
ACCENT = "#f5a623"
GAIN = "#0ca30c"
LOSS = "#e66767"


def _setup():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    installed = {f.name for f in font_manager.fontManager.ttflist}
    mono = next(f for f in ["Consolas", "Menlo", "DejaVu Sans Mono"] if f in installed)
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Inter", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 10,
        "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.facecolor": PANEL, "axes.edgecolor": GRID, "axes.labelcolor": TEXT_2,
        "axes.grid": True, "axes.axisbelow": True,
        "grid.color": GRID, "grid.linewidth": 0.8,
        "xtick.color": TEXT_3, "ytick.color": TEXT_3, "xtick.labelsize": 9, "ytick.labelsize": 9,
        "text.color": TEXT,
        "lines.linewidth": 2, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
    })
    return plt, mono


def _style_axes(ax, title, subtitle=None):
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    ax.set_title(title.upper(), loc="left", fontsize=12, fontweight="bold", color=ACCENT,
                 pad=22 if subtitle else 10)
    if subtitle:
        ax.text(0, 1.025, subtitle, transform=ax.transAxes, fontsize=9.5, color=TEXT_3, va="bottom")


def spread_labels(values, min_gap):
    """Nudge label positions apart so text doesn't overlap. Returns new positions."""
    order = np.argsort(values)
    out = np.array(values, dtype=float)
    for a, b in zip(order[:-1], order[1:]):
        if out[b] - out[a] < min_gap:
            out[b] = out[a] + min_gap
    return out


def pct(x, digits=0):
    x = round(x, digits + 2) + 0.0  # avoids printing "-0%"
    return f"{x:+.{digits}%}"


def render(analysis, path):
    plt, mono = _setup()
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.gridspec import GridSpec
    from matplotlib.patches import FancyBboxPatch
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    a = analysis
    m = a.metrics
    first, last = a.dates[0], a.dates[-1]
    fig = plt.figure(figsize=(18, 12.5))
    gs = GridSpec(3, 12, figure=fig, height_ratios=[0.72, 3.1, 3.1],
                  left=0.04, right=0.97, top=0.895, bottom=0.05, hspace=0.42, wspace=1.2)

    # ---- Header
    fig.text(0.04, 0.966, "MAGNIFICENT SEVEN", fontsize=26, fontweight="bold", color=TEXT, va="center")
    fig.text(0.97, 0.966, f"V{__version__}  ·  AS OF {last:%d %b %Y}".upper(), fontsize=11, color=ACCENT,
             va="center", ha="right", fontfamily=mono)
    rf_note = (f"fixed {a.rf_avg:.0%} risk-free rate" if a.rf_is_fallback
               else f"Sharpe vs 13-week T-bill (avg {a.rf_avg:.1%})")
    fig.text(0.04, 0.934,
             f"Daily adjusted closes from {first:%b %d, %Y}  ·  {len(a.returns):,} trading days"
             f"  ·  {rf_note}  ·  Source: Yahoo Finance",
             fontsize=11, color=TEXT_3, va="center")
    fig.add_artist(plt.Line2D([0.04, 0.97], [0.915, 0.915], color=ACCENT, linewidth=1.5))

    # ---- Ticker tape: one quote tile per series
    tape = TICKERS + [PORTFOLIO, BENCHMARK]
    tape_gs = gs[0, :].subgridspec(1, len(tape), wspace=0.07)
    for i, name in enumerate(tape):
        row = m.loc[name]
        ax = fig.add_subplot(tape_gs[0, i])
        ax.set_axis_off()
        ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.05",
                                    transform=ax.transAxes, facecolor=PANEL, edgecolor=GRID,
                                    linewidth=1, mutation_aspect=1.9, clip_on=False))
        ax.plot([0.09], [0.8], "o" if name in TICKERS else "D", markersize=7, color=COLORS[name],
                transform=ax.transAxes, clip_on=False)
        ax.text(0.17, 0.8, label(name), fontsize=10.5, fontweight="bold", color=TEXT, va="center",
                transform=ax.transAxes)
        up = round(row["total"], 2) + 0.0 >= 0
        ax.text(0.07, 0.46, "▲" if up else "▼", fontsize=11, color=GAIN if up else LOSS, va="center",
                transform=ax.transAxes)
        ax.text(0.2, 0.46, pct(row["total"]), fontsize=18, fontweight="bold", color=TEXT,
                va="center", transform=ax.transAxes, fontfamily=mono)
        ax.text(0.07, 0.15, f"CAGR {pct(row['cagr'])}  SR {row['sharpe']:.2f}", fontsize=8.5,
                color=TEXT_3, va="center", transform=ax.transAxes, fontfamily=mono)

    # ---- Growth of $100 (benchmark behind, stocks, portfolio on top)
    growth = a.growth
    ax = fig.add_subplot(gs[1, :8])
    _style_axes(ax, "Growth of $100", "Log scale, so equal distances mean equal percent gains")
    ax.set_yscale("log")
    ax.plot(growth.index, growth[BENCHMARK], color=COLORS[BENCHMARK], linewidth=1.6, zorder=2)
    for t in TICKERS:
        ax.plot(growth.index, growth[t], color=COLORS[t], zorder=3)
    ax.plot(growth.index, growth[PORTFOLIO], color=COLORS[PORTFOLIO], linewidth=2.8, zorder=4)

    names = TICKERS + [PORTFOLIO, BENCHMARK]
    end = growth[names].iloc[-1]
    lo, hi = np.log10(growth[names].min().min()), np.log10(growth[names].max().max())
    label_y = 10 ** spread_labels(np.log10(end.values), min_gap=(hi - lo) * 0.045)
    span = growth.index[-1] - growth.index[0]
    x_end, x_label = growth.index[-1], growth.index[-1] + span * 0.025
    for name, y_true, y_text in zip(names, end.values, label_y):
        ax.plot([x_end], [y_true], "o", markersize=8, color=COLORS[name],
                markeredgecolor=PANEL, markeredgewidth=2, zorder=5, clip_on=False)
        ax.plot([x_end, x_label], [y_true, y_text], color=GRID, linewidth=0.8, zorder=1, clip_on=False)
        ax.text(x_label, y_text, f" {label(name):<8} {'$' + format(y_true, ',.0f'):>6}", fontsize=9.5, color=TEXT_2,
                va="center", ha="left", clip_on=False, fontfamily=mono,
                bbox=dict(facecolor=PANEL, edgecolor="none", pad=1.5))
    ax.set_xlim(growth.index[0], x_end + span * 0.17)
    ax.axhline(100, color=TEXT_3, linewidth=0.8, zorder=1)
    ticks = [t for t in (25, 50, 100, 200, 400, 800, 1600, 3200) if 10 ** lo * 0.8 <= t <= 10 ** hi * 1.25]
    ax.yaxis.set_major_locator(FixedLocator(ticks))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.grid(axis="x", visible=False)
    handles = [plt.Line2D([], [], color=COLORS[n], linewidth=2.8 if n == PORTFOLIO else 2, label=label(n))
               for n in names]
    ax.legend(handles=handles, ncol=len(names), loc="upper left", frameon=False, fontsize=9,
              labelcolor=TEXT_2, handlelength=1.2, columnspacing=1.2, borderaxespad=0.2)

    # ---- Risk vs return
    ax = fig.add_subplot(gs[1, 8:])
    _style_axes(ax, "Risk vs return", "Up and to the left is better: more growth, less bounce")
    refs = [PORTFOLIO, BENCHMARK]
    x_span = m.loc[names, "vol"].max() - m.loc[names, "vol"].min()
    y_span = m.loc[names, "cagr"].max() - m.loc[names, "cagr"].min()
    for name in refs:
        x, y = m.loc[name, "vol"], m.loc[name, "cagr"]
        ax.plot(x, y, "D", markersize=12, markerfacecolor="none", markeredgecolor=COLORS[name],
                markeredgewidth=2, zorder=2)
        ax.annotate(label(name), (x, y), xytext=(0, 13), textcoords="offset points",
                    fontsize=9.5, color=TEXT_2, va="bottom", ha="center")
    for name in TICKERS:
        x, y = m.loc[name, "vol"], m.loc[name, "cagr"]
        ax.plot(x, y, "o", markersize=11, color=COLORS[name], markeredgecolor=PANEL,
                markeredgewidth=2, zorder=3)
        # If a diamond sits right next to this dot, drop the label below so they don't collide.
        crowded = any(abs(m.loc[r, "vol"] - x) < 0.08 * x_span and abs(m.loc[r, "cagr"] - y) < 0.08 * y_span
                      for r in refs)
        ax.annotate(name, (x, y), xytext=(-4, -14) if crowded else (9, 0), textcoords="offset points",
                    fontsize=9.5, color=TEXT_2, va="center", zorder=4)
    ax.axhline(0, color=TEXT_3, linewidth=0.8, zorder=1)
    ax.margins(x=0.22, y=0.15)
    ax.set_xlabel("Volatility (yearly)")
    ax.set_ylabel("Growth per year (CAGR)")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))

    # ---- Correlation heatmap
    ax = fig.add_subplot(gs[2, :4])
    _style_axes(ax, "Do they move together?", "Correlation of daily returns. 1.00 = perfectly in step")
    n = len(TICKERS)
    cmap = LinearSegmentedColormap.from_list("corr", ["#3987e5", "#2a3038", "#e66767"])
    ax.pcolormesh(a.corr.values, cmap=cmap, vmin=-1, vmax=1, edgecolors=PANEL, linewidth=2)
    for i in range(n):
        for j in range(n):
            ax.text(j + 0.5, i + 0.5, f"{a.corr.values[i, j]:.2f}", ha="center", va="center",
                    fontsize=10, color=TEXT, fontfamily=mono)
    ax.set_xticks(np.arange(n) + 0.5, TICKERS)
    ax.set_yticks(np.arange(n) + 0.5, TICKERS)
    ax.tick_params(colors=TEXT_2)
    ax.invert_yaxis()
    ax.set_aspect("equal")
    ax.grid(False)

    # ---- Drawdowns, one small panel per series (3 x 3)
    dd_names = TICKERS + [PORTFOLIO, BENCHMARK]
    dd_gs = gs[2, 4:].subgridspec(3, 3, hspace=0.55, wspace=0.12)
    floor = np.floor(a.drawdown[dd_names].min().min() * 10) / 10
    shared = None
    for k, name in enumerate(dd_names):
        ax = fig.add_subplot(dd_gs[k // 3, k % 3], sharey=shared)
        shared = shared or ax
        for side in ("top", "right", "left", "bottom"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=0)
        dd = a.drawdown[name]
        ax.fill_between(dd.index, dd, 0, color=COLORS[name], alpha=0.35, linewidth=0)
        ax.plot(dd.index, dd, color=COLORS[name], linewidth=1.3)
        ax.set_ylim(floor, 0.02)
        ax.set_title(label(name), loc="left", fontsize=10.5, fontweight="bold", color=TEXT, pad=4)
        ax.set_title(f"worst {dd.min():.0%}", loc="right", fontsize=9.5, color=TEXT_2, pad=4,
                     fontfamily=mono)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
        ax.yaxis.set_major_locator(FixedLocator([floor / 2, 0]) if floor < -0.4 else ax.yaxis.get_major_locator())
        ax.xaxis.set_major_locator(FixedLocator([]))
        ax.grid(axis="x", visible=False)
        if k % 3:
            ax.tick_params(labelleft=False)
        if k == 0:
            ax.text(0, 1.55, "DRAWDOWNS", transform=ax.transAxes, fontsize=12, fontweight="bold", color=ACCENT)
            ax.text(0, 1.33, f"How far below its previous peak each one sat, {first:%Y} to {last:%Y}",
                    transform=ax.transAxes, fontsize=9.5, color=TEXT_3)

    fig.savefig(path, dpi=150)
    plt.close(fig)
