/** The supported JSON Schema subset is enforced by the OpenAPI generator. */
export type Schema =
  | boolean
  | {
      $ref?: string;
      type?: string;
      anyOf?: readonly Schema[];
      const?: unknown;
      enum?: readonly unknown[];
      properties?: { readonly [key: string]: Schema };
      required?: readonly string[];
      additionalProperties?: Schema;
      items?: Schema;
      prefixItems?: readonly Schema[];
      minItems?: number;
      maxItems?: number;
      minimum?: number;
      maximum?: number;
      exclusiveMinimum?: number;
      exclusiveMaximum?: number;
      minLength?: number;
      maxLength?: number;
      pattern?: string;
    };

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function matchesSchema(
  value: unknown,
  schema: Schema,
  definitions: Record<string, Schema>,
): boolean {
  if (typeof schema === "boolean") return schema;
  if (schema.$ref) {
    const reference = definitions[schema.$ref.split("/").at(-1) ?? ""];
    return reference !== undefined && matchesSchema(value, reference, definitions);
  }
  if ("const" in schema && value !== schema.const) return false;
  if (schema.enum && !schema.enum.includes(value)) return false;
  if (schema.anyOf && !schema.anyOf.some((option) => matchesSchema(value, option, definitions)))
    return false;
  switch (schema.type) {
    case "null":
      return value === null;
    case "boolean":
      return typeof value === "boolean";
    case "string": {
      if (typeof value !== "string") return false;
      const length = Array.from(value).length;
      return (
        (schema.minLength === undefined || length >= schema.minLength) &&
        (schema.maxLength === undefined || length <= schema.maxLength) &&
        (schema.pattern === undefined || new RegExp(schema.pattern, "u").test(value))
      );
    }
    case "integer":
    case "number":
      return (
        typeof value === "number" &&
        Number.isFinite(value) &&
        (schema.type !== "integer" || Number.isInteger(value)) &&
        (schema.minimum === undefined || value >= schema.minimum) &&
        (schema.maximum === undefined || value <= schema.maximum) &&
        (schema.exclusiveMinimum === undefined || value > schema.exclusiveMinimum) &&
        (schema.exclusiveMaximum === undefined || value < schema.exclusiveMaximum)
      );
    case "array":
      return (
        Array.isArray(value) &&
        (schema.minItems === undefined || value.length >= schema.minItems) &&
        (schema.maxItems === undefined || value.length <= schema.maxItems) &&
        value.every((item: unknown, index) =>
          matchesSchema(item, schema.prefixItems?.[index] ?? schema.items ?? true, definitions),
        )
      );
    case "object":
      return (
        isRecord(value) &&
        (schema.required ?? []).every((key) => Object.hasOwn(value, key)) &&
        Object.entries(value).every(([key, item]) =>
          matchesSchema(
            item,
            schema.properties && Object.hasOwn(schema.properties, key)
              ? schema.properties[key]
              : (schema.additionalProperties ?? true),
            definitions,
          ),
        )
      );
    default:
      return true;
  }
}
