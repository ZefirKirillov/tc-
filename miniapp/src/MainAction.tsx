import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { haptic, useMainButton, useTyping, type MainCfg } from './tg'

/** Primary action of the current view.
 *  - default: Telegram MainButton (in-page button in a plain browser) — used inside sheets,
 *    where the tab island is covered;
 *  - float: an in-page button floating just ABOVE the tab island, so it is not hit by accident
 *    when reaching for the tabs. While the keyboard is open the island is hidden and an in-page
 *    button could end up under the keyboard, so typing falls back to Telegram's MainButton,
 *    which always sits right above the keyboard.
 *  Mount at most one per screen. */
export default function MainAction({ cfg, float }: { cfg: MainCfg; float?: boolean }) {
  const typing = useTyping()
  // The slot is rendered by App after the screens, so look it up once mounted.
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  useEffect(() => { setSlot(document.getElementById('fab-slot')) }, [])
  const floating = !!float && !typing
  const native = useMainButton(floating ? null : cfg)
  if (!cfg) return null
  if (floating) {
    // Rendered into the slot at the end of the page (App), so the spacer always sits
    // under the last content no matter where the screen declares its action.
    if (!slot) return null
    return createPortal((
      <>
        <div className="fab-spacer" aria-hidden="true" />
        <div className="fab">
          <button className="btn btn-primary" disabled={cfg.disabled || cfg.busy}
            onClick={() => { haptic('medium'); cfg.onClick() }}>
            {cfg.busy ? '…' : cfg.text}
          </button>
        </div>
      </>
    ), slot)
  }
  if (native) return null
  return (
    <button className="btn btn-primary btn-block mt" disabled={cfg.disabled || cfg.busy} onClick={cfg.onClick}>
      {cfg.busy ? '…' : cfg.text}
    </button>
  )
}
