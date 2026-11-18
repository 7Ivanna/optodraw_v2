// Words of a text with its code fences removed (rule D4): the budget test and the README test count the same way.
export function words(text) {
  let fence = false;
  return text.split('\n').filter((line) => (line.startsWith('```') ? ((fence = !fence), false) : !fence))
    .join('\n').split(/\s+/).filter(Boolean).length;
}
