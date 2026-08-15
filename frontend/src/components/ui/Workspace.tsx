import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

type Rail = 'left' | 'right';

const FOCUSABLE_SELECTOR = 'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

function getFocusable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    .filter((element) => !element.closest('[inert], [aria-hidden="true"], [hidden]'));
}

function matchesDrawerMode(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(max-width: 1199px)').matches;
}

interface WorkspaceProps {
  top?: ReactNode;
  left?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
}

export function Workspace({ top, left, right, children }: WorkspaceProps) {
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [drawerMode, setDrawerMode] = useState(matchesDrawerMode);
  const [mobileRail, setMobileRail] = useState<Rail | null>(null);
  const leftRailId = `workspace-left-${useId()}`;
  const rightRailId = `workspace-right-${useId()}`;
  const leftRailRef = useRef<HTMLElement>(null);
  const rightRailRef = useRef<HTMLElement>(null);
  const leftTriggerRef = useRef<HTMLButtonElement>(null);
  const rightTriggerRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia('(max-width: 1199px)');
    const handleModeChange = (event: MediaQueryListEvent) => {
      setDrawerMode(event.matches);
      setMobileRail(null);
    };
    setDrawerMode(query.matches);
    query.addEventListener?.('change', handleModeChange);
    query.addListener?.(handleModeChange);
    return () => {
      query.removeEventListener?.('change', handleModeChange);
      query.removeListener?.(handleModeChange);
    };
  }, []);

  useEffect(() => {
    if (!mobileRail) return;

    const rail = mobileRail === 'left' ? leftRailRef.current : rightRailRef.current;
    const focusable = rail ? getFocusable(rail)[0] : null;
    (focusable ?? rail)?.focus();

    const handleDrawerKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (!event.defaultPrevented) setMobileRail(null);
        return;
      }
      if (event.key !== 'Tab' || !rail) return;

      const focusableElements = getFocusable(rail);
      if (focusableElements.length === 0) {
        event.preventDefault();
        rail.focus();
        return;
      }

      const first = focusableElements[0];
      const last = focusableElements[focusableElements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', handleDrawerKey);
    return () => window.removeEventListener('keydown', handleDrawerKey);
  }, [mobileRail]);

  useEffect(() => {
    if (!mobileRail && returnFocusRef.current) {
      returnFocusRef.current.focus();
      returnFocusRef.current = null;
    }
  }, [mobileRail]);

  const toggleMobile = (rail: Rail) => {
    setMobileRail(current => {
      if (current === rail) return null;
      returnFocusRef.current = rail === 'left' ? leftTriggerRef.current : rightTriggerRef.current;
      return rail;
    });
  };

  const leftVisible = drawerMode ? mobileRail === 'left' : leftOpen;
  const rightVisible = drawerMode ? mobileRail === 'right' : rightOpen;

  return (
    <div className="workspace">
      <main className="workspace__stage">{children}</main>
      <header className="workspace__top">
        {left && <button type="button" className="workspace__top-control workspace__top-control--left" aria-label="切換左側工作區" aria-expanded={leftOpen} aria-controls={leftRailId} onClick={() => setLeftOpen(value => !value)}>‹</button>}
        {top}
        {right && <button type="button" className="workspace__top-control workspace__top-control--right" aria-label="切換右側工作區" aria-expanded={rightOpen} aria-controls={rightRailId} onClick={() => setRightOpen(value => !value)}>›</button>}
      </header>

      {left && (
        <aside
          ref={leftRailRef}
          id={leftRailId}
          aria-label="左側工作區"
          aria-hidden={!leftVisible}
          aria-modal={mobileRail === 'left' ? true : undefined}
          role={mobileRail === 'left' ? 'dialog' : undefined}
          tabIndex={mobileRail === 'left' ? -1 : undefined}
          inert={!leftVisible ? true : undefined}
          className={`workspace__rail workspace__rail--left ${leftOpen ? 'is-open' : ''} ${mobileRail === 'left' ? 'is-mobile-open' : ''}`}
        >
          {mobileRail === 'left' && (
            <div className="workspace__drawer-header">
              <span className="workspace__drawer-title">控制</span>
              <button
                type="button"
                className="workspace__drawer-close"
                aria-label="關閉左側抽屜"
                onClick={() => setMobileRail(null)}
              >
                關閉 ✕
              </button>
            </div>
          )}
          <div className="workspace__rail-body">
            {left}
          </div>
        </aside>
      )}
      {right && (
        <aside
          ref={rightRailRef}
          id={rightRailId}
          aria-label="右側工作區"
          aria-hidden={!rightVisible}
          aria-modal={mobileRail === 'right' ? true : undefined}
          role={mobileRail === 'right' ? 'dialog' : undefined}
          tabIndex={mobileRail === 'right' ? -1 : undefined}
          inert={!rightVisible ? true : undefined}
          className={`workspace__rail workspace__rail--right ${rightOpen ? 'is-open' : ''} ${mobileRail === 'right' ? 'is-mobile-open' : ''}`}
        >
          {mobileRail === 'right' && (
            <div className="workspace__drawer-header">
              <span className="workspace__drawer-title">歷史</span>
              <button
                type="button"
                className="workspace__drawer-close"
                aria-label="關閉右側抽屜"
                onClick={() => setMobileRail(null)}
              >
                關閉 ✕
              </button>
            </div>
          )}
          <div className="workspace__rail-body">
            {right}
          </div>
        </aside>
      )}

      <div className="workspace__drawer-controls" aria-label="行動工作區控制">
        {left && <button ref={leftTriggerRef} type="button" aria-label={mobileRail === 'left' ? '關閉左側工作區' : '開啟左側工作區'} aria-expanded={mobileRail === 'left'} aria-controls={leftRailId} onClick={() => toggleMobile('left')}>控制</button>}
        {right && <button ref={rightTriggerRef} type="button" aria-label={mobileRail === 'right' ? '關閉右側工作區' : '開啟右側工作區'} aria-expanded={mobileRail === 'right'} aria-controls={rightRailId} onClick={() => toggleMobile('right')}>歷史</button>}
      </div>

      {mobileRail && <button type="button" className="workspace__backdrop" aria-label="關閉側欄" onClick={() => setMobileRail(null)} />}
    </div>
  );
}
