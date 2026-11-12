// Observe real HTTP used by browser scenarios without changing any request.
const token = /\{([^{}\/]+)\}|:([A-Za-z_][\w]*)/g;
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\${enc}");

export function contractRoute(template) {
  const names = [];
  let expression = "^", cursor = 0;
  for (const match of template.matchAll(token)) {
    expression += escape(template.slice(cursor, match.index)) + "([^/]+)";
    names.push(match[1] ?? match[2]);
    cursor = match.index + match[0].length;
  }
  return { names, pattern: new RegExp(expression + escape(template.slice(cursor)) + "/?$") };
}

export function shapeError(schema, value, path = "$") {
  if (!schema || typeof schema !== "object") return null;
  if (schema.nullable && value === null) return null;
  const alternatives = schema.anyOf ?? schema.oneOf;
  if (Array.isArray(alternatives)) {
    const matches = alternatives.filter(option => !shapeError(option, value, path)).length;
    if (!matches || (schema.oneOf && matches !== 1)) return path + " has no valid schema variant";
  }
  if (Array.isArray(schema.allOf)) {
    for (const option of schema.allOf) {
      const mismatch = shapeError(option, value, path);
      if (mismatch) return mismatch;
    }
  }
  const is = kind => {
    switch (kind) {
      case "null": return value === null;
      case "integer": return Number.isInteger(value);
      case "array": return Array.isArray(value);
      case "object": return value !== null && typeof value === "object" && !Array.isArray(value);
      case "string": case "boolean": case "number": return typeof value === kind;
      default: return true;
    }
  };
  const types = Array.isArray(schema.type) ? schema.type : schema.type ? [schema.type] : [];
  if (types.length && !types.some(is)) return path + " expected " + types.join("|");
  if ((schema.required || schema.properties) && !is("object") && !types.length)
    return path + " expected object";
  if (is("object")) {
    for (const field of schema.required ?? [])
      if (!Object.hasOwn(value, field)) return path + "." + field + " is missing";
    for (const [field, child] of Object.entries(schema.properties ?? {})) {
      if (!Object.hasOwn(value, field)) continue;
      const mismatch = shapeError(child, value[field], path + "." + field);
      if (mismatch) return mismatch;
    }
  }
  if (schema.items && is("array")) {
    for (let i = 0; i < value.length; i++) {
      const mismatch = shapeError(schema.items, value[i], path + "[" + i + "]");
      if (mismatch) return mismatch;
    }
  }
  return null;
}

export function wireError(apis, method, pathname, status, body) {
  if (!pathname.startsWith("/api/") || (method === "GET" && pathname === "/api/health")) return null;
  let decoded;
  try { decoded = decodeURI(pathname); }
  catch { return method + " " + pathname + " has invalid path encoding"; }
  const matches = Object.entries(apis).map(([id, api]) => ({ id, api, route: contractRoute(api.signature.path) }))
    .filter(({ api, route }) => api.signature.method === method && route.pattern.test(decoded))
    .sort((a, b) => a.route.names.length - b.route.names.length);
  if (!matches.length) return method + " " + pathname + " has no matching API contract";
  const { id, api, route } = matches[0];
  const parameters = route.pattern.exec(decoded).slice(1);
  for (let i = 0; i < parameters.length; i++) {
    const value = parameters[i];
    const declared = api.request?.params?.properties?.[route.names[i]];
    if (/^[:{]/.test(value) || (declared?.type === "integer" && !/^-?\d+$/.test(value)))
      return id + " missing concrete route context for " + route.names[i];
  }
  // A conditional GET may be served from the browser's previously validated 200 response.
  if (status === 304 && method === "GET" && api.response.success.status === 200) return null;
  const responses = [api.response.success, ...api.response.errors];
  const expected = responses.find(response => response.status === status);
  if (!expected) return id + " unexpected HTTP status " + status;
  if (status === 204 || status === 304 || method === "HEAD") return null;
  const mismatch = shapeError(expected.body, body);
  return mismatch && id + " HTTP " + status + " response " + mismatch;
}
