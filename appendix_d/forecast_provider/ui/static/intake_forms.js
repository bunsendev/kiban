import { parseList } from "./format.js";

export function mappingPayload(byId) {
  const value = (id) => byId(id).value.trim();
  const center = value("mapping-center");
  const centerMode = value("mapping-center-mode");
  const availability = value("mapping-availability");
  return {
    date_column: value("mapping-date"),
    jan_column: value("mapping-jan"),
    product_name_column: value("mapping-product"),
    quantity_column: value("mapping-quantity"),
    unit_column: value("mapping-unit"),
    center_column: centerMode === "COLUMN" ? center : null,
    center_value: centerMode === "FIXED" ? center : null,
    row_type_column: value("mapping-row-type") || null,
    available_at_column: availability === "OBSERVED" ? value("mapping-available-at") : null,
    date_formats: parseList(value("mapping-date-formats")),
    allowed_units: parseList(value("mapping-units")),
    availability_mode: availability,
    file_mode: value("mapping-file-mode"),
  };
}

export function syncAvailability(byId) {
  const observed = byId("mapping-availability").value === "OBSERVED";
  const field = byId("mapping-available-at");
  field.disabled = !observed;
  field.required = observed;
  if (!observed) field.value = "";
}
