import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

export function DetailDialog({
  open,
  title,
  drawer = false,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  drawer?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const element = dialog.current!;
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    element.showModal();
    return () => {
      element.close();
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  return createPortal(
    <dialog
      ref={dialog}
      className={`detail-dialog live-workspace ${drawer ? 'detail-drawer' : ''}`}
      aria-labelledby={titleId}
      onKeyDown={(event) => {
        if (event.key !== 'Tab') return;
        const controls = Array.from(
          event.currentTarget.querySelectorAll<HTMLElement>(
            'button, a[href], input, select, textarea, summary, [tabindex="0"]',
          ),
        ).filter((element) => !element.matches(':disabled') && element.getClientRects().length > 0);
        if (!controls.length) return;
        const current = controls.indexOf(document.activeElement as HTMLElement);
        const next =
          current < 0
            ? event.shiftKey
              ? controls.length - 1
              : 0
            : (current + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
        event.preventDefault();
        controls[next].focus();
      }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClose={() => {
        if (open && !dialog.current?.open) onClose();
      }}
    >
      <div className="detail-dialog-heading">
        <h2 id={titleId}>{title}</h2>
        <button className="dialog-close" onClick={onClose} aria-label={`Close ${title}`}>
          <X size={18} />
        </button>
      </div>
      <div className="detail-dialog-body">{children}</div>
    </dialog>,
    document.body,
  );
}
