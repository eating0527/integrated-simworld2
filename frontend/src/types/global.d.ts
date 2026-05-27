declare global {
  interface MediaDevices {
    addEventListener?: (
      type: 'devicechange',
      listener: EventListenerOrEventListenerObject
    ) => void;
    removeEventListener?: (
      type: 'devicechange',
      listener: EventListenerOrEventListenerObject
    ) => void;
  }
}

export {};
