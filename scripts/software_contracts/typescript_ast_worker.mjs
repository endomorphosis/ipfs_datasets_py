#!/usr/bin/env node
/**
 * Pinned, bounded TypeScript Compiler API worker.
 *
 * Protocol: one JSON request line on stdin, one JSON response line on stdout.
 * The worker parses source held in memory.  Its CompilerHost refuses every
 * other file, so imports are recorded lexically but never loaded or executed.
 */

import { createRequire } from "node:module";
import process from "node:process";

const PROTOCOL = "ipfs-datasets.software-contracts.typescript-worker@1";
// JSON escaping can expand an otherwise valid eight-megabyte source blob.
const HARD_MAX_REQUEST_BYTES = 64 * 1024 * 1024;
const HARD_MAX_OUTPUT_BYTES = 64 * 1024 * 1024;
const HARD_MAX_FACTS = 250_000;
const SUPPORTED_EXTENSIONS = new Set([
  ".cjs",
  ".js",
  ".jsx",
  ".mjs",
  ".mts",
  ".ts",
  ".tsx",
]);

function argument(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) return fallback;
  return process.argv[index + 1];
}

const typescriptModule = argument("--typescript-module", "typescript");
const expectedVersion = argument("--expected-version", "5.6.3");
const require = createRequire(import.meta.url);
let ts = null;
let compilerReason = "";
try {
  ts = require(typescriptModule);
  if (
    !ts ||
    typeof ts.version !== "string" ||
    ts.version !== expectedVersion
  ) {
    compilerReason =
      `TypeScript compiler version ${String(ts?.version || "<unknown>")} ` +
      `does not match pinned ${expectedVersion}.`;
    ts = null;
  }
} catch (error) {
  compilerReason =
    `Pinned TypeScript compiler ${typescriptModule} is unavailable: ` +
    `${error && typeof error.code === "string" ? error.code : "load_error"}.`;
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, stable(value[key])]),
    );
  }
  return value;
}

function respond(payload) {
  const encoded = Buffer.from(
    `${JSON.stringify(stable({ protocol: PROTOCOL, ...payload }))}\n`,
    "utf8",
  );
  if (encoded.length > HARD_MAX_OUTPUT_BYTES) {
    const fallback = {
      protocol: PROTOCOL,
      request_id:
        typeof payload.request_id === "string" ? payload.request_id : "unknown",
      status: "unsupported",
      code: "typescript.resource_limit",
      compiler_version: ts?.version || "",
      node_version: process.version,
      reason: `Worker output exceeded ${HARD_MAX_OUTPUT_BYTES} bytes.`,
    };
    process.stdout.write(`${JSON.stringify(stable(fallback))}\n`);
    return;
  }
  process.stdout.write(encoded);
}

function exactObject(value, fields) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...fields].sort();
  return (
    actual.length === expected.length &&
    actual.every((item, index) => item === expected[index])
  );
}

async function readOneLine() {
  const chunks = [];
  let length = 0;
  for await (const chunk of process.stdin) {
    length += chunk.length;
    if (length > HARD_MAX_REQUEST_BYTES) {
      throw new Error(`request exceeds ${HARD_MAX_REQUEST_BYTES} bytes`);
    }
    chunks.push(chunk);
  }
  const payload = Buffer.concat(chunks).toString("utf8");
  if (!payload.endsWith("\n")) throw new Error("request is not JSONL terminated");
  const lines = payload.slice(0, -1).split("\n");
  if (lines.length !== 1) throw new Error("expected exactly one request line");
  return JSON.parse(lines[0]);
}

function suffix(path) {
  const lowered = path.toLowerCase();
  for (const extension of SUPPORTED_EXTENSIONS) {
    if (lowered.endsWith(extension)) return extension;
  }
  const index = lowered.lastIndexOf(".");
  return index >= 0 ? lowered.slice(index) : "";
}

function moduleName(path) {
  const extension = suffix(path);
  const stem = extension ? path.slice(0, -extension.length) : path;
  return stem.replaceAll("/", ".").replaceAll(" ", "_") || "__main__";
}

function scriptKind(path) {
  const extension = suffix(path);
  if (extension === ".tsx") return ts.ScriptKind.TSX;
  if (extension === ".jsx") return ts.ScriptKind.JSX;
  if ([".js", ".mjs", ".cjs"].includes(extension)) return ts.ScriptKind.JS;
  return ts.ScriptKind.TS;
}

