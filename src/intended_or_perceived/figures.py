"""Render the three prespecified study figures from analysis summary CSVs."""

import argparse
import csv
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnchoredOffsetbox, HPacker, TextArea
from matplotlib.ticker import MaxNLocator, PercentFormatter

REFERENCES = ("intended", "perceived")
STRATA = ("low", "middle", "high")
MODEL_ORDER = (
    "openai/gpt-audio-1.5",
    "google/gemini-3.5-flash-lite",
    "google/gemini-4-carbon",
)
_COLORS = ("#0072B2", "#B04700", "#007B60")
_SHAPES = ("o", "s", "^")
_INK = "#19242e"
_SECONDARY = "#465565"
_GRID = "#d9e0e6"
_DATASET_URL = "https://github.com/CheyneyComputerScience/CREMA-D"
_LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
_ATTRIBUTION = (
    f"Contains information from CREMA-D ({_DATASET_URL}), made available "
    f"under the Open Database License 1.0 ({_LICENSE_URL})."
)
_REFERENCE_TITLES = {
    "intended": "Intended emotion",
    "perceived": "Perceived voice emotion",
}
_BASELINES = (
    ("neutral_estimate", "|", "Always Neutral"),
    ("majority_estimate", "+", "Majority class"),
)
_STYLE = {
    "font.family": "DejaVu Sans",
    "font.size": 9.6,
    "text.color": _INK,
    "axes.labelcolor": _INK,
    "axes.edgecolor": _GRID,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.titleweight": "bold",
    "axes.titlesize": 10.5,
    "xtick.color": _SECONDARY,
    "ytick.color": _SECONDARY,
    "pdf.fonttype": 42,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
}


def _index(path, fields):
    indexed = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = tuple(row[field].strip().lower() for field in fields)
            if key in indexed:
                raise ValueError(f"Duplicate figure row {key} in {path.name}")
            indexed[key] = row
    if not indexed:
        raise ValueError(f"No figure rows in {path.name}")
    return indexed


def _number(row, key):
    value = (row.get(key) or "").strip().lower()
    if value in {"", "na", "nan", "none", "undefined"}:
        return None
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(f"Expected a proportion in [0, 1] for {key}")
    return result


def _name(model):
    return model.split("/", 1)[-1]


def _models(rows):
    available = {key[0] for key in rows}
    return [model for model in MODEL_ORDER if model in available] + sorted(
        available.difference(MODEL_ORDER)
    )


def _mark(color, shape, name, *, line="None", fill=True):
    return Line2D(
        [],
        [],
        color=color,
        label=name,
        marker=shape,
        linestyle=line,
        linewidth=1.4,
        markerfacecolor=color if fill else "white",
        markersize=6,
    )


def _grid(axis, dimension):
    axis.set_axisbelow(True)
    axis.grid(axis=dimension, color=_GRID, linewidth=0.65)
    axis.tick_params(length=0)


def _interval(axis, row, y, prefix, color, shape, *, fill=True):
    point = _number(row, prefix + "estimate")
    if point is None:
        return
    low, high = (_number(row, prefix + bound) for bound in ("ci_low", "ci_high"))
    if low is not None and high is not None:
        if low > high:
            raise ValueError("Confidence interval endpoints are reversed")
        axis.hlines(y, low, high, color=color, linewidth=1.6)
        axis.vlines([low, high], y - 0.045, y + 0.045, color=color, linewidth=1)
    axis.plot(
        point,
        y,
        color=color,
        marker=shape,
        markersize=6.6,
        markerfacecolor=color if fill else "white",
    )


def _baseline_keys(rows):
    return [
        item
        for item in _BASELINES
        if any(_number(row, item[0]) is not None for row in rows.values())
    ]


def _add_attribution(figure):
    footer = (
        ("CREMA-D data (Cao et al., 2014)  ·  ", None),
        (_DATASET_URL.removeprefix("https://"), _DATASET_URL),
        ("  ·  ODbL 1.0  ·  ", None),
        (_LICENSE_URL.removeprefix("https://"), _LICENSE_URL),
    )
    parts = [
        TextArea(
            label,
            textprops={
                "fontsize": 8,
                "color": _COLORS[0] if url else _SECONDARY,
                "url": url,
            },
        )
        for label, url in footer
    ]
    stripe = AnchoredOffsetbox(
        loc="lower center",
        child=HPacker(children=parts, align="baseline", pad=0, sep=0),
        pad=0,
        borderpad=0,
        frameon=False,
        bbox_to_anchor=(0.5, 0.023),
        bbox_transform=figure.transFigure,
    )
    figure.add_artist(stripe)


