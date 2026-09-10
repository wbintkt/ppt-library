"""Keep preview text and export numbering aligned with PDF's visible slides."""


def is_visible_slide(element) -> bool:
    # OOXML xsd:boolean permits both lexical forms; omitted show defaults to true.
    return element.get("show", "true").strip().lower() not in {"0", "false"}
