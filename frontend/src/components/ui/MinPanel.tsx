import type React from 'react';
import { useRef, useState } from 'react';

interface MinPanelProps {
  title: string;
  children: React.ReactNode;
  as?: 'div' | 'aside';
  className?: string;
  style?: React.CSSProperties;
  bodyClassName?: string;
  bodyStyle?: React.CSSProperties;
  actions?: React.ReactNode;
  draggable?: boolean;
}

function styleNumber(value: React.CSSProperties[keyof React.CSSProperties], fallback: number) {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.endsWith('px')) return Number.parseFloat(value);
  return fallback;
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
  draggable = false,
}: MinPanelProps) {
  const [minimized, setMinimized] = useState(false);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const rootRef = useRef<HTMLElement | null>(null);
  const dragRef = useRef({
    active: false,
    moved: false,
    startX: 0,
    startY: 0,
    left: 0,
    top: 0,
  });
  const Root = as;
  const positionedStyle = position
    ? { ...style, left: position.left, top: position.top, right: 'auto', bottom: 'auto' }
    : style;
  const rootStyle = {
    ...positionedStyle,
    borderRadius: 'var(--panel-radius)',
    ...(minimized ? {
      width: 'max-content',
      minWidth: 'max-content',
      height: 'max-content',
      maxHeight: 'max-content',
    } : {}),
  };
  const bodyLayoutStyle: React.CSSProperties = minimized
    ? {
      ...bodyStyle,
      position: 'absolute',
      width: 0,
      height: 0,
      overflow: 'hidden',
    }
    : bodyStyle ?? {};

  const stopDrag = () => {
    dragRef.current.active = false;
    window.removeEventListener('pointermove', moveDrag);
    window.removeEventListener('pointerup', stopDrag);
    window.removeEventListener('pointercancel', stopDrag);
  };

  const moveDrag = (event: PointerEvent) => {
    if (!dragRef.current.active) return;
    dragRef.current.moved = true;
    setPosition({
      left: dragRef.current.left + event.clientX - dragRef.current.startX,
      top: dragRef.current.top + event.clientY - dragRef.current.startY,
    });
  };

  const startDrag = (event: React.PointerEvent) => {
    if (!draggable) return;
    const rect = event.currentTarget.closest('.min-panel')?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = {
      active: true,
      moved: false,
      startX: event.clientX,
      startY: event.clientY,
      left: position?.left ?? styleNumber(style?.left, rect.left),
      top: position?.top ?? styleNumber(style?.top, rect.top),
    };
    window.addEventListener('pointermove', moveDrag);
    window.addEventListener('pointerup', stopDrag);
    window.addEventListener('pointercancel', stopDrag);
  };

  const toggleMinimized = () => {
    if (dragRef.current.moved) {
      dragRef.current.moved = false;
      return;
    }
    setMinimized(value => {
      if (!value && rootRef.current) {
        const rect = rootRef.current.getBoundingClientRect();
        setPosition({ left: rect.left, top: rect.top });
      }
      return !value;
    });
  };
  const setRootRef = (node: HTMLElement | null) => {
    rootRef.current = node;
  };

  return (
    <Root
      ref={setRootRef as React.RefCallback<HTMLDivElement & HTMLElementTagNameMap['aside']>}
      className={`${className} min-panel ${draggable ? 'is-draggable' : ''} ${minimized ? 'is-min' : ''}`.trim()}
      style={rootStyle}
    >
      <div className="min-panel__bar">
        <button
          type="button"
          className="min-panel__title-btn"
          aria-label={`${minimized ? 'Restore' : 'Minimize'} ${title}`}
          onClick={toggleMinimized}
          onPointerDown={startDrag}
        >
          {title}
        </button>
        {!minimized && actions}
      </div>
      <div
        className={`min-panel__body ${bodyClassName}`.trim()}
        aria-hidden={minimized}
        style={bodyLayoutStyle}
      >
        <div className="min-panel__body-inner">
          {children}
        </div>
      </div>
    </Root>
  );
}