def _reference_accuracy(rows):
    models = _models(rows)
    fig, axes = plt.subplots(1, 2, figsize=(8.3, 3.65), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.235, right=0.975, top=0.835, bottom=0.35, wspace=0.19)
    baselines = _baseline_keys(rows)
    for axis, reference in zip(axes, REFERENCES, strict=True):
        axis.set_title(_REFERENCE_TITLES[reference], pad=10)
        for index, model in enumerate(models):
            row = rows.get((model, reference), {})
            _interval(axis, row, index - 0.10, "", _COLORS[0], "o")
            _interval(axis, row, index + 0.14, "human_", _SECONDARY, "D", fill=False)
            for offset, (key, marker, _) in enumerate(baselines):
                value = _number(row, key)
                if value is not None:
                    axis.plot(
                        value,
                        index - 0.46 + offset * 0.17,
                        marker=marker,
                        color=_SECONDARY,
                        markersize=5.5,
                        markeredgewidth=1.3,
                    )
            if row.get("n_valid"):
                axis.text(
                    0.995,
                    index - 0.38,
                    f"n={row['n_valid']}",
                    transform=axis.get_yaxis_transform(),
                    ha="right",
                    va="center",
                    fontsize=7.8,
                    color=_SECONDARY,
                )
        axis.set_xticks([0, 0.25, 0.5, 0.75, 1])
        axis.set_xlim(-0.025, 1.025)
        axis.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
        axis.spines["left"].set_visible(False)
        _grid(axis, "x")
    axes[0].set_yticks(range(len(models)), [_name(model) for model in models])
    axes[0].set_ylim(len(models) - 0.52, -0.6)
    fig.supxlabel("Accuracy or individual listener agreement", y=0.21, fontsize=9.5)
    handles = [
        _mark(_COLORS[0], "o", "Model"),
        _mark(_SECONDARY, "D", "Individual listener", fill=False),
        *[_mark(_SECONDARY, marker, label) for _, marker, label in baselines],
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncols=len(handles),
        frameon=False,
        bbox_to_anchor=(0.56, 0.085),
        fontsize=8.7,
    )
    return fig


def _agreement_accuracy(rows):
    models = _models(rows)
    fig, axes = plt.subplots(
        1, len(models), figsize=(8.3, 3.85), sharey=True, squeeze=False
    )
    fig.subplots_adjust(left=0.095, right=0.985, top=0.834, bottom=0.336, wspace=0.27)
    baselines = _baseline_keys(rows)
    for index, (axis, model) in enumerate(zip(axes[0], models, strict=True)):
        axis.set_title(_name(model), pad=10)
        tick_labels = [stratum.capitalize() for stratum in STRATA]
        for reference_index, reference in enumerate(REFERENCES):
            records = [rows.get((model, reference, stratum), {}) for stratum in STRATA]
            estimates = [_number(row, "estimate") for row in records]
            x = list(range(len(STRATA)))
            color, marker = _COLORS[reference_index], _SHAPES[reference_index]
            axis.plot(
                x,
                estimates,
                color=color,
                marker=marker,
                linewidth=1.6,
                markersize=6.2,
                linestyle="-" if reference == "intended" else "--",
            )
            for position, row in enumerate(records):
                for offset, (key, shape, _) in enumerate(baselines):
                    value = _number(row, key)
                    if value is not None:
                        adjustment = (0.115 + offset * 0.095) * (
                            -1 if reference_index == 0 else 1
                        )
                        axis.plot(
                            position + adjustment,
                            value,
                            color=color,
                            marker=shape,
                            markersize=6.3,
                            markeredgewidth=1.2,
                        )
                if (
                    reference == "intended"
                    and row.get("n_valid")
                    and row.get("n_planned")
                ):
                    other = rows.get((model, "perceived", STRATA[position]), {})
                    if (
                        other.get("n_valid") == row["n_valid"]
                        and other.get("n_planned") == row["n_planned"]
                    ):
                        tick_labels[position] += (
                            f"\n{row['n_valid']}/{row['n_planned']}"
                        )
        axis.set_xticks(range(len(STRATA)), tick_labels, fontsize=8.5)
        axis.set_xlim(-0.32, 2.32)
        axis.set_yticks([0, 0.25, 0.5, 0.75, 1])
        axis.set_ylim(-0.025, 1.025)
        axis.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
        if index > 0:
            axis.spines["left"].set_visible(False)
        _grid(axis, "y")
    axes[0][0].set_ylabel("Accuracy")
    fig.supxlabel("Voice agreement stratum", y=0.198, fontsize=9.5)
    handles = [
        _mark(
            _COLORS[index],
            _SHAPES[index],
            _REFERENCE_TITLES[reference],
            line="-" if index == 0 else "--",
        )
        for index, reference in enumerate(REFERENCES)
    ] + [_mark(_SECONDARY, marker, label) for _, marker, label in baselines]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncols=len(handles),
        frameon=False,
        bbox_to_anchor=(0.535, 0.081),
        fontsize=8.6,
    )
    return fig


