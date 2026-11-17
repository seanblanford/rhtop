"""Arrange visible panels without duplicating dashboard widgets."""

from itertools import zip_longest

from textual.containers import Container

from ..settings import PANELS


def arrange(workspace: Container, panels: list[str], layout: str, width: int) -> None:
    visible = [name for name in PANELS if name in panels and name != "watchlists"]
    main = [name for name in visible if name != "assets"]
    tables = [name for name in main if name != "account"]
    spans = {name: 1 for name in PANELS}
    if layout == "mirrored":
        sidebar = [name for name in ("account", "assets") if name in visible]
        if tables and sidebar:
            order = [name for pair in zip_longest(tables, sidebar) for name in pair if name]
            column_count, row_count = 2, max(len(tables), len(sidebar))
            columns = f"1fr {30 if width < 110 else 34}"
            if len(tables) == 1:
                spans[tables[0]] = row_count
            if len(sidebar) == 1:
                spans[sidebar[0]] = row_count
        else:
            order = tables or sidebar
            column_count, row_count = 1, len(order)
            columns = "1fr"
        rows = "3fr 2fr" if row_count == 2 else "1fr"
    elif layout == "stacked" or not main or "assets" not in visible and width < 90:
        order = visible
        columns, rows = "1fr", " ".join("1fr" for _ in visible)
        column_count, row_count = 1, len(visible)
    elif width < 110 and "assets" in visible:
        order = [main[0], "assets", *main[1:]]
        spans["assets"] = len(main)
        columns, rows = "1fr 30", " ".join("1fr" for _ in main)
        column_count, row_count = 2, len(main)
    elif "account" in main and tables:
        order = ["account", tables[0]]
        columns = "27 1fr"
        spans["account"] = len(tables)
        if "assets" in visible:
            order.append("assets")
            columns += " 34"
            spans["assets"] = len(tables)
        order.extend(tables[1:])
        rows = "3fr 2fr" if len(tables) == 2 else "1fr"
        column_count, row_count = 2 + ("assets" in visible), len(tables)
    elif "assets" in visible:
        order = [main[0], "assets", *main[1:]]
        spans["assets"] = len(main)
        columns, rows = "1fr 34", "3fr 2fr" if len(main) == 2 else "1fr"
        column_count, row_count = 2, len(main)
    else:
        order = main
        columns, rows = "1fr", " ".join("1fr" for _ in main)
        column_count, row_count = 1, len(main)
    column_spans = {name: 1 for name in PANELS}
    order = list(order)
    if "watchlists" in panels:
        if layout != "stacked" and width >= 110 and visible:
            order.insert(column_count, "watchlists")
            columns += " 30"
            spans["watchlists"] = row_count
            column_count += 1
        else:
            order.append("watchlists")
            column_spans["watchlists"] = column_count
            rows = " ".join("1fr" for _ in range(row_count + 1))
            row_count += 1
        visible.append("watchlists")
    for name in PANELS:
        widget = workspace.query_one(f"#{name}")
        widget.display = name in visible
        widget.styles.row_span = spans[name]
        widget.styles.column_span = column_spans[name]
    # Hidden widgets come last so auto-placement is deterministic after toggles.
    for index, name in enumerate(order + [name for name in PANELS if name not in order]):
        child = workspace.query_one(f"#{name}")
        if workspace.children[index] != child:
            workspace.move_child(child, before=index)
    workspace.styles.grid_size_columns = column_count
    workspace.styles.grid_size_rows = row_count
    workspace.styles.grid_columns = columns
    workspace.styles.grid_rows = rows
