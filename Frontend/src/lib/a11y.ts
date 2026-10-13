/** Builds an aria-describedby value from the hint and error ids that <Field> renders. */
export function describedBy(id: string, hint?: string, error?: string): string | undefined {
  const ids = [error ? `${id}-error` : "", hint ? `${id}-hint` : ""].filter(Boolean).join(" ");
  return ids || undefined;
}
