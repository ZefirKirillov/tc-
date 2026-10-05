// Line icon set on a 24px grid, 1.6 stroke, currentColor — replaces emoji in UI chrome.

type P = { size?: number; className?: string }

function I({ size = 20, className, children }: P & { children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      {children}
    </svg>
  )
}

export const Ico = {
  orbit: (p: P) => <I {...p}><circle cx="12" cy="12" r="3" /><ellipse cx="12" cy="12" rx="9.5" ry="4.5" transform="rotate(-30 12 12)" /></I>,
  dumbbell: (p: P) => <I {...p}><path d="M6.5 7v10M17.5 7v10M3.5 9.5v5M20.5 9.5v5M6.5 12h11" /></I>,
  tasks: (p: P) => <I {...p}><path d="M4 6.5l1.5 1.5L8 5.5M4 12.5l1.5 1.5L8 11.5M4 18.5l1.5 1.5L8 17.5M11.5 7h8.5M11.5 13h8.5M11.5 19h8.5" /></I>,
  food: (p: P) => <I {...p}><path d="M3.5 12h17a8.5 8.5 0 0 1-17 0zM8 8.5c0-1.5 1-1.5 1-3M12 8.5c0-1.5 1-1.5 1-3M16 8.5c0-1.5 1-1.5 1-3" /></I>,
  ai: (p: P) => <I {...p}><path d="M12 3.5l1.8 5 5 1.8-5 1.8-1.8 5-1.8-5-5-1.8 5-1.8zM18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" /></I>,
  chart: (p: P) => <I {...p}><path d="M4 4v16h16" /><path d="M7.5 15l3.5-4 3 2.5 5-6.5" /></I>,
  flame: (p: P) => <I {...p}><path d="M12 21c3.6 0 6-2.4 6-5.8 0-4.2-3.4-6.2-4.4-10.2-2 1.4-3.3 3.6-3.1 6.2-1-.6-1.7-1.6-1.9-2.8C7.1 9.9 6 12.2 6 15.2 6 18.6 8.4 21 12 21z" /></I>,
  spark: (p: P) => <I {...p}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.5 2.5M15.2 15.2l2.5 2.5M6.3 17.7l2.5-2.5M15.2 8.8l2.5-2.5" /></I>,
  check: (p: P) => <I {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></I>,
  skip: (p: P) => <I {...p}><path d="M5 6l8 6-8 6zM18 6v12" /></I>,
  trash: (p: P) => <I {...p}><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l.8 12.5h9.4L17.5 7" /></I>,
  camera: (p: P) => <I {...p}><path d="M4 8h3.5L9 5.5h6L16.5 8H20v11H4z" /><circle cx="12" cy="13.3" r="3.3" /></I>,
  plus: (p: P) => <I {...p}><path d="M12 5v14M5 12h14" /></I>,
  arrow: (p: P) => <I {...p}><path d="M5 12h14M13 6l6 6-6 6" /></I>,
  back: (p: P) => <I {...p}><path d="M19 12H5M11 6l-6 6 6 6" /></I>,
  refresh: (p: P) => <I {...p}><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4" /></I>,
  history: (p: P) => <I {...p}><path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v4h4M12 8v4l3 2" /></I>,
  clock: (p: P) => <I {...p}><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></I>,
  repeat: (p: P) => <I {...p}><path d="M4 11V9.5A3.5 3.5 0 0 1 7.5 6H19M16 3l3 3-3 3M20 13v1.5a3.5 3.5 0 0 1-3.5 3.5H5M8 21l-3-3 3-3" /></I>,
  alert: (p: P) => <I {...p}><path d="M12 4l9 16H3zM12 10v4.5M12 17.3v.2" /></I>,
  offline: (p: P) => <I {...p}><path d="M3 3l18 18M8.5 16.5a5 5 0 0 1 7 0M5 12.8a10 10 0 0 1 4.2-2.4M19 12.8a10 10 0 0 0-3-2M2 9a14 14 0 0 1 4.2-2.7M22 9a14 14 0 0 0-10.5-3.4" /></I>,
  moon: (p: P) => <I {...p}><path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z" /></I>,
  flag: (p: P) => <I {...p}><path d="M5 21V4M5 4.5h12l-2.5 4 2.5 4H5" /></I>,
  pen: (p: P) => <I {...p}><path d="M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4" /></I>,
  scale: (p: P) => <I {...p}><rect x="3.5" y="3.5" width="17" height="17" rx="3" /><path d="M8.5 9.5a5 5 0 0 1 7 0L12 13z" /></I>,
  tune: (p: P) => <I {...p}><path d="M4 7h9M18 7h2M4 17h3M11 17h9" /><circle cx="15.5" cy="7" r="2.2" /><circle cx="8.5" cy="17" r="2.2" /></I>,
  // check-in categories
  sleep: (p: P) => <I {...p}><path d="M13 5h5l-5 6h5M4 13h4l-4 5h4" /></I>,
  activity: (p: P) => <I {...p}><path d="M3 12h4l2.5-6 5 12 2.5-6h4" /></I>,
  idle: (p: P) => <I {...p}><rect x="3" y="7" width="18" height="10" rx="5" /><path d="M7.5 10.5v3M6 12h3M15.5 11h.1M17.5 13h.1" /></I>,
  target: (p: P) => <I {...p}><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="0.8" /></I>,
}

export type IconName = keyof typeof Ico
