import { useEffect, useRef } from "react";

// These are inline fieldsets, not modal dialogs: no focus trap or hidden content.
// Only focus changes; server authorization and submission logic remain untouched.
export function useInlineConfirmationFocus(open: boolean) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const regionRef = useRef<HTMLElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open) confirmRef.current?.focus();
    else if (wasOpen.current) {
      const trigger = triggerRef.current;
      (trigger && !trigger.disabled ? trigger : regionRef.current)?.focus();
    }
    wasOpen.current = open;
  }, [open]);
  return { triggerRef, confirmRef, regionRef };
}
