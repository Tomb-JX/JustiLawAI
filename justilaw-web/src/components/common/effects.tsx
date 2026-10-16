/**
 * 视觉效果原语（配合 globals.css 的效果层）。
 * 全部零依赖、纯 transform/opacity 合成器动画；
 * prefers-reduced-motion 下由全局 CSS 降级。
 */
import { memo, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** 光标聚光灯卡片：鼠标进入时跟随高光（CSS 变量 --spot-x/y 驱动） */
export const SpotlightCard = memo(function SpotlightCard({
  className,
  children,
  onClick,
  style,
}: {
  className?: string
  children: ReactNode
  onClick?: () => void
  style?: React.CSSProperties
}) {
  const onMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    const rect = el.getBoundingClientRect()
    el.style.setProperty('--spot-x', `${e.clientX - rect.left}px`)
    el.style.setProperty('--spot-y', `${e.clientY - rect.top}px`)
  }, [])
  return (
    <div className={cn('spotlight-card', className)} style={style} onMouseMove={onMove} onClick={onClick}>
      {children}
    </div>
  )
})

/**
 * 数字滚动：从 0 计数到目标值（rAF，300ms 内完成，卡片出现时触发一次）。
 * 系统开启"减弱动态效果"时直接显示终值。
 */
export function CountUp({ value, duration = 900, className }: { value: number; duration?: number; className?: string }) {
  const [display, setDisplay] = useState(0)
  const ref = useRef<HTMLSpanElement>(null)
  const started = useRef(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || duration <= 0) {
      setDisplay(value)
      return
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting || started.current) return
        started.current = true
        const t0 = performance.now()
        const tick = (t: number) => {
          const p = Math.min(1, (t - t0) / duration)
          // easeOutCubic：起步快收尾缓，数字"落定"感
          setDisplay(Math.round(value * (1 - Math.pow(1 - p, 3))))
          if (p < 1) requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
      },
      { threshold: 0.4 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [value, duration])

  return (
    <span ref={ref} className={className}>
      {display.toLocaleString()}
    </span>
  )
}
