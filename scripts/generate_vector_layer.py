#!/usr/bin/env python3
"""Convert the IA DUOR armarios DXF into a calibrated SVG overlay."""

from __future__ import annotations

import html
import sys
from pathlib import Path

import ezdxf
from ezdxf.path import make_path

DXF_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("111 - Armários.dxf")
OUTPUT_PATH = Path("layers/armarios.svg")
MAP_WIDTH, MAP_HEIGHT = 42240, 15120
REFERENCE_LAYER = "SVG_REFERENCIA"
CAD_LEFT = CAD_TOP = 0.0
PX_PER_UNIT = 1.0


def xy(point) -> tuple[float, float]:
    return ((point.x - CAD_LEFT) * PX_PER_UNIT, (CAD_TOP - point.y) * PX_PER_UNIT)


def fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def layer_status(layer: str) -> str | None:
    name = layer.upper()
    if "REMOVER" in name:
        return "remover"
    if "IMPLANTAR" in name:
        return "implantar"
    if "EXISTENTE" in name:
        return "existente"
    return None


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


def text_svg(entity, css_class: str) -> str | None:
    kind = entity.dxftype()
    if kind == "TEXT":
        value, point = entity.dxf.text, entity.dxf.insert
        height, rotation = float(entity.dxf.height), float(entity.dxf.rotation)
    elif kind == "MTEXT":
        value, point = entity.plain_text(), entity.dxf.insert
        height = float(entity.dxf.char_height)
        rotation = float(getattr(entity.dxf, "rotation", 0.0))
    else:
        return None
    if not value.strip():
        return None
    x, y = xy(point)
    size = max(height * PX_PER_UNIT, 1.0)
    transform = f' transform="rotate({fmt(rotation)} {fmt(x)} {fmt(y)})"' if rotation else ""
    return (f'<text class="{css_class}" x="{fmt(x)}" y="{fmt(y)}" '
            f'font-size="{fmt(size)}"{transform}>{html.escape(value)}</text>')


def entity_svg(entity, css_class: str, status: str) -> list[str]:
    kind = entity.dxftype()
    if kind == "INSERT":
        output: list[str] = []
        try:
            for child in entity.virtual_entities():
                if layer_status(child.dxf.layer) == status:
                    output.extend(entity_svg(child, css_class, status))
        except (ezdxf.DXFError, AttributeError):
            pass
        return output
    if kind == "CIRCLE":
        cx, cy = xy(entity.dxf.center)
        radius = abs(float(entity.dxf.radius) * PX_PER_UNIT)
        return [f'<circle class="{css_class}" cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(radius)}"/>']
    if kind in {"LINE", "ARC", "ELLIPSE", "LWPOLYLINE", "POLYLINE", "SPLINE"}:
        d = path_d(entity)
        return [f'<path class="{css_class}" d="{d}"/>'] if d else []
    if kind in {"TEXT", "MTEXT"}:
        text = text_svg(entity, f"simbolo-texto status-{status}")
        return [text] if text else []
    return []


def insert_metadata(insert) -> tuple[str, str, str]:
    attrs = {a.dxf.tag.upper(): a.dxf.text for a in insert.attribs}
    double = insert.dxf.name in {"*U44", "*U45"}
    equipment_type = "armario-duplo" if double else "armario"
    remove_key = "AD_REMOVER" if double else "ARM_REMOVER"
    status = "remover" if attrs.get(remove_key, "00+000") != "00+000" else "implantar"
    local = attrs.get("LOCAL") or attrs.get("ARM_LOCAL") or ""
    title = ("Armário duplo" if double else "Armário") + f" — {status.title()}"
    if local:
        title += f" — km {local}"
    return equipment_type, status, title


def main() -> None:
    global CAD_LEFT, CAD_TOP, PX_PER_UNIT
    document = ezdxf.readfile(DXF_PATH)
    modelspace = document.modelspace()
    references = [e for e in modelspace.query("CIRCLE")
                  if e.dxf.layer.upper().rstrip(". ") == REFERENCE_LAYER]
    if len(references) != 2:
        raise RuntimeError(f"Expected exactly two {REFERENCE_LAYER} circles, found {len(references)}")
    references.sort(key=lambda e: float(e.dxf.center.x))
    start, end = references[0].dxf.center, references[1].dxf.center
    CAD_LEFT, CAD_TOP = float(start.x), float(start.y)
    end_x, end_y = float(end.x), float(end.y)
    if abs(end_y - CAD_TOP) > 0.01:
        raise RuntimeError(f"Reference circles are not horizontally aligned: {CAD_TOP} vs {end_y}")
    PX_PER_UNIT = MAP_WIDTH / (end_x - CAD_LEFT)

    svg = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {MAP_WIDTH} {MAP_HEIGHT}" '
        f'data-cad-origin-x="{CAD_LEFT:.10f}" data-cad-origin-y="{CAD_TOP:.10f}" '
        f'data-cad-reference-end-x="{end_x:.10f}" data-cad-reference-end-y="{end_y:.10f}" '
        f'data-pixels-per-unit="{PX_PER_UNIT:.12f}" role="img" aria-label="Armários de sinalização">',
        "<style>",
        ".armario{fill:none;stroke-linecap:round;stroke-linejoin:round;stroke-width:8}",
        ".status-existente{stroke:#22c55e;fill:#22c55e}",
        ".status-implantar{stroke:#ef4444;fill:#ef4444}",
        ".status-remover{stroke:#facc15;fill:#facc15;stroke-dasharray:28 18}",
        ".simbolo-texto{font-family:Arial,sans-serif;font-weight:700;paint-order:stroke;stroke-width:1.5}",
        ".objeto-vetorial{pointer-events:all;cursor:pointer}",
        ".objeto-vetorial:hover .armario{stroke:#fff;stroke-width:12}",
        "</style>",
        '<g id="camada-armarios">',
    ]
    wanted_blocks = {"*U10", "*U12", "*U44", "*U45"}
    seen: set[tuple] = set()
    object_index = 0
    for insert in modelspace.query("INSERT"):
        if insert.dxf.name not in wanted_blocks:
            continue
        equipment_type, status, title = insert_metadata(insert)
        point = insert.dxf.insert
        key = (equipment_type, status, round(float(point.x), 4), round(float(point.y), 4))
        if key in seen:
            continue
        seen.add(key)
        geometry = entity_svg(insert, f"armario status-{status}", status)
        if not geometry:
            continue
        object_index += 1
        attrs = {a.dxf.tag: a.dxf.text for a in insert.attribs}
        data_attrs = " ".join(f'data-{html.escape(k.lower().replace("_", "-"))}="{html.escape(v)}"'
                              for k, v in attrs.items() if v)
        svg.append(f'<g id="armario-{object_index}" class="objeto-vetorial tipo-{equipment_type} status-{status}" '
                   f'data-tipo="{equipment_type}" data-status="{status}" {data_attrs}>')
        svg.append(f"<title>{html.escape(title)}</title>")
        svg.extend(geometry)
        svg.append("</g>")
    svg.extend(["</g>", "</svg>"])
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(svg), encoding="utf-8")
    print(f"Generated {OUTPUT_PATH} with {object_index} armario objects; "
          f"origin=({CAD_LEFT:.10f}, {CAD_TOP:.10f}); scale={PX_PER_UNIT:.12f}")


if __name__ == "__main__":
    main()
