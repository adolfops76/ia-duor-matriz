#!/usr/bin/env python3
"""Convert the IA DUOR signalling DXF into a georeferenced SVG overlay."""

from __future__ import annotations

import html
import sys
from pathlib import Path

import ezdxf
from ezdxf.path import make_path


DXF_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("004z DUTOS ARMÁRIOS 2.dxf")
OUTPUT_PATH = Path("layers/dutos-armarios.svg")

# The raster matrix is 22 x 14 cells. The reference span runs from the
# upper-left corner of 01A to the upper-right corner of 22A. Y is inverted
# when converting CAD coordinates to screen coordinates.
MAP_WIDTH = 42240
MAP_HEIGHT = 15120
REFERENCE_END_X = 245507.6571
REFERENCE_END_Y = 390262.3884
PX_PER_UNIT = 1.0

# Populated from the center of the SVG_REFERENCIA circle in the source DXF.
CAD_LEFT = 0.0
CAD_TOP = 0.0


def xy(point) -> tuple[float, float]:
    return (
        (point.x - CAD_LEFT) * PX_PER_UNIT,
        (CAD_TOP - point.y) * PX_PER_UNIT,
    )


def fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def path_d(entity) -> str | None:
    try:
        vertices = list(make_path(entity).flattening(distance=0.08, segments=8))
    except (TypeError, ValueError, AttributeError, ezdxf.DXFError):
        return None
    if len(vertices) < 2:
        return None
    points = [xy(vertex) for vertex in vertices]
    command = [f"M {fmt(points[0][0])} {fmt(points[0][1])}"]
    command.extend(f"L {fmt(x)} {fmt(y)}" for x, y in points[1:])
    if getattr(entity, "closed", False):
        command.append("Z")
    return " ".join(command)


def entity_svg(entity, css_class: str) -> list[str]:
    kind = entity.dxftype()
    if kind == "INSERT":
        output: list[str] = []
        try:
            for child in entity.virtual_entities():
                output.extend(entity_svg(child, css_class))
        except (ezdxf.DXFError, AttributeError):
            pass
        return output
    if kind == "CIRCLE":
        cx, cy = xy(entity.dxf.center)
        radius = abs(float(entity.dxf.radius) * PX_PER_UNIT)
        return [f'<circle class="{css_class}" cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(radius)}"/>']
    if kind in {"LINE", "ARC", "ELLIPSE", "LWPOLYLINE", "POLYLINE", "SPLINE"}:
        d = path_d(entity)
        return [f'<path class="{css_class}" d="{d}"/>' ] if d else []
    return []


def equipment_metadata(insert) -> tuple[str, str, str]:
    name = insert.dxf.name
    layer = insert.dxf.layer.upper()
    dynamic = {
        "*U13": ("armario", "implantar"),
        "*U14": ("armario", "existente"),
        "*U15": ("armario", "remover"),
        "*U16": ("house", "existente"),
        "*U54": ("armario-duplo", "existente"),
        "*U55": ("armario-duplo", "implantar"),
        "*U56": ("armario-duplo", "remover"),
    }
    if name in dynamic:
        equipment_type, status = dynamic[name]
    elif name == "00 - CXA PASSAGEM":
        equipment_type, status = "caixa-passagem", "existente"
    else:
        equipment_type, status = "equipamento", "existente"
    if "IMPLANTAR" in layer:
        status = "implantar"
    elif "REMOVER" in layer:
        status = "remover"
    elif "EXISTENTE" in layer or "LOCAL" in layer:
        status = "existente"

    attrs = {a.dxf.tag: a.dxf.text for a in insert.attribs}
    local = next((v for k, v in attrs.items() if "LOCAL" in k and v not in {"", "00+000", "000+000"}), "")
    label = equipment_type.replace("-", " ").title()
    title = f"{label} — {status.title()}"
    if local:
        title += f" — km {local}"
    return equipment_type, status, title


