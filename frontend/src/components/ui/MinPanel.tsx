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
  headerContent,
}: MinPanelProps) {
  const [minimized, setMinimized] = useState(defaultMinimized);
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
          onClick={() => setMinimized(value => !value)}
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
