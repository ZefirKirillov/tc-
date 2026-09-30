// 🌌 Cosmic theme — deep space gradients, nebula glow, star accents.
// Uses Telegram theme vars as fallback so the app still adapts to light/dark TG themes.

export const C = {
  bg0: '#0b0620',
  bg1: '#160b33',
  card: 'rgba(38, 24, 80, 0.72)',
  cardBorder: 'rgba(150, 110, 255, 0.28)',
  text: '#f2ecff',
  muted: '#b9a8e8',
  accent: '#a78bfa',
  accent2: '#22d3ee',
  star: '#ffd166',
  good: '#34d399',
  bad: '#f87171',
  warn: '#fbbf24',
}

export const s: Record<string, React.CSSProperties> = {
  page: {
    fontFamily: 'system-ui, -apple-system, sans-serif',
    padding: 16,
    paddingBottom: 84,
    maxWidth: 520,
    margin: '0 auto',
    color: C.text,
    minHeight: '100vh',
    background: `radial-gradient(1200px 600px at 80% -10%, rgba(139,92,246,0.35), transparent 60%), radial-gradient(900px 500px at 10% 20%, rgba(34,211,238,0.18), transparent 60%), radial-gradient(700px 700px at 50% 110%, rgba(255,45,150,0.16), transparent 60%), linear-gradient(180deg, ${C.bg0}, ${C.bg1})`,
  },
  h: { margin: '8px 0 4px', textShadow: '0 0 18px rgba(167,139,250,0.55)' },
  sub: { margin: '2px 0', opacity: 0.85, color: C.muted },
  err: {
    color: '#ffe4e6', background: 'rgba(248,113,113,0.16)', border: '1px solid rgba(248,113,113,0.45)',
    borderRadius: 10, padding: '8px 12px',
  },
  toast: {
    color: '#ecfdf5', background: 'rgba(52,211,153,0.16)', border: '1px solid rgba(52,211,153,0.45)',
    borderRadius: 10, padding: '8px 12px',
  },
  hint: { opacity: 0.7, fontSize: 14, color: C.muted },
  card: {
    background: C.card, border: `1px solid ${C.cardBorder}`, borderRadius: 16,
    padding: 12, marginTop: 12, backdropFilter: 'blur(6px)',
    boxShadow: '0 4px 24px rgba(0,0,0,0.35), inset 0 0 24px rgba(139,92,246,0.08)',
  },
  row: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginBottom: 8 },
  bar: { fontFamily: 'monospace', color: C.star },
  btns: { display: 'flex', gap: 4, flexWrap: 'wrap' },
  btn: {
    minWidth: 30, height: 32, borderRadius: 10, color: C.text,
    border: `1px solid ${C.cardBorder}`, background: 'rgba(167,139,250,0.12)',
  },
  btnSm: {
    padding: '6px 10px', borderRadius: 10, color: C.text,
    border: `1px solid ${C.cardBorder}`, background: 'rgba(167,139,250,0.12)',
  },
  btnActive: {
    background: 'linear-gradient(135deg, #8b5cf6, #22d3ee)', color: '#0b0620',
    border: '1px solid transparent', padding: '6px 10px', borderRadius: 10, fontWeight: 700,
  },
  input: {
    width: '100%', boxSizing: 'border-box', padding: 10, borderRadius: 10,
    border: `1px solid ${C.cardBorder}`, fontSize: 15, background: 'rgba(11,6,32,0.6)', color: C.text,
  },
  textarea: {
    width: '100%', boxSizing: 'border-box', padding: 10, borderRadius: 10, minHeight: 110,
    border: `1px solid ${C.cardBorder}`, fontSize: 14, background: 'rgba(11,6,32,0.6)', color: C.text,
    fontFamily: 'inherit',
  },
  inputSm: {
    padding: 8, borderRadius: 10, border: `1px solid ${C.cardBorder}`,
    fontSize: 14, width: 130, background: 'rgba(11,6,32,0.6)', color: C.text, colorScheme: 'dark',
  },
  primary: {
    padding: '9px 16px', borderRadius: 12, border: 'none',
    background: 'linear-gradient(135deg, #8b5cf6, #22d3ee)', color: '#0b0620',
    fontSize: 15, fontWeight: 700, boxShadow: '0 0 16px rgba(139,92,246,0.5)',
  },
  danger: {
    padding: '8px 12px', borderRadius: 10, border: `1px solid ${C.bad}`,
    background: 'transparent', color: C.bad,
  },
  nav: {
    position: 'fixed', bottom: 0, left: 0, right: 0, display: 'flex',
    background: 'rgba(11,6,32,0.92)', borderTop: `1px solid ${C.cardBorder}`,
    padding: '8px 4px calc(8px + env(safe-area-inset-bottom))', backdropFilter: 'blur(8px)',
  },
  navBtn: { flex: 1, border: 'none', background: 'none', fontSize: 20, padding: 8, opacity: 0.55 },
  navActive: {
    flex: 1, border: 'none', background: 'rgba(167,139,250,0.18)', fontSize: 20,
    padding: 8, borderRadius: 12, textShadow: '0 0 12px rgba(167,139,250,0.9)',
  },
  skeleton: {
    borderRadius: 12, marginTop: 12, height: 74,
    background: 'linear-gradient(90deg, rgba(167,139,250,0.08) 25%, rgba(167,139,250,0.22) 50%, rgba(167,139,250,0.08) 75%)',
    backgroundSize: '200% 100%', animation: 'tc-shimmer 1.2s infinite',
  },
  confirmOverlay: {
    position: 'fixed', inset: 0, background: 'rgba(5,2,15,0.7)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50, padding: 24,
  },
  confirmBox: {
    background: C.bg1, border: `1px solid ${C.cardBorder}`, borderRadius: 16,
    padding: 20, maxWidth: 340, width: '100%', color: C.text,
  },
}
