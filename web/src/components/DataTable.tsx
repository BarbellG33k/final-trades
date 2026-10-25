import { Fragment, type ReactNode } from "react";
import { EmptyState } from "./ui";

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  num?: boolean;
  width?: string;
}

interface DataTableProps<T> {
  rows: T[];
  columns: Column<T>[];
  keyOf: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  isExpanded?: (row: T) => boolean;
  renderExpanded?: (row: T) => ReactNode;
  emptyMessage?: string;
}

export function DataTable<T>({
  rows,
  columns,
  keyOf,
  onRowClick,
  isExpanded,
  renderExpanded,
  emptyMessage = "No records",
}: DataTableProps<T>) {
  if (rows.length === 0) return <EmptyState message={emptyMessage} />;
  return (
    <div className="overflow-x-auto">
      <table className="grid text-[12.5px]">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.num ? "num text-right" : ""} style={c.width ? { width: c.width } : undefined}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const expanded = isExpanded?.(row) ?? false;
            return (
              <Fragment key={keyOf(row)}>
                <tr
                  className={expanded ? "expanded" : undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  style={onRowClick ? { cursor: "pointer" } : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                >
                  {columns.map((c) => (
                    <td key={c.key} className={c.num ? "num text-right" : undefined}>
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
                {expanded && renderExpanded && (
                  <tr className="expanded">
                    <td colSpan={columns.length} className="!p-0">
                      {renderExpanded(row)}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
