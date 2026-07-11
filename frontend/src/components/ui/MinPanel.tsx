import type React from 'react';
import { useId, useState } from 'react';

interface MinPanelProps {
  title: string;
  children: React.ReactNode;
  as?: 'div' | 'aside';
  className?: string;
  style?: React.CSSProperties;
  bodyClassName?: string;
  bodyStyle?: React.CSSProperties;
  actions?: React.ReactNode;
  defaultMinimized?: boolean;
  minimized?: boolean;
  onMinimizedChange?: (minimized: boolean) => void;
  headerContent?: React.ReactNode;
}

export function MinPanel({
  title,
  children,
  as = 'div',
  className = '',
  style,
  bodyClassName = '',
  bodyStyle,
  actions,
  defaultMinimized = false,
  minimized: controlledMinimized,
  onMinimizedChange,
  headerContent,
}: MinPanelProps) {
  const [uncontrolledMinimized, setUncontrolledMinimized] = useState(defaultMinimized);
  const minimized = controlledMinimized ?? uncontrolledMinimized;
  const bodyId = useId();
  const Root = as;

  return (
    <Root
      className={`${className} min-panel ${minimized ? 'is-min' : ''}`.trim()}
      style={style}
    >
      <div className="min-panel__bar">
        <button
          type="button"
          className="min-panel__title-btn"
          aria-label={`${minimized ? 'Restore' : 'Minimize'} ${title}`}
          aria-expanded={!minimized}
          aria-controls={bodyId}
          onClick={() => {
            const next = !minimized;
            onMinimizedChange?.(next);
            if (controlledMinimized === undefined) setUncontrolledMinimized(next);
          }}
        >
          {headerContent ?? <span>{title}</span>}
          <span className="min-panel__chevron" aria-hidden="true">⌄</span>
        </button>
        {!minimized && actions}
      </div>
      <div
        id={bodyId}
        className={`min-panel__body ${bodyClassName}`.trim()}
        aria-hidden={minimized}
        inert={minimized ? true : undefined}
        style={bodyStyle}
      >
        <div className="min-panel__body-inner">
          {children}
        </div>
      </div>
    </Root>
  );
}
