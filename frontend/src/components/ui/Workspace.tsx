import { useEffect, useState, type ReactNode } from 'react';

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

  useEffect(() => {
    const closeDrawer = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileRail(null);
    };
    window.addEventListener('keydown', closeDrawer);
    return () => window.removeEventListener('keydown', closeDrawer);
  }, []);

  const toggleMobile = (rail: Rail) => setMobileRail(current => current === rail ? null : rail);

  return (
    <div className="workspace">
      <main className="workspace__stage">{children}</main>
      {top && <header className="workspace__top">{top}</header>}

      {left && (
        <aside id="workspace-left" className={`workspace__rail workspace__rail--left ${leftOpen ? 'is-open' : ''} ${mobileRail === 'left' ? 'is-mobile-open' : ''}`}>
          {left}
        </aside>
      )}
      {right && (
        <aside id="workspace-right" className={`workspace__rail workspace__rail--right ${rightOpen ? 'is-open' : ''} ${mobileRail === 'right' ? 'is-mobile-open' : ''}`}>
          {right}
        </aside>
      )}

      <div className="workspace__rail-controls" aria-label="工作區顯示控制">
        {left && <button type="button" aria-label="切換左側工作區" aria-expanded={leftOpen} aria-controls="workspace-left" onClick={() => setLeftOpen(value => !value)}>‹</button>}
        {right && <button type="button" aria-label="切換右側工作區" aria-expanded={rightOpen} aria-controls="workspace-right" onClick={() => setRightOpen(value => !value)}>›</button>}
      </div>

      <div className="workspace__drawer-controls" aria-label="行動工作區控制">
        {left && <button type="button" aria-label="開啟左側工作區" aria-expanded={mobileRail === 'left'} aria-controls="workspace-left" onClick={() => toggleMobile('left')}>控制</button>}
        {right && <button type="button" aria-label="開啟右側工作區" aria-expanded={mobileRail === 'right'} aria-controls="workspace-right" onClick={() => toggleMobile('right')}>狀態</button>}
      </div>

      {mobileRail && <button type="button" className="workspace__backdrop" aria-label="關閉側欄" onClick={() => setMobileRail(null)} />}
    </div>
  );
}
