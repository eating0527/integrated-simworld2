import { useState } from 'react';
import { MinPanel } from './MinPanel';
import { PanelStatus } from './PanelUi';

const API = import.meta.env.VITE_API_URL || '';

export function ControllerScreenPanel() {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const streamUrl = `${API}/api/controller-stream.mjpg`;

  return (
    <MinPanel
      className="panel-ui controller-screen-panel"
      title="無人機畫面"
      actions={(
        <PanelStatus tone={connected ? 'live' : 'waiting'} label={connected ? 'Live' : 'Waiting'} />
      )}
    >
      <div className="controller-screen-panel__frame">
        <img
          className="controller-screen-panel__image"
          src={streamUrl}
          alt="ALIGN AP3 controller mirror"
          onLoad={() => {
            setConnected(true);
            setError('');
          }}
          onError={() => {
            setConnected(false);
            setError('Controller video stream unavailable. Confirm ADB is connected and backend can launch ffmpeg.');
          }}
        />
        {!connected && (
          <div className="controller-screen-panel__empty">
            <div>Waiting for controller mirror...</div>
            {error && <div className="controller-screen-panel__error">{error}</div>}
          </div>
        )}
      </div>
    </MinPanel>
  );
}
