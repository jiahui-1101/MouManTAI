import type { KeyboardEvent } from 'react';

export interface WorkflowStage<T extends string> { id: T; label: string }

interface WorkflowTabsProps<T extends string> {
  stages: readonly WorkflowStage<T>[];
  active: T;
  onChange: (stage: T) => void;
  label: string;
  className: string;
  idPrefix?: string;
}

/** Shared, keyboard-operable tabs for focused operational workspaces. */
export function WorkflowTabs<T extends string>({ stages, active, onChange, label, className, idPrefix }: WorkflowTabsProps<T>) {
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const current = stages.findIndex(stage => stage.id === active);
    let next = current;
    if (event.key === 'ArrowRight') next = (current + 1) % stages.length;
    else if (event.key === 'ArrowLeft') next = (current - 1 + stages.length) % stages.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = stages.length - 1;
    else return;
    event.preventDefault();
    onChange(stages[next].id);
    const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    buttons[next]?.focus();
  };
  return <nav className={className} role="tablist" aria-label={label} onKeyDown={onKeyDown}>
    {stages.map(stage => <button key={stage.id} id={idPrefix ? `${idPrefix}-tab-${stage.id}` : undefined}
      type="button" role="tab" tabIndex={stage.id === active ? 0 : -1}
      aria-selected={stage.id === active}
      aria-controls={idPrefix ? `${idPrefix}-panel-${stage.id}` : undefined}
      onClick={() => onChange(stage.id)}>{stage.label}</button>)}
  </nav>;
}