function parseFacts(request) {
  const source = request.source;
  const sourceBytes = Buffer.byteLength(source, "utf8");
  if (sourceBytes > request.max_source_bytes) {
    return {
      status: "unsupported",
      code: "typescript.resource_limit",
      reason:
        `Source has ${sourceBytes} bytes; limit is ` +
        `${request.max_source_bytes}.`,
    };
  }
  const extension = suffix(request.path);
  if (!SUPPORTED_EXTENSIONS.has(extension)) {
    return {
      status: "unsupported",
      code: "typescript.unsupported_extension",
      reason: `Source extension ${extension || "<none>"} is unsupported.`,
    };
  }

  const sourceFile = ts.createSourceFile(
    request.path,
    source,
    ts.ScriptTarget.ES2022,
    true,
    scriptKind(request.path),
  );

  // A no-I/O Program supplies real TypeChecker/Symbol classification without
  // reading imports, libraries, config files, or ambient project state.
  const compilerOptions = {
    allowJs: true,
    checkJs: false,
    jsx: ts.JsxEmit.Preserve,
    noLib: true,
    noResolve: true,
    target: ts.ScriptTarget.ES2022,
  };
  const compilerHost = {
    fileExists: (fileName) => fileName === request.path,
    getCanonicalFileName: (fileName) => fileName,
    getCurrentDirectory: () => "/",
    getDefaultLibFileName: () => "lib.d.ts",
    getNewLine: () => "\n",
    getSourceFile: (fileName) =>
      fileName === request.path ? sourceFile : undefined,
    readFile: () => undefined,
    useCaseSensitiveFileNames: () => true,
    writeFile: () => {
      throw new Error("emit is disabled");
    },
  };
  const program = ts.createProgram(
    [request.path],
    compilerOptions,
    compilerHost,
  );
  const typeChecker = program.getTypeChecker();

  let nodeCount = 0;
  function count(node) {
    nodeCount += 1;
    if (nodeCount > request.max_ast_nodes) return;
    ts.forEachChild(node, count);
  }
  count(sourceFile);
  if (nodeCount > request.max_ast_nodes) {
    return {
      status: "unsupported",
      code: "typescript.resource_limit",
      reason:
        `AST has more than ${request.max_ast_nodes} nodes; ` +
        "the parse is incomplete.",
    };
  }

  // TypeScript offsets are UTF-16 code units.  Build one bounded table so all
  // durable offsets and columns are UTF-8 bytes as required by shared AST v1.
  const byteOffsets = new Uint32Array(source.length + 1);
  let byteCursor = 0;
  for (let index = 0; index < source.length; ) {
    const codePoint = source.codePointAt(index);
    const width = codePoint > 0xffff ? 2 : 1;
    byteOffsets[index] = byteCursor;
    if (width === 2) byteOffsets[index + 1] = byteCursor;
    byteCursor += Buffer.byteLength(String.fromCodePoint(codePoint), "utf8");
    index += width;
    byteOffsets[index] = byteCursor;
  }
  const lineStarts = sourceFile.getLineStarts();

  function span(nodeOrStart, optionalEnd) {
    const startPosition =
      typeof nodeOrStart === "number"
        ? nodeOrStart
        : nodeOrStart.getStart(sourceFile, false);
    const endPosition =
      typeof nodeOrStart === "number" ? optionalEnd : nodeOrStart.getEnd();
    const startLC = sourceFile.getLineAndCharacterOfPosition(startPosition);
    const endLC = sourceFile.getLineAndCharacterOfPosition(endPosition);
    return {
      start_byte: byteOffsets[startPosition],
      end_byte: byteOffsets[endPosition],
      start_line: startLC.line + 1,
      start_column:
        byteOffsets[startPosition] - byteOffsets[lineStarts[startLC.line]],
      end_line: endLC.line + 1,
      end_column:
        byteOffsets[endPosition] - byteOffsets[lineStarts[endLC.line]],
    };
  }

  const counters = new Map();
  function next(kind) {
    const value = counters.get(kind) || 0;
    counters.set(kind, value + 1);
    return value;
  }
  function id(kind, node) {
    return `${kind}:${span(node).start_byte}:${next(kind)}`;
  }
  function compact(text) {
    return text.trim().replace(/\s+/gu, " ");
  }
  function textOf(node) {
    if (!node) return "";
    return compact(source.slice(node.getStart(sourceFile, false), node.getEnd()));
  }
  function expressionName(node) {
    if (!node) return "";
    if (ts.isIdentifier(node) || ts.isPrivateIdentifier(node)) return node.text;
    if (node.kind === ts.SyntaxKind.ThisKeyword) return "this";
    if (node.kind === ts.SyntaxKind.SuperKeyword) return "super";
    if (ts.isPropertyAccessExpression(node)) {
      const parent = expressionName(node.expression);
      return parent ? `${parent}.${node.name.text}` : node.name.text;
    }
    if (ts.isElementAccessExpression(node)) {
      const parent = expressionName(node.expression);
      return parent ? `${parent}[]` : "subscript";
    }
    if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
      return expressionName(node.expression);
    }
    return ts.SyntaxKind[node.kind] || "dynamic";
  }
  function declarationName(nameNode, owner) {
    if (!nameNode) return ["anonymous", false];
    if (
      ts.isIdentifier(nameNode) ||
      ts.isPrivateIdentifier(nameNode) ||
      ts.isStringLiteral(nameNode) ||
      ts.isNumericLiteral(nameNode)
    ) {
      return [String(nameNode.text), false];
    }
    unsupported(
      owner,
      "typescript.computed_name",
      "computed_name",
      "Computed declaration names are normalized as 'computed'.",
    );
    return ["computed", true];
  }
  function modifiers(node) {
    if (!node) return [];
    return ts.canHaveModifiers(node) ? ts.getModifiers(node) || [] : [];
  }
  function hasModifier(node, kind) {
    return modifiers(node).some((item) => item.kind === kind);
  }
  function decoratorNames(node) {
    if (!ts.canHaveDecorators(node)) return [];
    return (ts.getDecorators(node) || []).map((item) =>
      expressionName(item.expression),
    );
  }
  function visibility(node) {
    if (hasModifier(node, ts.SyntaxKind.PrivateKeyword)) return "private";
    if (hasModifier(node, ts.SyntaxKind.ProtectedKeyword)) return "protected";
    if (hasModifier(node, ts.SyntaxKind.PublicKeyword)) return "public";
    return "unspecified";
  }
  function defaultKind(node) {
    if (!node) return "none";
    if (
      ts.isLiteralExpression(node) ||
      ts.isArrayLiteralExpression(node) ||
      ts.isObjectLiteralExpression(node)
    ) {
      return "literal";
    }
    if (
      ts.isArrowFunction(node) ||
      ts.isFunctionExpression(node) ||
      ts.isClassExpression(node)
    ) {
      return "factory";
    }
    return "expression";
  }

  const scopes = [];
  const symbols = [];
  const imports = [];
  const references = [];
  const calls = [];
  const effects = [];
  const diagnostics = [];
  const unsupportedRecords = [];
  const exports = new Set();
  const scopeStack = ["scope:module"];
  const qualifierStack = [];
  const definitionOrdinals = new Map();
  let factCount = 0;

  function addFact(collection, value) {
    factCount += 1;
    if (factCount > HARD_MAX_FACTS) {
      throw new Error(`fact count exceeds ${HARD_MAX_FACTS}`);
    }
    collection.push(value);
  }
  function currentScope() {
    return scopeStack[scopeStack.length - 1];
  }
  function unsupported(node, code, construct, reason) {
    addFact(unsupportedRecords, {
      unsupported_id: id("unsupported", node),
      code,
      construct,
      reason,
      span: span(node),
    });
  }
  function reference(node, name, context, isQualified = false) {
    const value = {
      reference_id: id("reference", node),
      name: name || "dynamic",
      scope_id: currentScope(),
      context,
      span: span(node),
      is_qualified: isQualified,
    };
    addFact(references, value);
    return value;
  }
  function effect(node, kind, operation, subject = "") {
    addFact(effects, {
      effect_id: id("effect", node),
      scope_id: currentScope(),
      kind,
      operation,
      span: span(node),
      subject,
    });
  }
  function qualified(name) {
    return [moduleName(request.path), ...qualifierStack, name].join(".");
  }
  function symbol(node, name, kind, signature = null, flags = []) {
    const ordinalKey = `${currentScope()}\u0000${name}`;
    const ordinal = definitionOrdinals.get(ordinalKey) || 0;
    definitionOrdinals.set(ordinalKey, ordinal + 1);
    if (ordinal > 0) {
      addFact(diagnostics, {
        code: "typescript.duplicate_definition",
        severity: "warning",
        message:
          `${name} is redefined in the same lexical scope; definitions ` +
          "remain distinct until resolution.",
        span: span(node),
      });
    }
    const compilerSymbol =
      node.name && typeof node.name === "object"
        ? typeChecker.getSymbolAtLocation(node.name)
        : undefined;
    if (compilerSymbol && (compilerSymbol.flags & ts.SymbolFlags.Alias) !== 0) {
      flags.push("alias_symbol");
    }
    const rawDecorators = decoratorNames(node);
    const normalizedDecorators = [...new Set(rawDecorators)];
    if (rawDecorators.length !== normalizedDecorators.length) {
      unsupported(
        node,
        "typescript.repeated_decorator",
        "repeated_decorator",
        "Repeated decorator order requires a TypeScript-owned syntax record.",
      );
    }
    const value = {
      symbol_id: id("symbol", node),
      name,
      qualified_name: qualified(name),
      kind,
      scope_id: currentScope(),
      span: span(node),
      definition_ordinal: ordinal,
      signature,
      visibility: visibility(node),
      decorator_names: normalizedDecorators,
      flags: [...new Set(flags)].sort(),
    };
    addFact(symbols, value);
    if (
      currentScope() === "scope:module" &&
      (hasModifier(node, ts.SyntaxKind.ExportKeyword) ||
        hasModifier(node, ts.SyntaxKind.DefaultKeyword))
    ) {
      exports.add(
        hasModifier(node, ts.SyntaxKind.DefaultKeyword) ? "default" : name,
      );
    }
    return value;
  }
  function scope(node, kind, ownerSymbolId = null) {
    const value = {
      scope_id: id(`scope:${kind}`, node),
      kind,
      span: span(node),
      parent_scope_id: currentScope(),
      owner_symbol_id: ownerSymbolId,
    };
    addFact(scopes, value);
    return value.scope_id;
  }
  function parameterSignature(parameters) {
    return parameters.map((parameter, position) => {
      let kind = "positional_or_named";
      if (parameter.dotDotDotToken) kind = "variadic_positional";
      if (
        position === 0 &&
        ts.isIdentifier(parameter.name) &&
        ["this", "self"].includes(parameter.name.text)
      ) {
        kind = "receiver";
      }
      const [name] = declarationName(parameter.name, parameter);
      return {
        name,
        kind,
        position,
        annotation: textOf(parameter.type),
        default_kind: defaultKind(parameter.initializer),
      };
    });
  }
  function signature(node) {
    let generator = Boolean(node.asteriskToken);
    return {
      parameters: parameterSignature(node.parameters || []),
      return_annotation: textOf(node.type),
      is_async: hasModifier(node, ts.SyntaxKind.AsyncKeyword),
      is_generator: generator,
    };
  }
  function functionFlags(node) {
    const result = [];
    if (hasModifier(node, ts.SyntaxKind.AsyncKeyword)) result.push("coroutine");
    if (node.asteriskToken) result.push("generator");
    if (hasModifier(node, ts.SyntaxKind.StaticKeyword)) result.push("static");
    if (hasModifier(node, ts.SyntaxKind.AbstractKeyword)) result.push("abstract");
    if (hasModifier(node, ts.SyntaxKind.DeclareKeyword)) result.push("declare");
    if (hasModifier(node, ts.SyntaxKind.ExportKeyword)) result.push("export");
    if (hasModifier(node, ts.SyntaxKind.DefaultKeyword)) result.push("default");
    return result;
  }
  function visitFunction(node, kind) {
    const [name] = declarationName(node.name, node);
    const definition = symbol(
      node,
      name,
      kind,
      signature(node),
      functionFlags(node),
    );
    for (const decorator of ts.canHaveDecorators(node)
      ? ts.getDecorators(node) || []
      : []) {
      reference(
        decorator.expression,
        expressionName(decorator.expression),
        "decorator",
        ts.isPropertyAccessExpression(decorator.expression),
      );
    }
    const childScope = scope(node, "function", definition.symbol_id);
    scopeStack.push(childScope);
    qualifierStack.push(name);
    for (const parameter of node.parameters || []) {
      const [parameterName] = declarationName(parameter.name, parameter);
      symbol(parameter, parameterName, "parameter");
      if (parameter.type) visit(parameter.type);
      if (parameter.initializer) visit(parameter.initializer);
    }
    if (node.type) visit(node.type);
    if (node.body) visit(node.body);
    qualifierStack.pop();
    scopeStack.pop();
  }

  addFact(scopes, {
    scope_id: "scope:module",
    kind: "module",
    span: span(0, source.length),
    parent_scope_id: null,
    owner_symbol_id: null,
  });

  function declarationIdentifier(node) {
    const parent = node.parent;
    if (!parent) return false;
    return (
      parent.name === node &&
      !ts.isPropertyAccessExpression(parent)
    );
  }

  function referenceContext(node) {
    const parent = node.parent;
    if (!parent) return "read";
    if (
      (ts.isCallExpression(parent) || ts.isNewExpression(parent)) &&
      parent.expression === node
    ) {
      return "call";
    }
    if (ts.isTypeNode(parent)) return "type";
    if (ts.isDecorator(parent)) return "decorator";
    if (ts.isHeritageClause(parent)) return "base";
    if (ts.isExportSpecifier(parent)) return "export";
    if (parent.kind === ts.SyntaxKind.DeleteExpression) {
      return "delete";
    }
    if (
      ts.isBinaryExpression(parent) &&
      parent.left === node &&
      parent.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
      parent.operatorToken.kind <= ts.SyntaxKind.LastAssignment
    ) {
      return "write";
    }
    return "read";
  }

  function visit(node) {
    if (ts.isSourceFile(node)) {
      ts.forEachChild(node, visit);
      return;
    }
    if (ts.isClassDeclaration(node) || ts.isClassExpression(node)) {
      const [name] = declarationName(node.name, node);
      const definition = symbol(node, name, "class", null, functionFlags(node));
      const childScope = scope(node, "class", definition.symbol_id);
      for (const decorator of ts.canHaveDecorators(node)
        ? ts.getDecorators(node) || []
        : []) {
        reference(
          decorator.expression,
          expressionName(decorator.expression),
          "decorator",
          ts.isPropertyAccessExpression(decorator.expression),
        );
      }
      for (const heritage of node.heritageClauses || []) {
        for (const type of heritage.types) {
          reference(
            type.expression,
            expressionName(type.expression),
            "base",
            ts.isPropertyAccessExpression(type.expression),
          );
        }
      }
      scopeStack.push(childScope);
      qualifierStack.push(name);
      for (const member of node.members) visit(member);
      qualifierStack.pop();
      scopeStack.pop();
      return;
    }
    if (ts.isInterfaceDeclaration(node)) {
      const [name] = declarationName(node.name, node);
      const definition = symbol(node, name, "interface", null, functionFlags(node));
      const childScope = scope(node, "interface", definition.symbol_id);
      for (const heritage of node.heritageClauses || []) {
        for (const type of heritage.types) {
          reference(
            type.expression,
            expressionName(type.expression),
            "base",
            ts.isPropertyAccessExpression(type.expression),
          );
        }
      }
      scopeStack.push(childScope);
      qualifierStack.push(name);
      for (const member of node.members) visit(member);
      qualifierStack.pop();
      scopeStack.pop();
      return;
    }
    if (ts.isFunctionDeclaration(node)) {
      visitFunction(node, "function");
      return;
    }
    if (ts.isMethodDeclaration(node) || ts.isMethodSignature(node)) {
      visitFunction(node, "method");
      return;
    }
    if (ts.isConstructorDeclaration(node)) {
      visitFunction(node, "constructor");
      return;
    }
    if (
      ts.isGetAccessorDeclaration(node) ||
      ts.isSetAccessorDeclaration(node)
    ) {
      visitFunction(node, "method");
      return;
    }
    if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
      unsupported(
        node,
        "typescript.callable_expression",
        ts.isArrowFunction(node) ? "arrow_function" : "function_expression",
        "Callable expression signatures are retained only at their lexical site.",
      );
      const childScope = scope(node, "function");
      scopeStack.push(childScope);
      for (const parameter of node.parameters) {
        const [parameterName] = declarationName(parameter.name, parameter);
        symbol(parameter, parameterName, "parameter");
      }
      visit(node.body);
      scopeStack.pop();
      return;
    }
    if (ts.isTypeAliasDeclaration(node)) {
      symbol(node, node.name.text, "type_alias", null, functionFlags(node));
      ts.forEachChild(node, visit);
      return;
    }
    if (ts.isEnumDeclaration(node)) {
      symbol(node, node.name.text, "enum", null, functionFlags(node));
      unsupported(
        node,
        "typescript.enum_members",
        "enum_members",
        "Enum member values require a TypeScript-owned syntax record.",
      );
      ts.forEachChild(node, visit);
      return;
    }
    if (ts.isModuleDeclaration(node)) {
      const [name] = declarationName(node.name, node);
      const definition = symbol(node, name, "namespace", null, functionFlags(node));
      const childScope = scope(node, "namespace", definition.symbol_id);
      scopeStack.push(childScope);
      qualifierStack.push(name);
      if (node.body) visit(node.body);
      qualifierStack.pop();
      scopeStack.pop();
      return;
    }
    if (ts.isVariableDeclaration(node)) {
      if (ts.isIdentifier(node.name)) {
        symbol(
          node,
          node.name.text,
          "variable",
          null,
          hasModifier(node.parent?.parent, ts.SyntaxKind.ExportKeyword)
            ? ["export"]
            : [],
        );
      } else {
        unsupported(
          node,
          "typescript.destructuring_definition",
          "destructuring_definition",
          "Destructured binding shape requires a TypeScript-owned syntax record.",
        );
      }
      if (node.type) visit(node.type);
      if (node.initializer) visit(node.initializer);
      return;
    }
    if (ts.isPropertyDeclaration(node) || ts.isPropertySignature(node)) {
      const [name] = declarationName(node.name, node);
      const flags = [];
      if (hasModifier(node, ts.SyntaxKind.StaticKeyword)) flags.push("static");
      if (hasModifier(node, ts.SyntaxKind.ReadonlyKeyword)) flags.push("readonly");
      if (node.questionToken) flags.push("optional");
      symbol(node, name, "property", null, flags);
      ts.forEachChild(node, visit);
      return;
    }
    if (ts.isImportDeclaration(node)) {
      const module = ts.isStringLiteral(node.moduleSpecifier)
        ? node.moduleSpecifier.text
        : textOf(node.moduleSpecifier);
      if (!node.importClause) {
        addFact(imports, {
          import_id: id("import", node),
          scope_id: currentScope(),
          module,
          kind: "side_effect",
          span: span(node),
          imported_name: null,
          local_name: null,
          is_type_only: false,
        });
      } else {
        if (node.importClause.name) {
          addFact(imports, {
            import_id: id("import", node),
            scope_id: currentScope(),
            module,
            kind: "symbol",
            span: span(node),
            imported_name: "default",
            local_name: node.importClause.name.text,
            is_type_only: Boolean(node.importClause.isTypeOnly),
          });
        }
        const bindings = node.importClause.namedBindings;
        if (bindings && ts.isNamespaceImport(bindings)) {
          addFact(imports, {
            import_id: id("import", bindings),
            scope_id: currentScope(),
            module,
            kind: "namespace",
            span: span(node),
            imported_name: null,
            local_name: bindings.name.text,
            is_type_only: Boolean(node.importClause.isTypeOnly),
          });
        } else if (bindings && ts.isNamedImports(bindings)) {
          for (const element of bindings.elements) {
            addFact(imports, {
              import_id: id("import", element),
              scope_id: currentScope(),
              module,
              kind: "symbol",
              span: span(element),
              imported_name: (element.propertyName || element.name).text,
              local_name: element.name.text,
              is_type_only: Boolean(
                node.importClause.isTypeOnly || element.isTypeOnly,
              ),
            });
          }
        }
      }
      effect(node, "import", "read", module);
      return;
    }
    if (ts.isExportDeclaration(node)) {
      const module =
        node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)
          ? node.moduleSpecifier.text
          : ".";
      if (node.exportClause && ts.isNamedExports(node.exportClause)) {
        for (const element of node.exportClause.elements) {
          const importedName = (element.propertyName || element.name).text;
          exports.add(element.name.text);
          if (node.moduleSpecifier) {
            addFact(imports, {
              import_id: id("import", element),
              scope_id: currentScope(),
              module,
              kind: "re_export",
              span: span(element),
              imported_name: importedName,
              local_name: element.name.text,
              is_type_only: Boolean(node.isTypeOnly || element.isTypeOnly),
            });
          } else {
            reference(element, importedName, "export");
          }
        }
      } else if (node.moduleSpecifier) {
        addFact(imports, {
          import_id: id("import", node),
          scope_id: currentScope(),
          module,
          kind: "re_export",
          span: span(node),
          imported_name: "*",
          local_name: null,
          is_type_only: Boolean(node.isTypeOnly),
        });
      }
      return;
    }
    if (ts.isExportAssignment(node)) {
      exports.add("default");
      visit(node.expression);
      return;
    }
    if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
      const calleeName = expressionName(node.expression) || "dynamic";
      const calleeReference = reference(
        node.expression,
        calleeName,
        "call",
        ts.isPropertyAccessExpression(node.expression) ||
          ts.isElementAccessExpression(node.expression),
      );
      const isAwaited = ts.isAwaitExpression(node.parent);
      let kind = ts.isNewExpression(node) ? "constructor" : "direct";
      if (calleeName === "super") kind = "super";
      else if (
        ts.isPropertyAccessExpression(node.expression) ||
        ts.isElementAccessExpression(node.expression)
      ) {
        kind = "method";
      } else if (!ts.isIdentifier(node.expression)) {
        kind = "dynamic";
      }
      addFact(calls, {
        call_id: id("call", node),
        scope_id: currentScope(),
        callee_name: calleeName,
        kind,
        argument_count: (node.arguments || []).length,
        span: span(node),
        callee_reference_id: calleeReference.reference_id,
        named_argument_names: [],
        is_awaited: isAwaited,
      });
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword) {
        const target = node.arguments?.[0];
        if (target && ts.isStringLiteral(target)) {
          addFact(imports, {
            import_id: id("import", node),
            scope_id: currentScope(),
            module: target.text,
            kind: "dynamic",
            span: span(node),
            imported_name: null,
            local_name: null,
            is_type_only: false,
          });
          effect(node, "import", "read", target.text);
        }
      }
      if (
        ["eval", "Function", "globalThis.eval"].includes(calleeName) ||
        (node.expression.kind === ts.SyntaxKind.ImportKeyword &&
          (!node.arguments?.[0] || !ts.isStringLiteral(node.arguments[0])))
      ) {
        unsupported(
          node,
          "typescript.dynamic_execution",
          "dynamic_execution",
          "Dynamic execution or import targets cannot be bounded statically.",
        );
      }
      ts.forEachChild(node, visit);
      return;
    }
    if (ts.isAwaitExpression(node)) {
      effect(node, "await", "await", expressionName(node.expression));
      visit(node.expression);
      return;
    }
    if (ts.isThrowStatement(node)) {
      effect(node, "exception", "raise", expressionName(node.expression));
      if (node.expression) visit(node.expression);
      return;
    }
    if (ts.isPropertyAccessExpression(node)) {
      const name = expressionName(node);
      const context = referenceContext(node);
      reference(node, name, context, true);
      if (name.startsWith("this.")) {
        effect(
          node,
          "object_state",
          context === "write"
            ? "write"
            : context === "delete"
              ? "delete"
              : "read",
          name,
        );
      }
      visit(node.expression);
      return;
    }
    if (ts.isIdentifier(node) && !declarationIdentifier(node)) {
      reference(node, node.text, referenceContext(node));
      return;
    }
    if (ts.isWithStatement(node)) {
      unsupported(
        node,
        "typescript.dynamic_scope",
        "with_statement",
        "JavaScript with-statements require dynamic name resolution.",
      );
    }
    ts.forEachChild(node, visit);
  }

  try {
    visit(sourceFile);
  } catch (error) {
    return {
      status: "unsupported",
      code: "typescript.resource_limit",
      reason:
        error instanceof Error
          ? error.message
          : "TypeScript fact extraction failed.",
    };
  }

  for (const diagnostic of sourceFile.parseDiagnostics || []) {
    const start = Math.max(0, diagnostic.start || 0);
    const end = Math.min(
      source.length,
      start + Math.max(0, diagnostic.length || 0),
    );
    addFact(diagnostics, {
      code: `typescript.parse.${diagnostic.code}`,
      severity: "error",
      message: ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
      span: span(start, end),
    });
    addFact(unsupportedRecords, {
      unsupported_id: `unsupported:${byteOffsets[start]}:${next("unsupported")}`,
      code: "typescript.syntax_error",
      construct: "syntax_error",
      reason: ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
      span: span(start, end),
    });
  }

  return {
    status: "ok",
    facts: {
      module: {
        module_id: `module:source:${byteCursor}`,
        name: moduleName(request.path),
        scope_id: "scope:module",
        span: span(0, source.length),
        export_names: [...exports].sort(),
      },
      scopes,
      symbols,
      imports,
      references,
      calls,
      effects,
      diagnostics,
      unsupported: unsupportedRecords,
    },
    usage: {
      source_bytes: sourceBytes,
      ast_nodes: nodeCount,
      facts: factCount,
    },
  };
}

