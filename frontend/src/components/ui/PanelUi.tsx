import type React from 'react';

export type PanelStatusTone = 'live' | 'waiting' | 'warning' | 'danger' | 'neutral';

export const PANEL_POS = {
  aircraft: { position: 'fixed', top: 14, left: 276, zIndex: 998, width: 300 },
  usrp: { position: 'fixed', top: 132, left: 276, zIndex: 997, width: 340 },
  gps: { position: 'fixed', top: 14, right: 14, zIndex: 999, width: 280 },
  controller: { position: 'fixed', top: 240, right: 14, zIndex: 955, width: 'min(34vw, 420px)', minWidth: 320 },
} satisfies Record<string, React.CSSProperties>;

export function PanelStatus({ label, tone = 'neutral' }: { label: React.ReactNode; tone?: PanelStatusTone }) {
  return (
    <span className={`panel-ui-status panel-ui-status--${tone}`}>
      <span className="panel-ui-status__dot" />
      {label}
    </span>
  );
}

export function PanelGrid({ children }: { children: React.ReactNode }) {
  return <div className="panel-ui-grid">{children}</div>;
}

export function PanelField({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="panel-ui-field">
      <span className="panel-ui-field__label">{label}</span>
      <span className="panel-ui-field__value">{value}</span>
    </div>
  );
}

export function PanelSection({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`panel-ui-section ${className}`.trim()}>{children}</div>;
}

export function PanelFooter({ children }: { children: React.ReactNode }) {
  return <div className="panel-ui-footer">{children}</div>;
}

export function PanelEmpty({ children }: { children: React.ReactNode }) {
  return <div className="panel-ui-empty">{children}</div>;
}