def main() -> None:
    global CAD_LEFT, CAD_TOP, PX_PER_UNIT
    document = ezdxf.readfile(DXF_PATH)
    modelspace = document.modelspace()

    reference_circles = [
        entity for entity in modelspace.query("CIRCLE")
        if entity.dxf.layer.upper().rstrip(". ") == "SVG_REFERENCIA"
    ]
    if not reference_circles:
        raise RuntimeError(
            "Expected at least one SVG_REFERENCIA circle, found none"
        )
    reference_circles.sort(key=lambda entity: float(entity.dxf.center.x))
    start = reference_circles[0].dxf.center
    CAD_LEFT = float(start.x)
    CAD_TOP = float(start.y)

    if len(reference_circles) >= 2:
        end = reference_circles[-1].dxf.center
        end_x = float(end.x)
        end_y = float(end.y)
        end_source = "DXF circle"
    else:
        end_x = REFERENCE_END_X
        end_y = REFERENCE_END_Y
        end_source = "declared 22A endpoint"

    if abs(end_y - CAD_TOP) > 0.01:
        raise RuntimeError(
            f"Reference points are not horizontally aligned: {CAD_TOP} vs {end_y}"
        )
    span = end_x - CAD_LEFT
    if span <= 0:
        raise RuntimeError(f"Invalid horizontal reference span: {span}")
    PX_PER_UNIT = MAP_WIDTH / span

    duct_groups = {
        "00 - FM22195-Q01 - BANCO DE DUTOS LONGITUDINAL": ("dutos-longitudinais", "duto-longitudinal", "duto longitudinal"),
        "00 - FM22195-Q01 - BANCO DE DUTOS LOCAL": ("dutos-locais", "duto-local", "duto local"),
        "00 - FM22195-Q01 - BANCO DE DUTOS APARENTE": ("dutos-aparentes", "duto-aparente", "duto aparente"),
        "00 - FM22195-Q01 - BANCO DE DUTOS CAIXA": ("caixas-dutos", "caixa-dutos", "caixa de dutos"),
    }

    svg: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {MAP_WIDTH} {MAP_HEIGHT}" '
        f'data-cad-origin-x="{CAD_LEFT:.10f}" data-cad-origin-y="{CAD_TOP:.10f}" '
        f'data-cad-reference-end-x="{end_x:.10f}" data-cad-reference-end-y="{end_y:.10f}" '
        f'data-reference-end-source="{end_source}" data-pixels-per-unit="{PX_PER_UNIT:.12f}" '
        f'role="img" aria-label="Dutos e armários de sinalização">',
        "<style>",
        ".vetor{fill:none;stroke-linecap:round;stroke-linejoin:round}",
        ".duto-longitudinal{stroke:#0ea5e9;stroke-width:7}",
        ".duto-local{stroke:#facc15;stroke-width:7}",
        ".duto-aparente{stroke:#a855f7;stroke-width:7;stroke-dasharray:22 13}",
        ".caixa-dutos{stroke:#f97316;stroke-width:4;fill:rgba(249,115,22,.10)}",
        ".equipamento{stroke-width:5;fill:rgba(17,24,39,.18);pointer-events:all;cursor:pointer}",
        ".status-existente{stroke:#22c55e}",
        ".status-implantar{stroke:#ef4444}",
        ".status-remover{stroke:#facc15;stroke-dasharray:18 10}",
        ".equipamento:hover{stroke:#ffffff;stroke-width:8}",
        "</style>",
        '<g id="camada-dutos-armarios">',
    ]

    for layer, (group_id, style_class, title) in duct_groups.items():
        svg.append(f'<g id="{group_id}" data-layer="{html.escape(layer)}"><title>{title.title()}</title>')
        css_class = f"vetor {style_class}"
        for entity in modelspace:
            if entity.dxf.layer != layer:
                continue
            svg.extend(entity_svg(entity, css_class))
        svg.append("</g>")

    wanted_blocks = {"*U13", "*U14", "*U15", "*U16", "*U54", "*U55", "*U56", "00 - CXA PASSAGEM"}
    svg.append('<g id="equipamentos">')
    object_index = 0
    for insert in modelspace.query("INSERT"):
        if insert.dxf.name not in wanted_blocks:
            continue
        equipment_type, status, title = equipment_metadata(insert)
        geometry = entity_svg(insert, f"vetor equipamento status-{status}")
        if not geometry:
            continue
        object_index += 1
        attrs = {a.dxf.tag: a.dxf.text for a in insert.attribs}
        data_attrs = " ".join(
            f'data-{html.escape(key.lower().replace("_", "-"))}="{html.escape(value)}"'
            for key, value in attrs.items()
            if value
        )
        svg.append(
            f'<g id="objeto-{object_index}" class="objeto-vetorial tipo-{equipment_type} status-{status}" '
            f'data-tipo="{equipment_type}" data-status="{status}" {data_attrs}>'
        )
        svg.append(f"<title>{html.escape(title)}</title>")
        svg.extend(geometry)
        svg.append("</g>")
    svg.extend(["</g>", "</g>", "</svg>"])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(svg), encoding="utf-8")
    print(
        f"Generated {OUTPUT_PATH} with {object_index} interactive equipment objects; "
        f"origin=({CAD_LEFT:.10f}, {CAD_TOP:.10f}); "
        f"end=({end_x:.10f}, {end_y:.10f}) [{end_source}]; scale={PX_PER_UNIT:.12f}"
    )


if __name__ == "__main__":
    main()
