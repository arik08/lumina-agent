const flowchartNodePattern = /(^|[\s;])([A-Za-z_][A-Za-z0-9_-]*)\s*(\[\[|\(\(|\(\[|\[\(|\{\{|\[|\(|\{)/g;
const closingDelimiter = new Map([
  ["(", ")"],
  ["[", "]"],
  ["{", "}"],
]);

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