let requestId = "unknown";
try {
  const request = await readOneLine();
  if (request && typeof request.request_id === "string") {
    requestId = request.request_id;
  }
  if (
    !request ||
    request.protocol !== PROTOCOL ||
    typeof request.request_id !== "string" ||
    typeof request.operation !== "string"
  ) {
    respond({
      request_id: requestId,
      status: "unsupported",
      code: "typescript.invalid_request",
      compiler_version: ts?.version || "",
      node_version: process.version,
      reason: "Request envelope is invalid.",
    });
  } else if (request.operation === "probe") {
    if (!exactObject(request, ["protocol", "request_id", "operation"])) {
      respond({
        request_id: requestId,
        status: "unsupported",
        code: "typescript.invalid_request",
        compiler_version: ts?.version || "",
        node_version: process.version,
        reason: "Probe request fields are closed.",
      });
    } else {
      respond({
        request_id: requestId,
        status: ts ? "ok" : "unsupported",
        code: ts ? "" : "typescript.compiler_unavailable",
        compiler_version: ts?.version || "",
        node_version: process.version,
        reason: ts ? "" : compilerReason,
      });
    }
  } else if (request.operation === "parse") {
    const fields = [
      "protocol",
      "request_id",
      "operation",
      "path",
      "source",
      "max_source_bytes",
      "max_ast_nodes",
    ];
    if (
      !exactObject(request, fields) ||
      typeof request.path !== "string" ||
      request.path.length === 0 ||
      typeof request.source !== "string" ||
      !Number.isSafeInteger(request.max_source_bytes) ||
      request.max_source_bytes <= 0 ||
      request.max_source_bytes > 8 * 1024 * 1024 ||
      !Number.isSafeInteger(request.max_ast_nodes) ||
      request.max_ast_nodes <= 0 ||
      request.max_ast_nodes > 5_000_000
    ) {
      respond({
        request_id: requestId,
        status: "unsupported",
        code: "typescript.invalid_request",
        compiler_version: ts?.version || "",
        node_version: process.version,
        reason: "Parse request fields or bounds are invalid.",
      });
    } else if (!ts) {
      respond({
        request_id: requestId,
        status: "unsupported",
        code: "typescript.compiler_unavailable",
        compiler_version: "",
        node_version: process.version,
        reason: compilerReason,
      });
    } else {
      const result = parseFacts(request);
      respond({
        request_id: requestId,
        compiler_version: ts.version,
        node_version: process.version,
        ...result,
      });
    }
  } else {
    respond({
      request_id: requestId,
      status: "unsupported",
      code: "typescript.invalid_request",
      compiler_version: ts?.version || "",
      node_version: process.version,
      reason: `Operation ${request.operation} is unsupported.`,
    });
  }
} catch (error) {
  respond({
    request_id: requestId,
    status: "unsupported",
    code: "typescript.invalid_request",
    compiler_version: ts?.version || "",
    node_version: process.version,
    reason:
      error instanceof Error ? error.message : "Worker request processing failed.",
  });
}