def _repeat_stability(rows):
    models = _models(rows)
    fig, axes = plt.subplots(1, 2, figsize=(8.3, 3.95), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.108, right=0.975, top=0.843, bottom=0.307, wspace=0.16)
    x_max = max((_number(row, "flip_rate") or 0 for row in rows.values()), default=0)
    y_max = max(
        (_number(row, "accuracy_range") or 0 for row in rows.values()), default=0
    )
    for axis, reference in zip(axes, REFERENCES, strict=True):
        axis.set_title(_REFERENCE_TITLES[reference], pad=10)
        for index, model in enumerate(models):
            row = rows.get((model, reference), {})
            rate, span = (_number(row, key) for key in ("flip_rate", "accuracy_range"))
            if rate is not None and span is not None:
                axis.scatter(
                    rate * 100,
                    span * 100,
                    marker=_SHAPES[index % len(_SHAPES)],
                    s=60,
                    color=_COLORS[index % len(_COLORS)],
                    edgecolor="white",
                    linewidth=0.7,
                    zorder=3,
                )
        axis.set_xlim(-max(0.25, x_max * 3), min(103, max(2, x_max * 112)))
        axis.set_ylim(-max(0.12, y_max * 3), min(103, max(1, y_max * 115)))
        ticks = (1, 2, 2.5, 5, 10)
        axis.xaxis.set_major_locator(MaxNLocator(nbins=5, steps=ticks))
        axis.yaxis.set_major_locator(MaxNLocator(nbins=5, steps=ticks))
        axis.xaxis.set_major_formatter(
            PercentFormatter(xmax=100, decimals=0 if x_max >= 0.10 else 1)
        )
        _grid(axis, "both")
    axes[0].set_ylabel("Range of repeat accuracy\n(percentage points)")
    axes[1].spines["left"].set_visible(False)
    fig.supxlabel("Clips with a label change across repeats", y=0.18, fontsize=9.5)
    handles = []
    for index, model in enumerate(models):
        counts = {
            (row.get("n_complete"), row.get("n_planned"))
            for (name, _), row in rows.items()
            if name == model
        }
        legend_name = _name(model)
        if len(counts) == 1:
            complete, planned = next(iter(counts))
            if complete and planned:
                legend_name += f" ({complete}/{planned})"
        handles.append(
            _mark(
                _COLORS[index % len(_COLORS)],
                _SHAPES[index % len(_SHAPES)],
                legend_name,
            )
        )
    fig.legend(
        handles=handles,
        loc="lower center",
        ncols=len(handles),
        frameon=False,
        bbox_to_anchor=(0.56, 0.079),
        fontsize=8.6,
    )
    return fig


def render(tables: Path, output: Path):
    """Render archival vector PDFs and 300-dpi PNGs from three summary tables."""
    output.mkdir(parents=True, exist_ok=True)
    definitions = (
        ("figure1_reference_accuracy", ("model", "reference"), _reference_accuracy),
        (
            "figure2_agreement_accuracy",
            ("model", "reference", "stratum"),
            _agreement_accuracy,
        ),
        ("figure3_repeat_stability", ("model", "reference"), _repeat_stability),
    )
    with plt.rc_context(_STYLE):
        for index, (name, fields, plot) in enumerate(definitions, start=1):
            rows = _index(tables / f"figure{index}.csv", fields)
            figure = plot(rows)
            try:
                _add_attribution(figure)
                figure.savefig(
                    output / f"{name}.png",
                    dpi=300,
                    metadata={"Description": _ATTRIBUTION},
                )
                figure.savefig(
                    output / f"{name}.pdf",
                    metadata={"CreationDate": None, "Subject": _ATTRIBUTION},
                )
            finally:
                plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=Path, default=Path("results/analysis"))
    parser.add_argument("--output", type=Path, default=Path("results/figures"))
    args = parser.parse_args()
    render(args.tables, args.output)


if __name__ == "__main__":
    main()
