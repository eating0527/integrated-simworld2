import { useEffect, useId, useState, type ReactNode } from 'react';

type Rail = 'left' | 'right';

interface WorkspaceProps {
  top?: ReactNode;
  left?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
}

export function Workspace({ top, left, right, children }: WorkspaceProps) {
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [mobileRail, setMobileRail] = useState<Rail | null>(null);
  const leftRailId = `workspace-left-${useId()}`;
  const rightRailId = `workspace-right-${useId()}`;

  useEffect(() => {
    if (!mobileRail) return;

    const closeDrawer = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) setMobileRail(null);
    };
    window.addEventListener('keydown', closeDrawer);
    return () => window.removeEventListener('keydown', closeDrawer);
  }, [mobileRail]);

  const toggleMobile = (rail: Rail) => setMobileRail(current => current === rail ? null : rail);

  return (
    <div className="workspace">
      <main className="workspace__stage">{children}</main>
      <header className="workspace__top">
        {left && <button type="button" className="workspace__top-control workspace__top-control--left" aria-label="切換左側工作區" aria-expanded={leftOpen} aria-controls={leftRailId} onClick={() => setLeftOpen(value => !value)}>‹</button>}
        {top}
        {right && <button type="button" className="workspace__top-control workspace__top-control--right" aria-label="切換右側工作區" aria-expanded={rightOpen} aria-controls={rightRailId} onClick={() => setRightOpen(value => !value)}>›</button>}
      </header>

      {left && (
        <aside id={leftRailId} aria-label="左側工作區" className={`workspace__rail workspace__rail--left ${leftOpen ? 'is-open' : ''} ${mobileRail === 'left' ? 'is-mobile-open' : ''}`}>
          {left}
        </aside>
      )}
      {right && (
        <aside id={rightRailId} aria-label="右側工作區" className={`workspace__rail workspace__rail--right ${rightOpen ? 'is-open' : ''} ${mobileRail === 'right' ? 'is-mobile-open' : ''}`}>
          {right}
        </aside>
      )}

      <div className="workspace__drawer-controls" aria-label="行動工作區控制">
        {left && <button type="button" aria-label={mobileRail === 'left' ? '關閉左側工作區' : '開啟左側工作區'} aria-expanded={mobileRail === 'left'} aria-controls={leftRailId} onClick={() => toggleMobile('left')}>控制</button>}
        {right && <button type="button" aria-label={mobileRail === 'right' ? '關閉右側工作區' : '開啟右側工作區'} aria-expanded={mobileRail === 'right'} aria-controls={rightRailId} onClick={() => toggleMobile('right')}>狀態</button>}
      </div>

      {mobileRail && <button type="button" className="workspace__backdrop" aria-label="關閉側欄" onClick={() => setMobileRail(null)} />}
    </div>
  );
}
