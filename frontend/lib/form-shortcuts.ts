import type { KeyboardEvent } from "react";

export const SUBMIT_SHORTCUT_LABEL = "Ctrl + Enter";

/** Ctrl/⌘ + Enter in a textarea submits its form, as a click on the submit button would. */
export function handleSubmitShortcut(event: KeyboardEvent<HTMLTextAreaElement>): void {
  if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
  event.preventDefault();
  event.currentTarget.form?.requestSubmit();
}
