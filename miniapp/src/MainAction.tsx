import { useMainButton, type MainCfg } from './tg'

/** Primary action of the current view: Telegram MainButton inside Telegram,
 *  an in-page full-width button in a regular browser. Mount at most one per screen. */
export default function MainAction({ cfg }: { cfg: MainCfg }) {
  const native = useMainButton(cfg)
  if (native || !cfg) return null
  return (
    <button className="btn btn-primary btn-block mt" disabled={cfg.disabled || cfg.busy} onClick={cfg.onClick}>
      {cfg.busy ? '…' : cfg.text}
    </button>
  )
}
