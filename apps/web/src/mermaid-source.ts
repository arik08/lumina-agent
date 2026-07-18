const flowchartNodePattern = /(^|[\s;])([A-Za-z_][A-Za-z0-9_-]*)\s*(\[\[|\(\(|\(\[|\[\(|\{\{|\[|\(|\{)/g;
const mermaidStructuralClassNames = new Set(["root"]);
const classDefinitionPattern = /((?:^|[;\n])\s*classDef\s+)([A-Za-z_][A-Za-z0-9_-]*)/gm;
const classAssignmentPattern = /((?:^|[;\n])\s*class\s+[A-Za-z_][A-Za-z0-9_,-]*\s+)([A-Za-z_][A-Za-z0-9_-]*)/gm;
const closingDelimiter = new Map([
  ["(", ")"],
  ["[", "]"],
  ["{", "}"],
]);

function safeClassName(className: string) {
  return mermaidStructuralClassNames.has(className) ? `lumina-${className}` : className;
}

export function repairMermaidClassNames(source: string) {
  if (!/^\s*(?:flowchart|graph)\b/m.test(source)) return source;
  const collidingNames = new Set(
    [...source.matchAll(classDefinitionPattern)]
      .map((match) => match[2])
      .filter((className) => mermaidStructuralClassNames.has(className)),
  );
  if (collidingNames.size === 0) return source;

  return source
    .replace(classDefinitionPattern, (_match, prefix: string, className: string) => `${prefix}${safeClassName(className)}`)
    .replace(classAssignmentPattern, (_match, prefix: string, className: string) => `${prefix}${safeClassName(className)}`)
    .replace(/:::\s*([A-Za-z_][A-Za-z0-9_-]*)/g, (match, className: string) => (
      collidingNames.has(className) ? match.replace(className, safeClassName(className)) : match
    ));
}

function findLabelEnd(line: string, start: number, opening: string) {
  const stack = [...opening];
  for (let index = start; index < line.length; index += 1) {
    const character = line[index];
    if (closingDelimiter.has(character)) {
      stack.push(character);
      continue;
    }
    const expected = closingDelimiter.get(stack[stack.length - 1]);
    if (character !== expected) continue;
    stack.pop();
    if (stack.length === 0) return index - opening.length + 1;
  }
  return -1;
}

function quoteUnquotedNodeLabels(line: string) {
  let repaired = line;
  flowchartNodePattern.lastIndex = 0;
  for (let match = flowchartNodePattern.exec(repaired); match; match = flowchartNodePattern.exec(repaired)) {
    const opening = match[3];
    const openingStart = match.index + match[0].lastIndexOf(opening);
    const labelStart = openingStart + opening.length;
    const labelEnd = findLabelEnd(repaired, labelStart, opening);
    if (labelEnd < 0) continue;

    const label = repaired.slice(labelStart, labelEnd).trim();
    const alreadyQuoted = label.startsWith('"') || label.startsWith("`");
    if (!label || alreadyQuoted || label.includes('"') || label.includes("`")) {
      flowchartNodePattern.lastIndex = labelEnd + opening.length;
      continue;
    }

    const quotedLabel = `"${label}"`;
    repaired = `${repaired.slice(0, labelStart)}${quotedLabel}${repaired.slice(labelEnd)}`;
    flowchartNodePattern.lastIndex = labelStart + quotedLabel.length + opening.length;
  }
  return repaired;
}

export function repairMermaidSource(source: string) {
  if (!/^\s*(?:flowchart|graph)\b/m.test(source)) return source;
  return source
    .split("\n")
    .map(quoteUnquotedNodeLabels)
    .join("\n");
}
